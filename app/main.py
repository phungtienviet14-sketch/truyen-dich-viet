import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app import config
from app.auth import RateLimiter, check_origin, get_session, get_user_session, keyed_hash
from app.database import AsyncSessionLocal, engine, init_db
from app.models import AuditLog
from app.routes import admin, auth, public

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate_production()
    await init_db()
    embedded = None
    if config.RUN_EMBEDDED_WORKER:
        from app.embedded_worker import start_embedded_worker
        embedded = await start_embedded_worker()
    try:
        yield
    finally:
        if embedded is not None:
            await embedded.stop()
        await engine.dispose()


app = FastAPI(title="Truyện Dịch Việt", lifespan=lifespan, docs_url=None if config.APP_ENV == "production" else "/docs")
app.state.rate_limiter = RateLimiter()
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "app" / "static")), name="static")
app.include_router(auth.router)
app.include_router(public.router)
app.include_router(admin.router)


@app.middleware("http")
async def security_boundary(request: Request, call_next):
    request.state.admin_session = await get_session(request)
    request.state.user_session, request.state.current_user = await get_user_session(request)
    path = request.url.path
    ip = request.client.host if request.client else "unknown"
    request.state.actor_key = keyed_hash(ip)
    if path.startswith("/admin") and path not in {"/admin/login", "/admin/logout"} and not request.state.admin_session:
        return RedirectResponse("/admin/login", status_code=303)
    limit = 5 if path == "/admin/login" and request.method == "POST" else 300
    window = 300 if limit == 5 else 60
    key = f"{request.state.actor_key}:{'login' if limit == 5 else 'all'}"
    if not path.startswith(("/static/", "/health/")) and not app.state.rate_limiter.allow(key, limit, window):
        return JSONResponse({"detail": "Quá nhiều yêu cầu. Vui lòng thử lại sau."}, status_code=429, headers={"Retry-After": str(window)})
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        try:
            check_origin(request)
        except HTTPException as error:
            return JSONResponse({"detail": error.detail}, status_code=error.status_code)
        if int(request.headers.get("content-length", "0") or "0") > 65_536:
            return JSONResponse({"detail": "Yêu cầu quá lớn."}, status_code=413)
        if not request.state.admin_session and path != "/admin/login":
            if not app.state.rate_limiter.allow(f"write:{request.state.actor_key}", 20, 60):
                return JSONResponse({"detail": "Vui lòng chờ trước khi gửi thêm."}, status_code=429)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'"
    if config.APP_ENV == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.state.admin_session or path.startswith(("/admin", "/api/auth")):
        response.headers["Cache-Control"] = "no-store"
    if request.state.admin_session and request.method not in {"GET", "HEAD", "OPTIONS"}:
        async with AsyncSessionLocal() as db:
            db.add(AuditLog(username=request.state.admin_session.username, action=f"{request.method} {path}"[:255], status_code=response.status_code))
            await db.commit()
    return response


@app.exception_handler(ValueError)
async def invalid_value(request, error):
    logger.warning("Invalid operation on %s (%s)", request.url.path, type(error).__name__)
    return JSONResponse({"detail": "Dữ liệu hoặc cấu hình thao tác không hợp lệ."}, status_code=422)


@app.exception_handler(Exception)
async def internal_error(request, error):
    logger.error("Unhandled error on %s (%s): %s", request.url.path, type(error).__name__, error, exc_info=True)
    return JSONResponse({"detail": "Không thể hoàn tất yêu cầu. Vui lòng thử lại sau."}, status_code=500)


@app.get("/health/live")
async def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness():
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT id FROM novels LIMIT 1"))
        return {"status": "ready"}
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
