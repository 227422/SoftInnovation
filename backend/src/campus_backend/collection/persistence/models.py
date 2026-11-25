from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from campus_backend.core.db import Base


class Job(Base):
    __tablename__ = 'collector_jobs'
    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    source_id: Mapped[str] = mapped_column(String(160), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    due_at: Mapped[float] = mapped_column(Float, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[float | None] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[float] = mapped_column(Float)


class HostLimit(Base):
    __tablename__ = 'collector_host_limits'
    host: Mapped[str] = mapped_column(String(255),primary_key=True)
    retry_at: Mapped[float] = mapped_column(Float)
    code: Mapped[str] = mapped_column(String(40))
