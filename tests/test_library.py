"""Reader-facing library: rankings, search and genre browsing."""
import pytest

from app.catalog import BY_SLUG
from app.models import Novel

pytestmark = pytest.mark.asyncio


async def seed(db):
    """Three novels whose columns deliberately disagree, so a chart that sorts
    by the wrong one is visible in the assertions."""
    rows = [
        Novel(title="玄幻甲", title_vi="Huyen Huyen Giap", author="Tac Gia A",
              source_url="https://www.piaotia.com/html/1/11/index.html",
              category="huyen-huyen", source_status="ongoing",
              source_recommends=900, source_favorites=5, view_count=1,
              favorite_count=1, total_chapters=10, translated_chapters=2),
        Novel(title="都市乙", title_vi="Do Thi At", author="Tac Gia B",
              source_url="https://www.piaotia.com/html/1/22/index.html",
              category="do-thi", source_status="completed",
              source_recommends=10, source_favorites=800, view_count=50,
              favorite_count=3, total_chapters=20, translated_chapters=20),
        # No source numbers at all: must sort last, not as a zero.
        Novel(title="未分类丙", title_vi="Chua Phan Loai Binh", author="Tac Gia C",
              source_url="https://www.piaotia.com/html/1/33/index.html",
              view_count=5, favorite_count=2, total_chapters=5, translated_chapters=0),
    ]
    db.add_all(rows)
    await db.commit()
    return rows


# --- Rankings ---------------------------------------------------------------

async def test_vietnamese_board_ranks_by_reader_activity(client, db):
    await seed(db)
    body = (await client.get("/bang-xep-hang?board=viet&sort=doc-nhieu")).text
    assert body.index("Do Thi At") < body.index("Chua Phan Loai Binh") < body.index("Huyen Huyen Giap")


async def test_chinese_board_ranks_by_source_numbers(client, db):
    await seed(db)
    body = (await client.get("/bang-xep-hang?board=trung&sort=de-cu")).text
    assert body.index("Huyen Huyen Giap") < body.index("Do Thi At")
    # A novel with no source measurement sorts last instead of posing as zero.
    assert body.index("Do Thi At") < body.index("Chua Phan Loai Binh")


async def test_ranking_shows_the_number_it_sorted_by(client, db):
    """A chart must show the measurement it ranked on.

    Regression: the metric was passed with a loop-level `set`, which an
    `include` never sees, so every row rendered without its number.
    """
    await seed(db)
    body = (await client.get("/bang-xep-hang?board=trung&sort=de-cu")).text
    assert "Tổng đề cử tại nguồn" in body and "900" in body
    body = (await client.get("/bang-xep-hang?board=viet&sort=yeu-thich")).text
    assert "Được yêu thích" in body


async def test_ranking_numbers_rows_from_one(client, db):
    await seed(db)
    assert 'rounded-br-2xl' in (await client.get("/bang-xep-hang?board=viet")).text


async def test_chinese_board_states_when_the_numbers_were_captured(client, db):
    await seed(db)
    assert "trang nguồn tự công bố" in (await client.get("/bang-xep-hang?board=trung")).text


async def test_unknown_board_falls_back_to_the_vietnamese_one(client, db):
    await seed(db)
    assert (await client.get("/bang-xep-hang?board=nonsense")).status_code == 200


# --- Search -----------------------------------------------------------------

@pytest.mark.parametrize("term,expected", [
    ("Do Thi", "Do Thi At"),        # Vietnamese title
    ("玄幻甲", "Huyen Huyen Giap"),   # source title
    ("Tac Gia C", "Chua Phan Loai Binh"),  # author
])
async def test_search_matches_title_and_author(client, db, term, expected):
    await seed(db)
    assert expected in (await client.get("/tim-kiem", params={"q": term})).text


async def test_search_reports_no_match_without_erroring(client, db):
    await seed(db)
    response = await client.get("/tim-kiem", params={"q": "khong-he-ton-tai-zzz"})
    assert response.status_code == 200 and "Không tìm thấy" in response.text


async def test_search_treats_like_wildcards_as_characters(client, db):
    """A reader searching "%" means the character, not "match anything"."""
    from app.models import Novel
    db.add_all([
        Novel(title="Giam gia 100%", source_url="https://www.piaotia.com/html/2/1/index.html"),
        Novel(title="Khong lien quan", source_url="https://www.piaotia.com/html/2/2/index.html"),
    ])
    await db.commit()
    body = (await client.get("/tim-kiem", params={"q": "%"})).text
    assert "Giam gia 100%" in body and "Khong lien quan" not in body


async def test_search_underscore_does_not_match_any_character(client, db):
    from app.models import Novel
    db.add_all([
        Novel(title="Ten_co_gach", source_url="https://www.piaotia.com/html/3/1/index.html"),
        Novel(title="TenXcoXgach", source_url="https://www.piaotia.com/html/3/2/index.html"),
    ])
    await db.commit()
    body = (await client.get("/tim-kiem", params={"q": "Ten_co"})).text
    assert "Ten_co_gach" in body and "TenXcoXgach" not in body


async def test_search_api_ignores_one_character_terms(client, db):
    await seed(db)
    assert (await client.get("/api/novels/search", params={"q": "D"})).json()["results"] == []


async def test_search_api_returns_display_fields(client, db):
    await seed(db)
    results = (await client.get("/api/novels/search", params={"q": "Do Thi"})).json()["results"]
    assert len(results) == 1
    assert results[0]["title"] == "Do Thi At" and results[0]["genre"] == BY_SLUG["do-thi"]["name"]


# --- Genres -----------------------------------------------------------------

async def test_genre_page_lists_only_its_own_novels(client, db):
    await seed(db)
    body = (await client.get("/the-loai/huyen-huyen")).text
    assert "Huyen Huyen Giap" in body and "Do Thi At" not in body


async def test_unknown_genre_is_not_found(client, db):
    await seed(db)
    assert (await client.get("/the-loai/khong-co-the-loai")).status_code == 404


async def test_genre_index_counts_each_genre(client, db):
    await seed(db)
    body = (await client.get("/the-loai")).text
    assert BY_SLUG["huyen-huyen"]["name"] in body
    # The uncategorised novel is reported rather than quietly dropped.
    assert "chưa phân loại" in body


# --- Reads ------------------------------------------------------------------

async def test_a_repeat_visit_counts_once_per_day(client, db, sample_novel):
    for _ in range(3):
        assert (await client.get(f"/novel/{sample_novel.id}")).status_code == 200
    await db.refresh(sample_novel)
    assert sample_novel.view_count == 1
