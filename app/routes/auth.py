import asyncio
import hmac

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete

from app import config
from app.auth import (COOKIE_NAME, LOGIN_COOKIE, check_origin, create_session,
                      login_csrf, require_admin, verify_login_csrf, verify_password)
from app.database import AsyncSessionLocal
from app.models import AdminSession
from app.web import templates

router = APIRouter()


def set_login_cookie(response, token):
    response.set_cookie(LOGIN_COOKIE, token, max_age=900, httponly=True,
                        secure=config.SESSION_COOKIE_SECURE, samesite="strict", path="/")


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
                        httponly=True, secure=config.SESSION_COOKIE_SECURE, samesite="strict", path="/")
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
