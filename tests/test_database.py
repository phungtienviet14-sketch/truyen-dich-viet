import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal, engine
from app.models import Chapter

pytestmark = pytest.mark.asyncio


async def test_foreign_keys_enabled():
    async with engine.connect() as connection:
        assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar() == 1


async def test_duplicate_chapter_rejected(sample_novel):
    async with AsyncSessionLocal() as db:
        db.add(Chapter(novel_id=sample_novel.id, chapter_index=1, chapter_title_raw="duplicate", url="https://www.piaotia.com/different.html"))
        with pytest.raises(IntegrityError):
            await db.commit()
