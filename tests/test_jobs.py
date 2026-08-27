import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models import Chapter, Novel


async def seed_novel(count=4, statuses=None):
    async with AsyncSessionLocal() as db:
        novel = Novel(title="Fixture", source_url="https://www.piaotia.com/html/1/1/index.html")
        db.add(novel)
        await db.flush()
        chapters = [Chapter(novel_id=novel.id, chapter_index=i + 1,
                            chapter_title_raw=f"第{i + 1}章", content_raw="这是正文。",
                            url=f"https://www.piaotia.com/html/1/1/{i + 1}.html",
                            status=statuses[i] if statuses else "pending") for i in range(count)]
        db.add_all(chapters)
        await db.commit()
        return novel.id, [chapter.id for chapter in chapters]


@pytest.mark.asyncio
async def test_batch_limit_is_real_and_round_robin_order():
    from app.translator.batch_manager import BatchTranslationManager
    from app.translator.job_models import TranslationTask
    first, first_ids = await seed_novel()
    second, second_ids = await seed_novel()
    result = await BatchTranslationManager().start_batch(
        novel_ids=[first, second], policy="round_robin", chapters_per_novel=2)
    async with AsyncSessionLocal() as db:
        ids = list((await db.scalars(select(TranslationTask.chapter_id).where(
            TranslationTask.job_id == result["job_id"]).order_by(TranslationTask.position))).all())
    assert ids == [first_ids[0], second_ids[0], first_ids[1], second_ids[1]]


@pytest.mark.asyncio
async def test_enqueued_work_survives_manager_recreation_and_filters_errors():
    from app.translator.worker import TranslationManager
    from app.translator.job_models import TranslationTask
    novel_id, ids = await seed_novel(3, ["error", "pending", "completed"])
    first = await TranslationManager().start_translation(novel_id, errors_only=True)
    assert await TranslationManager().is_running(novel_id)
    second = await TranslationManager().start_translation(novel_id)
    assert second["status"] == "already_running"
    async with AsyncSessionLocal() as db:
        chosen = list((await db.scalars(select(TranslationTask.chapter_id))).all())
    assert chosen == [ids[0]]
    assert first["status"] == "started"


@pytest.mark.asyncio
async def test_worker_lease_excludes_second_worker_and_recovers_expired():
    from app.translator.jobs import acquire_lease, release_lease
    from app.translator.job_models import WorkerLease
    assert await acquire_lease("worker-a")
    assert not await acquire_lease("worker-b")
    async with AsyncSessionLocal() as db:
        await db.execute(update(WorkerLease).values(expires_at=datetime(2000, 1, 1)))
        await db.commit()
    assert await acquire_lease("worker-b")
    await release_lease("worker-a")
    assert not await acquire_lease("worker-c")


@pytest.mark.asyncio
async def test_pause_resume_cancel_are_persisted():
    from app.translator.batch_manager import BatchTranslationManager
    from app.translator.job_models import TranslationTask
    await seed_novel()
    await BatchTranslationManager().start_batch()
    await BatchTranslationManager().pause()
    assert (await BatchTranslationManager().get_status())["is_paused"]
    await BatchTranslationManager().resume()
    assert not (await BatchTranslationManager().get_status())["is_paused"]
    await BatchTranslationManager().stop()
    assert not (await BatchTranslationManager().get_status())["is_running"]
    async with AsyncSessionLocal() as db:
        assert all(task.active_key is None for task in (await db.scalars(select(TranslationTask))).all())


