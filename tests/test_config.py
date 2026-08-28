"""Connection-string normalization: managed Postgres hands out libpq strings."""
import pytest

from app.config import normalize_database_url


@pytest.mark.parametrize("raw, expected", [
    # Neon and Supabase hand out libpq strings; channel_binding is libpq-only and
    # reaches asyncpg.connect() as an unexpected keyword argument if kept.
    ("postgresql://u:p@host/db?sslmode=require&channel_binding=require",
     "postgresql+asyncpg://u:p@host/db?ssl=require"),
    ("postgres://u:p@host/db?sslmode=require", "postgresql+asyncpg://u:p@host/db?ssl=require"),
    ("postgresql://u:p@host/db?sslmode=disable", "postgresql+asyncpg://u:p@host/db?ssl=disable"),
    ("postgresql://u:p@host/db?sslmode=verify-full", "postgresql+asyncpg://u:p@host/db?ssl=verify-full"),
    # An unrecognised mode must not silently drop TLS.
    ("postgresql://u:p@host/db?sslmode=bogus", "postgresql+asyncpg://u:p@host/db?ssl=require"),
    ("postgresql://u:p@host/db?options=-csearch_path%3Dx", "postgresql+asyncpg://u:p@host/db"),
    ("sqlite+aiosqlite:///data/novels.db", "sqlite+aiosqlite:///data/novels.db"),
])
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected


def test_normalize_database_url_keeps_asyncpg_keywords():
    assert normalize_database_url(
        "postgresql://u:p@host/db?target_session_attrs=read-write&channel_binding=disable"
    ) == "postgresql+asyncpg://u:p@host/db?target_session_attrs=read-write"
