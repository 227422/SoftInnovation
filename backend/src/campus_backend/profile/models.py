"""Compatibility imports; profile mappings live in persistence.models."""
from .persistence.models import ProfileIdempotency, StudentProfile

__all__ = ["ProfileIdempotency", "StudentProfile"]
