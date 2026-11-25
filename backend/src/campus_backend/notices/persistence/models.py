from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from campus_backend.core.db import Base


class Notice(Base):
    __tablename__ = 'notices'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    school_id: Mapped[str] = mapped_column(String(100), index=True)
    source_id: Mapped[str] = mapped_column(String(160), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[float] = mapped_column(Float)
    last_seen_at: Mapped[float] = mapped_column(Float)
    last_success_at: Mapped[float | None] = mapped_column(Float)
    admitted_at: Mapped[float | None] = mapped_column(Float)
    last_fetch_started_at: Mapped[float | None] = mapped_column(Float)
    latest_version: Mapped[str] = mapped_column(String(80))
    current_version: Mapped[str | None] = mapped_column(String(80))
    fetch_status: Mapped[str] = mapped_column(String(40), default='processing')
    fetch_error: Mapped[str | None] = mapped_column(Text)


class NoticeVersion(Base):
    __tablename__ = 'notice_versions'
    notice_id: Mapped[str] = mapped_column(ForeignKey('notices.id'), primary_key=True)
    content_version: Mapped[str] = mapped_column(String(80), primary_key=True)
    raw: Mapped[dict] = mapped_column(JSON)
    document: Mapped[dict | None] = mapped_column(JSON)
    analysis: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float)
    processed_at: Mapped[float | None] = mapped_column(Float)


class NoticeSource(Base):
    __tablename__ = 'notice_sources'
    notice_id: Mapped[str] = mapped_column(ForeignKey('notices.id'), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(160), primary_key=True)
