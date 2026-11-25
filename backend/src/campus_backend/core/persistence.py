"""Shared SQLAlchemy mechanics. Business modules must not import this module."""
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .storage import StorageConflict, StorageError


@contextmanager
def storage_errors():
    """Translate driver-specific failures at the adapter boundary."""
    try:
        yield
    except IntegrityError:
        raise StorageConflict("Storage constraint rejected the operation") from None
    except SQLAlchemyError:
        raise StorageError("Storage operation failed") from None


@contextmanager
def write_transaction(db):
    """Reserve SQLite's writer before validation; release on every exit path.

    The request's earlier auth lookup is read-only. End its implicit transaction
    before taking ownership here. A future database adapter must supply the
    equivalent ordering guarantee rather than copying this SQLite statement.
    """
    with storage_errors():
        db.rollback()
        try:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            yield
            db.commit()
        except Exception:
            db.rollback()
            raise


def check_ready(db):
    # Include an application table so an uninitialized database is not ready.
    from campus_backend.auth.persistence.models import User
    with storage_errors():
        db.execute(select(User.id).limit(1))
