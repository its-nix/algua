"""The real public merge-back entry must refuse the old direct-main bypass."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from algua.operator import pr_admission
from algua.operator.gitops import RealGitOps
from algua.operator.journal import MergeBackRecord
from algua.operator.mergeback import run_merge_back
from tests.operator import test_gitops_smoke as smoke
from tests.operator import test_mergeback as legacy

_git = smoke._git

@pytest.fixture
def git_repo(tmp_path):
    return smoke.repo.__wrapped__(tmp_path)

TIP, BASE, MERGE, TREE = "a" * 40, "b" * 40, "c" * 40, "d" * 40


def evidence():
    policy = {"schema": "merge-pr-admission/v1", "repository": "owner/repo",
              "pull_request": 3, "head_sha": TIP, "base_sha": BASE, "reviewer_ids": [2],
              "required_checks": {"gate": 7}, "isolation": {
                  "passed": True, "assessment_ref": "synthetic fixture, not a Task4 assessment",
                  "scope": "authoritative_strategy_execution", "baseline_commit": BASE},
              "checked_tree": {"base_sha": BASE, "head_sha": TIP, "tree_sha": TREE,
                               "check_run_ids": {"gate": 21}}}
    pr = {"number": 3, "head": {"sha": TIP, "repo": {"full_name": "owner/repo"}},
          "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
          "merged": True, "merge_commit_sha": MERGE, "user": {"id": 1}}
    reviews = [{"id": 11, "state": "APPROVED", "commit_id": TIP, "user": {"id": 2}}]
    checks = {"total_count": 1, "check_runs": [{"id": 21, "name": "gate", "app": {"id": 7},
               "head_sha": TIP, "status": "completed", "conclusion": "success"}]}
    return policy, pr, reviews, checks


class ReviewedGit(legacy.FakeGit):
    def __init__(self):
        super().__init__(branch_tip=TIP, origin_main=MERGE, local_main=BASE,
                         merge_sha=MERGE, tip_on_origin=True)

    def resolve(self, ref):
        if ref == MERGE + "^1":
            return BASE
        return TREE if ref == MERGE + "^{tree}" else super().resolve(ref)

    def adopt_verified_main(self, merge):
        assert merge == MERGE
        self.calls.append("adopt")
        self.local_main = self.origin_main


def install_evidence(monkeypatch, data=None):
    policy, pr, reviews, checks = evidence() if data is None else data
    monkeypatch.setattr(pr_admission, "_descriptor", lambda: deepcopy(policy))
    monkeypatch.setattr(pr_admission, "_api", lambda _repo, path:
                        checks if "/check-runs" in path else reviews if "/reviews" in path else pr)
    monkeypatch.setattr(legacy, "run_merge_back", run_merge_back)


def test_verified_existing_pr_drives_actual_strict_saga_once(monkeypatch):
    install_evidence(monkeypatch)
    git, journal, promoter = ReviewedGit(), legacy.FakeJournal(), legacy.Promoter()
    result = legacy._run(git, journal, stage={"s": "backtested"}, promoter=promoter)
    assert result.status == "promoted_allocated" and len(promoter.tokens) == 1
    assert journal.latest("s", TIP).pr_merge_sha == MERGE
    assert journal.latest("s", TIP).pr_number == 3
    second = legacy._run(git, journal, stage={"s": "paper"}, promoter=promoter)
    assert second.status == "promoted_allocated"
    assert journal.latest("s", TIP).base_sha == BASE
    assert len(promoter.tokens) == 1
    assert not any(isinstance(c, tuple) and c[0] in {"begin", "push"} for c in git.calls)


@pytest.mark.parametrize("change", ["head", "review_head", "author", "dismissed", "ci_head",
                                   "ci_pending", "ci_app", "ci_missing", "ci_new_failure",
                                   "isolation", "runtime", "protected", "tree", "tree_head",
                                   "tree_check", "tree_missing", "unmerged"])
def test_missing_or_stale_evidence_never_imports_or_promotes(monkeypatch, change):
    policy, pr, reviews, checks = evidence()
    git = ReviewedGit()
    if change == "head":
        pr["head"]["sha"] = BASE
    if change == "review_head":
        reviews[0]["commit_id"] = BASE
    if change == "author":
        pr["user"]["id"] = 2
    if change == "dismissed":
        reviews.append(dict(reviews[0], id=12, state="DISMISSED"))
    if change == "ci_head":
        checks["check_runs"][0]["head_sha"] = BASE
    if change == "ci_pending":
        checks["check_runs"][0]["status"] = "in_progress"
    if change == "ci_app":
        checks["check_runs"][0]["app"]["id"] = 8
    if change == "ci_missing":
        checks = {"total_count": 0, "check_runs": []}
    if change == "ci_new_failure":
        checks["check_runs"].append(dict(checks["check_runs"][0], id=22, conclusion="failure"))
        checks["total_count"] = 2
    if change == "isolation":
        policy["isolation"]["passed"] = False
    if change == "runtime":
        policy["isolation"]["scope"] = "authoring_write_wall"
    if change == "tree":
        policy["checked_tree"]["tree_sha"] = BASE
    if change == "tree_head":
        policy["checked_tree"]["head_sha"] = BASE
    if change == "tree_check":
        policy["checked_tree"]["check_run_ids"]["gate"] = 22
    if change == "tree_missing":
        policy.pop("checked_tree")
    if change == "unmerged":
        pr["merged"] = False
    if change == "protected":
        git.entries = [legacy.DiffEntry("100644", "M", None, "algua/registry/promotion.py")]
    install_evidence(monkeypatch, (policy, pr, reviews, checks))
    producer, promoter = legacy.Producer(), legacy.Promoter()
    result = legacy._run(git, legacy.FakeJournal(), stage={"s": "backtested"},
                         promoter=promoter, producer=producer)
    assert result.status == "awaiting_pr_admission"
    assert producer.calls == promoter.tokens == []
    assert "adopt" not in git.calls


def test_old_inflight_journal_requires_owner_recovery(monkeypatch):
    install_evidence(monkeypatch)
    journal = legacy.FakeJournal()
    journal.append(MergeBackRecord("s", "feat/s", TIP, merge_sha=MERGE))
    promoter = legacy.Promoter()
    result = legacy._run(ReviewedGit(), journal, stage={"s": "backtested"}, promoter=promoter)
    assert result.status == "owner_recovery_required" and not promoter.tokens


def test_failed_promote_history_is_retained_awaiting_reviewed_revert(monkeypatch):
    install_evidence(monkeypatch)
    git, journal = ReviewedGit(), legacy.FakeJournal()
    result = legacy._run(git, journal, stage={"s": "backtested"},
                         promoter=legacy.Promoter(commit=False))
    assert result.status == "reviewed_revert_pending"
    assert journal.latest("s", TIP).terminal == "promote_failed"
    assert journal.latest("s", TIP).revert_sha is None


def test_real_git_behind_main_adopts_verified_external_merge(git_repo, monkeypatch):
    """Real Git/FF, synthetic GH evidence and callback seams; no actual Task4/CI claim."""
    repo = git_repo
    _git(repo, "checkout", "feature")
    (repo / "algua/strategies/fixture").mkdir(parents=True)
    _git(repo, "mv", "algua/strat.py", "algua/strategies/fixture/strategy.py")
    _git(repo, "commit", "-m", "fixture: reviewed strategy path")
    _git(repo, "branch", "feat/s")
    tip = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "main")
    base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "merge", "--no-ff", "feature", "-m", "fixture external merge")
    merge = _git(repo, "rev-parse", "HEAD").strip()
    tree = _git(repo, "rev-parse", "HEAD^{tree}").strip()
    _git(repo, "push", "origin", "main")  # Fixture external publisher, never application code.
    _git(repo, "reset", "--hard", base)
    policy, pr, reviews, checks = evidence()
    policy.update(head_sha=tip, base_sha=base)
    policy["isolation"]["baseline_commit"] = base
    policy["checked_tree"].update(head_sha=tip, base_sha=base, tree_sha=tree)
    pr["head"]["sha"] = tip
    pr["merge_commit_sha"] = merge
    reviews[0]["commit_id"] = checks["check_runs"][0]["head_sha"] = tip
    install_evidence(monkeypatch, (policy, pr, reviews, checks))
    git, journal = RealGitOps(repo), legacy.FakeJournal()
    result = legacy._run(git, journal, stage={"s": "backtested"})
    assert result.status == "promoted_allocated"
    assert git.resolve("main") == merge
    assert (repo / "algua/strategies/fixture/strategy.py").read_text() == "SIGNAL = 1\n"


def test_public_fence_blocks_remote_revert_before_intake(monkeypatch):
    install_evidence(monkeypatch)
    git, journal, promoter = ReviewedGit(), legacy.FakeJournal(), legacy.Promoter()
    original = promoter.__call__
    def promote(token):
        result = original(token)
        git.origin_blobs = {legacy._STRAT_ENTRY.new_path: "removed"}
        return result
    kwargs = dict(git=git, journal=journal, strategy="s", branch="feat/s",
                  codeowners_text=legacy._CODEOWNERS, stage_of=lambda _: "backtested",
                  run_gate=lambda: pytest.fail("local gate must not execute PR code"),
                  ensure_backtested=legacy.Ensurer(), produce_evidence=legacy.Producer(),
                  promote=promote, passing_gate_by_token=promoter.by_token,
                  gate_exists_by_token=promoter.exists,
                  intake=lambda: pytest.fail("reverted content reached intake"),
                  target_allocated=lambda _: True)
    result = run_merge_back(**kwargs)
    assert result.status == "awaiting_pr_admission"
    assert journal.latest("s", TIP).promote_status == "passed"
    assert len(promoter.tokens) == 1


def test_public_entry_preserves_stage_and_token_guards(monkeypatch):
    install_evidence(monkeypatch)
    with pytest.raises(legacy.StageDriftError):
        legacy._run(ReviewedGit(), legacy.FakeJournal(), stage={"s": "candidate"})
    promoter = legacy.Promoter(commit=False)
    result = legacy._run(ReviewedGit(), legacy.FakeJournal(), stage={"s": "backtested"},
                         promoter=promoter, gate_exists_by_token=lambda _: True)
    assert result.status == "reviewed_revert_pending"
    assert promoter.tokens == []


@pytest.mark.skipif(sys.platform != "linux", reason="CLI imports Linux containment primitives")
def test_actual_main_missing_admission_never_opens_registry(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli import paper_cmd
    from algua.cli.main import app
    from algua.config.settings import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("ALGUA_MERGEBACK_ADMISSION", raising=False)
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "never-created.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    repo, git_dir = tmp_path / "repo", tmp_path / "git"
    repo.mkdir()
    git_dir.mkdir()
    (repo / "CODEOWNERS").write_text(legacy._CODEOWNERS)
    git = ReviewedGit()
    monkeypatch.setattr(paper_cmd, "RealGitOps", lambda _root: git)
    original = paper_cmd.subprocess.run
    def run(args, **kwargs):
        if args == ['git', 'rev-parse', '--show-toplevel']:
            return SimpleNamespace(stdout=str(repo))
        if args == ['git', 'rev-parse', '--absolute-git-dir']:
            return SimpleNamespace(stdout=str(git_dir))
        return original(args, **kwargs)
    monkeypatch.setattr(paper_cmd.subprocess, "run", run)
    result = CliRunner().invoke(app, ["paper", "merge-back", "--branch", "feat/s",
        "--strategy", "s", "--universe", "sp500", "--start", "2024-01-01",
        "--end", "2024-06-01", "--demo"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "awaiting_pr_admission"
    assert not (tmp_path / "never-created.db").exists()
    assert not git.calls


def test_public_entry_without_admission_never_publishes_or_promotes(monkeypatch):
    monkeypatch.delenv("ALGUA_MERGEBACK_ADMISSION", raising=False)
    git = legacy.FakeGit()
    promoter = legacy.Promoter()
    monkeypatch.setattr(legacy, "run_merge_back", run_merge_back)
    result = legacy._run(git, legacy.FakeJournal(), stage={"s": "backtested"},
                         promoter=promoter)
    assert result.status == "awaiting_pr_admission"
    assert promoter.tokens == []
    assert not any(isinstance(c, tuple) and c[0] in {"begin", "push"} for c in git.calls)


@pytest.mark.parametrize("operation", ["push_cas", "push_revert"])
def test_real_git_has_no_direct_main_publication(tmp_path, monkeypatch, operation):
    git = RealGitOps(tmp_path)
    calls = []
    monkeypatch.setattr(git, "fetch_remote", lambda _ref: None)
    monkeypatch.setattr(git, "remote_tip", lambda _ref: "b" * 40)
    monkeypatch.setattr(git, "_run", lambda args: calls.append(args))
    with pytest.raises(RuntimeError, match="direct-main publication disabled"):
        getattr(git, operation)("a" * 40, "b" * 40)
    assert calls == []
