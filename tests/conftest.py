"""Suite-wide isolation for developer-environment surfaces a test must never inherit.

Four leaks, all caused by a test resolving a real, developer-machine surface by default when
pytest runs from the repo root. The fourth, real Alpaca HTTP, is documented on its fixture,
``_no_real_alpaca_http``, at the end of this file.

**1. The knowledge vault (write leak).** ``Settings.knowledge_dir`` defaults to the RELATIVE path
``kb`` — the developer's actual Obsidian vault. The gate commands sync the vault as a side effect
(``_common.sync_kb_doc``, wired into ``backtest --register`` / ``registry transition`` /
``research promote`` / ``paper promote``), and that sync now scaffolds a doc for a registered
strategy that lacks one. Without this fixture, any test exercising those commands would create
``kb/strategies/<fixture-strategy>.md`` in the working tree.

Only the DEFAULT is redirected: a test that sets ``ALGUA_KNOWLEDGE_DIR`` itself (several do, to
assert on the vault they built) still wins, because its own ``monkeypatch.setenv`` runs after this
conftest-level fixture.

**2. The repo-root ``.env`` (read leak).** ``Settings.model_config`` sets ``env_file=".env"``, so
pydantic-settings reads the developer's real ``.env`` from the CWD on every instantiation. That
silently defeats ``monkeypatch.delenv``, which only clears the PROCESS environment: a test that
deletes ``ALGUA_ALPACA_API_KEY`` to assert credentials are ABSENT still gets a real key from the
file, and the assertion inverts. This is not hypothetical — ``test_cli_core.py``'s two ``doctor``
tests (``test_doctor_paper_flag_gates_paper_credentials``,
``test_doctor_advisory_rows_do_not_gate_exit``) passed in CI and in a fresh worktree while failing
for any developer who had actually configured credentials, which is precisely backwards: the suite
was green exactly where the credentials were missing.

Disabling ``env_file`` for the whole suite makes "a clean env" mean what those tests already say it
means, and matches ``get_settings``' own stated contract ("Fresh Settings each call (re-reads env;
keeps tests isolated)"). A test that genuinely needs a value still sets it with
``monkeypatch.setenv``, which is unaffected. Deliberately suite-wide rather than per-test: the
failure mode is silent and machine-dependent, so it must not depend on each future test author
remembering it.
"""

from __future__ import annotations

import fcntl
import os
import tempfile
from pathlib import Path
from typing import Any

# Under ``pytest -n auto`` every worker would otherwise start its own BLAS/Arrow/OpenMP thread pool
# (one per core), and the oversubscription made the parallel suite several times SLOWER than serial.
# Set before numpy/pyarrow import; child processes the tests spawn inherit it.
for _var in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "ARROW_DEFAULT_CPU_THREAD_COUNT",
):
    os.environ.setdefault(_var, "1")

from urllib.parse import urlsplit  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from algua.config.settings import Settings  # noqa: E402

# ``empty_exit_venues`` (Story 2.2 §8): an explicit, opt-in fixture -- never autouse. A test that
# drives an allocation-shedding transition names it to get empty fake venues for both lanes' exit
# drains; one that forgets meets the real drain and, at worst, the Alpaca guard at the end of this
# file.
pytest_plugins = ("tests._exit_drain",)


@pytest.fixture(autouse=True)
def _isolated_knowledge_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))


