"""Crawler policy/parser fixtures never contact external sources."""
import asyncio
from unittest.mock import AsyncMock

import datetime

import pytest

from app.crawler import get_crawler
from app.crawler.biquge import BiqugeCrawler
from app.crawler.piaotia import PiaotiaCrawler


@pytest.mark.parametrize("url", [
    "https://evil.example/?piaotia.com", "http://www.piaotia.com/html/1/2/",
    "https://www.piaotia.com:8443/", "https://user@www.piaotia.com/",
    "https://127.0.0.1/", "https://www.piaotia.com.evil.example/",
])
def test_unapproved_sources_fail_closed(url):
    with pytest.raises(ValueError):
        get_crawler(url)


@pytest.mark.asyncio
async def test_biquge_joins_links_and_rejects_external_links(monkeypatch):
    monkeypatch.setenv("CRAWLER_ALLOWED_HOSTS", "www.piaotia.com,books.example")
    crawler = BiqugeCrawler()
    monkeypatch.setattr(crawler, "fetch_html", AsyncMock(return_value='''
      <div id="list"><a href="/book/42/1.html">第一章</a>
      <a href="2.html">第二章</a><a href="https://evil.example/3.html">广告</a>
      <a href="/book/42/1.html#top">duplicate</a></div>'''), raising=False)
    chapters = await crawler.get_chapter_list("https://books.example/book/42/index.html")
    assert [item["url"] for item in chapters] == [
        "https://books.example/book/42/1.html", "https://books.example/book/42/2.html"]


@pytest.mark.asyncio
async def test_piaotia_catalog_only_contains_same_book(monkeypatch):
    crawler = PiaotiaCrawler()
    monkeypatch.setattr(crawler, "fetch_html", AsyncMock(return_value='''
      <a href="/html/1/2/101.html">一</a><a href="102.html">二</a>
      <a href="/html/9/9/1.html">other book</a><a href="/index.html">home</a>
      <a href="//evil.example/103.html">external</a>'''), raising=False)
    chapters = await crawler.get_chapter_list("https://www.piaotia.com/html/1/2/")
    assert [item["url"] for item in chapters] == [
        "https://www.piaotia.com/html/1/2/101.html", "https://www.piaotia.com/html/1/2/102.html"]


@pytest.mark.asyncio
@pytest.mark.parametrize("crawler", [PiaotiaCrawler, BiqugeCrawler])
async def test_missing_content_is_error_not_success(monkeypatch, crawler):
    instance = crawler()
    monkeypatch.setattr(instance, "fetch_html", AsyncMock(return_value="<h1>Access denied</h1>"), raising=False)
    with pytest.raises(ValueError, match="content|nội dung"):
        await instance.get_chapter_content("https://www.piaotia.com/html/1/2/1.html")


@pytest.mark.asyncio
async def test_sync_persists_raw_and_preserves_indices_when_catalog_shifts(monkeypatch, db, sample_novel):
    from sqlalchemy import select
    from app.models import Chapter
    from app.crawler.auto_updater import AutoUpdater
    crawler = AsyncMock()
    crawler.get_chapter_list.return_value = [
        {"index": 1, "title": "New preface", "url": "https://www.piaotia.com/html/1/1/99.html"},
        {"index": 2, "title": "一", "url": "https://www.piaotia.com/html/1/1/1.html"},
        {"index": 3, "title": "二", "url": "https://www.piaotia.com/html/1/1/2.html"},
    ]
    crawler.get_chapter_content.return_value = {"title": "原文", "content": "新版本原文"}
    monkeypatch.setattr("app.crawler.auto_updater.get_crawler", lambda _: crawler)
    updater = AutoUpdater()
    first = await updater.sync_single_novel(sample_novel.id)
    second = await updater.sync_single_novel(sample_novel.id)
    novel_id = sample_novel.id
    db.expire_all()
    rows = list((await db.execute(select(Chapter).where(Chapter.novel_id == novel_id)
                                 .order_by(Chapter.chapter_index))).scalars())
    assert first["new_chapters"] == 1 and second["new_chapters"] == 0
    assert [row.url.rsplit("/", 1)[-1] for row in rows] == ["1.html", "2.html", "99.html"]
    assert all(row.content_raw == "新版本原文" and row.raw_hash and row.raw_fetched_at for row in rows)
    assert rows[0].content_vi == "Nội dung tiếng Việt" and rows[0].status == "completed"
    assert rows[0].source_changed is True


