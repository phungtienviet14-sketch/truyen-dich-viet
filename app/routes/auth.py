import asyncio
import hmac
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app import config
from app.auth import (COOKIE_NAME, LOGIN_COOKIE, USER_COOKIE_NAME, USER_SESSION_TTL_SECONDS,
                      check_origin, create_session, create_user_session, login_csrf,
                      require_admin, require_user, user_password_hash,
                      verify_login_csrf, verify_password, verify_user_password)
from app.database import AsyncSessionLocal
from app.models import AdminSession, User, UserSession
from app.web import templates

router = APIRouter()


class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: Optional[str] = Field(None, max_length=100)
    avatar: Optional[str] = Field("🧙‍♂️", max_length=50)
    initial_data: Optional[Dict[str, Any]] = None


class UserLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=128)
    initial_data: Optional[Dict[str, Any]] = None


class UserSyncRequest(BaseModel):
    data: Dict[str, Any]


def set_login_cookie(response, token):
    response.set_cookie(LOGIN_COOKIE, token, max_age=900, httponly=True,
                        secure=config.SESSION_COOKIE_SECURE, samesite="lax", path="/")


def merge_user_data(existing_str: str, incoming_data: Optional[Dict[str, Any]]) -> str:
    try:
        current = json.loads(existing_str or "{}")
    except Exception:
        current = {}

    if not isinstance(current, dict):
        current = {}

    if not incoming_data or not isinstance(incoming_data, dict):
        return json.dumps(current, ensure_ascii=False)

    # 1. Favorites merge
    cur_favs = {f["id"]: f for f in current.get("favorites", []) if isinstance(f, dict) and "id" in f}
    in_favs = {f["id"]: f for f in incoming_data.get("favorites", []) if isinstance(f, dict) and "id" in f}
    for fid, fav in in_favs.items():
        if fid not in cur_favs or (str(fav.get("savedAt", "")) >= str(cur_favs[fid].get("savedAt", ""))):
            cur_favs[fid] = fav
    merged_favs = list(cur_favs.values())

    # 2. Reading history merge
    cur_hist = current.get("reading_history", {})
    if not isinstance(cur_hist, dict):
        cur_hist = {}
    in_hist = incoming_data.get("reading_history", {})
    if isinstance(in_hist, dict):
        for nid, h in in_hist.items():
            if not isinstance(h, dict):
                continue
            cur_h = cur_hist.get(str(nid))
            if not cur_h:
                cur_hist[str(nid)] = h
            else:
                if h.get("chapter_index", 0) >= cur_h.get("chapter_index", 0):
                    cur_hist[str(nid)] = h
                elif str(h.get("updated_at", "")) > str(cur_h.get("updated_at", "")):
                    cur_hist[str(nid)] = h

    # 3. Preferences merge
    cur_prefs = current.get("preferences", {})
    if not isinstance(cur_prefs, dict):
        cur_prefs = {}
    in_prefs = incoming_data.get("preferences", {})
    if isinstance(in_prefs, dict):
        cur_prefs.update(in_prefs)

    result = {
        "favorites": merged_favs,
        "reading_history": cur_hist,
        "preferences": cur_prefs
    }
    return json.dumps(result, ensure_ascii=False)


# ==========================================
# ADMIN AUTH ROUTES
# ==========================================

@router.get("/api/auth/csrf")
async def csrf_token(request: Request):
    session = request.state.admin_session
    token = session.csrf_token if session else login_csrf()
    response = JSONResponse({"csrf_token": token}, headers={"Cache-Control": "no-store"})
    if not session:
        set_login_cookie(response, token)
    return response


@router.get("/admin/login")
async def login_page(request: Request):
    token = login_csrf()
    response = templates.TemplateResponse(request=request, name="admin/login.html", context={"csrf_token": token, "error": None})
    set_login_cookie(response, token)
    return response


