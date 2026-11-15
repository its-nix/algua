# Daily historical universe rules

Frozen definition, 2026-11-15, for [PRD §12](../PRD.md#12-markets-and-timeframes) and
[§25](../PRD.md#25-development-sequence). The sole rule configuration is
[`us-liquid-common-v1.json`](../../deploy/research/us-liquid-common-v1.json), rule ID
`us-liquid-common/v1`. This document explains that configuration; it is not a second parameter
source. Canonical configuration SHA256:
`38d880b7b6079fd460d48e5bb144b14c74a0089f55fff37e7cfc1ecee867c7b2`.

Hash the UTF-8 bytes of the existing
[`canonical_json(parsed_config)`](../../algua/contracts/canonical.py), without a trailing newline:
NFC-normalized strings, sorted keys, compact separators, `ensure_ascii=False`, `allow_nan=False`.
Whitespace in the source file does not affect identity. Any rule change requires a new version
and hash fixed before that version's strategy-return evaluation. These initial floors retain the conservative
[machinery screen's](midcap-machinery.md) shape, without using returns to choose them. They do
not inherit its current S&P 400 selection, 300-name cap, sector sampling or historical claims.

## As-of selection

For each XNYS session `t`, select at its completed close using daily bars through `t` and
eligibility facts effective and known by that close. The daily bar's UTC-midnight date label is
not its availability time. Membership `U[t]` labels the closed-bar decision on `t`; it must never
be exposed to a decision before that close. Execution remains at least one bar later, on the
next eligible session. Holidays/weekends supply neither observations nor selection dates.

Start with a historically complete inventory, including securities that later delisted, and
dated identity/eligibility records. Include US-domiciled issuers' ordinary common shares listed
on NYSE (`XNYS`), Nasdaq (`XNAS`) or NYSE American (`XASE`), denominated and quoted in USD.
REIT and BDC common shares count; multiple ordinary share classes count separately. Exclude
ADRs/ADSs, foreign-domiciled issuers, ETFs/ETNs, other funds, preferreds, units, partnerships,
warrants, rights, OTC and non-USD listings. BDC common shares are the explicit fund exception.
No index, market-cap or sector criterion applies. A current
vendor category, exchange, ticker or `isdelisted` flag cannot establish a historical fact.
Broker tradability is a separate operational-admission check, not a historical selection input.

Each eligible security must satisfy all of these inclusive floors:

- Raw close on `t` ≥ USD 10.
- At least 252 distinct valid observed XNYS session bars through `t`, for the same stable security
  ID in the same uninterrupted listing episode. A relisting starts a new episode and count.
- A valid bar on every one of the 60 XNYS sessions ending at `t`. Compute each day's dollar volume
  as that day's raw close × raw share volume; take the median, the mean of sorted observations
  30 and 31. The median must be ≥ USD 20,000,000. Use each day's raw units, including across a
  split; neither `adj_close` nor adjusted volume is an interchangeable operand. Zero volume
  counts as zero, not missing.

The history floor is a conservative **listing-age lower bound**, not an IPO date or an exact
one-year age claim. Within a verified continuous episode, 252 distinct dated observations prove
the security existed on at least 252 sessions (at least 251 session intervals from first to
last). Missing older observations only delay admission. History before the snapshot's coverage
is not inferred. This avoids trusting today's `firstpricedate` as the original listing date.
Unresolved episode continuity or ticker reuse cannot be bridged to reach the floor.

Sort eligible securities by descending median dollar volume, then by ascending ASCII
lexicographic canonical stable security ID; retain the first 1,000. Ties never expand the cap.
There is no hysteresis or sector balancing. Retain all if fewer qualify; record the shortfall,
without lowering floors or filling with unknowns. Store the resulting set sorted by stable ID.
For deterministic thresholds and ties, convert each pinned canonical float64 operand to its
shortest round-trip decimal string (Python 3.12 `str(float(value))`) and use exact decimal
multiplication and median arithmetic, without intermediate rounding or tolerances. Thus a
numeric near-tie is not an ID tie. Pin normalized bars, calendar/version and arithmetic inputs
with the future materialization evidence.

## Missing inputs and exits

Canonical bars must satisfy the [frozen schema](../contracts/bar-schema.md), with finite,
positive raw prices and finite nonnegative volume; duplicate security/session rows are invalid.
Count only actual valid session observations, never calendar days, forward fills or duplicates.
Missing old sessions need not be contiguous; they do not count toward 252. The trailing window
is 60 calendar-selected exchange sessions, not the most recent 60 available rows.

Distinguish a certified absence (for example, a known suspension/no-trade session) from unknown
vendor coverage. A certified absent trailing-window bar excludes that security for an incomplete
window; a certified absent older bar only reduces its history count. Unknown inventory coverage,
required dated metadata, currency, identity/episode mapping or expected bars refuses the date's
materialization and qualification. Invalid or duplicate required bars also refuse. Report known
economic exclusions and missing-input reasons, but never silently drop unknowns and promote the
next rank. A known ineligible instrument does not require a liquidity history. No interpolation,
stale close, today's survivor list or arbitrary ticker ordering resolves missing evidence.

Recompute after every close. Adds are inclusive on the decision-session label `t`; drops are
exclusive from the first `t` no longer selected, matching the existing
[constituent interval seam](../../algua/data/constituents.py). Before the first fully supported
date there is no qualified timeline. A failed date must not let the prior membership silently
stand in as fresh evidence. Corrections require a new universe identity, preserving immutable
existing timelines. Empty sets need explicit integration handling: the current import command
refuses an empty timeline snapshot; this definition does not authorize a workaround.

A price/rank exit removes eligibility for selection, not a held position or its economic
history. Selection must not consult later delistings or future recovery values. The separate
reviewed action/terminal layer must retain and account for held names after selection exits;
unresolved terminal economics must refuse the backtest, never erase a loss or assume the last
close. Zero recovery and acquisition consideration remain dependencies in the
[daily PIT design](../superpowers/specs/2026-11-12-pit-data-pipeline-design.md), not changes here.

## Deterministic synthetic examples

All IDs and values below are invented, with complete eligible metadata and valid history unless
stated otherwise. They contain no vendor rows or strategy returns.

| Input at closed session `t` | Result |
|---|---|
| `SEC-A`: close 10, each of 60 volumes 2,000,000, 252 valid history sessions | Median USD 20,000,000; all three floors pass exactly. |
| `SEC-B`: close 10, 30 dollar volumes of 18,000,000 and 30 of 22,000,000, 252 sessions | Median `(18,000,000 + 22,000,000) / 2 = 20,000,000`; passes liquidity. |
| `SEC-C`: same as `SEC-A`, but 251 valid observations | Excluded for history; 252nd valid observation admits it if other floors still pass. No IPO date is asserted. |
| `SEC-D`: 252 observations across two listing episodes, only 100 in the current episode | Excluded for history; old episode observations do not count. |
| `SEC-E`: 252 observations, but one certified absent bar within `t-59` through `t` | Excluded for incomplete window; using an older 60th row is forbidden. |
| `SEC-F`: expected bar on `t` absent with unknown cause, or historical currency unknown | Entire date refuses materialization/qualification; no replacement from rank 1,001. |
| `SEC-G`: 252 valid observations and one certified absent older session outside the 60-window | History floor passes; the older gap does not count and does not by itself disqualify. |

For the cutoff example, suppose 998 eligible IDs have liquidity strictly above USD 25,000,000.
`SEC-A`, `SEC-B`, `SEC-C` each have exactly USD 25,000,000 and otherwise pass. ASCII ordering puts
them at ranks 999, 1,000 and 1,001; select `SEC-A` and `SEC-B`, exclude `SEC-C`. Renaming a ticker
does not change this ordering. Reusing a ticker for another issuer must produce a different stable
ID and fresh history. With only 731 eligible IDs, select 731 and disclose a 269-name shortfall.

## Definition boundary and remaining data review

This freezes rules only. It creates no materialized universe, `verified_pit` provenance, gate
evidence, strategy qualification, provider cutover or trading authority. No existing proxy is
relabelled. The existing store/import seams are the integration target, not a second store or a
new bars schema. The configuration is not loaded by runtime commands today.

Before materialization can claim historical eligibility, reviewed data work must establish the
complete historical inventory, stable permanent-ID/dated-alias and listing-episode mapping,
dated instrument/domicile/venue/currency eligibility, missing-session accounting, raw-unit
reconstruction and action/terminal evidence. Vendor category labels must be mapped to the
declared instrument semantics with evidence; neither a current ticker table nor the rule hash
does that. Stable IDs must use a canonical ASCII representation that survives the existing
symbol normalization; its reviewed integration must pin that representation before ranking.
Bind the rule hash, exact input snapshots/metadata, calendar, materializer revision and coverage
to the future universe identity. The protected promotion-bound verifier remains a separate
human-reviewed change under the agreed daily price-only PIT standard.
