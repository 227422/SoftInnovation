"""Independent snapshots and replay results for each account."""
from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from campus_backend.core.db import Base


class StudentPreferences(Base):
    __tablename__ = "student_preferences"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_preferences_version"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    course_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    skill_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    goal_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    interest_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class PreferencesIdempotency(Base):
    __tablename__ = "preferences_idempotency"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
