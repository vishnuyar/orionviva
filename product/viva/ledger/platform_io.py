"""OS primitives for the ledger's writer exclusion and durable commit head."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import time

# Windows byte-range locks are mandatory for other handles, including readers.
# Reserve a byte outside the supported log extent rather than locking its header.
WINDOWS_LOCK_OFFSET = (1 << 63) - 2


def _windows_lock(fd: int, *, release: bool) -> None:
    import msvcrt

    position = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK if release else msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                if release or exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(0.01)
    finally:
        os.lseek(fd, position, os.SEEK_SET)


def lock_writer(fd: int) -> None:
    """Exclude other ledger writers, retaining Unix flock interoperability."""
    if os.name == "nt":
        if os.fstat(fd).st_size >= WINDOWS_LOCK_OFFSET:
            raise OSError("event log exceeds the supported Windows extent")
        _windows_lock(fd, release=False)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)


def unlock_writer(fd: int) -> None:
    if os.name == "nt":
        _windows_lock(fd, release=True)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def _windows_replace(source: Path, target: Path) -> None:
    import ctypes
    from ctypes import wintypes

    move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
    move.restype = wintypes.BOOL
    # REPLACE_EXISTING | WRITE_THROUGH, without a cross-volume copy fallback.
    if not move(str(source), str(target), 0x1 | 0x8):
        raise ctypes.WinError(ctypes.get_last_error())


def replace_commit_head(source: Path, target: Path) -> None:
    """Replace a flushed head using the platform's durable rename primitive."""
    if os.name == "nt":
        _windows_replace(source, target)
        return
    os.replace(source, target)
    directory_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
