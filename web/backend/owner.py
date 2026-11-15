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


# The only Sec-Fetch-Site values a write may carry: the app's own fetches (`same-origin`) and a
# user-initiated navigation such as the Web Share Target (`none`). `same-site` is refused too:
# every service on the tailnet shares the ts.net site, so it is not proof of this app.
ALLOWED_FETCH_SITES = frozenset({"none", "same-origin"})


def refuse_cross_site(request: Request) -> None:
    """A page elsewhere cannot write into the Inbox with the owner's tailnet identity.

    `tailscale serve` stamps the owner header on every request from the owner's device, so a
    browser's ``Sec-Fetch-Site`` is what tells the app's own requests apart. Absent headers
    (non-browser clients on the tailnet) still need the owner header above."""
    site = request.headers.get("sec-fetch-site")
    if site is not None and site.lower() not in ALLOWED_FETCH_SITES:
        raise Forbidden(f"writes from Sec-Fetch-Site={site[:20]} are refused")