@pytest.fixture(autouse=True)
def _no_repo_dotenv(monkeypatch):
    """Stop pydantic-settings reading the developer's real ``.env`` (see module docstring)."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture(autouse=True)
def _isolated_db_path(monkeypatch, tmp_path):
    """**3. The registry DB (write leak).** ``Settings.db_path`` defaults to the RELATIVE path
    ``data/algua.db`` — the developer's real, 1.8 MB registry DB. Before the strategy-run-tracking
    branch, an un-``--register``ed ``backtest run`` never touched the DB at all; that branch made
    ``run_backtest_task`` open ``registry_conn()`` UNCONDITIONALLY (to record the run row), so any
    test that exercises a backtest/walk-forward/sweep/gate path without setting
    ``ALGUA_DB_PATH`` itself now silently writes into the real registry the moment it runs on a
    developer machine (every CURRENT test happens to set it, by the established
    ``monkeypatch.setenv("ALGUA_DB_PATH", ...)`` idiom — but nothing enforces that a FUTURE test
    author remembers to). Same rationale as ``_isolated_knowledge_dir`` / ``_no_repo_dotenv``
    above: a silent, machine-dependent failure mode must not depend on each future test author
    remembering the idiom, so it is redirected suite-wide instead.

    Only the DEFAULT is redirected: a test that sets ``ALGUA_DB_PATH`` itself still wins, because
    its own ``monkeypatch.setenv`` runs AFTER this conftest-level fixture and simply overwrites the
    value this fixture set.
    """
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "_default_isolated_registry.db"))


@pytest.fixture(autouse=True)
def _isolated_registries():
    """Snapshot four of the five name->factory registries in ``algua/`` and restore them wholesale
    after each test: ``algua.data.importers``, ``algua.data.providers``, ``algua.execution.broker_
    factory``, and ``algua.tracking.factory``.

    Restore, not delete: the manual ``del _REGISTRY["dummy"]`` pattern this replaces reverts an
    ADDITION but silently keeps an OVERWRITE, and leaks entirely if the test errors first. For the
    broker registry that is a safety concern rather than tidiness -- a fake left registered under a
    live kind changes what a LATER test constructs across the paper/live boundary.

    Four registries, not the three the brief for this task named: ``algua.data.importers`` (local
    vendor-file importers, e.g. FirstRate/Databento) is a *separate* registry from
    ``algua.data.providers`` (network bar providers, e.g. yfinance/Alpaca) -- the manual cleanup in
    ``tests/test_data_ingest_streamed.py`` was on the importers registry, not providers. Both get
    the same fragile ``del``-in-``finally`` treatment today, so both are covered here.

    The fifth, ``algua.features.catalogue._REGISTRY``, is deliberately EXCLUDED: ``load_all_
    factors`` REBINDS the module global (``global _REGISTRY; ...; _REGISTRY = fresh``) rather than
    mutating it in place, so snapshotting it by reference here would go stale the moment a test
    called ``load_all_factors`` -- restoring the OLD dict object at teardown would not undo the
    rebind. It already has its own reset hook, ``catalogue._reset_registry()``, that its own tests
    call directly.
    """
    from algua.data.importers import _REGISTRY as importers
    from algua.data.providers import _REGISTRY as providers
    from algua.execution.broker_factory import _REGISTRY as brokers
    from algua.tracking.factory import _REGISTRY as trackers

    snapshots = [(r, dict(r)) for r in (importers, providers, brokers, trackers)]
    yield
    for registry, snapshot in snapshots:
        registry.clear()
        registry.update(snapshot)


def _is_alpaca_host(url: object) -> bool:
    """True for ``alpaca.markets`` and every ``*.alpaca.markets`` host (paper, live and data)."""
    host = (urlsplit(str(url)).hostname or "").lower()
    return host == "alpaca.markets" or host.endswith(".alpaca.markets")


@pytest.fixture(autouse=True)
def _no_real_alpaca_http(monkeypatch):
    """**4. Real Alpaca HTTP (network leak, Story 2.2 §8).** Every paper-lane and live-lane book
    exit now drains its resting orders through a default selector, so a test that sets dummy Alpaca
    credentials and forgets the explicit ``empty_exit_venues`` fixture would build a real broker
    and send HTTPS to Alpaca. ``requests.Session.request`` is the one function every real request
    passes through (``requests.get/post/delete`` delegate to it on a fresh session), whatever the
    verb or the lane, so it is wrapped here: an Alpaca host is recorded and refused with an
    ``AssertionError`` before anything is sent; every other host goes to the original unchanged.

    A raise alone can be swallowed (the exit drain audits a step exception into a ``BrokerError``,
    and the CLI catch-all turns any exception into an envelope), so a test that only asserts a
    refusal would still pass. Teardown therefore fails the test, listing every recorded request.
    There is no opt-out. Yields the record so the self-test can read and clear it."""
    recorded: list[str] = []
    original = requests.Session.request

    def guarded(self, method, url, *args, **kwargs):
        if _is_alpaca_host(url):
            call = f"{str(method).upper()} {url}"
            recorded.append(call)
            raise AssertionError(f"real Alpaca HTTP in a test: {call}")
        return original(self, method, url, *args, **kwargs)

    guarded._algua_alpaca_guard = True  # read by the self-test (tests are not type-checked)
    monkeypatch.setattr(requests.Session, "request", guarded)
    yield recorded
    if recorded:
        pytest.fail("real Alpaca HTTP attempted in a test (refused, nothing sent): "
                    f"{recorded}", pytrace=False)


class _CleanMainProbe:
    def branch(self) -> str:
        return "main"

    def tracked_dirty(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _clean_main_checkout(monkeypatch):
    """#687: the operator-lane checkout guard must not depend on the branch the SUITE runs on
    (worktrees are never ``main``). Replaces the real git probe with a clean-main fake; guard
    tests re-patch ``default_probe`` themselves. Test-only seam -- production has no bypass."""
    from algua.operator import checkout_guard
    monkeypatch.setattr(checkout_guard, "default_probe", lambda: _CleanMainProbe())


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Pin every ``serial``-marked test to one xdist worker (needs ``--dist loadgroup``)."""
    for item in items:
        if item.get_closest_marker("serial") is not None:
            item.add_marker(pytest.mark.xdist_group("serial"))


