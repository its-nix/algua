# PIT data pipeline: roadmap and Plan 1 (Sharadar sample check)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tool that decides whether Sharadar's data meets the agreed PIT standard (component A), before anything else is built.

**Architecture:** Pure parsers for three Sharadar tables (SEP prices, ACTIONS, TICKERS), pure check functions that score a small adversarial sample against the spec's PIT standard, and one CLI command that prints only check names, statuses and counts while writing the detailed report to a private path outside the repository.

**Tech Stack:** Python 3, pandas, typer CLI, pytest; existing `algua.data.corpactions` engine.

**Spec:** `docs/superpowers/specs/2026-11-12-pit-data-pipeline-design.md`

## Roadmap (scope check)

The spec covers five independently testable subsystems. They get one plan each, written in turn,
because the outcome of Plan 1 settles facts the later plans depend on (Sharadar's split-ratio
convention, whether `closeadj` matches Algua's `adj_close` (§4.10), and which terminal action types
carry consideration terms).

| Plan | Spec components | Starts when |
|---|---|---|
| **1. Sample check (this document)** | A | now (code); the run needs the owner's subscription |
| 2. Provider, importer, universe | B, C, §4.15 alias table | Plan 1 passes and the owner records it in the private KB |
| 3. Terminal economics + PIT verifier (protected) | D, I, §4.17 | Plan 2 merged |
| 4. VPS nightly data timer + lane refresh switch | E, §4.16 | Plan 3 merged |
| 5. Seal, home mirror, backup, agent boundary, evaluation counter | F, G, H, §4.18, §4.19 | Plan 4 running unattended |

A failed Plan 1 run stops the roadmap and reopens the provider choice (spec §5.A).

## Global Constraints

- The repository is public. No Sharadar rows, real prices or files derived from a real download
  may be committed — test fixtures are synthetic (invented tickers such as `ZZBK`, invented
  permatickers ≥ 900000, invented prices).
- Validation results and conclusions about the data's fitness stay private (spec §3 licence,
  §4.14). The CLI's stdout carries check names, statuses and counts only; anything containing
  prices goes to `--report-out`, which must resolve outside the repository.
- No change to any gate, threshold, lifecycle edge, frozen contract, or CODEOWNERS-protected file.
- `algua/cli/data_cmd.py` is at its size-ratchet pin (410); the new command lives in its own CLI
  module merged onto `data_app` in `algua/cli/main.py`, like `data_refresh_cmd`.
- CLI modules must not import each other (`tests/test_lint_imports.py`). Run `uv run lint-imports`.
- Focused checks per task; the full check at the end:
  `uv run pytest -q && uv run ruff check . && uv run mypy algua && uv run lint-imports`.
- Sharadar column and action names below come from the vendor's published table documentation
  and are held in constants in one module. They are confirmed on the first real download; an
  unexpected column set fails closed with a message naming the missing columns.

## Review Focus

1. **Split-ratio direction.** If Sharadar records a 2:1 split as `0.5` rather than `2.0`, the
   raw-units check must fail with a finding that says the inverse ratio would have matched — not a
   bare mismatch. Test: `test_raw_units_reports_inverted_ratio` (Task 2).
2. **A delisted name with no terminal action at all.** Must fail the terminal check, never be
   treated as "no terminal outcome needed". Test: `test_terminal_fails_when_delisted_has_no_action`
   (Task 2).
3. **An adversarial sample missing one required case** (e.g. no bankruptcy). The overall result
   must be `passed: false` — an easy sample must not pass. Test:
   `test_sample_coverage_fails_without_bankruptcy` (Task 2).
4. **`--report-out` inside the repository, or an existing file.** Must refuse before writing
   anything. Tests: `test_report_out_inside_repo_refused`, `test_report_out_existing_refused`
   (Task 3).
5. **Stdout leaking prices.** No float price value from the inputs may appear in stdout. Test:
   `test_stdout_contains_no_input_prices` (Task 3).

---

### Task 1: Sharadar table parsers

**Files:**
- Create: `algua/data/importers/sharadar_tables.py`
- Create: `tests/_sharadar_fixtures.py` (synthetic frames + CSV writer, reused by Tasks 2–3)
- Test: `tests/test_sharadar_tables.py`

