"""Installed-only authority. Development builds replace this entire module, never a flag."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ALLOWED_SIGNERS_PATH = Path('/etc/algua/authority/allowed_signers')
SSH_KEYGEN = '/usr/bin/ssh-keygen'
_MAX_ANCHOR = 1024 * 1024
_MAX_MANIFEST = 1024


class AnchorError(RuntimeError):
    """The installed authority cannot be trusted; no alternate authority is permitted."""


@dataclass(frozen=True)
class AnchorSnapshot:
    content: bytes
    path: Path
    pass_fds: tuple[int, ...]


def require_enrollment_allowed() -> None:
    raise AnchorError('installed enrollment refused; privileged human installation required')


def _check_fd(fd: int, *, directory: bool, authority_file: bool = True) -> None:
    info = os.fstat(fd)
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != 0:
        raise AnchorError('authority must contain only root-owned directories and regular files')
    wrong_file_mode = not directory and authority_file and stat.S_IMODE(info.st_mode) != 0o644
    if info.st_mode & 0o022 or wrong_file_mode:
        raise AnchorError('unsafe authority permissions')
    # Reject extended ACLs conservatively, including inherited directory defaults. Never
    # interpret chmod's group mask as proof that no named user can replace the anchor.
    for name in ('system.posix_acl_access', 'system.posix_acl_default'):
        try:
            acl = os.getxattr(fd, name)
        except OSError as exc:
            if exc.errno not in (errno.ENODATA, errno.ENOTSUP):
                raise
        else:
            if acl:
                raise AnchorError('authority ACL refused')


def _read_bounded(fd: int, limit: int) -> bytes:
    content = bytearray()
    while len(content) <= limit:
        chunk = os.read(fd, min(65536, limit + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
    if not content or len(content) > limit:
        raise AnchorError('empty or oversized authority file')
    return bytes(content)


def _read_authority() -> bytes:
    # dir_fd walks retain the checked inode; renaming a checked ancestor cannot redirect
    # a later open. A maintenance-time two-file replacement may safely refuse on mismatch.
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    directory = os.open('/', flags | os.O_DIRECTORY)
    try:
        _check_fd(directory, directory=True)
        for part in ('etc', 'algua', 'authority'):
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
            _check_fd(directory, directory=True)
        values = []
        for name, limit in (('allowed_signers', _MAX_ANCHOR), ('installed.json', _MAX_MANIFEST)):
            fd = os.open(name, flags | os.O_NONBLOCK, dir_fd=directory)
            try:
                _check_fd(fd, directory=False)
                values.append(_read_bounded(fd, limit))
            finally:
                os.close(fd)
    finally:
        os.close(directory)
    content, manifest = values
    try:
        # Duplicate fields also refuse rather than silently accepting the last digest.
        pairs = json.loads(manifest, object_pairs_hook=lambda pairs: pairs)
        expected = [('allowed_signers_sha256', hashlib.sha256(content).hexdigest()),
                    ('schema', 'algua-authority/v1')]
        if sorted(pairs) != expected:
            raise ValueError('manifest schema/hash')
    except (ValueError, TypeError) as exc:
        raise AnchorError('invalid authority manifest or anchor hash mismatch') from exc
    return content


def _check_process() -> None:
    if sys.platform != 'linux' or os.geteuid() == 0 or os.getuid() != os.geteuid():
        raise AnchorError('installed authority requires an unprivileged Linux process')
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
    if any(int(status[name].strip(), 16) for name in ('CapEff', 'CapPrm', 'CapInh', 'CapAmb')):
        raise AnchorError('runtime capabilities refused (including mount authority)')
    if status['NoNewPrivs'].strip() != '1':
        raise AnchorError('installed authority requires NoNewPrivileges')


def _trusted_path(path: Path) -> None:
    """Validate physical runtime paths descriptor-relatively, including every ancestor."""
    if not path.is_absolute() or '..' in path.parts:
        raise AnchorError('nonphysical runtime path')
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open('/', flags | os.O_DIRECTORY)
    try:
        _check_fd(fd, directory=True)
        for index, part in enumerate(path.parts[1:]):
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            directory = stat.S_ISDIR(os.fstat(fd).st_mode)
            if index < len(path.parts) - 2 and not directory:
                raise AnchorError('runtime ancestor is not a directory')
            _check_fd(fd, directory=directory, authority_file=False)
    finally:
        os.close(fd)


def _check_runtime() -> None:
    # This check is in the artifact's policy, not just its wrapper: direct and secondary
    # entrypoints must use the same isolated interpreter and immutable imports.
    if not sys.flags.isolated or not sys.flags.no_site:
        raise AnchorError('installed authority requires Python -I -S')
    origin = Path(__file__).absolute()
    match = re.match(r'^(/opt/algua/releases/[0-9a-f]{40})/', str(origin))
    if match is None:
        raise AnchorError('authority is outside a physical installed release')
    release = Path(match[1])
    _trusted_path(release)
    _trusted_path(Path(SSH_KEYGEN))
    _trusted_path(Path(sys.executable))
    trees = {release}
    for item in sys.path:
        if not item:
            raise AnchorError('current-directory import path refused')
        path = Path(item)
        if path.is_symlink():
            raise AnchorError('import symlink refused')
        # CPython includes a normally absent stdlib zip. Validate its parent even if absent.
        _trusted_path(path if path.exists() else path.parent)
        if path.is_dir():
            trees.add(path)
    # Include stdlib/dependency bytecode and native extensions. Ancestors are checked first;
    # the runtime cannot race the traversal. External ELF dependencies still need the human's
    # deployment inventory, alongside the interpreter that ran these checks.
    for tree in trees:
        for path in tree.rglob('*'):
            if path.is_symlink():
                raise AnchorError('runtime symlink refused')
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                _check_fd(fd, directory=path.is_dir(), authority_file=False)
            finally:
                os.close(fd)
    for alternate in ('signer_anchor_dev.py', 'signer_anchor_installed.py'):
        if list(release.rglob(alternate)):
            raise AnchorError('development or alternate authority implementation in live artifact')


@contextmanager
def open_anchor(path: Path) -> Iterator[AnchorSnapshot]:
    """Re-read the fixed authority and hold one sealed snapshot across both SSH calls."""
    if path != ALLOWED_SIGNERS_PATH:
        raise AnchorError('installed authority path override refused')
    fd = -1
    try:
        _check_process()
        _check_runtime()
        content = _read_authority()
        fd = os.memfd_create('algua-authority', os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
        with os.fdopen(os.dup(fd), 'wb', closefd=True) as stream:
            stream.write(content)
            stream.flush()
        seals = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SEAL
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(fd, fcntl.F_GET_SEALS) != seals:
            raise AnchorError('incomplete authority seals')
        snapshot_path = Path(f'/proc/self/fd/{fd}')
        if snapshot_path.read_bytes() != content:
            raise AnchorError('sealed authority descriptor unavailable')
        yield AnchorSnapshot(content, snapshot_path, (fd,))
    except (OSError, ValueError, AttributeError, KeyError) as exc:
        raise AnchorError('installed authority unavailable or unsafe') from exc
    finally:
        if fd >= 0:
            os.close(fd)


def operator_lock_path() -> Path | None:
    """Mutable coordination state belongs outside the immutable live release."""
    return Path('/var/lib/algua-live/operator.lock')
