"""Ephemeral SSH signing helpers for tests of the go-live signature wall.

Moved here from the deleted ``tests/test_human_actor.py`` (the signed ``--actor human`` override
was removed, spec 2026-11-13); go-live is the only signing namespace left, so it is the default.
"""
from __future__ import annotations

import subprocess

_NS = "algua-go-live"


def _make_key(tmp_path, name="id"):
    key = tmp_path / name
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", "t", "-f", str(key)],
                   check=True, capture_output=True)
    return key, (tmp_path / f"{name}.pub").read_text().strip()


def _anchor(tmp_path, principal, pub, namespaces=_NS):
    keytype, keyblob = pub.split()[0], pub.split()[1]
    path = tmp_path / "allowed_signers"
    path.write_text(f'{principal} namespaces="{namespaces}" {keytype} {keyblob}\n')
    return path


def _sign(key, payload, tmp_path, namespace=_NS):
    data = tmp_path / "payload.txt"
    data.write_text(payload)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-n", namespace, "-f", str(key), str(data)],
                   check=True, capture_output=True)
    return (tmp_path / "payload.txt.sig").read_bytes()
