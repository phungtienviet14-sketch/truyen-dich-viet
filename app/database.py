"""SQLite single-host persistence with per-connection constraints and migrations."""
import asyncio
import importlib.util
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import DATABASE_URL


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
                await migrate_sqlite(connection)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise
    else:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
