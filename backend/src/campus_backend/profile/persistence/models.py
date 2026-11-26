"""Durable profile snapshots and per-account idempotency outcomes."""
from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from campus_backend.core.db import Base


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    __table_args__ = (CheckConstraint("grade BETWEEN 1 AND 8", name="ck_profile_grade"),
                      CheckConstraint("version >= 1", name="ck_profile_version"))

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    school_id: Mapped[str] = mapped_column(String(128), nullable=False)
    school_name: Mapped[str] = mapped_column(String(255), nullable=False)
    college_id: Mapped[str] = mapped_column(String(128), nullable=False)
    college_name: Mapped[str] = mapped_column(String(255), nullable=False)
    major_id: Mapped[str] = mapped_column(String(128), nullable=False)
    major_name: Mapped[str] = mapped_column(String(255), nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    education_stage: Mapped[str | None] = mapped_column(String(13), nullable=True)
    admission_year: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ProfileIdempotency(Base):
    __tablename__ = "profile_idempotency"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
