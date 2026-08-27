"""SQL queue primitives. One leased worker owns all provider concurrency."""
import json
from datetime import timedelta

from sqlalchemy import delete, func, select, text, update

from app import config
from app.database import AsyncSessionLocal, dialect_insert
from app.models import Chapter
from app.translator.deepseek import PROMPT_VERSION
from app.translator.job_models import (DailyTokenBudget, TranslationCheckpoint,
    TranslationEvent, TranslationJob, TranslationTask, TranslationUsage, WorkerLease, utcnow)

ACTIVE_JOB_STATUSES = ("queued", "running", "paused")
ACTIVE_TASK_STATUSES = ("pending", "running")
LEASE_SECONDS = 90


class BudgetExceeded(RuntimeError):
    pass


class WorkInterrupted(RuntimeError):
    pass


def validate_concurrency(concurrency):
    if type(concurrency) is not int or not 1 <= concurrency <= config.MAX_CONCURRENT_TRANSLATIONS:
        raise ValueError(f"Concurrency phải từ 1 đến {config.MAX_CONCURRENT_TRANSLATIONS}.")


async def write_lock(db):
    # Serialize queue selection and insertion across web processes
    if "postgres" in str(config.DATABASE_URL):
        await db.execute(text("SELECT pg_advisory_xact_lock(424242)"))
    else:
        await db.execute(text("BEGIN IMMEDIATE"))


async def acquire_lease(owner):
    now = utcnow()
    async with AsyncSessionLocal() as db:
        await db.execute(dialect_insert(WorkerLease).values(id=1, owner=owner, expires_at=now)
                         .on_conflict_do_nothing(index_elements=["id"]))
        changed = await db.execute(update(WorkerLease).where(
            WorkerLease.id == 1, (WorkerLease.expires_at <= now) | (WorkerLease.owner == owner)
        ).values(owner=owner, expires_at=now + timedelta(seconds=LEASE_SECONDS)))
        await db.commit()
        return changed.rowcount == 1


async def renew_lease(owner):
    now = utcnow()
    async with AsyncSessionLocal() as db:
        changed = await db.execute(update(WorkerLease).where(
            WorkerLease.id == 1, WorkerLease.owner == owner, WorkerLease.expires_at > now
        ).values(expires_at=now + timedelta(seconds=LEASE_SECONDS)))
        await db.commit()
        return changed.rowcount == 1


async def release_lease(owner):
    async with AsyncSessionLocal() as db:
        await db.execute(delete(WorkerLease).where(WorkerLease.id == 1, WorkerLease.owner == owner))
        await db.commit()


async def lease_is_healthy(owner=None):
    async with AsyncSessionLocal() as db:
        query = select(WorkerLease.id).where(WorkerLease.id == 1, WorkerLease.expires_at > utcnow())
        if owner is not None:
            query = query.where(WorkerLease.owner == owner)
        return (await db.scalar(query)) is not None


async def recover_interrupted_work(owner):
    if not await lease_is_healthy(owner):
        raise WorkInterrupted("Worker không giữ lease.")
    async with AsyncSessionLocal() as db:
        await db.execute(update(TranslationTask).where(TranslationTask.status == "running")
                         .values(status="pending", updated_at=utcnow()))
        await db.execute(update(Chapter).where(Chapter.status == "translating").values(status="pending"))
        await db.execute(update(TranslationJob).where(TranslationJob.status == "running")
                         .values(status="queued", updated_at=utcnow()))
        await db.commit()


async def reserve_tokens(amount):
    if type(amount) is not int or amount < 1:
        raise ValueError("Token reservation must be positive")
    day = utcnow().date().isoformat()
    async with AsyncSessionLocal() as db:
        await db.execute(dialect_insert(DailyTokenBudget).values(day=day, reserved_tokens=0)
                         .on_conflict_do_nothing(index_elements=["day"]))
        result = await db.execute(update(DailyTokenBudget).where(
            DailyTokenBudget.day == day,
            DailyTokenBudget.reserved_tokens + amount <= config.TRANSLATION_DAILY_TOKEN_LIMIT
        ).values(reserved_tokens=DailyTokenBudget.reserved_tokens + amount))
        await db.commit()
    if result.rowcount != 1:
        raise BudgetExceeded("Đã đạt giới hạn token ngày (UTC). Job tạm dừng; quản trị viên có thể tiếp tục vào ngày sau.")
    return {"day": day, "amount": amount}


