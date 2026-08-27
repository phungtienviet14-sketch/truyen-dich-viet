"""Execute bounded windows of durable work under the singleton worker lease."""
import asyncio
import hashlib
import logging

import httpx
from sqlalchemy import func, select, update

from app import config
from app.crawler import get_crawler
from app.database import AsyncSessionLocal
from app.models import Chapter, Glossary, Novel
from app.translator.deepseek import DeepSeekTranslator, TranslationOutputError
from app.translator.job_models import TranslationJob, TranslationTask, WorkerLease, utcnow
from app.translator.jobs import (BudgetExceeded, ChapterCheckpoints, WorkInterrupted,
    emit_event, finish_job, record_usage, reserve_tokens, write_lock)

logger = logging.getLogger(__name__)


async def ensure_work_is_active(task_id, owner):
    async with AsyncSessionLocal() as db:
        active = await db.scalar(select(TranslationTask.id).join(TranslationJob).where(
            TranslationTask.id == task_id, TranslationTask.status == "running",
            TranslationJob.status.in_(("running", "queued"))))
        leased = await db.scalar(select(WorkerLease.id).where(
            WorkerLease.id == 1, WorkerLease.owner == owner, WorkerLease.expires_at > utcnow()))
    if active is None or leased is None:
        raise WorkInterrupted("Job đã tạm dừng, hủy hoặc worker mất lease.")


async def claim_window(owner):
    async with AsyncSessionLocal() as db:
        await write_lock(db)
        lease = await db.scalar(select(WorkerLease.id).where(
            WorkerLease.id == 1, WorkerLease.owner == owner, WorkerLease.expires_at > utcnow()))
        if lease is None:
            raise WorkInterrupted("Worker mất lease.")
        job = await db.scalar(select(TranslationJob).where(TranslationJob.status.in_(("queued", "running")))
                              .order_by(TranslationJob.id).limit(1))
        if job is None:
            return None, []
        concurrency = max(1, min(job.concurrency, config.MAX_CONCURRENT_TRANSLATIONS))
        tasks = (await db.scalars(select(TranslationTask).where(
            TranslationTask.job_id == job.id, TranslationTask.status == "pending")
            .order_by(TranslationTask.position).limit(concurrency))).all()
        await db.execute(update(TranslationJob).where(TranslationJob.id == job.id)
                         .values(status="running", updated_at=utcnow()))
        await db.execute(update(TranslationTask).where(TranslationTask.id.in_([task.id for task in tasks]))
                         .values(status="running", updated_at=utcnow()))
        await db.execute(update(Chapter).where(Chapter.id.in_([task.chapter_id for task in tasks]))
                         .values(status="translating", error_msg=None))
        await db.commit()
        return job.id, tasks


async def restore_pending(task, budget_error=None):
    async with AsyncSessionLocal() as db:
        await write_lock(db)
        changed = await db.execute(update(TranslationTask).where(
            TranslationTask.id == task.id, TranslationTask.status == "running")
            .values(status="pending", updated_at=utcnow()))
        if changed.rowcount:
            await db.execute(update(Chapter).where(Chapter.id == task.chapter_id,
                             Chapter.status == "translating").values(status="pending"))
        if budget_error:
            await db.execute(update(TranslationJob).where(TranslationJob.id == task.job_id,
                TranslationJob.status.in_(("running", "queued")))
                .values(status="paused", error=str(budget_error), updated_at=utcnow()))
        await db.commit()


async def save_outcome(task, result=None, error=None, needs_review=False, owner=None):
    async with AsyncSessionLocal() as db:
        await write_lock(db)
        if owner is not None:
            leased = await db.scalar(select(WorkerLease.id).where(
                WorkerLease.id == 1, WorkerLease.owner == owner, WorkerLease.expires_at > utcnow()))
            if leased is None:
                return False
        active = await db.scalar(select(TranslationTask.id).join(TranslationJob).where(
            TranslationTask.id == task.id, TranslationTask.status == "running",
            TranslationJob.status.in_(("running", "queued"))))
        if active is None:
            return False
        values = {"status": "needs_review" if needs_review else ("error" if error else "completed"),
                  "error_msg": error}
        if result is not None:
            values = {**values, "chapter_title_vi": result["title_vi"], "content_vi": result["content_vi"],
                      "translated_at": utcnow()}
        await db.execute(update(Chapter).where(Chapter.id == task.chapter_id).values(**values))
        await db.execute(update(TranslationTask).where(TranslationTask.id == task.id)
                         .values(status="error" if error else "completed", error=error, active_key=None,
                                 updated_at=utcnow()))
        count = await db.scalar(select(func.count(Chapter.id)).where(
            Chapter.novel_id == task.novel_id, Chapter.status == "completed"))
        await db.execute(update(Novel).where(Novel.id == task.novel_id)
                         .values(translated_chapters=count, updated_at=utcnow()))
        await db.commit()
        return True


