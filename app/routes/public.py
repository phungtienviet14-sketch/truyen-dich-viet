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
from app import catalog
from app.schemas import (CrawlRequest, TranslateRequest, BatchTranslateRequest, SyncConfigRequest, GlossaryCreate, DiscoverHotRequest, CommentCreate)
from app.crawler import get_crawler
from app.crawler.auto_updater import auto_updater
from app.translator import translation_manager
from app.translator.batch_manager import batch_manager
from app.exporters import export_to_txt, export_to_epub
from app.web import templates

logger = logging.getLogger(__name__)

router = APIRouter()

CHAPTERS_PER_PAGE = 100


@router.get("/", response_class=HTMLResponse)
async def index_view(request: Request, page: int = Query(1, ge=1, le=1000),
                     db: AsyncSession = Depends(get_db)):
    # Totals come from the database, not from summing every row in Python: the
    # library grows without bound and the page only ever shows one screenful.
    totals = (await db.execute(select(
        func.count(Novel.id), func.coalesce(func.sum(Novel.total_chapters), 0),
        func.coalesce(func.sum(Novel.translated_chapters), 0)))).one()
    query = select(Novel).order_by(Novel.request_count.desc(), Novel.updated_at.desc(), Novel.id)
    novels, novel_total = await paginate(db, query, page)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "novels": novels,
            "novel_total": int(totals[0] or 0),
            "page": page,
            "total": novel_total,
            "page_size": PAGE_SIZE,
            "page_url": "/?page=__PAGE__",
            "total_chapters_all": int(totals[1] or 0),
            "total_translated_all": int(totals[2] or 0),
            "auto_updater_stats": auto_updater.last_sync_stats,
            "auto_updater_enabled": auto_updater.is_enabled,
        }
    )


@router.get("/novel/{novel_id}", response_class=HTMLResponse)
async def novel_detail_view(novel_id: int, request: Request, page: int = Query(1, ge=1, le=10000),
                            db: AsyncSession = Depends(get_db)):
    novel_res = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_res.scalar_one_or_none()
    if not novel:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện.")

    # Paginated: a 7,000-chapter novel rendered the whole catalogue into one
    # page, which measured 6 MB of HTML before this.
    chapter_total = int(await db.scalar(
        select(func.count(Chapter.id)).where(Chapter.novel_id == novel_id)) or 0)
    chapter_pages = max(1, -(-chapter_total // CHAPTERS_PER_PAGE))
    chapter_page = min(max(page, 1), chapter_pages)
    chapters_res = await db.execute(
        select(Chapter)
        .options(load_only(Chapter.id, Chapter.novel_id, Chapter.chapter_index,
                           Chapter.chapter_title_raw, Chapter.chapter_title_vi, Chapter.status))
        .where(Chapter.novel_id == novel_id).order_by(Chapter.chapter_index)
        .limit(CHAPTERS_PER_PAGE).offset((chapter_page - 1) * CHAPTERS_PER_PAGE)
    )
    chapters = chapters_res.scalars().all()

    comments_res = await db.execute(
        select(Comment).where(Comment.novel_id == novel_id).order_by(desc(Comment.created_at)).limit(50)
    )
    comments = comments_res.scalars().all()
    await count_interaction(db, request, Novel, novel_id, "view_count", daily=True)

    return templates.TemplateResponse(
        request=request,
        name="novel_detail.html",
        context={
            "novel": novel,
            "chapters": chapters,
            "comments": comments,
            "chapter_total": chapter_total,
            "chapter_page": chapter_page,
            "chapter_pages": chapter_pages,
            "chapters_per_page": CHAPTERS_PER_PAGE,
        }
    )


@router.get("/novel/{novel_id}/chapter/{chapter_index}", response_class=HTMLResponse)
async def chapter_reader_view(novel_id: int, chapter_index: int, request: Request, db: AsyncSession = Depends(get_db)):
    novel_res = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_res.scalar_one_or_none()
    if not novel:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện.")

    chap_res = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_index == chapter_index)
    )
    chapter = chap_res.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="Không tìm thấy chương này.")

    prev_res = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_index < chapter_index).order_by(Chapter.chapter_index.desc()).limit(1)
    )
    prev_chapter = prev_res.scalar_one_or_none()

    next_res = await db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id, Chapter.chapter_index > chapter_index).order_by(Chapter.chapter_index).limit(1)
    )
    next_chapter = next_res.scalar_one_or_none()

    # Load chapter list for in-reader Chapter Drawer / TOC sidebar
    chapters_res = await db.execute(
        select(Chapter.chapter_index, Chapter.chapter_title_vi, Chapter.chapter_title_raw, Chapter.status)
        .where(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_index)
    )
    chapters = [
        {
            "chapter_index": row[0],
            "chapter_title_vi": row[1],
            "chapter_title_raw": row[2],
            "status": row[3],
        }
        for row in chapters_res.all()
    ]

    comments_res = await db.execute(
        select(Comment).where(Comment.novel_id == novel_id, Comment.chapter_index == chapter_index).order_by(desc(Comment.created_at)).limit(30)
    )
    comments = comments_res.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="reader.html",
        context={
            "novel": novel,
            "chapter": chapter,
            "prev_chapter": prev_chapter,
            "next_chapter": next_chapter,
            "chapters": chapters,
            "comments": comments,
        }
    )


