"""Bounded data-only unpacking for the separately approved paper artifact adopter."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

MAX_ZIP = 2 * 1024**3
MAX_TOTAL = 4 * 1024**3
MAX_FILE = 512 * 1024**2
MAX_MEMBERS = 100_000
NAMES = {'application.tar.gz', 'release-spec.json', 'provenance.json', 'SHA256SUMS'}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_raw(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'json_size')
    return raw


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def read_json(path, limit):
    return parse_json(read_raw(path, limit))


def unpack(archive: Path, stage: Path):
    with zipfile.ZipFile(archive) as outer:
        infos = outer.infolist()
        require(len(infos) == 4 and {i.filename for i in infos} == NAMES, 'zip_members')
        require(sum(i.file_size for i in infos) <= MAX_ZIP, 'zip_total')
        for item in infos:
            kind = stat.S_IFMT(item.external_attr >> 16)
            require(not item.is_dir() and kind in {0, stat.S_IFREG}, 'zip_type')
            limit = MAX_ZIP if item.filename == 'application.tar.gz' else 8 * 1024**2
            require(item.file_size <= limit, 'zip_file_size')
            with outer.open(item) as source, (stage / item.filename).open('xb') as target:
                copied = 0
                while chunk := source.read(1024**2):
                    copied += len(chunk)
                    require(copied <= limit, 'zip_file_size')
                    target.write(chunk)
    expected = []
    for line in (stage / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ')
        require(name in NAMES - {'SHA256SUMS'} and name not in expected, 'checksum_names')
        require(sha(stage / name) == digest, 'checksum_mismatch')
        expected.append(name)
    require(set(expected) == NAMES - {'SHA256SUMS'}, 'checksum_names')
    seen: set[str] = set()
    total = 0
    with tarfile.open(stage / 'application.tar.gz', 'r|gz') as inner:
        for member in inner:
            name = member.name.rstrip('/')
            parts = PurePosixPath(name).parts
            require(len(seen) < MAX_MEMBERS and name not in seen, 'tar_duplicate_or_count')
            require(len(name.encode()) <= 1024 and parts and parts[0] == 'release'
                    and name == str(PurePosixPath(name)) and '..' not in parts
                    and '\\' not in name and not name.startswith('/'), 'tar_path')
            require(member.type in {tarfile.DIRTYPE, tarfile.REGTYPE, tarfile.AREGTYPE}
                    and member.sparse is None, 'tar_type')
            require(0 <= member.size <= MAX_FILE, 'tar_file_size')
            total += member.size
            require(total <= MAX_TOTAL, 'tar_total')
            seen.add(name)
            destination = stage / name
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                require(destination.name != '.env', 'env_file')
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                content = inner.extractfile(member)
                if content is None:
                    raise ValueError('tar_missing_file')
                with content, destination.open('xb') as target:
                    copied = 0
                    while chunk := content.read(1024**2):
                        copied += len(chunk)
                        require(copied <= member.size, 'tar_file_size')
                        target.write(chunk)
                    require(copied == member.size, 'tar_truncated')
                destination.chmod(0o555 if member.mode & 0o111 else 0o444)
    root = stage / 'release'
    require(root.is_dir(), 'release_missing')
    files, git_files = {}, {}
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            (Path(base) / name).chmod(0o555)
        for name in names:
            path = Path(base) / name
            relative = path.relative_to(root)
            require(stat.S_ISREG(path.lstat().st_mode), 'unsafe_installed_file')
            if relative.parts[0] == '.git':
                git_files[Path(*relative.parts[1:]).as_posix()] = sha(path)
            else:
                require('.git' not in relative.parts, 'nested_git')
                files[relative.as_posix()] = sha(path)
    spec = read_json(stage / 'release-spec.json', 8 * 1024**2)
    provenance = read_json(stage / 'provenance.json', 64 * 1024)
    require(set(spec) == {'path', 'commit', 'lock_sha256', 'files', 'digest'}, 'release_shape')
    payload = {key: spec[key] for key in ('commit', 'lock_sha256', 'files')}
    require(hashlib.sha256(canonical(payload)).hexdigest() == spec['digest'], 'release_digest')
    require(files == spec['files'] and files.get('uv.lock') == spec['lock_sha256'], 'inventory')
    require(git_files and hashlib.sha256(canonical(git_files)).hexdigest()
            == provenance['git_metadata_digest'], 'git_metadata_digest')
    return root, spec, provenance
