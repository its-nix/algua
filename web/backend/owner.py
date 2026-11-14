"""The owner check every write passes (spec 2026-11-14 §7.3).

`tailscale serve` stamps the caller's tailnet identity in ``Tailscale-User-Login``. That header is
only trustworthy because the backend listens on a Unix socket nothing but tailscaled can open (see
web/README.md); the check itself is: the header must equal ``ALGUA_WEB_OWNER_LOGIN`` exactly. With
the env unset (or blank) every write is refused, so a misconfigured deploy fails closed.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Request

OWNER_HEADER = "Tailscale-User-Login"
OWNER_ENV = "ALGUA_WEB_OWNER_LOGIN"


class Forbidden(Exception):
    """The request may not write; rendered as 403 ``{"ok": false, "code": "forbidden"}``."""


def require_owner(request: Request) -> None:
    expected = os.environ.get(OWNER_ENV, "").strip()
    if not expected:
        raise Forbidden(f"writes are disabled: {OWNER_ENV} is not set")
    got = request.headers.get(OWNER_HEADER)
    if got is None or not hmac.compare_digest(got.encode(), expected.encode()):
        raise Forbidden("only the owner may write")


def refuse_cross_site(request: Request) -> None:
    """A page on another site cannot post into the Inbox with the owner's tailnet identity.

    Browsers send ``Sec-Fetch-Site``; the app's own fetches are ``same-origin``. Absent headers
    (non-browser clients on the tailnet) still need the owner header above."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise Forbidden("cross-site writes are refused")
