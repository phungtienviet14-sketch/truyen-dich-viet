import asyncio
import datetime
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.orm import load_only

from app import config
from app.auth import require_admin, keyed_hash, utcnow
from app.database import get_db, AsyncSessionLocal, dialect_insert
from app.models import Novel, Chapter, Glossary, SystemSetting, Comment, Interaction
from app.schemas import (CrawlRequest, TranslateRequest, BatchTranslateRequest, SyncConfigRequest, GlossaryCreate, DiscoverHotRequest, CommentCreate)
from app.crawler import get_crawler
from app.crawler.auto_updater import auto_updater
from app.crawler.identity import work_key
from app.crawler.sync_store import merge_catalog
from app.translator import translation_manager
from app.translator.batch_manager import batch_manager
from app.exporters import export_to_txt, export_to_epub
from app.web import templates

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard_view(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Novel).order_by(desc(Novel.request_count), desc(Novel.updated_at)))
    novels = result.scalars().all()

    total_chapters = sum(n.total_chapters for n in novels)
    total_translated = sum(n.translated_chapters for n in novels)

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_dashboard.html",
        context={
            "novels": novels,
            "total_chapters_all": total_chapters,
            "total_translated_all": total_translated,
            "auto_updater_stats": auto_updater.last_sync_stats,
            "auto_updater_enabled": auto_updater.is_enabled,
            "auto_updater_interval": auto_updater.interval_seconds // 60,
            "sync_logs": auto_updater.sync_logs[-20:],
            "batch_status": await batch_manager.get_status(),
        }
    )


@router.get("/admin/novel/{novel_id}", response_class=HTMLResponse)
async def admin_novel_translate_view(novel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    novel_res = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_res.scalar_one_or_none()
    if not novel:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện.")

    chapters_res = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.chapter_index)
    )
    chapters = chapters_res.scalars().all()

    glossaries_res = await db.execute(
        select(Glossary).where((Glossary.novel_id == novel_id) | (Glossary.novel_id.is_(None)))
    )
    glossaries = glossaries_res.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/admin_novel_translate.html",
        context={
            "novel": novel,
            "chapters": chapters,
            "glossaries": glossaries,
        }
    )


@router.get("/api/admin/batch-translate/status")
async def get_batch_status():
    return await batch_manager.get_status()


@router.post("/api/admin/batch-translate/start")
async def start_batch_translate(payload: BatchTranslateRequest):
    res = await batch_manager.start_batch(
        novel_ids=payload.novel_ids,
        policy=payload.policy,
        concurrency=payload.concurrency,
        chapters_per_novel=payload.chapters_per_novel
    )
    return res


@router.post("/api/admin/batch-translate/pause")
async def pause_batch_translate():
    batch_manager.pause()
    return {"status": "paused", "message": "Đã tạm dừng tiến trình dịch hàng loạt."}


@router.post("/api/admin/batch-translate/resume")
async def resume_batch_translate():
    batch_manager.resume()
    return {"status": "resumed", "message": "Đã tiếp tục tiến trình dịch hàng loạt."}


@router.post("/api/admin/batch-translate/stop")
async def stop_batch_translate():
    batch_manager.stop()
    return {"status": "stopped", "message": "Đã hủy bỏ toàn bộ hàng đợi dịch hàng loạt."}


@router.post("/api/admin/sync/novel/{novel_id}")
async def sync_single_novel_endpoint(novel_id: int):
    res = await auto_updater.sync_single_novel(novel_id)
    return res


@router.get("/api/admin/sync/logs")
async def get_sync_logs():
    return {
        "logs": auto_updater.sync_logs,
        "last_stats": auto_updater.last_sync_stats,
        "is_enabled": auto_updater.is_enabled,
        "interval_minutes": auto_updater.interval_seconds // 60
    }


@router.post("/api/admin/sync/config")
async def update_sync_config(payload: SyncConfigRequest):
    auto_updater.interval_seconds = max(300, payload.interval_minutes * 60)
    return {
        "status": "success",
        "interval_minutes": auto_updater.interval_seconds // 60,
        "message": f"Đã cập nhật chu kỳ đồng bộ tự động thành {auto_updater.interval_seconds // 60} phút/lần."
    }


