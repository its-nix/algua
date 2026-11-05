"""Publication observations never constitute review/CI/Task4 admission proof."""
from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy

import pytest

from algua.operator.gitops import RealGitOps
from algua.operator.mergeback import run_merge_back
from tests.operator import test_gitops_smoke as smoke
from tests.operator import test_mergeback as legacy

REPO = "its-nix/algua"
URL = f"https://github.com/{REPO}.git"


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    repo = smoke.repo.__wrapped__(tmp_path)
    (repo / "CODEOWNERS").write_text(legacy._CODEOWNERS)
    smoke._git(repo, "add", "CODEOWNERS")
    smoke._git(repo, "commit", "-m", "fixture owner policy")
    smoke._git(repo, "push", "origin", "main")
    smoke._git(repo, "checkout", "-B", "feature", "main")
    (repo / "algua/strategies/fixture").mkdir(parents=True)
    (repo / "algua/strategies/fixture/strategy.py").write_text("SIGNAL = 1\n")
    smoke._git(repo, "add", "algua/strategies/fixture/strategy.py")
    smoke._git(repo, "commit", "-m", "fixture strategy")
    smoke._git(repo, "branch", "feat/s")
    tip = smoke._git(repo, "rev-parse", "HEAD").strip()
    smoke._git(repo, "checkout", "main")
    base = smoke._git(repo, "rev-parse", "HEAD").strip()
    monkeypatch.delenv("ALGUA_MERGEBACK_ADMISSION", raising=False)
    monkeypatch.setenv("ALGUA_MERGEBACK_PUBLISH_PR", "1")
    monkeypatch.setattr(legacy, "run_merge_back", run_merge_back)
    return RealGitOps(repo), base, tip, tmp_path / "origin.git"


class Transport:
    """Synthetic GH only; canonical Git network operations map to a real private bare repo."""
    def __init__(self, monkeypatch, candidate):
        self.git, self.base, self.tip, self.remote = candidate
        self.original = subprocess.run
        self.pr = None
        self.posts = []
        self.pushes = []
        self.list_override = None
        self.before_push = None
        self.after_post = None
        self.lost_reply = False
        self.api_calls = []
        self.detail_override = None
        monkeypatch.setattr(subprocess, "run", self.run)

    def metadata(self):
        return {"number": 41, "state": "open", "merged": False, "draft": True,
                "head": {"ref": f"algua-research/{self.tip}", "sha": self.tip,
                         "repo": {"full_name": REPO}},
                "base": {"ref": "main", "sha": self.base, "repo": {"full_name": REPO}}}

    def run(self, args, **kwargs):
        if args[0] == "gh":
            self.api_calls.append(list(args))
            endpoint = args[2]
            assert endpoint.startswith(f"repos/{REPO}/pulls")
            if "--method" in args:
                body = json.loads(kwargs["input"])
                assert body["base"] == "main" and body["head"] == f"algua-research/{self.tip}"
                assert body["draft"] is True
                self.posts.append(body)
                self.pr = self.metadata()
                if self.after_post is not None:
                    self.after_post()
                if self.lost_reply:
                    raise subprocess.CalledProcessError(1, args, stderr=b"AUTH_TOKEN_SENTINEL")
                payload = self.pr
            elif "?" in endpoint:
                payload = self.list_override if self.list_override is not None else (
                    [] if self.pr is None else [self.pr])
            else:
                payload = self.detail_override if self.detail_override is not None else self.pr
            return subprocess.CompletedProcess(args, 0, json.dumps(payload).encode(), b"")
        if args[0] == "git":
            if args == ["git", "rev-parse", "--show-toplevel"]:
                return subprocess.CompletedProcess(args, 0, str(self.git.repo_root), "")
            if args == ["git", "rev-parse", "--absolute-git-dir"]:
                return subprocess.CompletedProcess(args, 0, str(self.git.repo_root / ".git"), "")
            if any("https://" in a for a in args):
                assert URL in args, "unexpected external Git destination"
                if "push" in args:
                    self.pushes.append(list(args))
                    if self.before_push is not None:
                        self.before_push()
                args = [str(self.remote) if a == URL else a for a in args]
        return self.original(args, **kwargs)


