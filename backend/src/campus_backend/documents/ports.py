from pathlib import Path
from typing import Protocol


class OCR(Protocol):
    """Replaceable local OCR. Must return text, never HTML or invented metadata."""
    def recognize(self, path: Path, *, timeout: float) -> str: ...


class ExtractionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
