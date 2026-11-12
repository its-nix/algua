# Point-in-time data pipeline and research/operations split

Date: 2026-11-12. Base: `main` at `cfc7b48`. Status: design agreed with the owner in conversation;
not yet implemented. Changes no threshold, lifecycle edge, capital or live permission. Adds one
protected (human-reviewed) PIT verifier that binds evidence into promotion (§4.6, component I).

## 1. Intent

The capped experimental route (`docs/agent/capped-live.md`) is unblocked in code, but no honest
strategy can satisfy its historical leg: `registry/experimental_qualification.py` requires a
research gate row with `pit_ok` and no PIT override, and current research snapshots are
current-constituent proxies (no delisted names, no historical membership; see
`docs/agent/pit-data-assessment.md`). Data, not paper duration, is now the binding constraint.

This design gives Algua one reliable, affordable source of survivorship-aware US equity history
plus the daily top-up from the same source, and splits the system into an always-on operations
plane and a home research plane, with the most recent period physically sealed from research.

The owner's framing of the seal: the forward test becomes twofold — the sealed period tests the
**strategy** on data its developer never saw, and the five paper sessions test the **machine** it
will run on. Strategy development and deployment stay separated.

## 2. Goals, non-goals, anti-goals

**Goals**
- Deep daily history (target: full history from Dec 1997) including delisted securities, from one
  vendor that also supplies the nightly top-up used by paper/live.
- A predeclared, rules-based universe computed per historical date from that data, materialized
  through the existing universe store so `resolve_pit_ok` (`registry/promotion.py:58`) passes on
  real evidence.
- A verifier that checks the PIT standard (§4.6) and records the result as evidence promotion
  binds to, instead of a timeline-coverage boolean alone.
- Unattended nightly ingest → verify → immutable snapshot on the VPS, with alerts.
- Home research server with a hash-verified mirror that never receives the sealed period's bars.
- Honest terminal economics, including zero-recovery bankruptcies.

**Non-goals**
- Index-membership data (S&P 400 etc.). Not needed for a rules-based universe.
- Fundamentals, news, intraday or hourly data. Sharadar fundamentals may come later separately;
  they would need a stricter PIT standard than §4.6.
- Price vintages / as-first-published archives.
- Airflow or any new orchestration framework.
- Changing research/forward thresholds or making advisory statistics binding.

**Anti-goals (failure even if it "works")**
- A passing `pit_ok` boolean treated as proof of data authenticity, or a current list backdated.
- Bankruptcies dropped or recorded as tiny positive terminal values to satisfy the delistings store.
- Raw vendor data, or anything that can reproduce it, in this public repository or sent to a
  third-party model provider.
- Research on the home server able to see the sealed period's bars.
- Two machines fetching the vendor independently and silently diverging.
- Universe size or rules tuned against Sharpe.

## 3. Constraints

- **License (Sharadar personal terms, read 2026-11-12):** natural person, personal non-professional
  use; automated trading of the owner's own account is permitted (FAQ). No sharing or
  redistribution. Within 30 days of cancellation all copies, caches, extracts and reproducing
  datasets must be deleted (affidavit on request); derived works that cannot reproduce the data
  (results, models, trade logs, statistics) may be kept. Conclusions about the data's fitness may
  not be published without Sharadar's written approval.
- **Owner facts:** Algua is the owner's private venture trading only the owner's money. Storage on
  machines the owner operates (VPS, home server) and a private, unshared Google Drive folder.
- **Budget:** PRD caps data + infrastructure + operating costs at about ILS 2,000. Sharadar Prices
  full history is USD 299/year (USD 39/month); 10-year tier USD 199/year.
- **Data facts (Sharadar):** ~21k stock tickers active and delisted; vendor-estimated 99%
  survivorship coverage; OHLCV split-adjusted; `closeunadj` provided; `closeadj` adjusts for
  splits, dividends and spinoffs; volume not adjusted for cash dividends/spinoffs; actions table
  and permanent identifiers available; history is latest-restated (no vintages).
- **Algua contracts:** raw OHLCV plus `adj_close` per `docs/contracts/bar-schema.md`; immutable
  snapshots; `data/store/delistings.py:25` currently rejects non-positive terminal values;
  `verified_pit` provenance is currently refused because no verifier exists; import-linter
  layering; CODEOWNERS-protected integrity code requires human review.

## 4. Decisions

