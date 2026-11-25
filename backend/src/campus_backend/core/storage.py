"""Database-independent failures shared by services and storage adapters."""


class StorageError(Exception):
    """Storage could not complete an operation; never contains driver details."""


class StorageConflict(StorageError):
    """A database constraint rejected a write; the service resolves its meaning."""