@router.post("/api/novels/crawl")
async def crawl_novel_endpoint(payload: CrawlRequest, db: AsyncSession = Depends(get_db)):
    url = payload.url.strip()
    crawler = get_crawler(url)

    try:
        novel_info = await crawler.get_novel_info(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Lỗi khi cào thông tin truyện: {str(e)}")

    catalog_url = novel_info["catalog_url"]
    identity = work_key(novel_info["title"], novel_info["author"])

    novel = await db.scalar(select(Novel).where(Novel.source_url == catalog_url))
    if novel is None and identity and not payload.allow_duplicate:
        # The same work mirrored on another Chinese platform has a different
        # catalog URL but the same fingerprint. Report it instead of importing
        # a second copy that would then be translated and paid for twice.
        twin = await db.scalar(select(Novel).where(Novel.work_key == identity).order_by(Novel.id))
        if twin is not None:
            name = twin.title_vi or twin.title
            return {
                "status": "duplicate",
                "novel_id": twin.id,
                "title": name,
                "existing_source_url": twin.source_url,
                "existing_source_name": twin.source_name,
                "total_chapters": twin.total_chapters,
                "message": (f"'{name}' đã có trong thư viện từ nguồn '{twin.source_name}'. "
                            f"Gửi lại với allow_duplicate=true nếu vẫn muốn nạp bản sao từ nguồn này."),
            }

    if novel is None:
        values = {
            "title": novel_info["title"],
            "title_vi": payload.title_vi or novel_info["title"],
            "author": novel_info["author"],
            "description": novel_info["description"],
            "cover_url": novel_info["cover_url"],
            "source_url": catalog_url,
            "source_name": novel_info["source_name"],
            "work_key": identity or None,
        }
        # Two admins pasting the same link race here; the unique index decides.
        await db.execute(dialect_insert(Novel).values(**values)
                         .on_conflict_do_nothing(index_elements=["source_url"]))
        await db.commit()
        novel = await db.scalar(select(Novel).where(Novel.source_url == catalog_url))
        if novel is None:
            raise HTTPException(status_code=500, detail="Không thể tạo bản ghi truyện.")

    try:
        chapters_data = await crawler.get_chapter_list(catalog_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Lỗi khi cào danh sách chương: {str(e)}")

    # Same merge path as the background sync: chapters are keyed by source URL,
    # so a renumbered catalog appends instead of colliding on chapter_index.
    new_count, total, _ = await merge_catalog(novel.id, catalog_url, chapters_data)

    return {
        "status": "success",
        "novel_id": novel.id,
        "title": novel.title,
        "new_chapters": new_count,
        "total_chapters": total,
        "message": f"Đã cào '{novel.title}': thêm {new_count} chương mới, tổng {total} chương."
    }


@router.get("/api/auto-updater/status")
async def get_auto_updater_status():
    return {
        "is_enabled": auto_updater.is_enabled,
        "interval_minutes": auto_updater.interval_seconds // 60,
        "last_sync_time": auto_updater.last_sync_time.isoformat() if auto_updater.last_sync_time else None,
        "stats": auto_updater.last_sync_stats
    }


@router.post("/api/auto-updater/toggle")
async def toggle_auto_updater():
    auto_updater.is_enabled = not auto_updater.is_enabled
    return {
        "is_enabled": auto_updater.is_enabled,
        "message": f"Đã {'bật' if auto_updater.is_enabled else 'tắt'} chế độ tự động cập nhật chương mới ngầm."
    }


@router.post("/api/auto-updater/sync-now")
async def sync_now_endpoint():
    stats = await auto_updater.sync_all_novels()
    return {
        "status": "success",
        "stats": stats,
        "message": stats["last_log"]
    }


@router.post("/api/auto-updater/discover-hot")
async def discover_hot_endpoint(payload: DiscoverHotRequest):
    try:
        imported = await auto_updater.discover_hot_novels(max_novels=payload.count, category_code=payload.category)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Không thể nạp bảng xếp hạng: {str(e)}")
    return {
        "status": "success",
        "imported_count": len(imported),
        "imported_novels": imported,
        "message": f"Đã tự động cào và nạp thành công {len(imported)} bộ truyện hot mới vào thư viện."
    }


@router.post("/api/novels/{novel_id}/translate")
async def start_translation_endpoint(novel_id: int, payload: TranslateRequest):
    result = await translation_manager.start_translation(
        novel_id=novel_id,
        start_chapter=payload.start_chapter,
        end_chapter=payload.end_chapter,
        concurrency=payload.concurrency,
        retranslate_completed=payload.retranslate_completed
    )
    return result


@router.post("/api/novels/{novel_id}/stop")
async def stop_translation_endpoint(novel_id: int):
    translation_manager.stop_translation(novel_id)
    return {"status": "stopped", "message": "Đã gửi tín hiệu dừng tiến trình dịch."}


@router.post("/api/novels/{novel_id}/translate-errors")
async def translate_errors_endpoint(novel_id: int):
    result = await translation_manager.start_translation(
        novel_id=novel_id,
        start_chapter=1,
        concurrency=3,
        retranslate_completed=False
    )
    return result


@router.post("/api/novels/{novel_id}/refresh-catalog")
async def refresh_catalog_endpoint(novel_id: int, db: AsyncSession = Depends(get_db)):
    res = await auto_updater.sync_single_novel(novel_id)
    return res


@router.get("/api/stream/{novel_id}")
async def sse_stream_endpoint(novel_id: int, request: Request):
    queue = translation_manager.subscribe(novel_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            translation_manager.unsubscribe(novel_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.delete("/api/novels/{novel_id}")
async def delete_novel_endpoint(novel_id: int, db: AsyncSession = Depends(get_db)):
    if translation_manager.is_running(novel_id):
        translation_manager.stop_translation(novel_id)

    await db.execute(delete(Chapter).where(Chapter.novel_id == novel_id))
    await db.execute(delete(Glossary).where(Glossary.novel_id == novel_id))
    await db.execute(delete(Comment).where(Comment.novel_id == novel_id))
    await db.execute(delete(Novel).where(Novel.id == novel_id))
    await db.commit()
    return {"status": "deleted", "message": "Đã xóa toàn bộ dữ liệu bộ truyện."}


@router.post("/api/novels/{novel_id}/glossary")
async def add_glossary_endpoint(novel_id: int, payload: GlossaryCreate, db: AsyncSession = Depends(get_db)):
    g = Glossary(
        novel_id=novel_id,
        original_term=payload.original_term.strip(),
        translated_term=payload.translated_term.strip(),
        note=payload.note
    )
    db.add(g)
    await db.commit()
    await db.refresh(g)
    return {"status": "success", "id": g.id}


@router.delete("/api/glossary/{glossary_id}")
async def delete_glossary_endpoint(glossary_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Glossary).where(Glossary.id == glossary_id))
    await db.commit()
    return {"status": "deleted"}