**Interfaces:**
- Produces:
  - `SEP_COLUMNS = ("ticker", "date", "open", "high", "low", "close", "volume", "closeadj", "closeunadj", "lastupdated")`
  - `ACTIONS_COLUMNS = ("date", "action", "ticker", "name", "value", "contraticker", "contraname")`
  - `TICKERS_COLUMNS = ("table", "permaticker", "ticker", "name", "exchange", "isdelisted", "category", "firstpricedate", "lastpricedate")`
  - `read_sep(path: Path) -> pd.DataFrame` — columns as above; `date` tz-aware UTC midnight; `ticker` upper-cased; prices float64; sorted by `(ticker, date)`.
  - `read_actions(path: Path) -> pd.DataFrame` — `date` UTC; `action` lower-cased; `value` float64 (NaN allowed); `contraticker` str or `None`.
  - `read_tickers(path: Path) -> pd.DataFrame` — only rows with `table == "SEP"`; `permaticker` int64; `isdelisted` bool (from `"Y"`/`"N"`); price dates UTC (NaT allowed).
  - `class SharadarSchemaError(ValueError)`.
  - In `tests/_sharadar_fixtures.py`: `sample_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]` (sep, actions, tickers) containing one of each required case — a 2:1 split (ratio `2.0`), a cash dividend, a zero-recovery bankruptcy (`bankruptcyliquidation`), a cash-and-stock acquisition (`acquisitionby` with `contraticker` and `value`), a reused ticker (two permatickers, non-overlapping price dates); and `write_csvs(tmp_path) -> dict[str, Path]` with keys `"sep"`, `"actions"`, `"tickers"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_read_sep_normalizes(tmp_path):
    paths = write_csvs(tmp_path)
    sep = read_sep(paths["sep"])
    assert list(sep.columns) == list(SEP_COLUMNS)
    assert str(sep["date"].dt.tz) == "UTC"
    assert (sep["date"].dt.hour == 0).all()
    assert sep["ticker"].str.isupper().all()
    assert sep.equals(sep.sort_values(["ticker", "date"]).reset_index(drop=True))

def test_read_sep_missing_column_names_it(tmp_path):
    p = tmp_path / "sep.csv"
    p.write_text("ticker,date,open\nZZA,2020-01-02,1\n")
    with pytest.raises(SharadarSchemaError, match="closeunadj"):
        read_sep(p)

def test_read_sep_duplicate_ticker_date_refused(tmp_path): ...
    # duplicate (ticker, date) row -> SharadarSchemaError match "duplicate"

def test_read_tickers_keeps_sep_table_only(tmp_path): ...
    # a row with table == "SF1" is dropped; isdelisted "Y" -> True

def test_read_actions_lowercases_action(tmp_path): ...
    # "Split" -> "split"; empty contraticker -> None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sharadar_tables.py -q`
Expected: FAIL with `ModuleNotFoundError: algua.data.importers.sharadar_tables`

- [ ] **Step 3: Implement the fixtures and the three readers**

