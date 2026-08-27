"""Isolated database and fake credentials: tests never use local user data."""
import hashlib
import os
import tempfile
from pathlib import Path

import httpx
import pytest_asyncio

TEST_DATA = Path(tempfile.mkdtemp(prefix="truyen-tests-"))
os.environ.update({
    "SKIP_DOTENV": "1", "PYTHON_DOTENV_DISABLED": "1", "APP_ENV": "test",
    "DATA_DIR": str(TEST_DATA),
    "DATABASE_URL": f"sqlite+aiosqlite:///{TEST_DATA / 'test.db'}",
    "APIKEY_DEEPSEEK": "mock-test-key", "DEEPSEEK_MODEL": "deepseek-v4-flash",
    "ADMIN_USERNAME": "testadmin", "SESSION_COOKIE_SECURE": "false",
    "SESSION_SECRET": "test-only-session-secret-never-use-in-production",
})
TEST_PASSWORD = "test-only-admin-password"
salt = "test-only-salt"
digest = hashlib.pbkdf2_hmac("sha256", TEST_PASSWORD.encode(), salt.encode(), 600_000).hex()
os.environ["ADMIN_PASSWORD_HASH"] = f"pbkdf2_sha256$600000${salt}${digest}"

from app import config  # noqa: E402
config.DATA_DIR = TEST_DATA
config.EXPORT_DIR = TEST_DATA / "exports"
config.EXPORT_DIR.mkdir(exist_ok=True)
config.DATABASE_URL = os.environ["DATABASE_URL"]
config.DATABASE_SYNC_URL = f"sqlite:///{TEST_DATA / 'test.db'}"
from app.main import app  # noqa: E402
from app.database import AsyncSessionLocal, Base, engine, init_db  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def isolated_database(monkeypatch):
    original_send = httpx.AsyncClient.send

    async def guarded_send(client, request, *args, **kwargs):
        transport = client._transport_for_url(request.url)
        if not isinstance(transport, (httpx.ASGITransport, httpx.MockTransport)):
            raise AssertionError("Real outbound HTTP is forbidden in tests; use MockTransport")
        return await original_send(client, request, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", guarded_send)
    await init_db()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    if hasattr(app.state, "rate_limiter"):
        app.state.rate_limiter.clear()
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def admin_client(client):
    token = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    response = await client.post("/admin/login", data={
        "username": "testadmin", "password": TEST_PASSWORD, "csrf_token": token,
    })
    assert response.status_code == 303
    token = (await client.get("/api/auth/csrf")).json()["csrf_token"]
    client.headers["X-CSRF-Token"] = token
    yield client


@pytest_asyncio.fixture
async def sample_novel(db):
    from app.models import Chapter, Novel
    novel = Novel(title="测试小说", title_vi="Truyện thử", source_url="https://www.piaotia.com/html/1/1/index.html", total_chapters=2, translated_chapters=1)
    db.add(novel)
    await db.flush()
    db.add_all([
        Chapter(novel_id=novel.id, chapter_index=1, chapter_title_raw="第一章", chapter_title_vi="Chương 1", url="https://www.piaotia.com/html/1/1/1.html", content_raw="原文", content_vi="Nội dung tiếng Việt", status="completed"),
        Chapter(novel_id=novel.id, chapter_index=2, chapter_title_raw="第二章", url="https://www.piaotia.com/html/1/1/2.html", content_raw="原文二", status="pending"),
    ])
    await db.commit()
    return novel
