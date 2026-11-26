"""Compatibility exports; ORM definitions live in catalog.persistence."""
from .persistence.models import College, Major, School

__all__ = ['School', 'College', 'Major']
