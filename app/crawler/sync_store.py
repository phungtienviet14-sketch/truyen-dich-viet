"""Short database transactions for catalog/raw synchronization and its lease."""
import hashlib
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, text, update

from app.database import AsyncSessionLocal, dialect_insert
from app.models import Chapter, Novel, SystemSetting
from .security import MAX_CATALOG_CHAPTERS, canonical_url, same_source_url

# 5 columns per row; well inside the 65535 bind parameters Postgres allows.
CATALOG_INSERT_BATCH = 500


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SyncLease:
    """A compare-and-swap DB lease shared by web and the separate worker."""
    def __init__(self, name):
        self.key = f"sync_lease:{name}"
        self.value = ""

    async def acquire(self):
        value = f"{time.time() + 120}:{uuid.uuid4().hex}"
        async with AsyncSessionLocal() as db:
            result = await db.execute(dialect_insert(SystemSetting).values(key=self.key, value=value)
                                      .on_conflict_do_nothing(index_elements=["key"]))
            if result.rowcount:
                await db.commit()
                self.value = value
                return True
            previous = await db.scalar(select(SystemSetting.value).where(SystemSetting.key == self.key))
            if previous and float(previous.split(":", 1)[0]) < time.time():
                result = await db.execute(update(SystemSetting).where(
                    SystemSetting.key == self.key, SystemSetting.value == previous).values(value=value))
                await db.commit()
                if result.rowcount:
                    self.value = value
                    return True
            await db.rollback()
            return False

    async def refresh(self):
        value = f"{time.time() + 120}:{self.value.split(':', 1)[1]}"
        async with AsyncSessionLocal() as db:
            result = await db.execute(update(SystemSetting).where(
                SystemSetting.key == self.key, SystemSetting.value == self.value).values(value=value))
            await db.commit()
        if not result.rowcount:
            raise RuntimeError("Đã mất khóa đồng bộ; hãy thử lại.")
        self.value = value

    async def release(self):
        async with AsyncSessionLocal() as db:
            await db.execute(delete(SystemSetting).where(
                SystemSetting.key == self.key, SystemSetting.value == self.value))
            await db.commit()


async def merge_catalog(novel_id, source_url, catalog):
    if not catalog or len(catalog) > MAX_CATALOG_CHAPTERS:
        raise ValueError("Mục lục trống hoặc vượt giới hạn chương.")
    checked = [dict(item, url=same_source_url(source_url, item["url"])) for item in catalog]
    if any(not str(item.get("title", "")).strip() or len(item["title"]) > 255 for item in checked):
        raise ValueError("Tiêu đề chương tại nguồn không hợp lệ.")
    async with AsyncSessionLocal() as db:
        rows = list((await db.execute(select(Chapter).where(Chapter.novel_id == novel_id))).scalars())
        existing = {canonical_url(row.url): row for row in rows}
        next_index = max((row.chapter_index for row in rows), default=0)
        new_count, seen, pending = 0, set(), []
        for item in checked:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            if item["url"] in existing:
                continue  # Source numbering may shift; published URLs stay stable.
            next_index += 1
            pending.append({"novel_id": novel_id, "chapter_index": next_index,
                            "chapter_title_raw": item["title"], "url": item["url"],
                            "status": "pending"})
        # One statement per batch, not per chapter: an 8,000-chapter catalogue
        # was 8,000 round trips to a managed database in another region.
        for start in range(0, len(pending), CATALOG_INSERT_BATCH):
            batch = pending[start:start + CATALOG_INSERT_BATCH]
            result = await db.execute(dialect_insert(Chapter).values(batch)
                                      .on_conflict_do_nothing(index_elements=["novel_id", "url"]))
            new_count += result.rowcount
        total = await db.scalar(select(func.count(Chapter.id)).where(Chapter.novel_id == novel_id))
        translated = await db.scalar(select(func.count(Chapter.id)).where(
            Chapter.novel_id == novel_id, Chapter.status == "completed", Chapter.content_vi.is_not(None)))
        await db.execute(update(Novel).where(Novel.id == novel_id).values(
            total_chapters=total, translated_chapters=translated, updated_at=utcnow()))
        await db.commit()
    return new_count, total, tuple(seen)


async def storage_used_mb():
    """Best-effort database size.

    Raw text is ~10x the cost of a catalog row, so an unattended backfill fills
    a bounded free tier in under a day. Reporting the size lets the caller stop
    storing raw while still tracking new chapters.
    """
    async with AsyncSessionLocal() as db:
        if db.bind.dialect.name == "postgresql":
            value = await db.scalar(text("SELECT pg_database_size(current_database())"))
        else:
            value = await db.scalar(text(
                "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"))
    return float(value or 0) / 1048576


async def raw_candidates(novel_id, urls, limit, stale_before=None):
    # Chapters with no raw at all come first: a library is only source-independent
    # once every chapter is stored. Refresh is bounded by ``stale_before`` because
    # ordering by ``raw_fetched_at`` alone refetches the oldest rows on every run
    # forever, so a finished novel keeps hitting the source for no new data.
    async with AsyncSessionLocal() as db:
        base = select(Chapter.id, Chapter.url).where(
            Chapter.novel_id == novel_id, Chapter.url.in_(urls), Chapter.status != "translating")
        missing = (await db.execute(base.where(
            (Chapter.content_raw.is_(None)) | (Chapter.content_raw == "")
        ).order_by(Chapter.chapter_index).limit(limit))).all()
        rows = [(row.id, row.url) for row in missing]
        if stale_before is None or len(rows) >= limit:
            return rows
        stale = (await db.execute(base.where(
            Chapter.content_raw.is_not(None), Chapter.content_raw != "",
            # A raw fetched by the translation path has no timestamp; treat it as due.
            (Chapter.raw_fetched_at.is_(None)) | (Chapter.raw_fetched_at < stale_before)
        ).order_by(Chapter.raw_fetched_at.asc().nullsfirst()).limit(limit - len(rows)))).all()
        return rows + [(row.id, row.url) for row in stale]


async def save_raw(chapter_id, payload):
    content = payload.get("content", "").strip()
    if not content:
        raise ValueError("Nguồn trả nội dung chương trống.")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    async with AsyncSessionLocal() as db:
        row = await db.get(Chapter, chapter_id)
        if row is None:
            raise ValueError("Chương đã bị xóa trong khi đồng bộ.")
        previous = row.raw_hash or (hashlib.sha256(row.content_raw.encode("utf-8")).hexdigest()
                                    if row.content_raw else None)
        changed = bool(previous and digest != previous)
        values = {"content_raw": content, "raw_hash": digest, "raw_fetched_at": utcnow(),
                  "source_changed": bool(row.source_changed or (changed and row.content_vi))}
        # Never replace editor text or reset translation state during sync.
        await db.execute(update(Chapter).where(Chapter.id == chapter_id).values(**values))
        await db.commit()
        return changed, bool(not row.content_vi and row.status == "pending")


async def raw_remaining(novel_id, urls):
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(func.count(Chapter.id)).where(
            Chapter.novel_id == novel_id, Chapter.url.in_(urls),
            (Chapter.content_raw.is_(None)) | (Chapter.content_raw == "")))
