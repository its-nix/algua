#!/usr/bin/env python3
"""One-time Google consent for Algua's Drive access (docs/agent/drive.md).

Run on a machine with a browser, signed in as the Drive owner:

    python3 scripts/drive_consent.py --client-secrets client_secret.json --out drive.json \
        [--create-folder "Algua"]

Scope is `drive.file` ONLY: the token can touch files THIS OAuth client created and nothing else
in the account. Everything it creates is owned by (and stored in) the signing-in account.
`--create-folder` creates the app's own folder with the fresh token and prints its id — use it as
ALGUA_DRIVE_FOLDER_ID (a drive.file app cannot reliably write into a folder it did not create).

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

SCOPES = "https://www.googleapis.com/auth/drive.file"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--client-secrets", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--create-folder", metavar="NAME",
                    help="create the app's own Drive folder and print its id")
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
            elif query.get("state") == state and "error" in query:
                result["error"] = query["error"]
                msg = b"Algua: consent was not granted. You can close this tab."
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
    print("Open this URL signed in as the Drive owner:\n\n" + url + "\n", flush=True)
    while "code" not in result and "error" not in result:
        server.handle_request()
    if "error" in result:
        print(f"consent not granted ({result['error']}); nothing written.")
        return 1

    form = urllib.parse.urlencode({
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=form)) as resp:  # noqa: S310
        token = json.loads(resp.read())
    if "refresh_token" not in token:
        print("No refresh_token returned; revoke the app's access and re-run.")
        return 1
    # Created owner-only from the first byte (no window at the umask's mode).
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"client_id": client_id, "client_secret": client_secret,
                             "refresh_token": token["refresh_token"]}))
    os.chmod(args.out, 0o600)  # an existing file keeps its old mode through O_CREAT
    print(f"wrote {args.out} (mode 0600)")
    if args.create_folder:
        body = json.dumps({"name": args.create_folder,
                           "mimeType": "application/vnd.google-apps.folder"}).encode()
        req = urllib.request.Request(
            "https://www.googleapis.com/drive/v3/files", data=body, method="POST",
            headers={"Authorization": f"Bearer {token['access_token']}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:  # noqa: S310
            folder = json.loads(resp.read())
        print(f"created folder {args.create_folder!r}: ALGUA_DRIVE_FOLDER_ID={folder['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