`pd.read_csv` with `dtype=str`, then validate the column set (extra columns are dropped; missing ones raise `SharadarSchemaError` listing them), then convert types. Do not register a `BarImporter` yet — that is Plan 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sharadar_tables.py -q && uv run lint-imports`
Expected: all pass; lint-imports reports no broken contracts.

- [ ] **Step 5: Commit**

```bash
git add algua/data/importers/sharadar_tables.py tests/_sharadar_fixtures.py tests/test_sharadar_tables.py
git commit -m "feat(data): parse Sharadar SEP/ACTIONS/TICKERS tables"
```

---

### Task 2: Sample-check rules

**Files:**
- Create: `algua/data/sharadar_check.py`
- Test: `tests/test_sharadar_check.py`

**Interfaces:**
- Consumes: Task 1 readers' frames; `algua.data.corpactions.Split`, `Dividend`, `check_adj_close_consistent`.
- Produces:
  - `Status = Literal["pass", "fail", "info"]`
  - `@dataclass(frozen=True) class CheckResult: name: str; status: Status; counts: dict[str, int]; findings: list[dict[str, object]]`
  - `@dataclass(frozen=True) class SampleCheckReport: checks: tuple[CheckResult, ...]` with property `passed: bool` (true iff no check has status `"fail"`) and `def summary(self) -> dict[str, object]` returning `{"passed": bool, "checks": [{"name", "status", "counts"}]}` — no findings.
  - `BANKRUPTCY_ACTIONS = frozenset({"bankruptcyliquidation"})`
  - `ACQUISITION_ACTIONS = frozenset({"acquisitionby", "mergerto"})`
  - `OTHER_DELIST_ACTIONS = frozenset({"delisted", "regulatorydelisting", "voluntarydelisting"})`
  - `TERMINAL_WINDOW_DAYS = 30` (terminal action must fall within this many days after `lastpricedate`)
  - `RTOL = 1e-3`
  - Check functions, each returning `CheckResult`:
    - `check_sample_coverage(sep, actions, tickers)` — name `"sample_coverage"`; fail unless the sample contains ≥1 each of: split, dividend, bankruptcy action, acquisition action with non-null `contraticker`, ticker string mapped to ≥2 permatickers. Counts per case; findings name each missing case.
    - `check_identity(sep, tickers)` — name `"identity"`; fail if two permatickers sharing a ticker have overlapping `[firstpricedate, lastpricedate]`, or if any SEP `(ticker, date)` cannot be assigned to exactly one permaticker by those date ranges.
    - `check_raw_units(sep, actions)` — name `"raw_units"`; for each row, `expected_unadj = close × Π ratio` over that ticker's splits with `date > row.date`; fail if `|expected − closeunadj| > RTOL × closeunadj` anywhere. A failing ticker whose rows would all match with `1/ratio` gets finding `{"ticker", "hint": "inverted_split_ratio"}`.
    - `check_adjusted(sep, actions)` — name `"adjusted_close"`; status always `"info"`; per ticker run `check_adj_close_consistent(closeunadj, closeadj, events)` with `Split(ex_date, ratio)` and `Dividend(ex_date, cash=value)`; counts `{"consistent": n, "inconsistent": m}`. This answers spec §4.10, it does not gate.
    - `check_terminal(actions, tickers)` — name `"terminal"`; for each `isdelisted` permaticker find actions for its ticker dated in `[lastpricedate, lastpricedate + TERMINAL_WINDOW_DAYS]`; classify `zero_recovery` (bankruptcy), `acquisition_resolved` (acquisition with `contraticker` and finite `value`), `acquisition_unresolved`, `other_delisting`, `no_action`. Fail iff any `no_action`. Counts per class.
    - `check_revisions(sep_now, sep_prev, *, older_than_days: int = 30)` — name `"revisions"`; status `"info"`; counts rows dated more than `older_than_days` before `sep_prev`'s max date whose `close`, `closeunadj` or `volume` differ between the two pulls.
  - `run_sharadar_check(sep, actions, tickers, sep_prev: pd.DataFrame | None = None) -> SampleCheckReport` — runs all checks in the order above; omits `revisions` when `sep_prev` is `None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_clean_sample_passes():
    report = run_sharadar_check(*sample_tables())
    assert report.passed
    assert [c.name for c in report.checks] == [
        "sample_coverage", "identity", "raw_units", "adjusted_close", "terminal"]

def test_sample_coverage_fails_without_bankruptcy():
    sep, actions, tickers = sample_tables()
    actions = actions[actions["action"] != "bankruptcyliquidation"]
    report = run_sharadar_check(sep, actions, tickers)
    assert not report.passed
    cov = next(c for c in report.checks if c.name == "sample_coverage")
    assert cov.status == "fail" and {"missing": "bankruptcy"} in cov.findings

def test_identity_fails_on_overlapping_reused_ticker(): ...
    # shift the second permaticker's firstpricedate inside the first's range -> status "fail"

def test_raw_units_reports_inverted_ratio():
    sep, actions, tickers = sample_tables()
    actions.loc[actions["action"] == "split", "value"] = 0.5
    res = check_raw_units(sep, actions)
    assert res.status == "fail"
    assert any(f.get("hint") == "inverted_split_ratio" for f in res.findings)

def test_adjusted_close_is_info_even_when_inconsistent(): ...
    # scale closeadj by 1.1 -> status "info", counts["inconsistent"] >= 1, report still passes

def test_terminal_fails_when_delisted_has_no_action():
    sep, actions, tickers = sample_tables()
    actions = actions[~actions["action"].isin(BANKRUPTCY_ACTIONS)]
    res = check_terminal(actions, tickers)
    assert res.status == "fail" and res.counts["no_action"] == 1

def test_terminal_classifies_zero_recovery_and_acquisition(): ...
    # counts == {"zero_recovery": 1, "acquisition_resolved": 1, ...zeros}

def test_revisions_counts_changed_old_rows(): ...
    # change one close 60 days before the end -> counts["changed_rows"] == 1; recent change not counted

