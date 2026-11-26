from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from campus_backend.core.db import Base


class School(Base):
    __tablename__ = 'catalog_schools'

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default='')
    source_url: Mapped[str] = mapped_column(Text, default='')
    source_version: Mapped[str] = mapped_column(String(80), default='')
    source_checked_on: Mapped[str] = mapped_column(String(10), default='')
    coverage: Mapped[str] = mapped_column(Text, default='')


class College(Base):
    __tablename__ = 'catalog_colleges'

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    school_id: Mapped[str] = mapped_column(ForeignKey('catalog_schools.id'), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default='')


class Major(Base):
    __tablename__ = 'catalog_majors'

    id: Mapped[str] = mapped_column(String(140), primary_key=True)
    school_id: Mapped[str] = mapped_column(ForeignKey('catalog_schools.id'), index=True)
    college_id: Mapped[str] = mapped_column(ForeignKey('catalog_colleges.id'), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(40), default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default='')
    degree: Mapped[str] = mapped_column(String(80), default='')
    duration: Mapped[str] = mapped_column(String(40), default='')
