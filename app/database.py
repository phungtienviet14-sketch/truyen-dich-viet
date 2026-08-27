"""Persistence for SQLite (single host) and Postgres (Render/Neon), with migrations."""
import asyncio
import importlib.util
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import DATABASE_URL

logger = logging.getLogger(__name__)


def get_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"timeout": 30}
    args = {}
    if "ssl=require" in url or "sslmode=require" in url or "neon.tech" in url:
        args["ssl"] = True
    return args


def dialect_insert(model):
    if "postgres" in DATABASE_URL:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        return pg_insert(model)
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    return sqlite_insert(model)


def get_engine_kwargs(url: str) -> dict:
    connect_args = get_connect_args(url)
    kwargs = {
        "echo": False,
        "connect_args": connect_args,
    }
    if not url.startswith("sqlite"):
        kwargs.update({
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 10,
            "max_overflow": 20,
        })
    return kwargs


engine = create_async_engine(DATABASE_URL, **get_engine_kwargs(DATABASE_URL))
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


def backup_legacy_database(path: str | None) -> None:
    if not path or path == ":memory:" or not Path(path).is_file():
        return
    with sqlite3.connect(path) as source:
        if source.execute("PRAGMA user_version").fetchone()[0] >= 2:
            return
        if not source.execute("SELECT name FROM sqlite_master WHERE name='chapters'").fetchone():
            return
        directory = Path(path).parent / "backups"
        directory.mkdir(exist_ok=True)
        target = directory / f"pre-migration-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}.db"
        with sqlite3.connect(target) as backup:
            source.backup(backup)


async def migrate_sqlite(connection) -> None:
    existing = (await connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).scalars().all()
    if "chapters" in existing:
        columns = {row[1] for row in (await connection.execute(text("PRAGMA table_info(chapters)"))).all()}
        for name, definition in {
            "raw_hash": "VARCHAR(64)", "raw_fetched_at": "DATETIME",
            "source_changed": "BOOLEAN NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                await connection.execute(text(f"ALTER TABLE chapters ADD COLUMN {name} {definition}"))
        for name, fields in {"uq_chapter_index": "novel_id, chapter_index", "uq_chapter_source": "novel_id, url"}.items():
            collision = (await connection.execute(text(f"SELECT 1 FROM chapters GROUP BY {fields} HAVING count(*) > 1 LIMIT 1"))).first()
            if collision:
                raise RuntimeError(f"Migration blocked: duplicate chapters ({fields}). Backup preserved; resolve collisions before restarting.")
            await connection.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON chapters ({fields})"))
    await connection.run_sync(Base.metadata.create_all)
    await connection.execute(text("PRAGMA user_version=2"))


async def migrate_novels(connection) -> None:
    """Additive novel-identity migration, portable across SQLite and Postgres.

    Runs before create_all: on a fresh database the table does not exist yet
    and create_all builds it with work_key already in place.
    """
    def inspect_novels(sync_connection):
        inspector = inspect(sync_connection)
        if "novels" not in inspector.get_table_names():
            return None
        return {column["name"] for column in inspector.get_columns("novels")}

    columns = await connection.run_sync(inspect_novels)
    if columns is None:
        return
    if "work_key" not in columns:
        await connection.execute(text("ALTER TABLE novels ADD COLUMN work_key VARCHAR(64)"))
    await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_novels_work_key ON novels (work_key)"))
    duplicates = (await connection.execute(text(
        "SELECT source_url FROM novels GROUP BY source_url HAVING count(*) > 1 LIMIT 5"
    ))).scalars().all()
    if duplicates:
        # Never fail a deploy over pre-existing data; the import path still
        # refuses new duplicates, and an admin can merge these by hand.
        logger.warning("Skipping uq_novel_source_url: %d duplicate source_url values remain (e.g. %s)",
                       len(duplicates), duplicates[0])
        return
    await connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_novel_source_url ON novels (source_url)"))


async def backfill_work_keys() -> None:
    """Fingerprint novels imported before work_key existed."""
    from sqlalchemy import select, update
    from app.crawler.identity import work_key
    from app.models import Novel
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Novel.id, Novel.title, Novel.author).where(
            (Novel.work_key.is_(None)) | (Novel.work_key == "")))).all()
        for row in rows:
            key = work_key(row.title or "", row.author or "")
            if key:
                await db.execute(update(Novel).where(Novel.id == row.id).values(work_key=key))
        if rows:
            await db.commit()
            logger.info("Backfilled work_key for %d novels", len(rows))


async def init_db():
    from app import models  # noqa: F401
    if importlib.util.find_spec("app.translator.job_models"):
        from app.translator import job_models  # noqa: F401
    if DATABASE_URL.startswith("sqlite"):
        await asyncio.to_thread(backup_legacy_database, engine.url.database)
        async with engine.connect() as connection:
            await connection.execute(text("PRAGMA journal_mode=WAL"))
            await connection.commit()
            await connection.execute(text("BEGIN IMMEDIATE"))
            try:
                await migrate_novels(connection)
                await migrate_sqlite(connection)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
    else:
        async with engine.begin() as connection:
            await migrate_novels(connection)
            await connection.run_sync(Base.metadata.create_all)
    await backfill_work_keys()