### Owner decisions
1. **Provider:** Sharadar Prices, full history, subscription treated as a permanent running cost.
2. **Topology:** VPS = operations plane; home server (2 TB disk, GPU) = research plane.
3. **Backup:** encrypted copy in the owner's private Google Drive (not the shared commercial-assets
   folder).
4. **Agents:** research/leap/forage agents and any LLM-backed tool see only derived results, never
   raw Sharadar bars. Accepted that past backtests become non-replayable after cancellation.
5. **Seal:** the most recent period's bars are physically withheld from the home server.
6. **PIT standard for daily price-only strategies.** Latest-restated history without vintages
   qualifies when all of these hold and are verified: (a) coverage includes delisted securities
   over the whole evaluated period; (b) the universe is rules-based and computed per date from
   data available on that date; (c) adjustments are reproducible from dated actions (§4.10);
   (d) every exit from the universe has a resolved terminal outcome or the backtest refuses.
   The residual risk (small vendor restatements of old prices) is accepted and recorded. This
   standard does not extend to fundamentals, news or any revisable non-price data. A verifier
   that checks (a)–(d) and binds its evidence into promotion is in scope (component I).
7. **Sealed-result feedback: full results go home.** Gate outcomes for sealed-period evaluations
   (pass/fail, holdout Sharpe and other metrics, scorecard rows, strategy return series) flow back
   to the home research plane. Bars never do. Accepted consequence: the sealed window acts as a
   shared validation set whose freshness decays as candidates are evaluated on it; selection
   against it is possible. Backstops are the per-strategy single-use holdout burn (unchanged), the
   capped capital of the experimental route, the five paper sessions, and the owner advancing `S`.

### Design calls (Claude's; owner may override)
8. **Single fetcher.** Only the VPS calls Sharadar. Home pulls finished snapshots one-way over a
   private tunnel (Tailscale or WireGuard), home-initiated; no inbound ports at home.