@router.get("/api/novels/{novel_id}/chapters")
async def get_novel_chapters_api(novel_id: int, db: AsyncSession = Depends(get_db)):
    novel_res = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_res.scalar_one_or_none()
    if not novel:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện.")

    chapters_res = await db.execute(
        select(Chapter.chapter_index, Chapter.chapter_title_vi, Chapter.chapter_title_raw, Chapter.status)
        .where(Chapter.novel_id == novel_id)
        .order_by(Chapter.chapter_index)
    )
    # One resolved title, not three overlapping ones: the reader drawer only
    # ever shows the fallback chain, and a 7,000-chapter novel sent ~950 KB.
    return [
        {
            "index": row[0],
            "title": row[1] or row[2] or f"Chương {row[0]}",
            "status": row[3] or "pending"
        }
        for row in chapters_res.all()
    ]


@router.post("/api/novels/{novel_id}/favorite")
async def toggle_favorite_endpoint(novel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    novel_res = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_res.scalar_one_or_none()
    if not novel:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện.")

    await count_interaction(db, request, Novel, novel_id, "favorite_count", daily=False)
    await db.refresh(novel)
    return {
        "status": "success",
        "favorite_count": novel.favorite_count,
        "message": f"Đã thêm '{novel.title_vi or novel.title}' vào Tủ Truyện Yêu Thích!"
    }


@router.post("/api/novels/{novel_id}/request-translation")
async def request_translation_endpoint(novel_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    novel_res = await db.execute(select(Novel).where(Novel.id == novel_id))
    novel = novel_res.scalar_one_or_none()
    if not novel:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện.")

    await count_interaction(db, request, Novel, novel_id, "request_count", daily=True)
    await db.refresh(novel)
    return {
        "status": "success",
        "request_count": novel.request_count,
        "message": f"Đã ghi nhận yêu cầu dịch (+1). Nhóm Truyện Dịch Việt sẽ ưu tiên dịch tiếp tác phẩm này!"
    }


@router.get("/api/novels/{novel_id}/comments")
async def get_comments_endpoint(novel_id: int, chapter_index: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    query = select(Comment).where(Comment.novel_id == novel_id)
    if chapter_index is not None:
        query = query.where(Comment.chapter_index == chapter_index)
    query = query.order_by(desc(Comment.created_at)).limit(50)
    res = await db.execute(query)
    comments = res.scalars().all()

    return [
        {
            "id": c.id,
            "user_name": c.user_name,
            "user_avatar": c.user_avatar,
            "content": c.content,
            "likes": c.likes,
            "created_at": c.created_at.strftime("%H:%M %d/%m/%Y"),
            "chapter_index": c.chapter_index
        }
        for c in comments
    ]


@router.post("/api/novels/{novel_id}/comments")
async def post_comment_endpoint(novel_id: int, payload: CommentCreate, db: AsyncSession = Depends(get_db)):
    if await db.get(Novel, novel_id) is None:
        raise HTTPException(404, "Không tìm thấy truyện.")
    if payload.chapter_index is not None:
        chapter = await db.scalar(select(Chapter.id).where(Chapter.novel_id == novel_id, Chapter.chapter_index == payload.chapter_index))
        if chapter is None:
            raise HTTPException(404, "Không tìm thấy chương.")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Nội dung bình luận không được để trống.")

    name = payload.user_name.strip() or "Đạo Hữu Vô Danh"
    avatar = payload.user_avatar or "🧙‍♂️"

    comment = Comment(
        novel_id=novel_id,
        chapter_index=payload.chapter_index,
        user_name=name,
        user_avatar=avatar,
        content=content,
        likes=0,
        created_at=datetime.datetime.utcnow()
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)

    return {
        "status": "success",
        "id": comment.id,
        "user_name": comment.user_name,
        "user_avatar": comment.user_avatar,
        "content": comment.content,
        "likes": comment.likes,
        "created_at": "Vừa xong",
        "chapter_index": comment.chapter_index
    }


@router.post("/api/comments/{comment_id}/like")
async def like_comment_endpoint(comment_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = res.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Bình luận không tồn tại.")

    await count_interaction(db, request, Comment, comment_id, "likes", daily=False)
    await db.refresh(comment)
    return {"status": "success", "likes": comment.likes}


@router.get("/api/novels/{novel_id}/download")
@router.get("/novel/{novel_id}/export/{export_format}")
async def download_novel_endpoint(
    novel_id: int, request: Request, export_format: Optional[str] = None,
    format: str = Query("epub", pattern="^(epub|txt)$"),
    start: Optional[int] = Query(None, ge=1), end: Optional[int] = Query(None, ge=1),
    lang: str = Query("vi", pattern="^(vi|raw)$"), db: AsyncSession = Depends(get_db),
):
    actual_format = export_format or format
    if actual_format not in {"txt", "epub"}:
        raise HTTPException(422, "Định dạng không hợp lệ.")
    if start and end and end < start:
        raise HTTPException(422, "Dải chương không hợp lệ.")
    if not request.app.state.rate_limiter.allow(f"download:{request.state.actor_key}", 5, 60):
        raise HTTPException(429, "Vui lòng chờ trước khi tải thêm.")
    novel = await db.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(404, "Không tìm thấy truyện.")
    query = select(Chapter).where(Chapter.novel_id == novel_id)
    if start:
        query = query.where(Chapter.chapter_index >= start)
    if end:
        query = query.where(Chapter.chapter_index <= end)
    chapters = list((await db.scalars(query.order_by(Chapter.chapter_index).limit(config.MAX_EXPORT_CHAPTERS + 1))).all())
    if not chapters:
        raise HTTPException(404, "Không có chương trong dải đã chọn.")
    if len(chapters) > config.MAX_EXPORT_CHAPTERS:
        raise HTTPException(422, f"Mỗi lần tải tối đa {config.MAX_EXPORT_CHAPTERS} chương.")
    if sum(len(c.content_raw or "") + len(c.content_vi or "") for c in chapters) > 15_000_000:
        raise HTTPException(422, "Dải chương quá lớn, vui lòng chia nhỏ.")
    exporter = export_to_txt if actual_format == "txt" else export_to_epub
    try:
        async with export_slots:
            filepath = await asyncio.to_thread(exporter, novel, chapters, start or chapters[0].chapter_index, end or chapters[-1].chapter_index, lang)
    except ValueError:
        raise HTTPException(409, "Một số chương chưa có nội dung theo ngôn ngữ đã chọn. Chọn dải nhỏ hơn hoặc chờ đồng bộ/dịch.")
    return FileResponse(filepath, filename=filepath.name, media_type="text/plain; charset=utf-8" if actual_format == "txt" else "application/epub+zip")


export_slots = asyncio.Semaphore(2)


async def count_interaction(db, request, model, entity_id, field, daily):
    period = utcnow().date().isoformat() if daily else "once"
    key = keyed_hash(f"{request.state.actor_key}:{model.__tablename__}:{entity_id}:{field}:{period}")
    inserted = await db.execute(dialect_insert(Interaction).values(key=key).on_conflict_do_nothing(index_elements=["key"]))
    if inserted.rowcount:
        await db.execute(update(model).where(model.id == entity_id).values({field: func.coalesce(getattr(model, field), 0) + 1}))
    await db.commit()


# --- Library: rankings, search, genres --------------------------------------

PAGE_SIZE = 24


async def paginate(db, query, page):
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = (await db.scalars(query.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE))).all()
    return rows, int(total or 0)


async def genre_counts(db):
    rows = (await db.execute(select(Novel.category, func.count(Novel.id)).group_by(Novel.category))).all()
    return {row[0]: row[1] for row in rows}


def library_context(**extra):
    return {"genres": catalog.GENRES, "status_labels": catalog.STATUS_LABELS, **extra}


@router.get("/bang-xep-hang", response_class=HTMLResponse)
async def rankings_view(request: Request, board: str = Query("viet"), sort: str = Query(""),
                        page: int = Query(1, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    board = board if board in ("viet", "trung") else "viet"
    chosen, label, query = catalog.ranked_query(board, sort)
    novels, total = await paginate(db, query, page)
    # The source counters are a snapshot; show the reader how old they are.
    captured = await db.scalar(select(func.max(Novel.source_stats_at))) if board == "trung" else None
    return templates.TemplateResponse(request=request, name="rankings.html", context=library_context(
        novels=novels, total=total, page=page, page_size=PAGE_SIZE,
        board=board, sort=chosen, sort_label=label, captured_at=captured,
        vi_orderings=catalog.VI_ORDERINGS, cn_orderings=catalog.CN_ORDERINGS))


@router.get("/tim-kiem", response_class=HTMLResponse)
async def search_view(request: Request, q: str = Query("", max_length=100),
                      page: int = Query(1, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    term = q.strip()
    novels, total = [], 0
    if term:
        query = (select(Novel).where(catalog.search_filter(term))
                 .order_by(desc(Novel.view_count), desc(Novel.updated_at), Novel.id))
        novels, total = await paginate(db, query, page)
    return templates.TemplateResponse(request=request, name="search.html", context=library_context(
        novels=novels, total=total, page=page, page_size=PAGE_SIZE, term=term))


@router.get("/the-loai", response_class=HTMLResponse)
async def genre_index_view(request: Request, db: AsyncSession = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="genres.html", context=library_context(
        counts=await genre_counts(db)))


@router.get("/the-loai/{slug}", response_class=HTMLResponse)
async def genre_view(request: Request, slug: str, page: int = Query(1, ge=1, le=200),
                     db: AsyncSession = Depends(get_db)):
    genre = catalog.BY_SLUG.get(slug)
    if genre is None:
        raise HTTPException(status_code=404, detail="Không có thể loại này.")
    query = (select(Novel).where(Novel.category == slug)
             .order_by(desc(Novel.view_count), desc(Novel.updated_at), Novel.id))
    novels, total = await paginate(db, query, page)
    return templates.TemplateResponse(request=request, name="genre.html", context=library_context(
        novels=novels, total=total, page=page, page_size=PAGE_SIZE, genre=genre))


@router.get("/api/novels/search")
async def search_api(q: str = Query("", max_length=100), db: AsyncSession = Depends(get_db)):
    """Backs the header suggestion box; capped so typing cannot scan the table."""
    term = q.strip()
    if len(term) < 2:
        return {"results": []}
    rows = (await db.scalars(select(Novel).where(catalog.search_filter(term))
                             .order_by(desc(Novel.view_count), Novel.id).limit(8))).all()
    return {"results": [{"id": n.id, "title": n.title_vi or n.title, "title_raw": n.title,
                         "author": n.author, "cover_url": n.cover_url,
                         "genre": catalog.genre_name(n.category),
                         "total_chapters": n.total_chapters,
                         "translated_chapters": n.translated_chapters} for n in rows]}