@router.post("/admin/login")
async def login(request: Request, username: str = Form(..., max_length=100), password: str = Form(..., max_length=1024), csrf_token: str = Form("")):
    check_origin(request)
    verify_login_csrf(request, csrf_token)
    valid_password = await asyncio.to_thread(verify_password, password, config.ADMIN_PASSWORD_HASH)
    if not config.ADMIN_USERNAME or not hmac.compare_digest(username, config.ADMIN_USERNAME) or not valid_password:
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng.")
    token, _ = await create_session()
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(COOKIE_NAME, token, max_age=config.SESSION_TTL_SECONDS,
                        httponly=True, secure=config.SESSION_COOKIE_SECURE, samesite="lax", path="/")
    response.delete_cookie(LOGIN_COOKIE)
    return response


@router.post("/admin/logout")
async def logout(session=Depends(require_admin)):
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AdminSession).where(AdminSession.token_hash == session.token_hash))
        await db.commit()
    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie(COOKIE_NAME)
    return response


# ==========================================
# READER USER AUTH & SYNC ROUTES
# ==========================================

@router.post("/api/user/register")
async def user_register(payload: UserRegisterRequest, request: Request):
    check_origin(request)
    username = payload.username.strip().lower()
    if not username.isalnum() and not "_" in username:
        raise HTTPException(400, "Tên tài khoản chỉ được chứa chữ cái, số và dấu gạch dưới.")

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Tên tài khoản này đã có người sử dụng. Hãy chọn tên khác.")

        pw_hash = await asyncio.to_thread(user_password_hash, payload.password)
        data_json_str = merge_user_data("{}", payload.initial_data)

        user = User(
            username=username,
            password_hash=pw_hash,
            display_name=payload.display_name.strip() if payload.display_name else payload.username,
            avatar=payload.avatar or "🧙‍♂️",
            data_json=data_json_str
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        token, _ = await create_user_session(user.id)

    response = JSONResponse({
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "avatar": user.avatar,
            "data": json.loads(user.data_json or "{}")
        }
    })
    response.set_cookie(
        USER_COOKIE_NAME, token, max_age=USER_SESSION_TTL_SECONDS,
        httponly=True, secure=config.SESSION_COOKIE_SECURE, samesite="lax", path="/"
    )
    return response


@router.post("/api/user/login")
async def user_login(payload: UserLoginRequest, request: Request):
    check_origin(request)
    username = payload.username.strip().lower()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(401, "Tên tài khoản hoặc mật khẩu không chính xác.")

        valid = await asyncio.to_thread(verify_user_password, payload.password, user.password_hash)
        if not valid:
            raise HTTPException(401, "Tên tài khoản hoặc mật khẩu không chính xác.")

        if payload.initial_data:
            user.data_json = merge_user_data(user.data_json, payload.initial_data)
            await db.commit()
            await db.refresh(user)

        token, _ = await create_user_session(user.id)

    response = JSONResponse({
        "success": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "avatar": user.avatar,
            "data": json.loads(user.data_json or "{}")
        }
    })
    response.set_cookie(
        USER_COOKIE_NAME, token, max_age=USER_SESSION_TTL_SECONDS,
        httponly=True, secure=config.SESSION_COOKIE_SECURE, samesite="lax", path="/"
    )
    return response


@router.post("/api/user/logout")
async def user_logout(request: Request):
    check_origin(request)
    token = request.cookies.get(USER_COOKIE_NAME)
    if token:
        import hashlib
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        async with AsyncSessionLocal() as db:
            await db.execute(delete(UserSession).where(UserSession.token_hash == token_hash))
            await db.commit()

    response = JSONResponse({"success": True, "status": "logged_out"})
    response.delete_cookie(USER_COOKIE_NAME, path="/")
    return response


@router.get("/api/user/me")
async def user_me(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user:
        return JSONResponse({"authenticated": False, "user": None})

    return JSONResponse({
        "authenticated": True,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "avatar": user.avatar,
            "data": json.loads(user.data_json or "{}")
        }
    })


@router.post("/api/user/sync")
async def user_sync(payload: UserSyncRequest, request: Request, user: User = Depends(require_user)):
    check_origin(request)
    async with AsyncSessionLocal() as db:
        db_user = await db.get(User, user.id)
        if not db_user:
            raise HTTPException(404, "Người dùng không tồn tại.")

        db_user.data_json = merge_user_data(db_user.data_json, payload.data)
        await db.commit()
        await db.refresh(db_user)
        updated_data = json.loads(db_user.data_json or "{}")

    return JSONResponse({
        "success": True,
        "data": updated_data
    })
