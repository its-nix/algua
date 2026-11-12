#!/usr/bin/env python3
"""One-time Google consent for the Algua Drive bot account (docs/agent/drive.md).

Run on a machine with a browser, signed in as the BOT account (not your personal one):

    python3 scripts/drive_consent.py --client-secrets client_secret.json --out drive.json

`client_secret.json` is the "Desktop app" OAuth client downloaded from Google Cloud Console.
Writes `{"client_id", "client_secret", "refresh_token"}` (mode 0600); copy it to the VPS as
ALGUA_DRIVE_CREDENTIALS. Stdlib only.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import secrets
import urllib.parse
import urllib.request
from pathlib import Path

SCOPES = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--client-secrets", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    raw = json.loads(args.client_secrets.read_text(encoding="utf-8"))
    client = raw.get("installed") or raw.get("web") or raw
    client_id, client_secret = client["client_id"], client["client_secret"]
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            if query.get("state") == state and "code" in query:
                result["code"] = query["code"]
                msg = b"Algua: consent received. You can close this tab."
            else:
                msg = b"Algua: unexpected callback."
            self.send_response(200)
            self.end_headers()
            self.wfile.write(msg)

        def log_message(self, *_a: object) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": state})
    print("Open this URL signed in as the Algua bot account:\n\n" + url + "\n", flush=True)
    while "code" not in result:
        server.handle_request()

    form = urllib.parse.urlencode({
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=form)) as resp:  # noqa: S310
        token = json.loads(resp.read())
    if "refresh_token" not in token:
        print("No refresh_token returned; revoke the app's access and re-run.")
        return 1
    args.out.write_text(json.dumps({"client_id": client_id, "client_secret": client_secret,
                                    "refresh_token": token["refresh_token"]}), encoding="utf-8")
    os.chmod(args.out, 0o600)
    print(f"wrote {args.out} (mode 0600)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