@pytest.mark.asyncio
async def test_parallel_sync_fetches_one_catalog_only(monkeypatch, sample_novel):
    from app.crawler.auto_updater import AutoUpdater
    crawler = AsyncMock()
    started, release = asyncio.Event(), asyncio.Event()

    async def catalog(_):
        started.set()
        await release.wait()
        return [{"index": 1, "title": "一", "url": "https://www.piaotia.com/html/1/1/1.html"}]

    crawler.get_chapter_list.side_effect = catalog
    crawler.get_chapter_content.return_value = {"title": "一", "content": "正文"}
    monkeypatch.setattr("app.crawler.auto_updater.get_crawler", lambda _: crawler)
    first = asyncio.create_task(AutoUpdater().sync_single_novel(sample_novel.id))
    await asyncio.wait_for(started.wait(), 2)
    second = await AutoUpdater().sync_single_novel(sample_novel.id)
    release.set()
    await first
    assert second["status"] == "busy"
    assert crawler.get_chapter_list.await_count == 1


@pytest.mark.asyncio
async def test_sync_reports_raw_failure_without_erasing_translation(monkeypatch, sample_novel, db):
    from sqlalchemy import select
    from app.models import Chapter
    from app.crawler.auto_updater import AutoUpdater
    crawler = AsyncMock()
    crawler.get_chapter_list.return_value = [{"index": 1, "title": "一", "url": "https://www.piaotia.com/html/1/1/1.html"}]
    crawler.get_chapter_content.side_effect = ValueError("missing content")
    monkeypatch.setattr("app.crawler.auto_updater.get_crawler", lambda _: crawler)
    result = await AutoUpdater().sync_single_novel(sample_novel.id)
    row = (await db.execute(select(Chapter).where(Chapter.novel_id == sample_novel.id, Chapter.chapter_index == 1))).scalar_one()
    assert result["status"] == "partial" and result["raw_errors"] == 1
    assert row.content_vi == "Nội dung tiếng Việt" and row.status == "completed"


