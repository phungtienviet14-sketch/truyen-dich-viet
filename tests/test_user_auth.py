import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import init_db


@pytest.mark.asyncio
async def test_user_register_login_sync_flow():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Register new user
        reg_payload = {
            "username": "tu_tien_gia",
            "password": "Password123!",
            "display_name": "Tu Tiên Giả",
            "avatar": "🐀",
            "initial_data": {
                "favorites": [{"id": 1, "title": "Phàm Nhân TuTiên", "savedAt": "2026-08-27T08:00:00Z"}],
                "reading_history":{"1": {"chapter_index": 5, "novel_title": "Phàm Nhân TuTiên"}},
                "preferences": {"theme": "dark", "fontSize": 22}
            }
        }
        res = await client.post("/api/user/register", json=reg_payload)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["success"] is True
        assert data["user"]["username"] == "tu_tien_gia"
        assert data["user"]["avatar"] == "🐀"
        assert len(data["user"]["data"][
            "favorites"
        ]) == 1
        assert "tdv_user_session" in res.cookies

        # 2. Get current user profile
        res_me = await client.get("/api/user/me")
        assert res_me.status_code == 200
        data_me = res_me.json()
        assert data_me["authenticated"] is True
        assert data_me["user"]["username"] == "tu_tien_gia"

        # 3. Sync additional data
        sync_payload = {
            "data": {
                "favorites": [
                    {"id": 1, "title": "Phàm Nhân TuTiên", "savedAt": "2026-08-27T08:00:00Z"},
                    {"id": 2, "title": "Tiên Nghịh", "savedAt": "2026-08-27T08:30:00Z"}
                ],
                "reading_history": {
                    "1": {"chapter_index": 10, "novel_title": "Phàm Nhân TuTiên"},
                    "2": {"chapter_index": 1, "novel_title": "Tiên Nghịh"}
                },
                "preferences": {"theme": "sepia", "fontSize": 20}
            }
        }
        res_sync = await client.post("/api/user/sync", json=sync_payload)
        assert res_sync.status_code == 200
        synced = res_sync.json()
        assert len(synced["success"] and synced["data"][
            "favorites"
        ]) == 2
        assert synced["data"]["reading_history"]["1"][
            "chapter_index"
        ] == 10

        # 4. Logout
        res_logout = await client.post("/api/user/logout")
        assert res_logout.status_code == 200

        # Check me is now unauthenticated
        res_me2 = await client.get("/api/user/me")
        assert res_me2.json()["authenticated"] is False

        # 5. Login again
        login_payload = {
            "username": "tu_tien_gia",
            "password": "Password123!"
        }
        res_login = await client.post("/api/user/login", json=login_payload)
        assert res_login.status_code == 200
        data_login = res_login.json()
        assert data_login["success"] is True
        assert len(data_login["user"][
            "data"
        ]["favorites"]) == 2


@pytest.mark.asyncio
async def test_user_register_duplicate_username():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        payload = {"username": "unique_dao_huu", "password": "Password123!"}
        res1 = await client.post("/api/user/register", json=payload)
        assert res1.status_code == 200

        res2 = await client.post("/api/user/register", json=payload)
        assert res2.status_code == 400
        assert "sử dụng" in res2.json()["detail"]
