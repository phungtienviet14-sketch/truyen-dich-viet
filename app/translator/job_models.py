"""Durable queue, API accounting and cache tables (additive schema)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TranslationJob(Base):
    __tablename__ = "translation_jobs"
    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False)
    active_key = Column(String(100), unique=True, nullable=True)
    status = Column(String(30), nullable=False, default="queued", index=True)
    policy = Column(String(30), default="all_pending")
    concurrency = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    error = Column(Text, nullable=True)


class TranslationTask(Base):
    __tablename__ = "translation_tasks"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("translation_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    active_key = Column(String(100), unique=True, nullable=True)
    position = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="pending", index=True)
    error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TranslationEvent(Base):
    __tablename__ = "translation_events"
    id = Column(Integer, primary_key=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("translation_jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class WorkerLease(Base):
    __tablename__ = "translation_worker_lease"
    id = Column(Integer, primary_key=True)
    owner = Column(String(100), nullable=False)
    expires_at = Column(DateTime, nullable=False)


class DailyTokenBudget(Base):
    __tablename__ = "translation_daily_budget"
    day = Column(String(10), primary_key=True)
    reserved_tokens = Column(Integer, nullable=False, default=0)


class TranslationUsage(Base):
    __tablename__ = "translation_usage"
    id = Column(Integer, primary_key=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True)
    request_id = Column(String(200), nullable=False)
    model = Column(String(100), nullable=False)
    prompt_version = Column(String(50), nullable=False)
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    estimated_usd = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class TranslationCheckpoint(Base):
    __tablename__ = "translation_checkpoints"
    id = Column(Integer, primary_key=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    cache_key = Column(String(64), nullable=False)
    result = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("chapter_id", "cache_key"),)