@pytest.mark.asyncio
async def test_sync_settings_survive_new_updater_instance():
    from app.crawler.auto_updater import AutoUpdater
    updater = AutoUpdater()
    await updater.configure(enabled=False, interval_seconds=600, auto_translate=True)
    restarted = AutoUpdater()
    await restarted.load_settings()
    assert (restarted.is_enabled, restarted.interval_seconds, restarted.auto_translate_on_sync) == (False, 600, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fe80::1", "::ffff:127.0.0.1"])
async def test_dns_private_answers_fail_closed(monkeypatch, address):
    from app.crawler.security import resolve_public_addresses
    resolver = AsyncMock(return_value=[(0, 0, 0, "", (address, 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    with pytest.raises(ValueError):
        await resolve_public_addresses("www.piaotia.com")


@pytest.mark.asyncio
async def test_transport_pins_connection_ip_and_preserves_tls_identity(monkeypatch):
    import httpx
    from app.crawler.security import PinnedTransport
    resolver = AsyncMock(return_value=("8.8.8.8",))
    monkeypatch.setattr("app.crawler.security.resolve_public_addresses", resolver)
    transport = PinnedTransport()
    sender = AsyncMock(return_value=httpx.Response(200, text="ok"))
    monkeypatch.setattr(transport.transport, "handle_async_request", sender)
    original = httpx.Request("GET", "https://www.piaotia.com/html/1/1/1.html")
    await transport.handle_async_request(original)
    sent = sender.call_args.args[0]
    assert sent.url.host == "8.8.8.8"
    assert sent.headers["host"] == sent.extensions["sni_hostname"] == "www.piaotia.com"
    assert original.url.host == "www.piaotia.com"
    await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["https://127.0.0.1/", "https://evil.example/", "http://www.piaotia.com/", "https://user@www.piaotia.com/"])
async def test_redirect_is_revalidated_before_following(monkeypatch, location):
    import httpx
    from app.crawler.security import _fetch_redirects
    monkeypatch.setattr("app.crawler.security._rate_limit", AsyncMock())
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": location})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await _fetch_redirects(client, "https://www.piaotia.com/", "utf-8")
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["declared", "streamed", "encoding", "type", "status"])
async def test_source_response_limits(monkeypatch, mode):
    import httpx
    from app.crawler.security import _fetch_redirects
    monkeypatch.setattr("app.crawler.security._rate_limit", AsyncMock())
    monkeypatch.setattr("app.crawler.security.MAX_RESPONSE_BYTES", 10)
    headers = {"content-type": "text/html"}
    if mode == "declared":
        headers["content-length"] = "1000000"
    if mode == "encoding":
        headers["content-encoding"] = "unsupported"
    if mode == "type":
        headers["content-type"] = "application/pdf"
    response = httpx.Response(403 if mode == "status" else 200, headers=headers,
                              content=b"x" * (20 if mode == "streamed" else 2))
    if mode == "streamed":
        del response.headers["content-length"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            await _fetch_redirects(client, "https://www.piaotia.com/", "utf-8")


@pytest.mark.asyncio
async def test_relative_redirect_and_legacy_encoding(monkeypatch):
    import httpx
    from app.crawler.security import _fetch_redirects
    monkeypatch.setattr("app.crawler.security._rate_limit", AsyncMock())
    responses = iter([httpx.Response(302, headers={"location": "next.html"}),
                      httpx.Response(200, content="原文".encode("gbk"))])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(responses))) as client:
        assert await _fetch_redirects(client, "https://www.piaotia.com/html/index.html", "utf-8") == "原文"


@pytest.mark.asyncio
@pytest.mark.parametrize("crawler", [PiaotiaCrawler, BiqugeCrawler])
async def test_metadata_and_content_fixtures(monkeypatch, crawler):
    instance = crawler()
    monkeypatch.setattr(instance, "fetch_html", AsyncMock(return_value='''
      <h1>测试小说</h1><p>作者：测试作者</p><td>作者：测试作者</td>
      <div id="intro">介绍</div><span class="hottext">介绍</span>
      <div class="cover"><img src="/files/article/image/1/2.jpg"></div>'''))
    info = await instance.get_novel_info("https://www.piaotia.com/html/1/2/index.html")
    assert info["title"] == "测试小说" and info["author"] == "测试作者"
    assert info["cover_url"] == "https://www.piaotia.com/files/article/image/1/2.jpg"
    monkeypatch.setattr(instance, "fetch_html", AsyncMock(return_value='''
      <h1>第一章</h1><div id="content">第一段<br/>第二段<script>evil()</script><a>广告</a></div>'''))
    chapter = await instance.get_chapter_content("https://www.piaotia.com/html/1/2/1.html")
    assert chapter == {"title": "第一章", "content": "第一段\n\n第二段"}


@pytest.mark.asyncio
@pytest.mark.parametrize("crawler", [PiaotiaCrawler, BiqugeCrawler])
async def test_empty_catalog_is_an_error(monkeypatch, crawler):
    instance = crawler()
    monkeypatch.setattr(instance, "fetch_html", AsyncMock(return_value="<h1>Forbidden</h1>"))
    with pytest.raises(ValueError):
        await instance.get_chapter_list("https://www.piaotia.com/html/1/2/index.html")


@pytest.mark.asyncio
async def test_sync_limit_and_auto_translate_only_ready_raw(monkeypatch, db):
    from app.models import Novel
    from app.crawler.auto_updater import AutoUpdater
    novel = Novel(title="测试", source_url="https://www.piaotia.com/html/1/1/index.html")
    db.add(novel)
    await db.commit()
    crawler = AsyncMock()
    crawler.get_chapter_list.return_value = [
        {"index": i, "title": f"章{i}", "url": f"https://www.piaotia.com/html/1/1/{i}.html"} for i in range(1, 4)]
    crawler.get_chapter_content.return_value = {"title": "章", "content": "正文"}
    enqueue = AsyncMock()
    monkeypatch.setenv("CRAWLER_MAX_RAW_PER_SYNC", "1")
    monkeypatch.setattr("app.crawler.auto_updater.get_crawler", lambda _: crawler)
    monkeypatch.setattr("app.translator.worker.translation_manager.start_translation", enqueue)
    result = await AutoUpdater().sync_single_novel(novel.id, auto_translate=True)
    assert result["raw_fetched"] == 1 and result["raw_remaining"] == 2 and result["status"] == "partial"
    assert len(enqueue.call_args.kwargs["chapter_ids"]) == 1


@pytest.mark.asyncio
async def test_fresh_raw_is_not_refetched(monkeypatch, db):
    """A finished novel must stop hitting the source.

    Ordering by ``raw_fetched_at`` alone always yields the oldest rows, so every
    run refetched the same chapters forever even when nothing had changed.
    """
    from app.models import Chapter, Novel
    from app.crawler.auto_updater import AutoUpdater
    from app.crawler.sync_store import utcnow
    novel = Novel(title="测试", source_url="https://www.piaotia.com/html/2/2/index.html")
    db.add(novel)
    await db.commit()
    urls = [f"https://www.piaotia.com/html/2/2/{i}.html" for i in range(1, 4)]
    db.add_all([Chapter(novel_id=novel.id, chapter_index=i + 1, chapter_title_raw=f"章{i + 1}",
                        url=url, content_raw="正文", raw_fetched_at=utcnow())
                for i, url in enumerate(urls)])
    await db.commit()

    crawler = AsyncMock()
    crawler.get_chapter_list.return_value = [
        {"index": i + 1, "title": f"章{i + 1}", "url": url} for i, url in enumerate(urls)]
    monkeypatch.setattr("app.crawler.auto_updater.get_crawler", lambda _: crawler)
    result = await AutoUpdater().sync_single_novel(novel.id, auto_translate=False)

    assert result["raw_fetched"] == 0 and result["raw_remaining"] == 0
    assert result["status"] == "success"
    crawler.get_chapter_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_raw_is_fetched_before_stale_refresh(monkeypatch, db):
    from app.models import Chapter, Novel
    from app.crawler.auto_updater import AutoUpdater
    from app.crawler.sync_store import utcnow
    novel = Novel(title="测试", source_url="https://www.piaotia.com/html/3/3/index.html")
    db.add(novel)
    await db.commit()
    stale_url = "https://www.piaotia.com/html/3/3/1.html"
    missing_url = "https://www.piaotia.com/html/3/3/2.html"
    db.add_all([
        Chapter(novel_id=novel.id, chapter_index=1, chapter_title_raw="章1", url=stale_url,
                content_raw="旧", raw_fetched_at=utcnow() - datetime.timedelta(days=90)),
        Chapter(novel_id=novel.id, chapter_index=2, chapter_title_raw="章2", url=missing_url),
    ])
    await db.commit()

    crawler = AsyncMock()
    crawler.get_chapter_list.return_value = [
        {"index": 1, "title": "章1", "url": stale_url}, {"index": 2, "title": "章2", "url": missing_url}]
    crawler.get_chapter_content.return_value = {"title": "章", "content": "正文"}
    monkeypatch.setenv("CRAWLER_MAX_RAW_PER_SYNC", "1")
    monkeypatch.setattr("app.crawler.auto_updater.get_crawler", lambda _: crawler)
    result = await AutoUpdater().sync_single_novel(novel.id, auto_translate=False)

    assert result["raw_fetched"] == 1 and result["raw_remaining"] == 0
    assert crawler.get_chapter_content.await_args.args[0] == missing_url


@pytest.mark.asyncio
async def test_raw_backfill_stops_at_the_storage_budget(monkeypatch, db):
    """Raw text is ~10x a catalog row, so an unattended backfill fills a free
    tier in under a day. The catalog must keep syncing when that happens."""
    from app.models import Chapter, Novel
    from app.crawler.auto_updater import AutoUpdater
    novel = Novel(title="测试", source_url="https://www.piaotia.com/html/4/4/index.html")
    db.add(novel)
    await db.commit()
    url = "https://www.piaotia.com/html/4/4/1.html"
    new_url = "https://www.piaotia.com/html/4/4/2.html"
    db.add(Chapter(novel_id=novel.id, chapter_index=1, chapter_title_raw="章1", url=url))
    await db.commit()

    crawler = AsyncMock()
    crawler.get_chapter_list.return_value = [
        {"index": 1, "title": "章1", "url": url}, {"index": 2, "title": "章2", "url": new_url}]
    monkeypatch.setattr("app.crawler.auto_updater.get_crawler", lambda _: crawler)
    monkeypatch.setattr("app.crawler.auto_updater.storage_used_mb", AsyncMock(return_value=9000.0))
    monkeypatch.setenv("CRAWLER_RAW_BUDGET_MB", "400")
    result = await AutoUpdater().sync_single_novel(novel.id, auto_translate=False)

    crawler.get_chapter_content.assert_not_awaited()
    assert result["raw_budget_reached"] is True and result["raw_fetched"] == 0
    # The new chapter is still recorded, so the novel keeps listing it.
    assert result["new_chapters"] == 1 and result["total_chapters"] == 2


def test_backfill_shortens_the_delay_only_while_progressing():
    from app.crawler.auto_updater import BACKFILL_INTERVAL_SECONDS, AutoUpdater
    updater = AutoUpdater()
    updater.interval_seconds = 1800
    updater.last_sync_stats = {"raw_remaining": 400, "raw_fetched": 60}
    assert updater._next_delay() == BACKFILL_INTERVAL_SECONDS
    # A source that only errors must not be polled every minute.
    updater.last_sync_stats = {"raw_remaining": 400, "raw_fetched": 0}
    assert updater._next_delay() == 1800
    updater.last_sync_stats = {"raw_remaining": 0, "raw_fetched": 60}
    assert updater._next_delay() == 1800


# --- Cross-platform deduplication ------------------------------------------

@pytest.mark.parametrize("title,author", [
    ("《凡人修仙传》最新章节", "忘语 著"),
    ("凡人修仙传_笔趣阁", "忘语"),
    ("凡人修仙传 全文阅读", " 忘语　"),
    ("凡人修仙传（无弹窗）", "忘语著"),
])
def test_mirrors_of_one_work_share_a_fingerprint(title, author):
    from app.crawler.identity import work_key
    assert work_key(title, author) == work_key("凡人修仙传", "忘语")


def test_different_works_and_authors_do_not_collide():
    from app.crawler.identity import work_key
    assert work_key("凡人修仙传", "忘语") != work_key("斗破苍穹", "忘语")
    assert work_key("凡人修仙传", "忘语") != work_key("凡人修仙传", "天蚕土豆")


@pytest.mark.parametrize("title", ["", "   ", "《》", "最新章节"])
def test_unparsed_titles_never_produce_a_shared_key(title):
    from app.crawler.identity import work_key
    assert work_key(title, "作者") == ""


def _fake_crawler(title, author, catalog_url, source_name):
    from types import SimpleNamespace
    return SimpleNamespace(
        get_novel_info=AsyncMock(return_value={
            "title": title, "author": author, "description": "", "cover_url": "",
            "source_url": catalog_url, "source_name": source_name, "catalog_url": catalog_url}),
        get_chapter_list=AsyncMock(return_value=[
            {"title": "第一章", "url": catalog_url.rsplit("/", 1)[0] + "/1.html", "index": 1}]),
        get_chapter_content=AsyncMock(return_value={"title": "第一章", "content": "正文"}),
    )


@pytest.mark.asyncio
async def test_second_platform_is_reported_as_duplicate_not_imported(monkeypatch, admin_client):
    from sqlalchemy import func, select
    from app.database import AsyncSessionLocal
    from app.models import Novel

    monkeypatch.setenv("CRAWLER_ALLOWED_HOSTS", "www.piaotia.com,books.example")
    monkeypatch.setattr("app.routes.admin.get_crawler", lambda url: _fake_crawler(
        "凡人修仙传", "忘语", "https://www.piaotia.com/html/1/1/index.html", "piaotia"))
    first = await admin_client.post("/api/novels/crawl", json={"url": "https://www.piaotia.com/bookinfo/1/1.html"})
    assert first.json()["status"] == "success"

    # Same work, different platform, different catalog URL.
    monkeypatch.setattr("app.routes.admin.get_crawler", lambda url: _fake_crawler(
        "《凡人修仙传》最新章节", "忘语 著", "https://books.example/book/9/index.html", "biquge"))
    second = await admin_client.post("/api/novels/crawl", json={"url": "https://books.example/book/9/"})
    body = second.json()
    assert body["status"] == "duplicate"
    assert body["novel_id"] == first.json()["novel_id"]
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count(Novel.id))) == 1