# ``serial`` tests write into the real source tree (``algua/strategies``, ``algua/features``), which
# every other test's strategy/factor discovery scans. ``xdist_group`` keeps them on one worker but
# not away from readers on the others, so they also take an exclusive cross-process lock: they hold
# it for the whole consecutive group, every other test holds it shared. The gate lock stops a
# stream of readers from starving a waiting writer. No-op cost without xdist.
_LOCK_DIR = Path(tempfile.gettempdir())
_LOCK_KEY = os.environ.get("PYTEST_XDIST_TESTRUNUID", f"solo-{os.getppid()}")
_tree_lock: dict[str, Any] = {"mode": None, "fd": None, "gate": None}


def _is_serial(item: pytest.Item | None) -> bool:
    return item is not None and item.get_closest_marker("serial") is not None


def _tree_open(name: str) -> int:
    return os.open(_LOCK_DIR / f"algua-pytest-{name}-{_LOCK_KEY}.lock", os.O_RDWR | os.O_CREAT)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    want = fcntl.LOCK_EX if _is_serial(item) else fcntl.LOCK_SH
    if _tree_lock["mode"] == want == fcntl.LOCK_EX:
        return  # still inside the consecutive serial group
    if _tree_lock["gate"] is None:
        _tree_lock["gate"] = _tree_open("gate")
    fd = _tree_open("tree")
    fcntl.flock(_tree_lock["gate"], fcntl.LOCK_EX)
    try:
        fcntl.flock(fd, want)
    finally:
        fcntl.flock(_tree_lock["gate"], fcntl.LOCK_UN)
    _tree_lock["mode"], _tree_lock["fd"] = want, fd


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    if _tree_lock["mode"] == fcntl.LOCK_EX and _is_serial(nextitem):
        return
    if _tree_lock["fd"] is not None:
        os.close(_tree_lock["fd"])  # closing the descriptor drops the flock
    _tree_lock["mode"], _tree_lock["fd"] = None, None