@pytest.mark.asyncio
async def test_daily_budget_reservations_are_atomic(monkeypatch):
    from app.translator import jobs
    monkeypatch.setattr(jobs.config, "TRANSLATION_DAILY_TOKEN_LIMIT", 100)
    results = await asyncio.gather(jobs.reserve_tokens(60), jobs.reserve_tokens(60), return_exceptions=True)
    assert sum(not isinstance(value, Exception) for value in results) == 1
    assert any(isinstance(value, jobs.BudgetExceeded) for value in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("concurrency", [0, -1, 10000])
async def test_translation_rejects_invalid_concurrency(concurrency):
    from app.translator.worker import TranslationManager
    with pytest.raises(ValueError):
        await TranslationManager().start_translation(1, concurrency=concurrency)


@pytest.mark.asyncio
async def test_dispatcher_completes_job_and_records_usage(monkeypatch):
    import httpx
    from app.translator.dispatcher import process_next
    from app.translator.jobs import acquire_lease
    from app.translator.worker import TranslationManager
    from app.translator.job_models import TranslationJob, TranslationUsage
    from app.translator.deepseek import DeepSeekTranslator

    async def post(client, url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "id": "unit-request", "model": "deepseek-v4-flash", "usage": {"prompt_tokens": 8, "completion_tokens": 12},
            "choices": [{"finish_reason": "stop", "message": {"content": "Chương 1\n\nĐây là nội dung."}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    novel_id, ids = await seed_novel(1)
    result = await TranslationManager().start_translation(novel_id)
    assert await acquire_lease("unit-worker")
    assert await process_next("unit-worker", DeepSeekTranslator(api_key="fake"))
    async with AsyncSessionLocal() as db:
        assert (await db.get(Chapter, ids[0])).status == "completed"
        assert (await db.get(Novel, novel_id)).translated_chapters == 1
        assert (await db.get(TranslationJob, result["job_id"])).status == "completed"
        usage = await db.scalar(select(TranslationUsage))
        assert usage.prompt_tokens == 8
        assert usage.estimated_usd > 0


@pytest.mark.asyncio
async def test_raw_is_saved_even_when_provider_fails(monkeypatch):
    from types import SimpleNamespace
    from app.translator import dispatcher
    from app.translator.jobs import acquire_lease
    from app.translator.worker import TranslationManager
    from app.translator.job_models import TranslationJob
    novel_id, ids = await seed_novel(1)
    async with AsyncSessionLocal() as db:
        await db.execute(update(Chapter).where(Chapter.id == ids[0]).values(content_raw=None))
        await db.commit()
    monkeypatch.setattr(dispatcher, "get_crawler", lambda url: SimpleNamespace(
        get_chapter_content=AsyncMock(return_value={"content": "刚保存的原文"})))
    provider = SimpleNamespace(translate_chapter=AsyncMock(side_effect=ValueError("Provider failed")))
    queued = await TranslationManager().start_translation(novel_id)
    await acquire_lease("unit-worker")
    await dispatcher.process_next("unit-worker", provider)
    async with AsyncSessionLocal() as db:
        chapter = await db.get(Chapter, ids[0])
        assert chapter.content_raw == "刚保存的原文"
        assert chapter.status == "error"
        assert (await db.get(TranslationJob, queued["job_id"])).status == "completed_with_errors"


@pytest.mark.asyncio
async def test_restart_recovers_claim_and_stale_owner_cannot_publish():
    from app.translator.dispatcher import claim_window, save_outcome
    from app.translator.jobs import acquire_lease, recover_interrupted_work
    from app.translator.worker import TranslationManager
    from app.translator.job_models import WorkerLease
    novel_id, ids = await seed_novel(1)
    await TranslationManager().start_translation(novel_id)
    await acquire_lease("old-worker")
    _, old_tasks = await claim_window("old-worker")
    async with AsyncSessionLocal() as db:
        await db.execute(update(WorkerLease).values(expires_at=datetime(2000, 1, 1)))
        await db.commit()
    await acquire_lease("new-worker")
    await recover_interrupted_work("new-worker")
    await claim_window("new-worker")
    assert not await save_outcome(old_tasks[0], owner="old-worker",
                                  result={"title_vi": "Stale", "content_vi": "Stale"})
    async with AsyncSessionLocal() as db:
        assert (await db.get(Chapter, ids[0])).content_vi is None


@pytest.mark.asyncio
async def test_paused_batch_claims_nothing_and_cancel_does_not_publish():
    from app.translator.batch_manager import BatchTranslationManager
    from app.translator.dispatcher import claim_window, save_outcome
    from app.translator.jobs import acquire_lease
    await seed_novel(2)
    manager = BatchTranslationManager()
    await manager.start_batch(concurrency=1)
    await acquire_lease("unit-worker")
    _, tasks = await claim_window("unit-worker")
    await manager.pause()
    assert await claim_window("unit-worker") == (None, [])
    await manager.stop()
    assert not await save_outcome(tasks[0], owner="unit-worker", result={"title_vi": "Canceled", "content_vi": "Canceled"})


@pytest.mark.asyncio
async def test_checkpoint_reuse_does_not_call_provider_twice(monkeypatch):
    from app.translator.deepseek import Completion, DeepSeekTranslator
    from app.translator.jobs import ChapterCheckpoints
    _, ids = await seed_novel(1)
    provider = DeepSeekTranslator(api_key="fake")
    call = AsyncMock(return_value=Completion("Chương 1\n\nMột bản dịch.", "deepseek-v4-flash", "req", 10, 8, "stop"))
    monkeypatch.setattr(provider, "_call_api", call)
    checkpoint = ChapterCheckpoints(ids[0])
    first = await provider.translate_chapter("第一章", "这是正文。", checkpoint=checkpoint)
    second = await provider.translate_chapter("第一章", "这是正文。", checkpoint=checkpoint)
    assert first["content_vi"] == second["content_vi"]
    assert call.await_count == 1
    await provider.translate_chapter("第一章", "原文已改变。", checkpoint=checkpoint)
    assert call.await_count == 2


@pytest.mark.asyncio
async def test_sse_event_replays_from_database():
    from app.translator.worker import TranslationManager
    novel_id, _ = await seed_novel(1)
    await TranslationManager().broadcast_event(novel_id, "chapter_success", {"chapter_index": 1})
    events = TranslationManager().iter_events(novel_id)
    event = await anext(events)
    await events.aclose()
    assert event["type"] == "chapter_success"
    assert event["event"] == "chapter_completed"
    assert event["id"] > 0


@pytest.mark.asyncio
async def test_request_exceeding_daily_budget_pauses_without_calling_api(monkeypatch):
    from app.translator import jobs
    from app.translator.deepseek import DeepSeekTranslator
    from app.translator.dispatcher import process_next
    from app.translator.worker import TranslationManager
    from app.translator.job_models import TranslationJob
    monkeypatch.setattr(jobs.config, "TRANSLATION_DAILY_TOKEN_LIMIT", 1)
    novel_id, ids = await seed_novel(1)
    queued = await TranslationManager().start_translation(novel_id)
    await jobs.acquire_lease("unit-worker")
    await process_next("unit-worker", DeepSeekTranslator(api_key="fake"))
    async with AsyncSessionLocal() as db:
        assert (await db.get(TranslationJob, queued["job_id"])).status == "paused"
        assert (await db.get(Chapter, ids[0])).status == "pending"