@pytest.mark.asyncio
async def test_allow_duplicate_keeps_a_deliberate_second_mirror(monkeypatch, admin_client):
    from sqlalchemy import func, select
    from app.database import AsyncSessionLocal
    from app.models import Novel

    monkeypatch.setenv("CRAWLER_ALLOWED_HOSTS", "www.piaotia.com,books.example")
    monkeypatch.setattr("app.routes.admin.get_crawler", lambda url: _fake_crawler(
        "凡人修仙传", "忘语", "https://www.piaotia.com/html/1/1/index.html", "piaotia"))
    await admin_client.post("/api/novels/crawl", json={"url": "https://www.piaotia.com/bookinfo/1/1.html"})

    monkeypatch.setattr("app.routes.admin.get_crawler", lambda url: _fake_crawler(
        "凡人修仙传", "忘语", "https://books.example/book/9/index.html", "biquge"))
    second = await admin_client.post("/api/novels/crawl", json={
        "url": "https://books.example/book/9/", "allow_duplicate": True})
    assert second.json()["status"] == "success"
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count(Novel.id))) == 2


@pytest.mark.asyncio
async def test_recrawling_the_same_catalog_adds_no_duplicate_chapters(monkeypatch, admin_client):
    from sqlalchemy import func, select
    from app.database import AsyncSessionLocal
    from app.models import Chapter, Novel

    monkeypatch.setattr("app.routes.admin.get_crawler", lambda url: _fake_crawler(
        "凡人修仙传", "忘语", "https://www.piaotia.com/html/1/1/index.html", "piaotia"))
    payload = {"url": "https://www.piaotia.com/bookinfo/1/1.html"}
    first = await admin_client.post("/api/novels/crawl", json=payload)
    second = await admin_client.post("/api/novels/crawl", json=payload)
    assert first.json()["new_chapters"] == 1
    assert second.json()["new_chapters"] == 0
    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(func.count(Novel.id))) == 1
        assert await db.scalar(select(func.count(Chapter.id))) == 1


