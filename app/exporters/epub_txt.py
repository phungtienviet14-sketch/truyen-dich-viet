"""Export only stored content, with versioned names and atomic publication."""
import hashlib
import json
import os
from contextlib import contextmanager
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List, Optional

from ebooklib import epub

from app.config import EXPORT_DIR
from app.models import Chapter, Novel


class ExportContentError(ValueError):
    """A requested export contains missing or unpublished chapter content."""


def _prepare(novel, chapters, start_idx, end_idx, lang, extension):
    if lang not in {"vi", "raw"}:
        raise ValueError("Ngôn ngữ xuất file không hợp lệ.")
    if not chapters:
        raise ExportContentError("Không có chương để xuất file.")
    end = end_idx if end_idx is not None else max(c.chapter_index for c in chapters)
    if start_idx < 1 or end < start_idx:
        raise ValueError("Dải chương không hợp lệ.")
    selected = tuple(sorted((c for c in chapters if start_idx <= c.chapter_index <= end),
                            key=lambda c: c.chapter_index))
    present = {c.chapter_index for c in selected}
    missing = set(range(start_idx, end + 1)) - present
    for chapter in selected:
        content = chapter.content_vi if lang == "vi" else chapter.content_raw
        if not content or not content.strip() or (lang == "vi" and chapter.status != "completed"):
            missing.add(chapter.chapter_index)
    if missing:
        indices = ", ".join(str(index) for index in sorted(missing)[:10])
        label = "bản dịch đã hoàn thành" if lang == "vi" else "nguyên tác đã lưu"
        raise ExportContentError(f"Thiếu {label} ở {len(missing)} chương: {indices}.")
    rows = tuple((c.chapter_index,
                  (c.chapter_title_vi or f"Chương {c.chapter_index}") if lang == "vi" else c.chapter_title_raw,
                  (c.content_vi if lang == "vi" else c.content_raw).strip()) for c in selected)
    metadata = (novel.title_vi or novel.title, novel.title, novel.author or "Chưa rõ", novel.description or "")
    snapshot = (2, novel.id, metadata, start_idx, end, lang, rows)
    digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / f"novel-{novel.id}-{start_idx}-{end}-{lang}-{digest}.{extension}"
    return path, metadata, rows, end


@contextmanager
def _atomic_destination(path: Path):
    """No reader can observe an incomplete file, including concurrent exports."""
    with NamedTemporaryFile(dir=path.parent, prefix=path.stem + "-", suffix=".tmp", delete=False) as file:
        temporary = Path(file.name)
    try:
        yield temporary
        try:
            with temporary.open("r+b") as file:
                os.fsync(file.fileno())
        except OSError:
            pass
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_to_txt(novel: Novel, chapters: List[Chapter], start_idx: int = 1,
                  end_idx: Optional[int] = None, lang: str = "vi") -> Path:
    path, metadata, rows, end = _prepare(novel, chapters, start_idx, end_idx, lang, "txt")
    if path.is_file():
        return path
    title, original_title, author, _ = metadata
    language = "Bản dịch Tiếng Việt (DeepSeek AI)" if lang == "vi" else "Nguyên tác Tiếng Trung"
    sections = (
        "=" * 52,
        f"TÁC PHẨM: {title}\nTÊN GỐC: {original_title}\nTÁC GIẢ: {author}",
        f"DẢI CHƯƠNG: Từ chương {start_idx} đến chương {end}\nNGÔN NGỮ: {language}",
        "=" * 52,
        *(f"### {chapter_title} ###\n\n{content}\n\n{'-' * 52}" for _, chapter_title, content in rows),
    )
    with _atomic_destination(path) as temporary:
        temporary.write_text("\n\n".join(sections), encoding="utf-8")
    return path


def _book_intro(metadata, start_idx, end, lang):
    title, original_title, author, description = (escape(value) for value in metadata)
    language = "Tiếng Việt (DeepSeek AI)" if lang == "vi" else "Nguyên tác Tiếng Trung"
    return (
        f"<h1>{title}</h1><p><strong>Tên gốc:</strong> {original_title}</p>"
        f"<p><strong>Tác giả:</strong> {author}</p>"
        f"<p><strong>Dải chương:</strong> {start_idx} - {end}</p>"
        f"<p><strong>Ngôn ngữ:</strong> {language}</p>"
        f"<hr/><h3>Giới thiệu</h3><p>{description}</p>"
    )


def export_to_epub(novel: Novel, chapters: List[Chapter], start_idx: int = 1,
                   end_idx: Optional[int] = None, lang: str = "vi") -> Path:
    path, metadata, rows, end = _prepare(novel, chapters, start_idx, end_idx, lang, "epub")
    if path.is_file():
        return path
    book = epub.EpubBook()
    book.set_identifier(path.stem)
    book.set_title(f"{metadata[0]} (Chương {start_idx} - {end})")
    book.set_language("vi" if lang == "vi" else "zh")
    book.add_author(metadata[2])
    style = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=(
        "body{font-family:Georgia,serif;line-height:1.8;padding:5%;color:#24292f}"
        "h1,h2,h3{text-align:center}p{text-indent:1.8em;margin-bottom:.9em;text-align:justify}"
    ))
    book.add_item(style)
    intro = epub.EpubHtml(title="Giới thiệu", file_name="intro.xhtml", lang="vi")
    intro.content = _book_intro(metadata, start_idx, end, lang)
    intro.add_item(style)
    book.add_item(intro)
    sections = [intro]
    for index, title, content in rows:
        section = epub.EpubHtml(title=title, file_name=f"chap_{index}.xhtml", lang="vi" if lang == "vi" else "zh")
        paragraphs = "".join(f"<p>{escape(paragraph.strip())}</p>" for paragraph in content.splitlines() if paragraph.strip())
        section.content = f"<h2>{escape(title)}</h2>{paragraphs}"
        section.add_item(style)
        book.add_item(section)
        sections = [*sections, section]
    book.toc = tuple(sections)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *sections]
    with _atomic_destination(path) as temporary:
        epub.write_epub(str(temporary), book, {"raise_exceptions": True})
    return path
