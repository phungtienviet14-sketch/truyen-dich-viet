"""Genre catalogue and library ordering shared by the reader pages.

The source exposes nine ranking sections (``booksort1``..``booksort9``); the
code a novel was discovered under is the only reliable genre signal, because
the per-novel info page leaves its own category field blank.
"""
from sqlalchemy import desc, nullslast, or_, select

from app.models import Novel

# (slug, source booksort code, source label, Vietnamese label)
GENRES = (
    ("huyen-huyen", "1", "玄幻魔法", "Huyền huyễn ma pháp"),
    ("vo-hiep", "2", "武侠修真", "Võ hiệp tu chân"),
    ("do-thi", "3", "都市言情", "Đô thị ngôn tình"),
    ("lich-su", "4", "历史军事", "Lịch sử quân sự"),
    ("vong-du", "5", "网游竞技", "Võng du cạnh kỹ"),
    ("khoa-huyen", "6", "科幻小说", "Khoa huyễn"),
    ("kinh-di", "7", "恐怖灵异", "Kinh dị linh dị"),
    ("dong-nhan", "8", "同人漫画", "Đồng nhân mạn họa"),
    ("khac", "9", "其他类型", "Thể loại khác"),
)

BY_SLUG = {slug: {"slug": slug, "code": code, "source_label": source, "name": name}
           for slug, code, source, name in GENRES}
BY_CODE = {code: BY_SLUG[slug] for slug, code, _, _ in GENRES}

LIKE_ESCAPE = "\\"

STATUS_LABELS = {"ongoing": "Đang ra", "completed": "Hoàn thành"}


def genre_name(slug):
    entry = BY_SLUG.get(slug or "")
    return entry["name"] if entry else "Chưa phân loại"


def slug_for_code(code):
    entry = BY_CODE.get(str(code))
    return entry["slug"] if entry else None


# Reader-facing orderings. Each is one explainable column, not a blended score:
# a chart the reader cannot explain is a chart they cannot trust.
VI_ORDERINGS = {
    "doc-nhieu": ("Đọc nhiều nhất", Novel.view_count),
    "yeu-thich": ("Được yêu thích", Novel.favorite_count),
    "yeu-cau": ("Được yêu cầu dịch", Novel.request_count),
    "da-dich": ("Dịch được nhiều nhất", Novel.translated_chapters),
}

CN_ORDERINGS = {
    "de-cu": ("Tổng đề cử tại nguồn", Novel.source_recommends),
    "thang": ("Đề cử trong tháng", Novel.source_monthly_recommends),
    "cat-giu": ("Lượt cất giữ tại nguồn", Novel.source_favorites),
    "do-dai": ("Truyện dài nhất", Novel.source_word_count),
}


def ordering(board, key):
    table = CN_ORDERINGS if board == "trung" else VI_ORDERINGS
    default = "de-cu" if board == "trung" else "doc-nhieu"
    chosen = key if key in table else default
    label, column = table[chosen]
    return chosen, label, column


def ranked_query(board, key):
    """Rows with no measurement sort last instead of pretending to be zero."""
    chosen, label, column = ordering(board, key)
    query = select(Novel).order_by(nullslast(desc(column)), desc(Novel.updated_at), Novel.id)
    return chosen, label, query


def search_filter(term):
    """Match the Vietnamese title, the source title, or the author.

    LIKE wildcards are escaped: a reader searching "100%" means the characters,
    not "anything", and an unescaped _ silently matches any single character.
    """
    escaped = term
    for character in (LIKE_ESCAPE, "%", "_"):
        escaped = escaped.replace(character, LIKE_ESCAPE + character)
    pattern = f"%{escaped}%"
    return or_(Novel.title.ilike(pattern, escape=LIKE_ESCAPE),
               Novel.title_vi.ilike(pattern, escape=LIKE_ESCAPE),
               Novel.author.ilike(pattern, escape=LIKE_ESCAPE))