def test_public_entry_publishes_and_reuses_exact_head_without_admission(candidate, monkeypatch):
    transport = Transport(monkeypatch, candidate)
    git, base, tip, remote = candidate
    promoter, journal = legacy.Promoter(), legacy.FakeJournal()
    result = legacy._run(git, journal, stage={"s": "backtested"}, promoter=promoter)
    publication = getattr(result, "publication", None)
    assert publication is not None, "public entry did not publish the queued local candidate"
    assert publication["head_sha"] == tip and publication["number"] == 41
    assert result.status == "awaiting_pr_admission"
    assert smoke._git(remote, "rev-parse", "main").strip() == base
    assert smoke._git(remote, "rev-parse", f"refs/heads/algua-research/{tip}").strip() == tip
    second = legacy._run(git, journal, stage={"s": "backtested"}, promoter=promoter)
    assert second.publication == publication
    assert len(transport.posts) == len(transport.pushes) == 1
    assert promoter.tokens == [] and journal.latest("s", tip) is None


def test_default_off_does_not_publish(candidate, monkeypatch):
    transport = Transport(monkeypatch, candidate)
    monkeypatch.delenv("ALGUA_MERGEBACK_PUBLISH_PR")
    result = legacy._run(candidate[0], legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication is None and not transport.posts and not transport.pushes


def test_fixed_api_host_ignores_inherited_gh_host(candidate, monkeypatch):
    monkeypatch.setenv("GH_HOST", "elsewhere.invalid")
    transport = Transport(monkeypatch, candidate)
    result = legacy._run(candidate[0], legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication is not None
    assert all("--hostname" in args and args[args.index("--hostname") + 1] == "github.com"
               for args in transport.api_calls)


def test_admission_api_also_ignores_inherited_gh_host(monkeypatch):
    from algua.operator.pr_admission import _api

    monkeypatch.setenv("GH_HOST", "elsewhere.invalid")
    captured = []
    def run(args, **_kwargs):
        captured.append(args)
        return subprocess.CompletedProcess(args, 0, b"{}", b"")
    monkeypatch.setattr(subprocess, "run", run)
    assert _api(REPO, "pulls/41") == {}
    assert captured[0][captured[0].index("--hostname") + 1] == "github.com"


def test_lookup_refuses_different_returned_pr_number(candidate, monkeypatch):
    transport = Transport(monkeypatch, candidate)
    transport.pr = transport.metadata()
    transport.detail_override = dict(transport.pr, number=42)
    result = legacy._run(candidate[0], legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication is None and not transport.posts


def test_reverted_protected_history_is_never_pushed(candidate, monkeypatch):
    git, base, _, remote = candidate
    repo = git.repo_root
    smoke._git(repo, "checkout", "feat/s")
    (repo / "algua/registry").mkdir()
    (repo / "algua/registry/promotion.py").write_text("PRIVATE_HISTORY_SENTINEL\n")
    smoke._git(repo, "add", "algua/registry/promotion.py")
    smoke._git(repo, "commit", "-m", "fixture protected edit")
    smoke._git(repo, "rm", "algua/registry/promotion.py")
    smoke._git(repo, "commit", "-m", "fixture revert")
    tip = smoke._git(repo, "rev-parse", "HEAD").strip()
    smoke._git(repo, "checkout", "main")
    transport = Transport(monkeypatch, (git, base, tip, remote))
    result = legacy._run(git, legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication is None and not transport.pushes and not transport.posts


def test_more_than_128_unpublished_commits_stays_pending(candidate, monkeypatch):
    git, base, tip, remote = candidate
    tree = smoke._git(git.repo_root, "rev-parse", f"{tip}^{{tree}}").strip()
    for index in range(128):
        tip = smoke._git(git.repo_root, "commit-tree", tree, "-p", tip,
                         "-m", f"fixture history {index}").strip()
    smoke._git(git.repo_root, "update-ref", "refs/heads/feat/s", tip)
    transport = Transport(monkeypatch, (git, base, tip, remote))
    result = legacy._run(git, legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication is None and not transport.posts and not transport.pushes


@pytest.mark.parametrize("race", [False, True])
def test_existing_or_racing_ref_is_never_updated(candidate, monkeypatch, race):
    git, base, tip, remote = candidate
    ref = f"refs/heads/algua-research/{tip}"
    transport = Transport(monkeypatch, candidate)
    def collide():
        transport.original(["git", "-C", str(remote), "update-ref", ref, base], check=True)
    if race:
        transport.before_push = collide
    else:
        collide()
    result = legacy._run(git, legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication is None and not transport.posts
    assert smoke._git(remote, "rev-parse", ref).strip() == base
    if race:
        assert f"--force-with-lease={ref}:" in transport.pushes[0]


@pytest.mark.parametrize("mismatch", ["sha", "ref", "repo", "base", "closed", "multiple"])
def test_wrong_or_ambiguous_pr_is_not_reused_or_recreated(candidate, monkeypatch, mismatch):
    transport = Transport(monkeypatch, candidate)
    transport.pr = transport.metadata()
    if mismatch == "sha":
        transport.pr["head"]["sha"] = transport.base
    if mismatch == "ref":
        transport.pr["head"]["ref"] = "unrelated"
    if mismatch == "repo":
        transport.pr["head"]["repo"]["full_name"] = "other/repo"
    if mismatch == "base":
        transport.pr["base"]["ref"] = "other"
    if mismatch == "closed":
        transport.pr["state"] = "closed"
    if mismatch == "multiple":
        transport.list_override = [transport.pr, deepcopy(transport.pr)]
    result = legacy._run(candidate[0], legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication is None and not transport.posts


def test_lost_creation_reply_reuses_strict_match_without_token_output(
        candidate, monkeypatch, capsys):
    transport = Transport(monkeypatch, candidate)
    transport.lost_reply = True
    result = legacy._run(candidate[0], legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication["number"] == 41 and len(transport.posts) == 1
    assert "AUTH_TOKEN_SENTINEL" not in str(result) + capsys.readouterr().out


def test_local_head_move_after_creation_refuses_observation(candidate, monkeypatch):
    transport = Transport(monkeypatch, candidate)
    transport.after_post = lambda: transport.original(
        ["git", "-C", str(candidate[0].repo_root), "update-ref", "refs/heads/feat/s", candidate[1]],
        check=True)
    result = legacy._run(candidate[0], legacy.FakeJournal(), stage={"s": "backtested"})
    assert result.publication is None and len(transport.posts) == 1


@pytest.mark.skipif(sys.platform != "linux", reason="CLI imports Linux containment primitives")
def test_actual_cli_observation_survives_pending_queue_without_budget(
        candidate, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from algua.cli import paper_cmd
    from algua.cli.main import app
    from algua.config.settings import Settings
    from tests.test_mergeback_queue import _item, mergeback_queue

    Transport(monkeypatch, candidate)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "never-created.db"))
    monkeypatch.setattr(paper_cmd, "RealGitOps", lambda _: candidate[0])
    result = CliRunner().invoke(app, ["paper", "merge-back", "--branch", "feat/s",
        "--strategy", "s", "--universe", "sp500", "--start", "2024-01-01",
        "--end", "2024-06-01", "--demo"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["publication"]["head_sha"] == candidate[2]
    assert payload["publication"]["authority"] == "none"
    assert payload["status"] == "awaiting_pr_admission" and payload["intake"] is None
    assert payload["promoted"] is payload["merged"] is False
    queue, lock = tmp_path / "queue.json", tmp_path / "queue.lock"
    mergeback_queue.enqueue(queue, lock, **_item())
    for _ in range(7):
        mergeback_queue.select_and_reserve(queue, lock)
        saved = mergeback_queue.record_attempt(queue, lock, key="strat_a@research-run/1",
                                               stdout_text=result.stdout)
        assert saved["action"] == "awaiting_admission"
        assert saved["item"]["last_result"]["publication"] == payload["publication"]
        assert saved["item"]["attempts"] == saved["item"]["transient_failures"] == 0
    assert not (tmp_path / "never-created.db").exists()
