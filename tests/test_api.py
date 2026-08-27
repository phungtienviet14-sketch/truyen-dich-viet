import pytest

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("method,path,payload", [
    ("get", "/api/admin/batch-translate/status", None),
    ("get", "/api/admin/sync/logs", None),
    ("post", "/api/novels/crawl", {"url": "https://www.piaotia.com/"}),
    ("post", "/api/novels/1/translate", {}),
    ("post", "/api/novels/1/stop", None),
    ("post", "/api/novels/1/translate-errors", None),
    ("post", "/api/auto-updater/toggle", None),
    ("post", "/api/auto-updater/sync-now", None),
    ("delete", "/api/novels/1", None),
    ("delete", "/api/glossary/1", None),
])
async def test_anonymous_cannot_manage(client, method, path, payload):
    response = await client.request(method, path, json=payload)
    assert response.status_code == 401


async def test_admin_redirects_to_login(client):
    response = await client.get("/admin")
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


async def test_public_views_and_chapter_list(client, sample_novel):
    for path in ["/", f"/novel/{sample_novel.id}", f"/novel/{sample_novel.id}/chapter/1"]:
        response = await client.get(path)
        assert response.status_code == 200
        assert 'href="/admin"' not in response.text
    chapters = await client.get(f"/api/novels/{sample_novel.id}/chapters")
    assert chapters.status_code == 200
    assert len(chapters.json()) == 2


async def test_admin_login_csrf_logout(admin_client, sample_novel):
    assert (await admin_client.get("/admin")).status_code == 200
    response = await admin_client.delete(f"/api/novels/{sample_novel.id}", headers={"X-CSRF-Token": "bad"})
    assert response.status_code == 403
    assert (await admin_client.post("/admin/logout")).status_code in (200, 303)
    assert (await admin_client.delete(f"/api/novels/{sample_novel.id}")).status_code == 401


async def test_login_needs_csrf(client):
    response = await client.post("/admin/login", data={"username": "testadmin", "password": "test-only-admin-password"})
    assert response.status_code == 403


async def test_votes_are_idempotent(client, sample_novel):
    path = f"/api/novels/{sample_novel.id}/request-translation"
    first = await client.post(path)
    second = await client.post(path)
    assert first.status_code == second.status_code == 200
    assert first.json()["request_count"] == second.json()["request_count"] == 1


async def test_comments_validate_relationship_and_length(client, sample_novel):
    assert (await client.post("/api/novels/999999/comments", json={"content": "hello"})).status_code == 404
    assert (await client.post(f"/api/novels/{sample_novel.id}/comments", json={"content": "x" * 5001})).status_code == 422
    assert (await client.post(f"/api/novels/{sample_novel.id}/comments", json={"content": "hello", "chapter_index": 99})).status_code == 404


@pytest.mark.parametrize("payload", [{"concurrency": 0}, {"concurrency": 100}, {"start_chapter": 9, "end_chapter": 1}])
async def test_translation_bounds(admin_client, sample_novel, payload):
    response = await admin_client.post(f"/api/novels/{sample_novel.id}/translate", json=payload)
    assert response.status_code == 422


async def test_download_does_not_crawl_or_mix_languages(client, sample_novel):
    path = f"/api/novels/{sample_novel.id}/download"
    response = await client.get(path, params={"format": "txt", "start": 1, "end": 1})
    assert response.status_code == 200
    assert "Nội dung tiếng Việt" in response.text
    response = await client.get(path, params={"format": "txt", "start": 1, "end": 2})
    assert response.status_code == 409


async def test_healthchecks(client):
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200