@pytest.mark.asyncio
async def test_discovery_skips_a_work_already_held_from_another_platform():
    from app.crawler.auto_updater import AutoUpdater
    from app.database import AsyncSessionLocal
    from app.crawler.identity import work_key
    from app.models import Novel

    async with AsyncSessionLocal() as db:
        db.add(Novel(title="凡人修仙传", author="忘语", source_name="biquge",
                     source_url="https://books.example/book/9/index.html",
                     work_key=work_key("凡人修仙传", "忘语")))
        await db.commit()
    imported = await AutoUpdater()._import_discovered({
        "title": "《凡人修仙传》最新章节", "author": "忘语 著", "description": "", "cover_url": "",
        "catalog_url": "https://www.piaotia.com/html/1/1/index.html"})
    assert imported is None


# --- Address pinning: the Render "cannot load novels" regression ------------

@pytest.mark.asyncio
async def test_ipv4_answers_are_tried_before_ipv6(monkeypatch):
    import socket
    from app.crawler.security import resolve_public_addresses
    # Cloudflare answers AAAA first for the novel sources.
    resolver = AsyncMock(return_value=[
        (socket.AF_INET6, 0, 0, "", ("2606:4700:3032::6815:4377", 443, 0, 0)),
        (socket.AF_INET, 0, 0, "", ("104.21.67.119", 443)),
    ])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    assert await resolve_public_addresses("www.piaotia.com") == (
        "104.21.67.119", "2606:4700:3032::6815:4377")


