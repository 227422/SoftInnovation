from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from campus_backend.core.db import Base


class Source(Base):
    __tablename__ = 'collector_sources'
    source_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    school_id: Mapped[str] = mapped_column(String(100), index=True)
    config: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default='pending')
    next_check_at: Mapped[float] = mapped_column(Float, default=0, index=True)
    last_attempt_at: Mapped[float | None] = mapped_column(Float)
    last_success_at: Mapped[float | None] = mapped_column(Float)
    last_error: Mapped[str | None] = mapped_column(Text)
    checks: Mapped[int] = mapped_column(Integer, default=0)
    history_status: Mapped[str] = mapped_column(String(40), default='pending')
