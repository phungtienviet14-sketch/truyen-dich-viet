"""Authentication, session management, PBKDF2 passwords, and CSRF protection."""
import argparse
import getpass
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from sqlalchemy import delete, select

from app import config
from app.database import AsyncSessionLocal
from app.models import AdminSession, User, UserSession

COOKIE_NAME = "tdv_session"
LOGIN_COOKIE = "tdv_login_csrf"
USER_COOKIE_NAME = "tdv_user_session"
USER_SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def password_hash(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Admin password must contain at least 12 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000).hex()
    return f"pbkdf2_sha256:600000:{salt}:{digest}"


def user_password_hash(password: str) -> str:
    if len(password) < 6:
        raise ValueError("Mật khẩu phải có ít nhất 6 ký tự")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"pbkdf2_sha256:100000:{salt}:{digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.replace("$", ":").split(":")
        rounds = int(iterations)
        if algorithm != "pbkdf2_sha256" or not 600_000 <= rounds <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), rounds).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def verify_user_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.replace("$", ":").split(":")
        rounds = int(iterations)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), rounds).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def keyed_hash(value: str) -> str:
    return hmac.new(config.SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def credential_version() -> str:
    return keyed_hash(f"{config.ADMIN_USERNAME}:{config.ADMIN_PASSWORD_HASH}")


async def get_session(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token or len(token) > 128:
        return None
    async with AsyncSessionLocal() as db:
        session = await db.get(AdminSession, hashlib.sha256(token.encode()).hexdigest())
        if session and session.expires_at > utcnow() and hmac.compare_digest(session.credential_version, credential_version()):
            return session
    return None


async def create_session():
    token = secrets.token_urlsafe(48)
    session = AdminSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),
                           csrf_token=secrets.token_hex(32), username=config.ADMIN_USERNAME,
                           credential_version=credential_version(),
                           expires_at=utcnow() + timedelta(seconds=config.SESSION_TTL_SECONDS))
    async with AsyncSessionLocal() as db:
        await db.execute(delete(AdminSession).where(AdminSession.expires_at <= utcnow()))
        db.add(session)
        await db.commit()
    return token, session


async def get_user_session(request: Request):
    token = request.cookies.get(USER_COOKIE_NAME)
    if not token or len(token) > 128:
        return None, None
    async with AsyncSessionLocal() as db:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        session = await db.get(UserSession, token_hash)
        if session and session.expires_at > utcnow():
            user = await db.get(User, session.user_id)
            if user:
                return session, user
    return None, None


async def create_user_session(user_id: int):
    token = secrets.token_urlsafe(48)
    session = UserSession(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        user_id=user_id,
        csrf_token=secrets.token_hex(32),
        expires_at=utcnow() + timedelta(seconds=USER_SESSION_TTL_SECONDS)
    )
    async with AsyncSessionLocal() as db:
        await db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
        db.add(session)
        await db.commit()
    return token, session


def check_origin(request: Request):
    origin = request.headers.get("origin")
    if not origin:
        return
    try:
        origin_parsed = urlparse(origin)
        host_header = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        origin_host = origin_parsed.netloc.split(":")[0].lower()
        expected_host = host_header.split(":")[0].lower()
        base_host = request.base_url.netloc.split(":")[0].lower()
        if origin_host and expected_host and origin_host != expected_host and origin_host != base_host:
            raise HTTPException(403, "Nguồn yêu cầu không hợp lệ.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(403, "Nguồn yêu cầu không hợp lệ.")

    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Không chấp nhận yêu cầu khác website.")


async def require_admin(request: Request):
    session = getattr(request.state, "admin_session", None)
    if session is None:
        raise HTTPException(401, "Vui lòng đăng nhập quản trị.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        token = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(token, session.csrf_token):
            raise HTTPException(403, "CSRF token không hợp lệ.")
    return session


async def require_user(request: Request):
    user = getattr(request.state, "current_user", None)
    if user is None:
        raise HTTPException(401, "Vui lòng đăng nhập tài khoản.")
    return user


def login_csrf() -> str:
    value = f"{int(time.time())}:{secrets.token_hex(24)}"
    return f"{value}:{keyed_hash(value)}"


def verify_login_csrf(request: Request, token: str):
    cookie = request.cookies.get(LOGIN_COOKIE, "")
    try:
        timestamp, nonce, signature = token.split(":")
        valid_time = 0 <= time.time() - int(timestamp) <= 900
        valid_signature = hmac.compare_digest(keyed_hash(f"{timestamp}:{nonce}"), signature)
    except (ValueError, TypeError):
        valid_time = valid_signature = False
    if not token or not hmac.compare_digest(cookie, token) or not valid_time or not valid_signature:
        raise HTTPException(403, "Phiên đăng nhập hết hạn. Vui lòng tải lại trang.")


class RateLimiter:
    """Bounded, per-process limiter. Deployment uses one web process."""
    def __init__(self):
        self.buckets = {}

    def clear(self):
        self.buckets.clear()

    def allow(self, key: str, limit: int, seconds: int) -> bool:
        now = time.monotonic()
        if len(self.buckets) > 10_000:
            self.buckets = {key: value for key, value in self.buckets.items() if value[0] > now}
            if len(self.buckets) > 10_000:
                return False
        expiry, count = self.buckets.get(key, (now + seconds, 0))
        if expiry <= now:
            expiry, count = now + seconds, 0
        self.buckets[key] = (expiry, count + 1)
        return count < limit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["hash-password"])
    parser.parse_args()
    password = getpass.getpass("New admin password (12+ characters): ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    print(password_hash(password))