@pytest.mark.asyncio
async def test_unreachable_address_family_falls_through_to_the_next_answer(monkeypatch):
    """Render has no outbound IPv6 route: a failed connect must not end the fetch."""
    import httpx
    from app.crawler.security import PinnedTransport
    monkeypatch.setattr("app.crawler.security.resolve_public_addresses",
                        AsyncMock(return_value=("2606:4700::1", "104.21.67.119")))
    transport = PinnedTransport()
    attempted = []

    async def sender(request):
        attempted.append(request.url.host)
        if ":" in request.url.host:
            raise httpx.ConnectError("network unreachable")
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(transport.transport, "handle_async_request", sender)
    response = await transport.handle_async_request(
        httpx.Request("GET", "https://www.piaotia.com/html/1/1/1.html"))
    assert response.status_code == 200
    assert attempted == ["2606:4700::1", "104.21.67.119"]
    await transport.aclose()


@pytest.mark.asyncio
async def test_connect_failure_on_every_address_is_reported(monkeypatch):
    import httpx
    from app.crawler.security import PinnedTransport
    monkeypatch.setattr("app.crawler.security.resolve_public_addresses",
                        AsyncMock(return_value=("2606:4700::1", "104.21.67.119")))
    transport = PinnedTransport()
    monkeypatch.setattr(transport.transport, "handle_async_request",
                        AsyncMock(side_effect=httpx.ConnectError("unreachable")))
    with pytest.raises(httpx.ConnectError):
        await transport.handle_async_request(
            httpx.Request("GET", "https://www.piaotia.com/html/1/1/1.html"))
    await transport.aclose()


