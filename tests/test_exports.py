"""Offline regression tests for safe, immutable export artifacts."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from lxml import etree

from app.exporters import epub_txt


@pytest.fixture
def export_data(tmp_path, monkeypatch):
    monkeypatch.setattr(epub_txt, "EXPORT_DIR", tmp_path)
    novel = SimpleNamespace(id=7, title="Same title", title_vi="Truyện <script>alert(1)</script>",
                            author="A & B", description='<img src=x onerror="alert(1)">')
    chapter = SimpleNamespace(chapter_index=1, chapter_title_raw="原文", chapter_title_vi="Chương <b>1</b>",
                              content_vi="Nội dung <script>alert(2)</script> & câu chuyện.",
                              content_raw="原文内容", status="completed")
    return novel, chapter


@pytest.mark.parametrize("exporter", [epub_txt.export_to_txt, epub_txt.export_to_epub])
def test_export_version_changes_for_content_and_identity(export_data, exporter):
    novel, chapter = export_data
    first = exporter(novel, [chapter])
    assert exporter(novel, [chapter]) == first
    revised = SimpleNamespace(**{**vars(chapter), "content_vi": "Bản dịch mới"})
    assert exporter(novel, [revised]) != first
    other = SimpleNamespace(**{**vars(novel), "id": 8})
    assert exporter(other, [chapter]) != first
    assert first.name.startswith("novel-7-1-1-vi-")


@pytest.mark.parametrize("exporter", [epub_txt.export_to_txt, epub_txt.export_to_epub])
@pytest.mark.parametrize("lang", ["vi", "raw"])
def test_export_rejects_missing_content(export_data, exporter, lang):
    novel, chapter = export_data
    missing = SimpleNamespace(**{**vars(chapter), f"content_{lang}": "  "})
    with pytest.raises(ValueError, match="1"):
        exporter(novel, [missing], lang=lang)


@pytest.mark.parametrize("exporter", [epub_txt.export_to_txt, epub_txt.export_to_epub])
def test_export_validates_range_and_language(export_data, exporter):
    novel, chapter = export_data
    for kwargs in ({"lang": "en"}, {"start_idx": 2, "end_idx": 1}):
        with pytest.raises(ValueError):
            exporter(novel, [chapter], **kwargs)
    with pytest.raises(ValueError):
        exporter(novel, [])


def test_epub_escapes_untrusted_metadata_and_content(export_data):
    novel, chapter = export_data
    path = epub_txt.export_to_epub(novel, [chapter])
    with ZipFile(path) as archive:
        documents = [etree.fromstring(archive.read(name)) for name in archive.namelist() if name.endswith(".xhtml")]
    assert all(not doc.xpath("//*[local-name()='script' or local-name()='img']") for doc in documents)
    assert any(chapter.content_vi in "".join(doc.itertext()) for doc in documents)
    assert any(novel.description in "".join(doc.itertext()) for doc in documents)


def test_txt_language_and_range_are_explicit(export_data):
    novel, chapter = export_data
    raw = epub_txt.export_to_txt(novel, [chapter], lang="raw")
    assert "原文内容" in raw.read_text(encoding="utf-8")
    assert chapter.content_vi not in raw.read_text(encoding="utf-8")


def test_concurrent_exports_are_complete_and_no_temp_files_remain(export_data):
    novel, chapter = export_data
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(lambda _: epub_txt.export_to_epub(novel, [chapter]), range(8)))
    assert len(set(paths)) == 1
    with ZipFile(paths[0]) as archive:
        assert archive.testzip() is None
    assert not list(paths[0].parent.glob("*.tmp"))


def test_failed_epub_write_leaves_no_partial_artifact(export_data, monkeypatch):
    novel, chapter = export_data
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(epub_txt.epub, "write_epub", fail)
    with pytest.raises(OSError):
        epub_txt.export_to_epub(novel, [chapter])
    assert list(epub_txt.EXPORT_DIR.iterdir()) == []
