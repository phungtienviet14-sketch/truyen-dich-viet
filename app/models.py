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
    total_chapters = Column(Integer, default=0)
    translated_chapters = Column(Integer, default=0)
    favorite_count = Column(Integer, default=0)
    request_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    chapters = relationship("Chapter", back_populates="novel", cascade="all, delete-orphan", order_by="Chapter.chapter_index")
    glossaries = relationship("Glossary", back_populates="novel", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="novel", cascade="all, delete-orphan", order_by="desc(Comment.created_at)")


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
