"""Explicit deployment configuration, independent from process working directory."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

BACKEND_ROOT = Path(__file__).resolve().parents[3]


def require_file_sqlite_url(database_url: str | URL) -> URL:
    """Require a file path so concurrent requests have independent SQLite connections."""
    message = "A file-backed SQLite database URL is required (sqlite:///path/to/file.db)."
    try:
        url = make_url(database_url)
    except (ArgumentError, ValueError):
        raise ValueError(message) from None
    if (
        url.drivername != "sqlite"
        or any(part is not None for part in (url.username, url.password, url.host, url.port))
        or not url.database
        or url.database == ":memory:"
        or url.database.lower().startswith("file:")
        or {"uri", "mode", "vfs"}.intersection(url.query)
    ):
        raise ValueError(message)
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: f'sqlite:///{BACKEND_ROOT / "data/campus.db"}')
    cookie_secure: bool = True
    cookie_name: str = 'campus_session'
    collector_data_dir: Path = field(default_factory=lambda: BACKEND_ROOT / 'data/collector')
    allowed_origins: tuple[str, ...] = ('http://127.0.0.1:8000', 'http://localhost:8000')

    def __post_init__(self):
        require_file_sqlite_url(self.database_url)
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or '*' in origin:
                raise ValueError('allowed_origins must contain exact HTTP(S) origins.')

    @classmethod
    def from_env(cls):
        values = {}
        if (value := os.getenv('CAMPUS_DATABASE_URL')) is not None:
            values['database_url'] = value
        if value := os.getenv('CAMPUS_COLLECTOR_DATA_DIR'):
            values['collector_data_dir'] = Path(value).expanduser().resolve()
        if value := os.getenv('CAMPUS_COOKIE_SECURE'):
            if value.lower() not in ('true', 'false'):
                raise ValueError('CAMPUS_COOKIE_SECURE must be true or false')
            values['cookie_secure'] = value.lower() == 'true'
        if (value := os.getenv('CAMPUS_ALLOWED_ORIGINS')) is not None:
            values['allowed_origins'] = tuple(x.strip() for x in value.split(',') if x.strip())
        return cls(**values)