async def record_usage(chapter_id, result, reservation):
    actual = result.prompt_tokens + result.completion_tokens
    cost = (result.prompt_tokens * config.DEEPSEEK_INPUT_USD_PER_MILLION
            + result.completion_tokens * config.DEEPSEEK_OUTPUT_USD_PER_MILLION) / 1_000_000
    async with AsyncSessionLocal() as db:
        if reservation:
            # Persist any unexpected overage instead of hiding it with a clamp.
            await db.execute(update(DailyTokenBudget).where(DailyTokenBudget.day == reservation["day"])
                             .values(reserved_tokens=DailyTokenBudget.reserved_tokens - reservation["amount"] + actual))
        exists = await db.scalar(select(Chapter.id).where(Chapter.id == chapter_id))
        db.add(TranslationUsage(chapter_id=exists, request_id=result.request_id, model=result.model,
                                prompt_version=PROMPT_VERSION, prompt_tokens=result.prompt_tokens,
                                completion_tokens=result.completion_tokens, estimated_usd=cost))
        await db.commit()


class ChapterCheckpoints:
    def __init__(self, chapter_id):
        self.chapter_id = chapter_id

    async def load(self, cache_key):
        async with AsyncSessionLocal() as db:
            result = await db.scalar(select(TranslationCheckpoint.result).where(
                TranslationCheckpoint.chapter_id == self.chapter_id, TranslationCheckpoint.cache_key == cache_key))
        return json.loads(result) if result else None

    async def save(self, cache_key, result):
        async with AsyncSessionLocal() as db:
            if await db.get(Chapter, self.chapter_id) is None:
                raise WorkInterrupted("Chương đã bị xóa.")
            await db.execute(dialect_insert(TranslationCheckpoint).values(chapter_id=self.chapter_id,
                cache_key=cache_key, result=json.dumps(result, ensure_ascii=False))
                .on_conflict_do_nothing(index_elements=["chapter_id", "cache_key"]))
            await db.commit()


async def emit_event(novel_id, kind, data, job_id=None):
    aliases = {"chapter_success": "chapter_completed", "complete": "finished"}
    payload = {**data, "type": kind, "event": aliases.get(kind, kind),
               "timestamp": utcnow().isoformat() + "Z"}
    async with AsyncSessionLocal() as db:
        # A delete can race an in-flight request. Do not resurrect records or expose errors.
        from app.models import Novel
        if await db.get(Novel, novel_id) is None:
            return
        db.add(TranslationEvent(novel_id=novel_id, job_id=job_id, payload=json.dumps(payload, ensure_ascii=False)))
        await db.commit()


async def cancel_job(job_id):
    async with AsyncSessionLocal() as db:
        await write_lock(db)
        chapter_ids = select(TranslationTask.chapter_id).where(
            TranslationTask.job_id == job_id, TranslationTask.status.in_(ACTIVE_TASK_STATUSES))
        await db.execute(update(Chapter).where(Chapter.id.in_(chapter_ids), Chapter.status == "translating")
                         .values(status="pending"))
        await db.execute(update(TranslationTask).where(TranslationTask.job_id == job_id,
                         TranslationTask.status.in_(ACTIVE_TASK_STATUSES))
                         .values(status="cancelled", active_key=None, updated_at=utcnow()))
        await db.execute(update(TranslationJob).where(TranslationJob.id == job_id,
                         TranslationJob.status.in_(ACTIVE_JOB_STATUSES))
                         .values(status="cancelled", active_key=None, updated_at=utcnow()))
        await db.commit()


async def set_job_status(job_id, status):
    if status not in ("paused", "queued"):
        raise ValueError("Invalid queue state")
    async with AsyncSessionLocal() as db:
        await db.execute(update(TranslationJob).where(TranslationJob.id == job_id,
                         TranslationJob.status.in_(ACTIVE_JOB_STATUSES))
                         .values(status=status, error=None, updated_at=utcnow()))
        await db.commit()


async def finish_job(job_id):
    async with AsyncSessionLocal() as db:
        await write_lock(db)
        job = await db.get(TranslationJob, job_id)
        if job is None or job.status not in ("running", "queued"):
            return
        tasks = (await db.scalars(select(TranslationTask).where(TranslationTask.job_id == job_id))).all()
        if any(task.status in ACTIVE_TASK_STATUSES for task in tasks):
            return
        failed = sum(task.status == "error" for task in tasks)
        status = "completed_with_errors" if failed else "completed"
        await db.execute(update(TranslationJob).where(TranslationJob.id == job_id)
                         .values(status=status, active_key=None, updated_at=utcnow()))
        await db.commit()
    for novel_id in {task.novel_id for task in tasks}:
        selected = [task for task in tasks if task.novel_id == novel_id]
        completed = sum(task.status == "completed" for task in selected)
        errors = sum(task.status == "error" for task in selected)
        await emit_event(novel_id, "complete", {"status": status, "completed_count": completed,
            "failed_count": errors, "total_to_translate": len(selected),
            "message": f"Hoàn tất: {completed} chương thành công, {errors} chương cần kiểm tra."}, job_id)