9. **Universe:** rules-based top ~1,000 liquid US common stocks, recomputed for each decision date
   from data available then (price floor, median dollar-volume rank, listing-age floor; starting
   from the existing midcap screen's rule shapes). Rules and size fixed before any research run
   and recorded with the universe identity.
10. **Raw reconstruction:** derive raw OHLC from `closeunadj` and the split actions so imported bars
    honor the bar-schema contract; keep vendor `closeadj` only if it matches Algua's `adj_close`
    definition, otherwise compute `adj_close` from dated actions.
11. **Terminal economics:** a reviewed change lets the delistings store record zero recovery
    honestly; cash/stock acquisition terms come from the vendor actions table where present; a
    held name with an unresolved terminal outcome keeps failing closed.
12. **Orchestration:** systemd timers on both machines, matching `deploy/systemd/`. VPS adds one
    data timer; home adds a mirror timer and runs research/training timers.
13. **Registry authority stays on the VPS.** Home research uses a scratch registry. Candidates
    return through the existing merge-back path; the VPS replays `research promote`
    authoritatively. GPU training happens at home and produces pinned model bytes plus provenance
    that travel in the frozen artifact (`docs/agent/model-artifacts.md`); the VPS only infers.
14. **Validation evidence is private.** Sample-check and verification reports live in the owner's
    private KB, not this repository.
15. **Security identity without a contract change.** The frozen bar schema stays keyed on
    `symbol`. Imported research data uses a stable Algua security key derived from the vendor's
    permanent identifier as `symbol`; a dated alias table maps it to the broker ticker at the
    execution edge (and back for broker-held positions). Renames keep one continuous series;
    reused tickers become distinct securities.
16. **Migration of running strategies.** Existing paper/live deployments keep their current bars
    provider until they are requalified on the new data; nothing is cut over silently. Changing
    the approved live bars provider remains the owner's explicit action. When Sharadar is late or
    incomplete, the lane fails closed (`refresh_failed`, timer retries); there is no fallback to a
    second vendor.
17. **Acquisition semantics.** Stock and mixed consideration is converted to a per-share cash
    value at the effective date (using the acquirer's close that day), preserving the current
    one-number terminal model. "Unresolved" means the vendor actions lack the consideration terms
    or the acquirer price; such a held name refuses, as today.
18. **Agent boundary strength.** The research loop keeps running backtests through the CLI.
    Enforcement: CLI and driver outputs carry metrics only (no bar rows), the agent sandbox denies
    direct reads of the snapshot directory where the seam allows, and `data inspect`-style row
    output is withheld from agents. The remaining path (a strategy deliberately printing values
    during a run) is a documented residual, accepted for now; a driver-mediated loop is a later
    option if it proves material.
19. **Seal-window evaluation count is recorded, not enforced.** Each authoritative evaluation on
    the sealed window increments a per-window counter shown with every sealed result and in the
    scorecard, so selection pressure is visible when the owner decides to advance `S`. It is
    advisory and vetoes nothing (consistent with decision 7).

## 5. Components

**A. Vendor sample check (first, before any build).** One adversarial sample: a bankruptcy with
zero recovery, a cash-and-stock acquisition, a reused ticker, a split, a dividend. Reconcile
identity, raw units, terminal economics and revision behavior against the PIT standard (§4.6).
Survivor spot-checks against yfinance are secondary. A failed check stops the project and reopens
the provider choice.

**B. Sharadar provider + importer.** Bulk backfill and nightly incremental fetch through the
existing provider/importer seams (`algua/data/providers/`, `data import-bars`), normalized to the
bar schema with stable security identity and dated ticker aliases. Output is immutable,
content-hashed snapshots; provenance records vendor, tier, retrieval time and payload hashes.

**C. Universe materializer.** Computes eligibility per date from the snapshot only, writes the
timeline through the existing universe store / `data import-universe` (add inclusive, drop
exclusive), and records the rule set in the universe identity.

**D. Terminal-economics change (protected, human-reviewed).** Zero-recovery support in
`data/store/delistings.py` and the backtest delisting realization (`algua/backtest/delisting.py`),
fed from vendor actions; unresolved cases refuse.

**E. VPS data timer.** Nightly after vendor publication: fetch → normalize → verify (`data verify`
plus completeness checks: every previously active symbol accounted for, no gaps, identity
continuity) → snapshot → alert on any failure. Serialized against the paper/live lanes using the
existing lock discipline. The paper/live `--refresh` path reads from this snapshot store rather
than calling another vendor, so research and trading see the same numbers.

**F. Seal boundary.** A recorded seal date `S`. Snapshots replicated to home are truncated to bars
dated before `S`. Authoritative gate evaluations on the VPS use holdouts that lie entirely at or
after `S`; their full results return home (§4.7) with the window's evaluation count (§4.19).
`S` advances only by explicit owner action; once advanced, the newly exposed period is treated as
previously inspected (never "fresh" again), consistent with burn-on-peek.

**G. Home mirror timer.** Pulls new pre-seal snapshots, verifies hashes with `data verify`, never
writes back to the VPS store. Encrypted weekly backup to the private Drive folder.

**H. Agent data boundary.** Agents receive derived metrics/reports only. Enforced by where data
lives and what driver commands expose, not by prompt instructions alone (§4.18).

**I. PIT verifier (protected, human-reviewed).** Checks (a)–(d) of §4.6 for a snapshot + universe
+ delistings triple and records a content-addressed verification result. Promotion binds to that
result (enabling the currently refused `verified_pit` provenance) rather than to timeline coverage
alone; a missing or failed verification fails closed. Detailed verification reports stay private
(§4.14); the repository holds only the code and pass/fail provenance.

## 6. Sequence

1. A — sample check (owner subscribes; ~1 month of cost at risk if it fails).
2. B + C on the VPS: backfill, universe, first authoritative snapshot.
3. D + I — terminal economics and PIT verifier (protected review).
4. E — nightly timer; switch paper/live refresh to the shared snapshot store.
5. F + G — seal boundary and home mirror; move the research loop home.
6. First new research campaign on the sealed setup; first candidate through the capped route.

## 7. Left to the builder

- Exact eligibility thresholds and rank cutoff within the predeclared shape (§4.9), fixed and
  recorded before research.
- Whether vendor `closeadj` can be used directly or `adj_close` must be computed (§4.10).
- Snapshot granularity (one backfill + daily increments vs periodic consolidation) and retention
  on the VPS.
- Tunnel product, backup encryption tool and schedule.
- How the seal boundary reconciles with per-run `holdout_frac` (`algua/backtest/walkforward.py:40`)
  — e.g. deriving the evaluation period so its holdout starts at `S` — provided holdouts never
  include pre-seal data visible at home and no protected threshold changes.
- Initial value of `S` (it must leave at least 63 sessions plus warmup after it for a gate).
- Verifier result storage shape and how it is keyed into the gate row.