# --- Anti-bot interstitial is reported as an environment problem ------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers", [
    (403, {"cf-mitigated": "challenge", "server": "cloudflare"}),
    (503, {"server": "cloudflare"}),
])
async def test_bot_challenge_is_reported_as_a_blocked_egress_ip(monkeypatch, status, headers):
    import httpx
    from app.crawler.security import SourceChallenged, _fetch_redirects
    monkeypatch.setattr("app.crawler.security._rate_limit", AsyncMock())

    def handler(request):
        return httpx.Response(status, headers=headers, text="<title>Just a moment...</title>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SourceChallenged, match="chống bot"):
            await _fetch_redirects(client, "https://www.piaotia.com/", "utf-8")


@pytest.mark.asyncio
async def test_an_ordinary_403_is_not_mistaken_for_a_challenge(monkeypatch):
    import httpx
    from app.crawler.security import SourceChallenged, _fetch_redirects
    monkeypatch.setattr("app.crawler.security._rate_limit", AsyncMock())

    def handler(request):
        return httpx.Response(403, headers={"server": "nginx"}, text="denied")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await _fetch_redirects(client, "https://www.piaotia.com/", "utf-8")
        # A plain 403 must still surface as an HTTP error, not a challenge.
        assert not issubclass(httpx.HTTPStatusError, SourceChallenged)
