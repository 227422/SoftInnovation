"""Keep database tooling out of business rules and client-facing routes."""
import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "src" / "campus_backend"
PURE_MODELS = {"campus_backend.documents.models", "campus_backend.classification.models"}
PROTECTED = [
    path for feature in ("auth", "catalog", "profile", "preferences", "sources", "collection",
                         "documents", "notices", "classification")
    for path in (SOURCE / feature).glob("*.py")
    if (path.name not in {"models.py", "seed.py", "__init__.py", "cli.py"}
        or f"campus_backend.{feature}.{path.stem}" in PURE_MODELS)
]


@pytest.mark.parametrize("path", PROTECTED, ids=lambda path: str(path.relative_to(SOURCE)))
def test_business_and_routes_do_not_import_database_tools(path):
    violations = []
    package = f"campus_backend.{path.parent.name}"
    for node in ast.walk(ast.parse(path.read_text())):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = resolve_name("." * node.level + (node.module or ""), package)
            names = [module, *(f"{module}.{alias.name}" for alias in node.names)]
        for name in names:
            if (name.split('.')[0] in {'sqlalchemy', 'sqlite3', 'psycopg', 'pymysql', 'alembic'}
                    or 'persistence' in name.split('.')
                    or name in {'campus_backend.core.db', 'campus_backend.database'}
                    or ((name == 'models' or name.endswith('.models')) and name not in PURE_MODELS)
                    or (path.name in {'service.py', 'ports.py'} and name.endswith('providers'))):
                violations.append(f'{node.lineno}: {name}')
    assert not violations, f'{path.name} leaks database implementation: {violations}'


def test_migrated_schema_matches_current_models(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from campus_backend.core.config import Settings
    from campus_backend.core.db import build_engine
    from campus_backend.database import initialize_database
    from campus_backend.metadata import metadata

    settings = Settings(database_url=f'sqlite:///{tmp_path / "schema.db"}')
    initialize_database(settings, seed=False)
    engine = build_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), metadata) == []
    finally:
        engine.dispose()
