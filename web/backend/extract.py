"""Readable text for Inbox items: PDF text (pypdf) and a best-effort, SSRF-guarded article fetch.

Everything here is best effort: any failure yields ``None`` and the item is still added with the
owner's link/file and note. The fetched text is untrusted content; the CLI bounds its size.

SSRF guard for :func:`fetch_article`: http(s) only; the host is resolved here and EVERY answer must
be a globally routable unicast address (no private, loopback, link-local, site-local, CGNAT/tailnet,
reserved, unspecified, multicast or NAT64; IPv4-mapped IPv6 is unwrapped first); redirects are
followed by hand (at most :data:`MAX_REDIRECTS`) with the same checks on every hop. Every TCP
connection is opened by :class:`_PinnedBackend`, which resolves and vets the host at connect time
and then connects to a vetted IP itself, so no second, unvetted lookup can rebind the name between
check and connect; the URL keeps the hostname, so the Host header, TLS SNI and certificate
verification still use the name. The address actually connected to is re-checked before the body
is read (defense in depth); proxies from the environment are ignored; the whole fetch has a
:data:`TIMEOUT_S` wall clock and the body is cut at :data:`MAX_BODY_BYTES`.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import re
import socket
import sys
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpcore
import httpx

from backend.params import InvalidParam

logger = logging.getLogger(__name__)

TIMEOUT_S = 5.0
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
# Never fetched in v1 (spec §7.3): the link plus the owner's note is the item.
UNFETCHED_DOMAINS = ("x.com", "twitter.com", "youtube.com", "youtu.be")
# Collected PDF text is cut here; the CLI bounds the stored text far below this anyway.
MAX_EXTRACTED_CHARS = 256 * 1024
# PDF extraction runs in a child process killed after PDF_TIMEOUT_S (a hostile content stream can
# pin a worker thread forever; a thread cannot be killed, a process can), and stops after
# MAX_PDF_PAGES pages even when the text is short.
MAX_PDF_PAGES = 200
PDF_TIMEOUT_S = 20.0
_WEB_DIR = Path(__file__).resolve().parents[1]
_REDIRECT_CODES = {301, 302, 303, 307, 308}


class _Refused(Exception):
    """The URL (or a redirect hop) is not one we will fetch."""


def extract_pdf_text(path: Path) -> str | None:
    """The PDF's text, or ``None`` when it has none (scanned/blank) or cannot be read."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts: list[str] = []
        size = 0
        for index, page in enumerate(reader.pages):
            if index >= MAX_PDF_PAGES:
                break
            chunk = page.extract_text() or ""
            parts.append(chunk)
            size += len(chunk)
            if size >= MAX_EXTRACTED_CHARS:
                break
        text = "\n".join(parts).strip()
    except Exception as exc:  # pypdf raises a zoo of errors on hostile/broken files
        logger.info("pdf text extraction failed for %s: %s", path.name, exc)
        return None
    return text[:MAX_EXTRACTED_CHARS] or None


def _worker_argv(path: Path) -> list[str]:
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from backend.extract import _worker_main; _worker_main(sys.argv[2])"
    )
    return [sys.executable, "-c", code, str(_WEB_DIR), str(path)]


def _worker_main(path: str) -> None:
    """Child-process entry: print the PDF's text (possibly empty) to stdout."""
    text = extract_pdf_text(Path(path)) or ""
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))


async def extract_pdf_text_bounded(path: Path) -> str | None:
    """:func:`extract_pdf_text` in a child process with a wall-clock timeout.

    ``None`` for a PDF with no text or an unreadable one (best effort, like the unbounded call).
    A PDF that does not finish within :data:`PDF_TIMEOUT_S` raises :class:`InvalidParam` (HTTP 422).
    """
    proc = await asyncio.create_subprocess_exec(
        *_worker_argv(path),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), PDF_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        logger.info("pdf text extraction timed out for %s", path.name)
        raise InvalidParam("pdf text extraction timed out") from None
    except BaseException:
        proc.kill()
        raise
    if proc.returncode != 0:
        logger.info("pdf text extraction worker failed for %s (rc=%s)", path.name, proc.returncode)
        return None
    text = out[: 4 * MAX_EXTRACTED_CHARS].decode("utf-8", errors="replace").strip()
    return text[:MAX_EXTRACTED_CHARS] or None


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def strip_controls(value: str | None) -> str | None:
    """Drop NUL and other C0/DEL control chars (keeping \\n and \\t): a NUL in an argv element
    makes the subprocess spawn raise, and none of them belong in an Inbox item."""
    if value is None:
        return None
    return _CONTROL_RE.sub("", value) or None


def is_unfetched_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in UNFETCHED_DOMAINS)


# NAT64 prefixes (RFC 6052 well-known, RFC 8215 local-use): a DNS64/NAT64 gateway turns these into
# the embedded IPv4 address, so 64:ff9b::7f00:1 reaches 127.0.0.1. Refused explicitly rather than
# relying on the stdlib tables (3.12 refuses them only because ::/8 counts as reserved, and those
# tables have changed across 3.12.x/3.13).
_NAT64 = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"))


def _is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # Deprecated site-local fec0::/10 still counts as global in the 3.12 tables.
        if ip.is_site_local or any(ip in net for net in _NAT64):
            return False
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


