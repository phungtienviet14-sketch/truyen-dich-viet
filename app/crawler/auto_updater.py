import asyncio
import json
import logging
import os

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.database import AsyncSessionLocal
from app.models import Novel, SystemSetting
from app.crawler import get_crawler
from app.crawler.piaotia import PiaotiaCrawler
from .security import same_source_url
from .sync_store import SyncLease, merge_catalog, raw_candidates, raw_remaining, save_raw, utcnow

logger = logging.getLogger("auto_updater")
SETTINGS_KEY = "auto_updater_config"


class AutoUpdater:
    def __init__(self):
        self.is_running = False
        self.is_enabled = True
        self.interval_seconds = 1800
        self.auto_translate_on_sync = False
        self.last_sync_time = None
        self.sync_logs = []
        self.last_sync_stats = {"novels_checked": 0, "new_chapters_found": 0,
                                "new_novels_discovered": 0, "last_log": "Chưa chạy lần nào"}
        self.task = None

    def add_log(self, novel_title, new_chaps, message, status="success"):
        self.sync_logs = [*self.sync_logs, {
            "time": utcnow().strftime("%H:%M:%S %d/%m/%Y"), "novel_title": novel_title,
            "new_chapters": new_chaps, "message": message, "status": status,
        }][-100:]

    async def load_settings(self):
        async with AsyncSessionLocal() as db:
            raw = await db.scalar(select(SystemSetting.value).where(SystemSetting.key == SETTINGS_KEY))
        if raw:
            values = json.loads(raw)
            self._apply_settings(values)

    def _apply_settings(self, values):
        interval = values.get("interval_seconds", 1800)
        if isinstance(interval, bool) or not isinstance(interval, int) or not 300 <= interval <= 86400:
            raise ValueError("Chu kỳ đồng bộ phải từ 300 đến 86400 giây.")
        if not isinstance(values.get("enabled", True), bool) or not isinstance(values.get("auto_translate", False), bool):
            raise ValueError("Cấu hình đồng bộ không hợp lệ.")
        self.is_enabled = values.get("enabled", True)
        self.interval_seconds = interval
        self.auto_translate_on_sync = values.get("auto_translate", False)

    async def configure(self, *, enabled=None, interval_seconds=None, auto_translate=None):
        await self.load_settings()
        values = {"enabled": self.is_enabled if enabled is None else enabled,
                  "interval_seconds": self.interval_seconds if interval_seconds is None else interval_seconds,
                  "auto_translate": self.auto_translate_on_sync if auto_translate is None else auto_translate}
        self._apply_settings(values)
        async with AsyncSessionLocal() as db:
            statement = insert(SystemSetting).values(key=SETTINGS_KEY, value=json.dumps(values))
            await db.execute(statement.on_conflict_do_update(
                index_elements=["key"], set_={"value": statement.excluded.value}))
            await db.commit()

    async def start(self):
        if self.task and not self.task.done():
            return
        await self.load_settings()
        self.is_running = True
        self.task = asyncio.create_task(self._periodic_loop())

    async def stop(self):
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def _periodic_loop(self):
        await asyncio.sleep(20)
        while self.is_running:
            try:
                await self.load_settings()
                if self.is_enabled:
                    await self.sync_all_novels()
            except Exception:
                logger.exception("AutoUpdater periodic sync failed")
            # Poll persisted config so disabling/changing the interval in web
            # does not wait for a full old interval in the separate worker.
            elapsed = 0
            while self.is_running and elapsed < self.interval_seconds:
                await asyncio.sleep(10)
                elapsed += 10
                await self.load_settings()

    async def sync_single_novel(self, novel_id, *, auto_translate=None):
        lease = SyncLease(str(novel_id))
        if not await lease.acquire():
            return {"status": "busy", "message": "Truyện đang được đồng bộ."}
        try:
            await self.load_settings()
            return await self._sync_locked(novel_id, lease, auto_translate)
        except Exception:
            logger.exception("Source sync failed for novel %s", novel_id)
            message = "Lỗi đồng bộ nguồn; kiểm tra nguồn/hostname và nhật ký máy chủ."
            self.add_log(f"Truyện #{novel_id}", 0, message, "error")
            return {"status": "error", "message": message}
        finally:
            await lease.release()

    async def _sync_locked(self, novel_id, lease, auto_translate):
        async with AsyncSessionLocal() as db:
            novel = await db.get(Novel, novel_id)
        if novel is None:
            return {"status": "error", "message": "Không tìm thấy truyện."}
        crawler = get_crawler(novel.source_url)
        catalog = await crawler.get_chapter_list(novel.source_url)
        await lease.refresh()
        new_count, total, urls = await merge_catalog(novel_id, novel.source_url, catalog)
        stats, translatable = await self._fetch_raw(novel_id, urls, crawler, lease)
        translate = self.auto_translate_on_sync if auto_translate is None else auto_translate
        if translate and translatable:
            from app.translator.worker import translation_manager
            await translation_manager.start_translation(novel_id, chapter_ids=translatable)
        status = "partial" if stats["raw_errors"] or stats["raw_remaining"] else "success"
        message = (f"Thêm {new_count} chương; đã lưu {stats['raw_fetched']} nguyên tác; "
                   f"còn thiếu {stats['raw_remaining']}; lỗi tải {stats['raw_errors']}.")
        self.add_log(novel.title_vi or novel.title, new_count, message, status)
        return {"status": status, "new_chapters": new_count, "total_chapters": total,
                "message": message, **stats}

    async def _fetch_raw(self, novel_id, urls, crawler, lease):
        limit = max(1, min(100, int(os.getenv("CRAWLER_MAX_RAW_PER_SYNC", "25"))))
        candidates = await raw_candidates(novel_id, urls, limit)
        fetched, errors, changed, translatable = 0, 0, 0, []
        for chapter_id, url in candidates:
            await lease.refresh()
            try:
                payload = await crawler.get_chapter_content(url)
                content_changed, can_translate = await save_raw(chapter_id, payload)
                fetched += 1
                changed += int(content_changed)
                if can_translate:
                    translatable.append(chapter_id)
            except Exception:
                errors += 1
                logger.exception("Raw fetch failed for chapter %s", chapter_id)
        return {"raw_fetched": fetched, "raw_errors": errors, "raw_changed": changed,
                "raw_remaining": await raw_remaining(novel_id, urls)}, translatable

    async def sync_all_novels(self):
        self.last_sync_time = utcnow()
        async with AsyncSessionLocal() as db:
            ids = list((await db.execute(select(Novel.id).order_by(Novel.id))).scalars())
        results = [await self.sync_single_novel(novel_id) for novel_id in ids]
        self.last_sync_stats = {
            "novels_checked": len(ids), "new_chapters_found": sum(r.get("new_chapters", 0) for r in results),
            "new_novels_discovered": 0, "errors": sum(r["status"] in ("error", "partial") for r in results),
            "raw_fetched": sum(r.get("raw_fetched", 0) for r in results),
            "raw_remaining": sum(r.get("raw_remaining", 0) for r in results),
            "last_log": f"Đã kiểm tra {len(ids)} bộ truyện.",
        }
        return self.last_sync_stats

    async def discover_hot_novels(self, max_novels=15, category_code="2"):
        if isinstance(max_novels, bool) or not isinstance(max_novels, int) or not 1 <= max_novels <= 15:
            raise ValueError("Mỗi lượt khám phá từ 1 đến 15 truyện.")
        if str(category_code) not in {str(number) for number in range(10)}:
            raise ValueError("Thể loại nguồn không hợp lệ.")
        lease = SyncLease("discovery")
        if not await lease.acquire():
            raise ValueError("Đang có lượt khám phá truyện chạy.")
        try:
            return await self._discover_locked(max_novels, str(category_code), lease)
        finally:
            await lease.release()

    async def _discover_locked(self, max_novels, category_code, lease):
        category = f"booksort{category_code}" if category_code != "0" else "booksort"
        url = f"https://www.piaotia.com/{category}/0/1.html"
        crawler = PiaotiaCrawler()
        soup = BeautifulSoup(await crawler.fetch_html(url), "html.parser")
        links = []
        for anchor in soup.select("a[href]"):
            if "bookinfo" not in anchor["href"]:
                continue
            try:
                candidate = same_source_url(url, anchor["href"])
            except ValueError:
                continue
            if candidate not in links:
                links.append(candidate)
        if not links:
            raise ValueError("Không tìm thấy truyện trong bảng xếp hạng nguồn.")
        imported = []
        for candidate in links[:max_novels]:
            await lease.refresh()
            try:
                info = await crawler.get_novel_info(candidate)
                novel_id = await self._import_discovered(info)
                if novel_id is None:
                    continue
                result = await self.sync_single_novel(novel_id, auto_translate=False)
                imported.append({"id": novel_id, "title": info["title"], "author": info["author"],
                                 "total_chapters": result.get("total_chapters", 0), "sync": result})
            except Exception:
                logger.exception("Discovery import failed")
                self.add_log("Khám phá nguồn", 0, "Không thể nhập một truyện từ nguồn.", "error")
        return imported

    async def _import_discovered(self, info):
        async with AsyncSessionLocal() as db:
            existing = await db.scalar(select(Novel.id).where(Novel.source_url == info["catalog_url"]))
            if existing is not None:
                return None
            novel = Novel(title=info["title"], title_vi=info["title"], author=info["author"],
                          description=info["description"], cover_url=info["cover_url"],
                          source_url=info["catalog_url"], source_name="piaotia")
            db.add(novel)
            await db.commit()
            return novel.id


auto_updater = AutoUpdater()
