"""Web-facing durable translation queue API; never starts background web tasks."""
import asyncio
import json

from sqlalchemy import select, update

from app import config
from app.database import AsyncSessionLocal
from app.models import Chapter, Novel
from app.translator.deepseek import DeepSeekTranslator
from app.translator.job_models import TranslationEvent, TranslationJob, TranslationTask, utcnow
from app.translator.jobs import (ACTIVE_TASK_STATUSES, emit_event, validate_concurrency, write_lock)


class TranslationManager:
    def __init__(self):
        self.translator = DeepSeekTranslator()

    async def is_running(self, novel_id):
        async with AsyncSessionLocal() as db:
            return (await db.scalar(select(TranslationTask.id).where(
                TranslationTask.novel_id == novel_id, TranslationTask.active_key.is_not(None)).limit(1))) is not None

    async def start_translation(self, novel_id, start_chapter=1, end_chapter=None,
                                concurrency=None, retranslate_completed=False,
                                errors_only=False, chapter_ids=None, max_chapters=None):
        concurrency = config.MAX_CONCURRENT_TRANSLATIONS if concurrency is None else concurrency
        validate_concurrency(concurrency)
        if start_chapter < 1 or (end_chapter is not None and end_chapter < start_chapter):
            raise ValueError("Khoảng chương không hợp lệ.")
        if max_chapters is not None and (type(max_chapters) is not int or max_chapters < 1):
            raise ValueError("Giới hạn chương phải là số nguyên dương.")
        if chapter_ids is not None and any(type(i) is not int or i < 1 for i in chapter_ids):
            raise ValueError("ID chương không hợp lệ.")
        async with AsyncSessionLocal() as db:
            await write_lock(db)
            if await db.get(Novel, novel_id) is None:
                raise ValueError("Không tìm thấy truyện.")
            active = await db.scalar(select(TranslationTask.job_id).where(
                TranslationTask.novel_id == novel_id, TranslationTask.active_key.is_not(None)).limit(1))
            if active is not None:
                return {"status": "already_running", "job_id": active, "message": "Truyện đã có trong hàng đợi."}
            query = select(Chapter.id).where(Chapter.novel_id == novel_id, Chapter.chapter_index >= start_chapter)
            if end_chapter is not None:
                query = query.where(Chapter.chapter_index <= end_chapter)
            if chapter_ids is not None:
                query = query.where(Chapter.id.in_(chapter_ids))
            if errors_only:
                query = query.where(Chapter.status.in_(("error", "needs_review")))
            elif not retranslate_completed:
                query = query.where(Chapter.status != "completed")
            query = query.order_by(Chapter.chapter_index)
            if max_chapters is not None:
                query = query.limit(max_chapters)
            selected = list((await db.scalars(query)).all())
            if not selected:
                return {"status": "empty", "message": "Không có chương phù hợp để dịch.", "total_chapters": 0}
            job = TranslationJob(kind="novel", active_key=f"novel:{novel_id}", concurrency=concurrency)
            db.add(job)
            await db.flush()
            db.add_all([TranslationTask(job_id=job.id, novel_id=novel_id, chapter_id=chapter_id,
                                       active_key=str(chapter_id), position=index)
                        for index, chapter_id in enumerate(selected)])
            await db.commit()
        await emit_event(novel_id, "start", {"message": f"Đã xếp {len(selected)} chương vào hàng đợi.",
                                           "total_to_translate": len(selected)}, job.id)
        return {"status": "started", "job_id": job.id, "total_chapters": len(selected),
                "message": f"Đã xếp {len(selected)} chương vào hàng đợi."}

    async def stop_translation(self, novel_id):
        async with AsyncSessionLocal() as db:
            await write_lock(db)
            active = (await db.scalars(select(TranslationTask).where(
                TranslationTask.novel_id == novel_id, TranslationTask.status.in_(ACTIVE_TASK_STATUSES)))).all()
            chapter_ids = [task.chapter_id for task in active]
            await db.execute(update(Chapter).where(Chapter.id.in_(chapter_ids), Chapter.status == "translating")
                             .values(status="pending"))
            await db.execute(update(TranslationTask).where(TranslationTask.id.in_([task.id for task in active]))
                             .values(status="cancelled", active_key=None, updated_at=utcnow()))
            await db.execute(update(TranslationJob).where(TranslationJob.active_key == f"novel:{novel_id}")
                             .values(status="cancelled", active_key=None, updated_at=utcnow()))
            await db.commit()
        await emit_event(novel_id, "cancelled", {"message": "Đã hủy chương chưa hoàn tất. Request đang gửi có thể vẫn tính phí."})

    async def broadcast_event(self, novel_id, event_type, data):
        await emit_event(novel_id, event_type, data)

    async def iter_events(self, novel_id, after_id=0):
        """DB event replay works across processes and Last-Event-ID reconnects."""
        cursor = max(0, after_id)
        while True:
            async with AsyncSessionLocal() as db:
                events = (await db.scalars(select(TranslationEvent).where(
                    TranslationEvent.novel_id == novel_id, TranslationEvent.id > cursor)
                    .order_by(TranslationEvent.id).limit(100))).all()
            for event in events:
                cursor = event.id
                yield {**json.loads(event.payload), "id": event.id}
            if not events:
                yield {"type": "heartbeat", "event": "heartbeat", "timestamp": utcnow().isoformat() + "Z"}
                await asyncio.sleep(1)


translation_manager = TranslationManager()
