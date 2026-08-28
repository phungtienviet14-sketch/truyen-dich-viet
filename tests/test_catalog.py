"""Genre catalogue and ranking-column selection (pure functions)."""
import pytest

from app.catalog import BY_CODE, BY_SLUG, GENRES, genre_name, ordering, slug_for_code


@pytest.mark.parametrize("board,key,expected", [
    ("viet", "yeu-thich", "yeu-thich"),
    ("viet", "khong-ton-tai", "doc-nhieu"),
    ("trung", "cat-giu", "cat-giu"),
    # A Vietnamese key must not leak onto the source board.
    ("trung", "doc-nhieu", "de-cu"),
])
def test_unknown_sort_falls_back_per_board(board, key, expected):
    assert ordering(board, key)[0] == expected


def test_every_genre_slug_and_code_is_unique():
    assert len({g[0] for g in GENRES}) == len(GENRES)
    assert len({g[1] for g in GENRES}) == len(GENRES)
    assert set(BY_CODE) == {g[1] for g in GENRES}


@pytest.mark.parametrize("code,slug", [("1", "huyen-huyen"), ("9", "khac"), ("0", None), ("x", None)])
def test_ranking_section_maps_to_a_genre(code, slug):
    assert slug_for_code(code) == slug


def test_an_unclassified_novel_is_labelled_not_blank():
    assert genre_name(None) == "Chưa phân loại"
    assert genre_name("huyen-huyen") == BY_SLUG["huyen-huyen"]["name"]
