"""Filesystem helpers shared by the project, library, asset, and run services.

Everything here exists to make the on-disk state safe under concurrency (spec §8.3): writes
land through a temporary file and an atomic ``os.replace`` so a reader never sees a torn file,
directory publication and index updates take a cross-process lock, and content hashing is
centralized so provenance uses one definition of "the bytes".
"""

from __future__ import annotations

import errno
import hashlib
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


def home_dir() -> Path:
    """Return ``$ARCAVEX_HOME`` if set, else ``~/.arcavex`` — the global library root (§5.1)."""
    env = os.environ.get("ARCAVEX_HOME")
    if env:
        return Path(env)
    return Path.home() / ".arcavex"


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (temp file in the same dir, then ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = _mkstemp_beside(path)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` (UTF-8) to ``path`` atomically."""
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_create_bytes(path: Path, data: bytes) -> None:
    """Publish complete ``data`` atomically, failing if ``path`` already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = _mkstemp_beside(path)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.link(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_create_text(path: Path, text: str) -> None:
    """Publish complete UTF-8 text atomically without replacing an existing path."""
    atomic_create_bytes(path, text.encode("utf-8"))


def _mkstemp_beside(path: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")


@contextmanager
def file_lock(
    lock_path: Path,
    *,
    timeout: float = 30.0,
    stale_after: float | None = None,
    poll: float = 0.05,
    validate: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Acquire an exclusive cross-process lock by creating ``lock_path`` with ``O_EXCL``.

    Used to serialize library template publication and index updates (§8.3) so two processes
    never write the same version directory or clobber an index. The lock is a plain file whose
    exclusive creation is the atomic primitive; it is removed on release. A stale lock older than
    ``stale_after`` is reclaimed so a crashed writer cannot wedge the project forever.

    ``timeout`` is how long *this* caller waits; ``stale_after`` is how old a lock must be before
    it is presumed abandoned. They default to the same value for callers that pass neither, but
    they are not the same question: a caller that wants to give up quickly would otherwise also
    declare a perfectly healthy lock abandoned and steal it, which is worse than waiting.
    """
    abandoned_after = timeout if stale_after is None else stale_after
    if validate is not None:
        validate()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if validate is not None:
        validate()
    deadline = time.monotonic() + timeout
    while True:
        try:
            if validate is not None:
                validate()
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            break
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            if _reclaim_if_stale(lock_path, abandoned_after, validate):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"could not acquire lock {lock_path} within {timeout}s") from exc
            time.sleep(poll)
    try:
        if validate is not None:
            validate()
        yield
    finally:
        try:
            if validate is not None:
                validate()
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _reclaim_if_stale(
    lock_path: Path,
    stale_after: float,
    validate: Callable[[], None] | None = None,
) -> bool:
    """Remove a lock file older than ``stale_after`` seconds; return whether it was reclaimed."""
    try:
        if validate is not None:
            validate()
        age = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return True  # vanished — try to acquire again
    if age > stale_after:
        try:
            if validate is not None:
                validate()
            lock_path.unlink()
            return True
        except FileNotFoundError:
            return True
    return False
