"""Request plumbing for the Inbox writes: body caps, uploads on disk, field validation.

The CLI (`research inbox add`) is the only writer of the Inbox; this module only turns a request
into its argv. Uploads land in ``$ALGUA_WEB_INBOX_DIR/<uuid>/<sanitized name>`` — by default
``<ALGUA_DATA_DIR>/inbox`` (the root settings' data root; relative paths resolve against the repo,
the CLI's working directory). Note the CLI also reads the repo's ``.env``; this backend does not,
so on a deploy ``ALGUA_DATA_DIR`` belongs in the service environment.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Request
from starlette.datastructures import FormData, UploadFile
from starlette.types import Message

from backend.algua_cli import REPO
from backend.params import InvalidParam

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Multipart framing plus the small text fields on top of the file itself.
FORM_OVERHEAD_BYTES = 256 * 1024
MAX_JSON_BYTES = 256 * 1024
MAX_URL_CHARS = 2048
MAX_TITLE_CHARS = 300
MAX_NOTE_CHARS = 4000
# Well under Linux's 128 KiB single-argv limit; the CLI keeps 16 KiB of it (MAX_NOTE_BYTES).
MAX_TEXT_BYTES = 64 * 1024
# Extracted text handed to the CLI by file; it stores at most MAX_NOTE_BYTES of it.
MAX_EXTRACTED_BYTES = 256 * 1024
MAX_SHARE_FILES = 5
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm"}
_URL_RE = re.compile(r"https?://[^\s<>\"']+")


class TooLarge(Exception):
    """Rendered as 413 ``{"ok": false, "code": "too_large"}``."""


def inbox_dir() -> Path:
    explicit = os.environ.get("ALGUA_WEB_INBOX_DIR", "").strip()
    if explicit:
        return Path(explicit)
    data = Path(os.environ.get("ALGUA_DATA_DIR", "").strip() or "data")
    if not data.is_absolute():
        data = REPO / data
    return data / "inbox"


def sanitize_name(name: str | None) -> str:
    """A safe single path component: basename only, a conservative charset, no leading dot."""
    base = Path((name or "").replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).lstrip("._")[:120]
    return base or "upload"


def check_content_length(request: Request, cap: int) -> None:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > cap:
        raise TooLarge(f"request body over {cap} bytes")


async def read_json(request: Request) -> Any:
    check_content_length(request, MAX_JSON_BYTES)
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_JSON_BYTES:
            raise TooLarge(f"request body over {MAX_JSON_BYTES} bytes")
        chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise InvalidParam("body must be valid JSON") from None


async def read_form(request: Request, *, max_files: int) -> FormData:
    """Parse a form while counting the bytes received: a chunked or lying client is cut off at
    the cap instead of spooling an unbounded upload to disk."""
    cap = MAX_UPLOAD_BYTES * max(max_files, 1) + FORM_OVERHEAD_BYTES
    check_content_length(request, cap)
    received = 0
    receive = request.receive

    async def capped_receive() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > cap:
                raise TooLarge(f"request body over {cap} bytes")
        return message

    capped = Request(request.scope, capped_receive)
    return await capped.form(max_files=max_files, max_fields=20)


def form_str(form: FormData, key: str) -> str | None:
    value = form.get(key)
    return (value.strip() or None) if isinstance(value, str) else None


def form_files(form: FormData, key: str) -> list[UploadFile]:
    return [f for f in form.getlist(key) if isinstance(f, UploadFile) and f.filename]


def _check_text(value: Any, name: str, max_chars: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidParam(f"{name} must be a string")
    value = value.strip()
    if "\x00" in value:
        raise InvalidParam(f"{name} must not contain NUL")
    if len(value) > max_chars:
        raise InvalidParam(f"{name} is longer than {max_chars} characters")
    return value or None


def check_title(value: Any) -> str | None:
    return _check_text(value, "title", MAX_TITLE_CHARS)


def check_note(value: Any) -> str | None:
    return _check_text(value, "note", MAX_NOTE_CHARS)


def check_url(value: Any) -> str | None:
    url = _check_text(value, "url", MAX_URL_CHARS)
    if url is not None and (not re.match(r"^https?://[^/\s]+", url) or re.search(r"\s", url)):
        raise InvalidParam("url must be an http(s) link")
    return url


def check_body_text(value: Any) -> str | None:
    text = _check_text(value, "text", MAX_TEXT_BYTES)
    if text is not None and len(text.encode()) > MAX_TEXT_BYTES:
        raise InvalidParam(f"text is longer than {MAX_TEXT_BYTES} bytes")
    return text


def url_in_text(text: str | None) -> str | None:
    """The single http(s) link inside shared text (Android often puts the link there)."""
    found = _URL_RE.findall(text or "")
    return found[0].rstrip(".,;:!?)") if len(found) == 1 else None


async def save_upload(upload: UploadFile) -> Path:
    """Copy the upload to its own directory, refusing it once it passes MAX_UPLOAD_BYTES."""
    target_dir = inbox_dir() / uuid.uuid4().hex
    target_dir.mkdir(parents=True, exist_ok=False)
    target = (target_dir / sanitize_name(upload.filename)).resolve()
    written = 0
    try:
        with target.open("xb") as out:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise TooLarge(f"file over {MAX_UPLOAD_BYTES} bytes")
                out.write(chunk)
    except BaseException:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    return target


def discard_upload(path: Path) -> None:
    shutil.rmtree(path.parent, ignore_errors=True)


def is_pdf(path: Path, content_type: str | None) -> bool:
    if path.suffix.lower() == ".pdf" or (content_type or "").lower() == "application/pdf":
        return True
    with path.open("rb") as fh:
        return fh.read(5) == b"%PDF-"


def is_text_file(path: Path, content_type: str | None) -> bool:
    return path.suffix.lower() in _TEXT_SUFFIXES or (content_type or "").startswith("text/")


def read_text_file(path: Path) -> str | None:
    with path.open("rb") as fh:
        raw = fh.read(MAX_EXTRACTED_BYTES)
    text = raw.decode("utf-8", errors="replace").strip()
    return text or None


@contextlib.contextmanager
def extracted_text_arg(text: str | None) -> Iterator[list[str]]:
    """``[--extracted-text-file=<tmp>]`` while the CLI runs (deleted after), or ``[]``."""
    if not text or not text.strip():
        yield []
        return
    raw = text.encode()[:MAX_EXTRACTED_BYTES].decode("utf-8", errors="ignore")
    fd, name = tempfile.mkstemp(prefix="algua-inbox-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
        yield [f"--extracted-text-file={name}"]
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def optional_args(*, title: str | None, note: str | None) -> list[str]:
    args: list[str] = []
    if title:
        args.append(f"--title={title}")
    if note:
        args.append(f"--note={note}")
    return args
