"""Durable batch selection: chapter limits are real; round-robin interleaves IDs."""
from itertools import zip_longest

from sqlalchemy import desc, select

from app import config
from app.database import AsyncSessionLocal
from app.models import Chapter, Novel
from app.translator.job_models import TranslationEvent, TranslationJob, TranslationTask
from app.translator.jobs import (ACTIVE_JOB_STATUSES, cancel_job, set_job_status,
                                 validate_concurrency, write_lock)


class BatchTranslationManager:
    async def start_batch(self, novel_ids=None, policy="request_priority", concurrency=None,
                          chapters_per_novel=None):
        concurrency = config.MAX_CONCURRENT_TRANSLATIONS if concurrency is None else concurrency
        validate_concurrency(concurrency)
        if policy not in {"request_priority", "all_pending", "round_robin"}:
            raise ValueError("Chính sách dịch không hợp lệ.")
        if chapters_per_novel is not None and (type(chapters_per_novel) is not int or chapters_per_novel < 1):
            raise ValueError("Giới hạn chương phải là số nguyên dương.")
        async with AsyncSessionLocal() as db:
            await write_lock(db)
            current = await db.scalar(select(TranslationJob).where(TranslationJob.active_key == "batch"))
            if current is not None:
                return {"status": "already_running", "job_id": current.id}
            query = select(Novel)
            if novel_ids is not None:
                query = query.where(Novel.id.in_(novel_ids))
            query = (query.order_by(desc(Novel.request_count), desc(Novel.favorite_count), Novel.id)
                     if policy == "request_priority" else query.order_by(Novel.id))
            novels = (await db.scalars(query)).all()
            groups = []
            for novel in novels:
                chapter_query = select(Chapter.id).where(Chapter.novel_id == novel.id,
                    Chapter.status != "completed", ~Chapter.id.in_(select(TranslationTask.chapter_id)
                    .where(TranslationTask.active_key.is_not(None)))).order_by(Chapter.chapter_index)
                if chapters_per_novel is not None:
                    chapter_query = chapter_query.limit(chapters_per_novel)
                ids = list((await db.scalars(chapter_query)).all())
                if ids:
                    groups = [*groups, [(novel.id, chapter_id) for chapter_id in ids]]
            ordered = ([item for row in zip_longest(*groups) for item in row if item is not None]
                       if policy == "round_robin" else [item for group in groups for item in group])
            if not ordered:
                return {"status": "empty", "total_chapters": 0, "queue_count": 0}
            job = TranslationJob(kind="batch", active_key="batch", policy=policy, concurrency=concurrency)
            db.add(job)
            await db.flush()
            db.add_all([TranslationTask(job_id=job.id, novel_id=novel_id, chapter_id=chapter_id,
                                       active_key=str(chapter_id), position=position)
                        for position, (novel_id, chapter_id) in enumerate(ordered)])
            await db.commit()
        return {"status": "started", "job_id": job.id, "total_chapters": len(ordered), "queue_count": len(groups)}

    async def _latest(self):
        async with AsyncSessionLocal() as db:
            return await db.scalar(select(TranslationJob).where(TranslationJob.kind == "batch")
                                   .order_by(TranslationJob.id.desc()).limit(1))

    async def get_status(self):
        job = await self._latest()
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(TranslationTask, Chapter.chapter_index, Novel.title, Novel.title_vi)
                .join(Chapter, Chapter.id == TranslationTask.chapter_id).join(Novel, Novel.id == TranslationTask.novel_id)
                .where(TranslationTask.job_id == (job.id if job else -1)).order_by(TranslationTask.position))).all()
        queue = []
        for novel_id in dict.fromkeys(row[0].novel_id for row in rows):
            selected = [row for row in rows if row[0].novel_id == novel_id]
            states = [row[0].status for row in selected]
            queue = [*queue, {"novel_id": novel_id, "title": selected[0][3] or selected[0][2],
                "pending_chapters": states.count("pending") + states.count("running"),
                "completed_chapters": states.count("completed"), "failed_chapters": states.count("error"),
                "status": "translating" if "running" in states else ("waiting" if "pending" in states else "completed")}]
        running = next((row for row in rows if row[0].status == "running"), None)
        processed = sum(row[0].status in ("completed", "error") for row in rows)
        return {"job_id": job.id if job else None, "status": job.status if job else "idle",
            "is_running": bool(job and job.status in ACTIVE_JOB_STATUSES),
            "is_paused": bool(job and job.status == "paused"), "policy": job.policy if job else "request_priority",
            "concurrency": job.concurrency if job else config.MAX_CONCURRENT_TRANSLATIONS,
            "current_novel_id": running[0].novel_id if running else None,
            "current_novel_title": (running[3] or running[2]) if running else None,
            "current_chapter": running[1] if running else None, "queue_length": len(queue), "queue": queue,
            "total_queued_chapters": len(rows), "processed_chapters": processed,
            "failed_chapters": sum(row[0].status == "error" for row in rows),
            "recent_logs": [{"time": "", "level": "error", "message": job.error}] if job and job.error else []}

    async def pause(self):
        job = await self._latest()
        if job:
            await set_job_status(job.id, "paused")

    async def resume(self):
        job = await self._latest()
        if job:
            await set_job_status(job.id, "queued")

    async def stop(self):
        job = await self._latest()
        if job:
            await cancel_job(job.id)


batch_manager = BatchTranslationManager()
