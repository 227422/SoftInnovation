from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from campus_backend.core.db import Base


class NoticeFollow(Base):
    __tablename__ = 'notice_follows'
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey('users.id'), primary_key=True)
    notice_id: Mapped[str] = mapped_column(String(80), ForeignKey('notices.id'), primary_key=True)
    starred: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    followed_at: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)
