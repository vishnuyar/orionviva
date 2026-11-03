"""Private paths, bounded ownership and durable exclusive publication."""
from contextlib import contextmanager
import ctypes
import errno
import os
from pathlib import Path
import stat
import sys
import threading
import time

from .store import AuthorityError, IntegrityError


class Busy(AuthorityError):
    """Another operation owns the application root."""


class RecoveryRequired(AuthorityError):
    """An interrupted publication needs explicit authenticated recovery."""


_coordination = {}
_coordination_guard = threading.Lock()


def directory(path, *, private=True):
    if os.name == "nt":
        raise AuthorityError("safe directory descriptor ownership is not qualified on this target")
    path = Path(path).absolute()
    if ".." in path.parts:
        raise AuthorityError("noncanonical application path")
    for ancestor in reversed((path, *path.parents)):
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise AuthorityError("unsafe application ancestor")
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise AuthorityError("application reparse point refused")
    if private and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise AuthorityError("application directory must be private")
    return path


@contextmanager
def directory_descriptor(path, *, private=True):
    path = directory(path, private=private)
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        pinned = os.fstat(descriptor)
        if identity(path) != (pinned.st_dev, pinned.st_ino):
            raise IntegrityError("application directory changed during acquisition")
        yield descriptor
        if identity(path) != (pinned.st_dev, pinned.st_ino):
            raise IntegrityError("application directory replaced during operation")
    finally:
        os.close(descriptor)


def identity(path):
    info = Path(path).lstat()
    return info.st_dev, info.st_ino


