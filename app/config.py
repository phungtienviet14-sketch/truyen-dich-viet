"""Environment configuration shared by web and the single-host worker."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
if os.getenv("SKIP_DOTENV", "0") != "1":
    load_dotenv(BASE_DIR / ".env")


def integer(name: str, default: int, minimum: int = 1, maximum: int = 1_000_000_000) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


APP_ENV = os.getenv("APP_ENV", "development")
APIKEY_DEEPSEEK = os.getenv("APIKEY_DEEPSEEK", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_MAX_TOKENS = integer("DEEPSEEK_MAX_TOKENS", 8192, 256, 32768)
MAX_CONCURRENT_TRANSLATIONS = integer("MAX_CONCURRENT_TRANSLATIONS", 3, 1, 5)
REQUEST_TIMEOUT = integer("REQUEST_TIMEOUT", 90, 5, 600)
TRANSLATION_DAILY_TOKEN_LIMIT = integer("TRANSLATION_DAILY_TOKEN_LIMIT", 100_000, 0)
DEEPSEEK_INPUT_USD_PER_MILLION = float(os.getenv("DEEPSEEK_INPUT_USD_PER_MILLION", "0.44"))
DEEPSEEK_OUTPUT_USD_PER_MILLION = float(os.getenv("DEEPSEEK_OUTPUT_USD_PER_MILLION", "1.32"))
MAX_EXPORT_CHAPTERS = integer("MAX_EXPORT_CHAPTERS", 500, 1, 2000)
EXPORT_TTL_HOURS = integer("EXPORT_TTL_HOURS", 24, 1, 168)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_urlsafe(48)
SESSION_TTL_SECONDS = integer("SESSION_TTL_SECONDS", 28800, 300, 86400)
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", str(APP_ENV == "production")).lower() == "true"
CRAWLER_ALLOWED_HOSTS = tuple(host.strip().lower() for host in os.getenv(
    "CRAWLER_ALLOWED_HOSTS", "www.piaotia.com,piaotia.com,www.piaotian.com,piaotian.com,www.biquge.com,biquge.com"
).split(",") if host.strip())

DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))).resolve()
EXPORT_DIR = DATA_DIR / "exports"
DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if "asyncpg" in url and "sslmode=" in url:
        url = url.replace("sslmode=require", "ssl=require").replace("sslmode=prefer", "ssl=prefer").replace("sslmode=disable", "ssl=disable")
    return url


RAW_DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR / 'novels.db'}")
DATABASE_URL = normalize_database_url(RAW_DATABASE_URL)
DATABASE_SYNC_URL = DATABASE_URL.replace("sqlite+aiosqlite:", "sqlite:").replace("postgresql+asyncpg:", "postgresql:")


def validate_production() -> None:
    if APP_ENV != "production":
        return
    if not ADMIN_USERNAME or not ADMIN_PASSWORD_HASH:
        raise RuntimeError("Configure ADMIN_USERNAME and ADMIN_PASSWORD_HASH before production startup")
    if len(os.getenv("SESSION_SECRET", "")) < 32 or not SESSION_COOKIE_SECURE:
        raise RuntimeError("Production requires SESSION_SECRET (32+ characters) and secure session cookies")