def safe_error(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return f"DeepSeek HTTP {exc.response.status_code}. Kiểm tra cấu hình, quota hoặc thử lại sau."
    if isinstance(exc, httpx.RequestError):
        return "Không kết nối được nguồn/API; thử lại sau."
    if isinstance(exc, (ValueError, TranslationOutputError)):
        return str(exc)[:500]
    return f"Xử lý chương thất bại ({type(exc).__name__}). Xem log máy chủ."


async def process_task(task, owner, translator):
    try:
        await ensure_work_is_active(task.id, owner)
        async with AsyncSessionLocal() as db:
            chapter = await db.get(Chapter, task.chapter_id)
            novel = await db.get(Novel, task.novel_id)
            terms = (await db.scalars(select(Glossary).where(
                (Glossary.novel_id == task.novel_id) | (Glossary.novel_id.is_(None))))).all()
        if chapter is None or novel is None:
            raise WorkInterrupted("Chương/truyện đã bị xóa.")
        glossary = [{"original_term": term.original_term, "translated_term": term.translated_term}
                    for term in terms]
        await emit_event(task.novel_id, "chapter_start", {"chapter_index": chapter.chapter_index,
            "title_raw": chapter.chapter_title_raw, "message": f"Đang dịch chương {chapter.chapter_index}."}, task.job_id)
        raw = chapter.content_raw
        if not raw:
            raw = (await get_crawler(novel.source_url).get_chapter_content(chapter.url))["content"]
            if not raw or not raw.strip():
                raise ValueError("Nguồn trả về nội dung chương trống.")
            async with AsyncSessionLocal() as db:
                values = {"content_raw": raw}
                if hasattr(Chapter, "raw_hash"):
                    values = {**values, "raw_hash": hashlib.sha256(raw.encode()).hexdigest()}
                await db.execute(update(Chapter).where(Chapter.id == chapter.id).values(**values))
                await db.commit()

        async def before_request(messages):
            await ensure_work_is_active(task.id, owner)
            # UTF-8 bytes upper-bound ordinary input tokens; add framing allowance.
            amount = sum(len(message["content"].encode()) for message in messages)
            return await reserve_tokens(amount + config.DEEPSEEK_MAX_TOKENS + 512)

        async def on_usage(result, reservation):
            await record_usage(task.chapter_id, result, reservation)

        result = await translator.translate_chapter(chapter.chapter_title_raw, raw, glossary_list=glossary,
            checkpoint=ChapterCheckpoints(chapter.id), before_request=before_request, on_usage=on_usage)
        issues = result.get("quality_issues", [])
        message = "; ".join(issues) if issues else None
        if await save_outcome(task, result, message, needs_review=bool(issues), owner=owner):
            await emit_event(task.novel_id, "chapter_error" if issues else "chapter_success", {
                "chapter_index": chapter.chapter_index, "title_raw": chapter.chapter_title_raw,
                "title_vi": result["title_vi"], "status": "needs_review" if issues else "completed",
                "message": message or f"Đã dịch xong chương {chapter.chapter_index}."}, task.job_id)
    except BudgetExceeded as exc:
        await restore_pending(task, budget_error=exc)
        await emit_event(task.novel_id, "error", {"message": str(exc), "status": "paused"}, task.job_id)
    except (WorkInterrupted, asyncio.CancelledError):
        await restore_pending(task)
        if asyncio.current_task().cancelling():
            raise
    except Exception as exc:
        logger.error("Translation task %s failed (%s)", task.id, type(exc).__name__)
        message = safe_error(exc)
        if await save_outcome(task, error=message, needs_review=isinstance(exc, TranslationOutputError), owner=owner):
            async with AsyncSessionLocal() as db:
                chapter_index = await db.scalar(select(Chapter.chapter_index).where(Chapter.id == task.chapter_id))
            await emit_event(task.novel_id, "chapter_error", {
                "chapter_index": chapter_index, "message": message}, task.job_id)


async def process_next(owner, translator=None):
    job_id, tasks = await claim_window(owner)
    if job_id is None:
        return False
    provider = translator or DeepSeekTranslator()
    await asyncio.gather(*(process_task(task, owner, provider) for task in tasks))
    await finish_job(job_id)
    return True