async def _resolve(host: str, port: int) -> list[str]:
    """Every address the host resolves to (blocking lookup kept off the event loop)."""
    infos = await asyncio.to_thread(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def _vetted_addresses(host: str, port: int) -> list[str]:
    """The host's addresses, refused unless there is at least one and EVERY one is public."""
    addrs = await _resolve(host, port)
    if not addrs or not all(_is_public(a) for a in addrs):
        raise _Refused(f"non-public address for {host}")
    return list(dict.fromkeys(addrs))


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Network backend that only ever connects to an address it vetted for this connection.

    httpcore hands ``connect_tcp`` the URL's hostname; instead of letting the inner backend
    resolve it again (a rebinding window), the name is resolved and vetted here and the inner
    backend is given the vetted IP. TLS is started afterwards by httpcore with the origin
    hostname, so SNI and certificate checks are unchanged."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._inner = inner if inner is not None else httpcore.AnyIOBackend()

    async def connect_tcp(
        self, host: str, port: int, timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        options = list(socket_options) if socket_options is not None else None
        last: Exception | None = None
        for addr in await _vetted_addresses(host, port):
            try:
                return await self._inner.connect_tcp(
                    addr, port, timeout=timeout, local_address=local_address,
                    socket_options=options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        assert last is not None  # _vetted_addresses never returns an empty list
        raise last

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise _Refused("unix sockets are never fetched")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _PinnedTransport(httpx.AsyncHTTPTransport):
    """httpx's own transport, over a connection pool whose every connection is pinned."""

    def __init__(self, backend: httpcore.AsyncNetworkBackend | None = None) -> None:
        super().__init__()
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(), http1=True, http2=False, retries=0,
            network_backend=backend if backend is not None else _PinnedBackend())


def _real_transport() -> httpx.AsyncBaseTransport:
    """The real-network transport (a test seam: tests swap the inner network backend)."""
    return _PinnedTransport()


def _transport() -> httpx.AsyncBaseTransport | None:
    """The transport to fetch with (tests substitute a mock); ``None`` = real network."""
    return None


def _peer_ip(response: httpx.Response) -> str | None:
    """The IP the response actually came from, when the transport exposes it."""
    stream = response.extensions.get("network_stream")
    if stream is None:
        return None
    addr = stream.get_extra_info("server_addr")
    return str(addr[0]) if addr else None


async def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _Refused(f"not an http(s) URL: {url[:80]}")
    if is_unfetched_host(parts.hostname):
        raise _Refused(f"not fetched in v1: {parts.hostname}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    await _vetted_addresses(parts.hostname, port)


async def _read_capped(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size >= MAX_BODY_BYTES:
            break
    return b"".join(chunks)[:MAX_BODY_BYTES]


async def _fetch(url: str) -> tuple[str | None, str | None]:
    substitute = _transport()
    # Only a test's substitute transport may lack the peer address; the real network must show it.
    real_network = substitute is None
    transport = _real_transport() if substitute is None else substitute
    async with httpx.AsyncClient(
        transport=transport, trust_env=False, follow_redirects=False,
        timeout=TIMEOUT_S, headers={"User-Agent": "algua-inbox/1"},
    ) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            await _check_url(url)
            async with client.stream("GET", url) as response:
                peer = _peer_ip(response)
                if peer is None and real_network:
                    raise _Refused("peer address not exposed; refusing to read the body")
                if peer is not None and not _is_public(peer):
                    raise _Refused(f"connected to non-public {peer}")
                if response.status_code in _REDIRECT_CODES:
                    location = response.headers.get("location")
                    if not location:
                        return None, None
                    url = urljoin(url, location)
                    continue
                if response.status_code != 200:
                    return None, None
                ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype not in ("text/html", "application/xhtml+xml", "text/plain"):
                    return None, None
                body = await _read_capped(response)
                encoding = response.encoding or "utf-8"
            decoded = body.decode(encoding, errors="replace")
            if ctype == "text/plain":
                return None, _collapse(decoded) or None
            return html_to_text(decoded)
        raise _Refused("too many redirects")


async def fetch_article(url: str) -> tuple[str | None, str | None]:
    """``(title, text)`` of a web page, best effort; ``(None, None)`` when refused or failed."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None, None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None, None
    if is_unfetched_host(parts.hostname):
        return None, None
    try:
        async with asyncio.timeout(TIMEOUT_S):
            title, text = await _fetch(url)
        return strip_controls(title), strip_controls(text)
    except _Refused as exc:
        logger.info("article fetch refused: %s", exc)
    except Exception as exc:  # network, TLS, decoding, timeout: all best effort
        logger.info("article fetch failed for %s: %s", parts.hostname, type(exc).__name__)
    return None, None


class _TextParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif not self._skip_depth:
            self.text_parts.append(data)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def html_to_text(markup: str) -> tuple[str | None, str | None]:
    """Title and visible text of an HTML document (scripts and styles stripped)."""
    parser = _TextParser()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # malformed markup: keep whatever was parsed
        pass
    title = _collapse(html.unescape(" ".join(parser.title_parts)))[:300] or None
    text = _collapse(" ".join(parser.text_parts)) or None
    return title, text

