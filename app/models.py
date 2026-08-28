import datetime
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base

class Novel(Base):
    __tablename__ = "novels"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    title_vi = Column(String(255), nullable=True)
    author = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    cover_url = Column(String(500), nullable=True)
    source_url = Column(String(500), nullable=False)
    source_name = Column(String(100), default="piaotia")
    # Fingerprint of (normalized title, normalized author). Mirrors of the same
    # work across platforms share it, so imports can refuse to duplicate a book.
    work_key = Column(String(64), nullable=True, index=True)
    total_chapters = Column(Integer, default=0)
    translated_chapters = Column(Integer, default=0)
    favorite_count = Column(Integer, default=0)
    request_count = Column(Integer, default=0)
    view_count = Column(Integer, default=0, server_default="0")
    # Genre comes from the ranking section a novel was discovered under: the
    # per-novel info page leaves its own category field blank.
    category = Column(String(40), nullable=True, index=True)
    source_status = Column(String(20), nullable=True)
    # The source publishes its own popularity counters. They are a snapshot, so
    # source_stats_at records when, and the reader is told.
    source_favorites = Column(Integer, nullable=True)
    source_recommends = Column(Integer, nullable=True)
    source_monthly_recommends = Column(Integer, nullable=True)
    source_word_count = Column(Integer, nullable=True)
    source_stats_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan", order_by="Chapter.chapter_index")
    glossaries = relationship("Glossary", back_populates="novel", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="novel", cascade="all, delete-orphan", order_by="desc(Comment.created_at)")

    __table_args__ = (
        UniqueConstraint("source_url", name="uq_novel_source_url"),
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_index = Column(Integer, nullable=False, index=True)
    chapter_title_raw = Column(String(255), nullable=False)
    chapter_title_vi = Column(String(255), nullable=True)
    url = Column(String(500), nullable=False)
    content_raw = Column(Text, nullable=True)
    content_vi = Column(Text, nullable=True)
    raw_hash = Column(String(64), nullable=True)
    raw_fetched_at = Column(DateTime, nullable=True)
    source_changed = Column(Boolean, nullable=False, default=False, server_default="0")
    status = Column(String(50), default="pending", index=True) # pending, translating, completed, error
    error_msg = Column(Text, nullable=True)
    translated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    novel = relationship("Novel", back_populates="chapters")

    __table_args__ = (
        Index("ix_novel_chapter_index", "novel_id", "chapter_index"),
        UniqueConstraint("novel_id", "chapter_index", name="uq_chapter_index"),
        UniqueConstraint("novel_id", "url", name="uq_chapter_source"),
    )


class Glossary(Base):
    __tablename__ = "glossaries"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=True, index=True) # Null for global glossary
    original_term = Column(String(255), nullable=False, index=True)
    translated_term = Column(String(255), nullable=False)
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    novel = relationship("Novel", back_populates="glossaries")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_index = Column(Integer, nullable=True, index=True) # Null for novel-level comments
    user_name = Column(String(100), default="Đạo Hữu Vô Danh")
    user_avatar = Column(String(50), default="🧙‍♂️")
    content = Column(Text, nullable=False)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    novel = relationship("Novel", back_populates="comments")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash = Column(String(64), primary_key=True)
    csrf_token = Column(String(64), nullable=False)
    username = Column(String(100), nullable=False)
    credential_version = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)


class Interaction(Base):
    __tablename__ = "interactions"
    key = Column(String(64), primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), nullable=False)
    action = Column(String(255), nullable=False)
    status_code = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), index=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=True)
    avatar = Column(String(50), default="🧙‍♂️")
    data_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                        onupdate=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))

    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    csrf_token = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))

    user = relationship("User", back_populates="sessions")
