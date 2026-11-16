"""The public recovery document must execute only its exact reviewed inline script."""
import base64
import hashlib
import re
from pathlib import Path


def test_recovery_csp_matches_exact_script():
    source = Path(__file__).resolve().parents[1] / "deploy/google-owner-ingress"
    html = (source / "auth-recovery.html").read_text()
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) == 1
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    config = (source / "auth-recovery.conf").read_text()
    script_policy = re.search(r"script-src ([^;]+)", config)
    assert script_policy is not None
    assert script_policy.group(1) == f"'sha256-{digest}'"
