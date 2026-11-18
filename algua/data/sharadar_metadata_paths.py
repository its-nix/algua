"""Output placement for the TICKERS metadata artifact: outside every checkout, new-only, 0600.

Every checkout (running, main, each linked worktree) is captured as an OPEN directory fd and
identified by (st_dev, st_ino). The output is walked from ``/`` with O_NOFOLLOW; each directory
fd, and the ``..`` chain of the deepest existing one up to the real root, is compared with those
identities, so case-insensitive and alias spellings cannot pass a string check. Scope: the
identity of each actually opened directory and its ``..`` ancestry. ``..`` alone does not prove
containment for every bind mount (it may return the alias's mount parent), and a root moved
or renamed after the ancestry check is outside the guarantee. The checked fd is written through.
Refusals are fixed, value-free text.
"""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

_REFUSE = "could not confirm output is outside every worktree"
_MAX_POINTER = 65536
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
_DIR_NOFOLLOW = _DIR | os.O_NOFOLLOW


class MetadataPrepareError(ValueError):
    """Refusal with fixed, value-free text."""


def _pointer(text: str, base: Path) -> Path:
    raw = text.strip()
    if raw.startswith("gitdir:"):
        raw = raw[len("gitdir:") :].strip()
    if not raw:
        raise MetadataPrepareError(_REFUSE)
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return Path(os.path.abspath(path))


def _mode(name: str, dir_fd: int) -> int | None:
    """lstat mode of a git-layout entry; None only when it is absent."""
    try:
        return os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return None


def _read_pointer(name: str, dir_fd: int) -> str:
    """Strict read of one small regular file: no symlink, no special file, UTF-8 only."""
    if not stat.S_ISREG(_mode(name, dir_fd) or 0):
        raise MetadataPrepareError(_REFUSE)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    fd = os.open(name, flags, dir_fd=dir_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise MetadataPrepareError(_REFUSE)
        raw = os.read(fd, _MAX_POINTER + 1)
    finally:
        os.close(fd)
    if len(raw) > _MAX_POINTER:
        raise MetadataPrepareError(_REFUSE)
    return raw.decode("utf-8")


def _ident(fd: int) -> tuple[int, int]:
    st = os.fstat(fd)
    return (st.st_dev, st.st_ino)


def _discover(repo_root: Path, stack: contextlib.ExitStack) -> set[tuple[int, int]]:
    """Identities of the running, main and every linked checkout, from fds held in ``stack``.

    Git entries are lstat/O_NOFOLLOW; a symlink, unreadable or non-regular entry, malformed
    pointer or a listed root that cannot be opened refuses; the referenced git dirs may not be
    symlinks. Only an absent ``.git`` (root only) or an absent ``worktrees`` directory is
    accepted. Pointer TEXT may spell a path through an
    ordinary alias (``/tmp``); the opened directory is what is identified.
    """
    ids: set[tuple[int, int]] = set()

    def opened(path: Path | str, dir_fd: int | None = None, *, nofollow: bool = False) -> int:
        fd = os.open(path, _DIR_NOFOLLOW if nofollow else _DIR, dir_fd=dir_fd)
        stack.callback(os.close, fd)
        return fd

    def capture(path: Path, *, nofollow: bool = False) -> int:
        fd = opened(path, nofollow=nofollow)
        ids.add(_ident(fd))
        return fd

    root = Path(os.path.abspath(repo_root))
    rfd = capture(root)
    mode = _mode(".git", rfd)
    if mode is None:
        return ids
    if stat.S_ISDIR(mode):
        common = root / ".git"
        cfd = opened(".git", rfd, nofollow=True)
    elif stat.S_ISREG(mode):
        gitdir = _pointer(_read_pointer(".git", rfd), root)
        gfd = capture(gitdir, nofollow=True)  # administrative dir: no final symlink
        common = _pointer(_read_pointer("commondir", gfd), gitdir)
        cfd = capture(common, nofollow=True)
        capture_fd = opened("..", cfd, nofollow=True)  # the actual main root, not its spelling
        ids.add(_ident(capture_fd))
    else:
        raise MetadataPrepareError(_REFUSE)
    wmode = _mode("worktrees", cfd)
    if wmode is None:
        return ids
    if not stat.S_ISDIR(wmode):
        raise MetadataPrepareError(_REFUSE)
    wfd = opened("worktrees", cfd, nofollow=True)
    for name in os.listdir(wfd):
        if not stat.S_ISDIR(_mode(name, wfd) or 0):
            raise MetadataPrepareError(_REFUSE)
        efd = opened(name, wfd, nofollow=True)
        capture(_pointer(_read_pointer("gitdir", efd), common / "worktrees" / name).parent)
    return ids


def publish_metadata(path: Path, data: bytes, *, repo_root: Path) -> Path:
    """Publish ``data`` at a NEW 0600 path that is not inside any checkout (see module doc)."""
    try:
        return _publish(path, data, repo_root)
    except MetadataPrepareError:
        raise
    except Exception:
        raise MetadataPrepareError("output could not be written") from None


def _publish(path: Path, data: bytes, repo_root: Path) -> Path:
    absolute = Path(os.path.abspath(path.expanduser()))
    *dirs, name = absolute.parts[1:]
    inside = MetadataPrepareError("output must be outside the repository")
    with contextlib.ExitStack() as stack:
        try:
            roots = _discover(repo_root, stack)
        except MetadataPrepareError:
            raise
        except Exception:
            raise MetadataPrepareError(_REFUSE) from None

        def descend(comp: str, parent: int | None) -> int | None:
            """Open one directory without following symlinks; None when it is absent."""
            try:
                fd = os.open(comp, _DIR_NOFOLLOW, dir_fd=parent)
            except FileNotFoundError:
                return None
            except OSError:  # symlink, non-directory or any other refusal
                raise MetadataPrepareError("output path must be real directories only") from None
            stack.callback(os.close, fd)
            if _ident(fd) in roots:
                raise inside
            return fd

        dfd = descend("/", None)
        assert dfd is not None
        missing: list[str] = []
        for i, comp in enumerate(dirs):
            nxt = descend(comp, dfd)
            if nxt is None:
                missing = dirs[i:]
                break
            dfd = nxt
        # kernel-level ancestry of the deepest existing directory, to the real root
        seen = {_ident(dfd)}
        cur = dfd
        while True:
            up = os.open("..", _DIR_NOFOLLOW, dir_fd=cur)
            stack.callback(os.close, up)
            ident = _ident(up)
            if ident in roots:
                raise inside
            if ident in seen:
                break
            seen.add(ident)
            cur = up
        for comp in missing:  # below a checked directory only
            os.mkdir(comp, 0o700, dir_fd=dfd)
            made = descend(comp, dfd)
            assert made is not None
            dfd = made
        tmp_name = f".{name}.{os.getpid()}.tmp"
        fd = os.open(
            tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.link(tmp_name, name, src_dir_fd=dfd, dst_dir_fd=dfd)  # atomic, no overwrite
        except FileExistsError:
            raise MetadataPrepareError(
                "output path already exists; refusing to overwrite"
            ) from None
        finally:
            try:
                os.unlink(tmp_name, dir_fd=dfd)
            except FileNotFoundError:
                pass
        os.fsync(dfd)
    return absolute
