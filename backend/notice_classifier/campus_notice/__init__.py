"""Public entry point for the rule-based campus notice classifier."""
from .engine import analyze_batch

__all__ = ['analyze_batch']
