"""Small cross-platform advisory file lock used for local state coordination."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path


def _lock(handle, *, blocking: bool) -> None:
    if os.name == "nt":
        import msvcrt
        # msvcrt.locking locks bytes from the current position. Keep one byte
        # in every lock file so both new and existing files behave consistently.
        if os.fstat(handle.fileno()).st_size == 0:
            os.write(handle.fileno(), b"\0")
        os.lseek(handle.fileno(), 0, os.SEEK_SET)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        try:
            msvcrt.locking(handle.fileno(), mode, 1)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc
    else:
        import fcntl
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(handle, flags)


def _unlock(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def locked_handle(handle, *, blocking: bool = True):
    _lock(handle, blocking=blocking)
    try:
        yield handle
    finally:
        _unlock(handle)


@contextmanager
def locked_path(path: Path, *, blocking: bool = True, binary: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    mode = "r+b" if binary else "r+"
    with os.fdopen(fd, mode) as handle:
        with locked_handle(handle, blocking=blocking):
            yield handle