def test_summary_has_no_findings():
    s = run_sharadar_check(*sample_tables()).summary()
    assert all(set(c) == {"name", "status", "counts"} for c in s["checks"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sharadar_check.py -q`
Expected: FAIL with `ModuleNotFoundError: algua.data.sharadar_check`

- [ ] **Step 3: Implement the check functions and `run_sharadar_check` in `algua/data/sharadar_check.py`**

Pure module: no file I/O, no imports outside `algua.data` and `algua.contracts`. Findings may contain dates, tickers and prices (they only ever go to the private report).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sharadar_check.py tests/test_sharadar_tables.py -q && uv run lint-imports && uv run mypy algua/data/sharadar_check.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add algua/data/sharadar_check.py tests/test_sharadar_check.py
git commit -m "feat(data): Sharadar adversarial sample-check rules"
```

---

### Task 3: `algua data vendor-check` command and owner runbook

**Files:**
- Create: `algua/cli/vendor_check_cmd.py`
- Modify: `algua/cli/main.py` (import the module; `data_cmd.data_app.add_typer(vendor_check_cmd.vendor_check_app)` next to the existing `data_refresh_cmd` line)
- Create: `docs/agent/sharadar-sample-check.md`
- Test: `tests/test_cli_vendor_check.py`

**Interfaces:**
- Consumes: Task 1 readers; Task 2 `run_sharadar_check`, `SampleCheckReport.summary()`, `.checks`.
- Produces: `algua data vendor-check --vendor sharadar --sep PATH --actions PATH --tickers PATH [--previous-sep PATH] --report-out PATH`.
  - stdout: `ok({"vendor": "sharadar", **report.summary(), "report_out": "<path>"})`.
  - Exit code 0 when `passed`, 1 when not (like `data verify`).
  - `--report-out` receives the full report as JSON (summary plus every check's findings), written with mode `0o600`.
  - Refusals (ValueError through `json_errors`, nothing written): unknown `--vendor`; `--report-out` resolving inside the repository root (`Path(algua.__file__).resolve().parents[1]`); `--report-out` already exists.

- [ ] **Step 1: Write the failing tests**

```python
def test_vendor_check_passes_and_writes_private_report(tmp_path):
    paths = write_csvs(tmp_path / "in")
    out = tmp_path / "private" / "report.json"
    res = runner.invoke(app, ["data", "vendor-check", "--vendor", "sharadar",
        "--sep", str(paths["sep"]), "--actions", str(paths["actions"]),
        "--tickers", str(paths["tickers"]), "--report-out", str(out)])
    body = json.loads(res.stdout)
    assert res.exit_code == 0 and body["passed"] is True
    full = json.loads(out.read_text())
    assert "findings" in full["checks"][0]
    assert oct(out.stat().st_mode & 0o777) == "0o600"

def test_vendor_check_failing_sample_exits_1(tmp_path): ...
    # drop the bankruptcy action row from the CSV -> exit 1, body["passed"] is False

def test_report_out_inside_repo_refused(tmp_path): ...
    # --report-out <repo_root>/report.json -> exit 1, file not created

def test_report_out_existing_refused(tmp_path): ...

def test_stdout_contains_no_input_prices(tmp_path):
    # every distinct close/closeunadj/closeadj value from the fixture, formatted with repr(),
    # is absent from res.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_vendor_check.py -q`
Expected: FAIL (`No such command 'vendor-check'`)

- [ ] **Step 3: Implement `vendor_check_cmd.py` and register it in `main.py`**

Own `vendor_check_app = typer.Typer()`; validate `--report-out` before reading any input; create parent directories for the report.

- [ ] **Step 4: Write `docs/agent/sharadar-sample-check.md`**

Owner runbook, no data and no conclusions. It covers:
- Subscribe to Sharadar Prices (full history).
- Choose the adversarial sample yourself using the five required cases. Add one acquisition
  with stock or mixed terms if one is available.
- Export SEP, ACTIONS and TICKERS for those tickers into a directory outside the repository.
- Pull SEP again after at least five trading days, to use as `--previous-sep`.
- Run the command with `--report-out` pointing into the private KB.
- Record the decision there, not here.

Also state:
- What a failure of each check means.
- That `adjusted_close` and `revisions` inform Plan 2 and do not gate.
- That a failed run stops the roadmap.

Link it from `docs/agent/pit-data-assessment.md` with a one-line "Next step" note (the spec stays unchanged).

- [ ] **Step 5: Run the focused and full checks**

Run: `uv run pytest tests/test_cli_vendor_check.py tests/test_sharadar_check.py tests/test_sharadar_tables.py tests/test_module_size_ratchet.py -q`, then the full check from Global Constraints.
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add algua/cli/vendor_check_cmd.py algua/cli/main.py docs/agent/sharadar-sample-check.md docs/agent/pit-data-assessment.md tests/test_cli_vendor_check.py
git commit -m "feat(cli): data vendor-check for the Sharadar PIT sample"
```

---

### Owner step after Plan 1 (not code)

1. Subscribe.
2. Run the check following `docs/agent/sharadar-sample-check.md`.
3. Record pass or fail in the private KB.

On a pass, Plan 2 gets written. The report answers three things Plan 2 needs: the split-ratio convention, whether `closeadj` matches §4.10, and the terminal action classes seen. On a fail, the provider choice reopens.