def _regular_info(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise AuthorityError("unsafe application file")
    return info


def regular(path):
    return _regular_info(Path(path).lstat())


def read(path):
    path = Path(path)
    directory(path.parent)
    before = regular(path)
    with directory_descriptor(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise IntegrityError("application file replaced during read")
            chunks = []
            while chunk := stream.read(64 * 1024):
                chunks.append(chunk)
            data = b"".join(chunks)
            after = os.fstat(stream.fileno())
    if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (
            before.st_size, before.st_mtime_ns, before.st_ctime_ns):
        raise IntegrityError("application file changed during read")
    if identity(path) != (before.st_dev, before.st_ino):
        raise IntegrityError("application file replaced after read")
    return data


def sync_directory(path):
    directory(path, private=False)
    if os.name == "nt":
        # Directory durability is an admission requirement, never a no-op.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.restype = ctypes.c_void_p
        handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0x02000000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "directory durability unavailable")
        try:
            if not kernel.FlushFileBuffers(ctypes.c_void_p(handle)):
                raise OSError(ctypes.get_last_error(), "directory flush refused")
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    else:
        with directory_descriptor(path, private=False) as fd:
            os.fsync(fd)


def exclusive_write(path, data):
    if type(data) is not bytes:
        raise AuthorityError("exact prepared bytes required")
    path = Path(path)
    directory(path.parent)
    with directory_descriptor(path.parent) as parent:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    regular(path)
    sync_directory(path.parent)


def mkdir(path):
    path = Path(path)
    with directory_descriptor(path.parent, private=False) as parent:
        os.mkdir(path.name, mode=0o700, dir_fd=parent)
        os.fsync(parent)
    return directory(path)


def unlink(path):
    path = Path(path)
    regular(path)
    with directory_descriptor(path.parent) as parent:
        os.unlink(path.name, dir_fd=parent)
        os.fsync(parent)


def rmdir(path):
    path = directory(path)
    with directory_descriptor(path.parent) as parent:
        os.rmdir(path.name, dir_fd=parent)
        os.fsync(parent)


def no_replace(source, destination):
    source, destination = Path(source), Path(destination)
    source_parent, target_parent = directory(source.parent, private=False), directory(destination.parent, private=False)
    source_identity, target_identity = identity(source_parent), identity(target_parent)
    if source.is_dir():
        directory(source)
    else:
        regular(source)
    source_member = identity(source)
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel.MoveFileExW(str(source), str(destination), 0x8):
            raise OSError(ctypes.get_last_error(), "exclusive publication refused")
    else:
        with directory_descriptor(source_parent, private=False) as source_fd, directory_descriptor(target_parent, private=False) as target_fd:
            library = ctypes.CDLL(None, use_errno=True)
            if sys.platform == "darwin":
                function, flags = getattr(library, "renameatx_np", None), 0x4
            elif sys.platform.startswith("linux"):
                function, flags = getattr(library, "renameat2", None), 1
            else:
                raise AuthorityError("exclusive native publication unsupported")
            if function is None:
                raise AuthorityError("exclusive native publication unavailable")
            function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            function.restype = ctypes.c_int
            if function(source_fd, os.fsencode(source.name), target_fd, os.fsencode(destination.name), flags):
                code = ctypes.get_errno()
                raise OSError(code, "exclusive native publication refused")
            installed = os.stat(destination.name, dir_fd=target_fd, follow_symlinks=False)
            if (installed.st_dev, installed.st_ino) != source_member:
                raise IntegrityError("published member differs from owned preparation")
            if stat.S_ISDIR(installed.st_mode):
                if stat.S_IMODE(installed.st_mode) & 0o077:
                    raise IntegrityError("published directory is not private")
            else:
                _regular_info(installed)
            os.fsync(source_fd)
            if source_identity != target_identity:
                os.fsync(target_fd)
            if identity(source_parent) != source_identity or identity(target_parent) != target_identity:
                raise IntegrityError("publication parent replaced")
    if identity(source_parent) != source_identity or identity(target_parent) != target_identity:
        raise IntegrityError("publication parent replaced")
    if identity(destination) != source_member:
        raise IntegrityError("published member differs from owned preparation")
    if destination.is_dir():
        directory(destination)
    else:
        regular(destination)


_HEADS = {"application.json": "application.next", "authority.json": "authority.next",
          "terminal.json": "terminal.next", "intent.json": "intent.next"}


def _head_names(path, temporary):
    path = Path(path)
    if type(temporary) is not str or _HEADS.get(path.name) != temporary:
        raise AuthorityError("unknown mutable application member")
    if path.name == "authority.json" and path.parent.name != "sql":
        raise AuthorityError("child metadata must be owned by SQL directory")
    if path.name == "intent.json":
        name = path.parent.name
        if path.parent.parent.name != "pending" or len(name) != 64 or any(char not in "0123456789abcdef" for char in name):
            raise AuthorityError("intent must be owned by exact operation directory")
    return path


def _read_at(parent, name):
    before = _regular_info(os.stat(name, dir_fd=parent, follow_symlinks=False))
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(descriptor, "rb") as stream:
        opened = _regular_info(os.fstat(stream.fileno()))
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise IntegrityError("mutable member replaced during descriptor acquisition")
        chunks = []
        while chunk := stream.read(64 * 1024):
            chunks.append(chunk)
        data = b"".join(chunks)
        after = os.fstat(stream.fileno())
    current = _regular_info(os.stat(name, dir_fd=parent, follow_symlinks=False))
    observed = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    if any((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != observed for info in (after, current)) or len(data) != before.st_size:
        raise IntegrityError("mutable member changed while reading")
    return before, data


def _replace_held(path, temporary, parent, expected, prepared_identity, *, allow_absent):
    path = _head_names(path, temporary)
    if type(expected) is not bytes:
        raise AuthorityError("exact mutable successor bytes required")
    if type(allow_absent) is not bool:
        raise AuthorityError("closed mutable target state required")
    try:
        _regular_info(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
    except FileNotFoundError:
        if not allow_absent:
            raise IntegrityError("required mutable target is missing")
    pinned = os.fstat(parent)
    if identity(path.parent) != (pinned.st_dev, pinned.st_ino):
        raise IntegrityError("mutable parent replaced before rename")
    os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
    installed, actual = _read_at(parent, path.name)
    if (installed.st_dev, installed.st_ino) != prepared_identity or actual != expected:
        raise IntegrityError("installed mutable head differs from issued preparation")
    os.fsync(parent)
    if identity(path.parent) != (pinned.st_dev, pinned.st_ino):
        raise IntegrityError("mutable parent replaced after rename")


def replace_head(path, data, *, temporary, allow_absent=False):
    if type(data) is not bytes:
        raise AuthorityError("exact mutable preparation bytes required")
    path = _head_names(path, temporary)
    with directory_descriptor(path.parent) as parent:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            prepared = _regular_info(os.fstat(stream.fileno()))
        checked, actual = _read_at(parent, temporary)
        prepared_identity = prepared.st_dev, prepared.st_ino
        if (checked.st_dev, checked.st_ino) != prepared_identity or actual != data:
            raise IntegrityError("mutable draft differs from issued preparation")
        _replace_held(path, temporary, parent, data, prepared_identity, allow_absent=allow_absent)


def finish_head(path, *, temporary, expected, allow_absent=False):
    if type(expected) is not bytes:
        raise AuthorityError("authenticated exact mutable successor bytes required")
    path = _head_names(path, temporary)
    with directory_descriptor(path.parent) as parent:
        prepared, data = _read_at(parent, temporary)
        if data != expected:
            raise IntegrityError("mutable successor changed after authentication")
        _replace_held(path, temporary, parent, data, (prepared.st_dev, prepared.st_ino), allow_absent=allow_absent)


class FileLock:
    def __init__(self, path, *, create=False):
        self.path = Path(path)
        self.fd = None
        try:
            directory(self.path.parent)
            flags = os.O_RDWR | os.O_NOFOLLOW
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            with directory_descriptor(self.path.parent) as parent:
                self.fd = os.open(self.path.name, flags, 0o600, dir_fd=parent)
                if create:
                    os.fsync(self.fd)
                    os.fsync(parent)
            regular(self.path)
            self.file_identity = identity(self.path)
            self.parent_identity = identity(self.path.parent)
            self.pid = os.getpid()
            self.owner = None
            self.depth = 0
            with _coordination_guard:
                self.local = _coordination.setdefault(self.file_identity, threading.Lock())
        except BaseException:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            raise

    def _check(self):
        if (self.fd is None or self.pid != os.getpid()
                or identity(self.path) != self.file_identity
                or identity(self.path.parent) != self.parent_identity
                or (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino) != self.file_identity):
            raise IntegrityError("application lock ownership changed")
        regular(self.path)

    @contextmanager
    def hold(self):
        self._check()
        thread = threading.get_ident()
        if self.owner == thread:
            self.depth += 1
            try:
                yield
                self._check()
            finally:
                self.depth -= 1
            return
        deadline = time.monotonic() + 5
        if not self.local.acquire(timeout=5):
            raise Busy("application lock busy")
        native = False
        try:
            self._check()
            while not native:
                try:
                    if os.name == "nt":
                        import msvcrt
                        position = os.lseek(self.fd, 0, os.SEEK_CUR)
                        try:
                            os.lseek(self.fd, 0x7FFFFFFF, os.SEEK_SET)
                            msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                        finally:
                            os.lseek(self.fd, position, os.SEEK_SET)
                    else:
                        import fcntl
                        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    native = True
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    if time.monotonic() >= deadline:
                        raise Busy("application lock busy") from error
                    time.sleep(min(0.01, deadline - time.monotonic()))
            self._check()
            self.owner, self.depth = thread, 1
            yield
            self._check()
        finally:
            self.owner, self.depth = None, 0
            if native:
                if os.name == "nt":
                    import msvcrt
                    position = os.lseek(self.fd, 0, os.SEEK_CUR)
                    try:
                        os.lseek(self.fd, 0x7FFFFFFF, os.SEEK_SET)
                        msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                    finally:
                        os.lseek(self.fd, position, os.SEEK_SET)
                else:
                    import fcntl
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            self.local.release()

    def close(self):
        if self.depth:
            raise AuthorityError("cannot close owned lock during operation")
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
