"""Atomic, directory-confined run storage for a single POSIX machine."""

import fcntl
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from ..json_io import compact_json, json_object
from ..run_contract import MAX_DOCUMENT_BYTES, FactRunError, RunSpec, RunState


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_NOFOLLOW | os.O_NONBLOCK
_STATE_BYTES = 16 * 1024 * 1024


def _check_regular(fd):
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise FactRunError('invalid_run_storage')


def _read(directory, name, max_bytes):
    try:
        fd = os.open(name, os.O_RDONLY | _FILE_FLAGS, dir_fd=directory)
    except FileNotFoundError:
        return None
    try:
        _check_regular(fd)
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            data = handle.read(max_bytes + 1)
    finally:
        os.close(fd)
    if len(data) > max_bytes:
        raise FactRunError('invalid_run_storage')
    return json_object(data)


def _write(directory, name, value, max_bytes):
    data = compact_json(value.model_dump(mode='json')).encode('utf-8')
    if len(data) > max_bytes:
        raise FactRunError('run_file_too_large')
    temp_name = f'.writing-{uuid4().hex}'
    fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _FILE_FLAGS, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temp_name, dir_fd=directory)
        except FileNotFoundError:
            pass


class _LockedRun:
    def __init__(self, directory, job_key):
        self._directory = directory
        self._job_key = job_key

    def read_spec(self, *, required=True):
        raw = _read(self._directory, 'input.json', MAX_DOCUMENT_BYTES)
        if raw is None:
            if required:
                raise FactRunError('unknown_job')
            return None
        spec = RunSpec.model_validate(raw)
        if spec.job_key != self._job_key:
            raise FactRunError('invalid_run_storage')
        return spec

    def write_spec(self, spec):
        _write(self._directory, 'input.json', spec, MAX_DOCUMENT_BYTES)

    def read_state(self, spec):
        raw = _read(self._directory, 'state.json', _STATE_BYTES)
        state = RunState.model_validate(raw) if raw is not None else RunState()
        state.validate_for(spec)
        return state

    def save_state(self, state):
        _write(self._directory, 'state.json', state, _STATE_BYTES)


class LocalFactRunStore:
    def __init__(self, root: Path):
        self._root = Path(root)

    def prepare(self, spec: RunSpec) -> str:
        key = spec.job_key
        with self._lock(key, create=True) as run:
            stored = run.read_spec(required=False)
            if stored is None:
                run.write_spec(spec)
            elif stored != spec:
                raise FactRunError('invalid_run_storage')
        return key

    def lock(self, job_key: str):
        return self._lock(job_key, create=False)

    @contextmanager
    def _lock(self, key: str, *, create: bool):
        if not re.fullmatch(r'[0-9a-f]{64}', key):
            raise FactRunError('invalid_job_key')
        try:
            if create:
                self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            root_fd = os.open(self._root, _DIRECTORY_FLAGS)
            try:
                if create:
                    try:
                        os.mkdir(key, mode=0o700, dir_fd=root_fd)
                    except FileExistsError:
                        pass
                    else:
                        os.fsync(root_fd)
                directory = os.open(key, _DIRECTORY_FLAGS, dir_fd=root_fd)
            finally:
                os.close(root_fd)
            try:
                lock_fd = os.open('.lock', os.O_RDWR | os.O_CREAT | _FILE_FLAGS, 0o600, dir_fd=directory)
                try:
                    _check_regular(lock_fd)
                    try:
                        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise FactRunError('run_busy') from None
                    yield _LockedRun(directory, key)
                finally:
                    os.close(lock_fd)
            finally:
                os.close(directory)
        except FileNotFoundError:
            raise FactRunError('unknown_job') from None
        except (OSError, ValueError, RecursionError):
            raise FactRunError('invalid_run_storage') from None
