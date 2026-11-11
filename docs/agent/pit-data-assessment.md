# Minimum PIT data for the liquid-midcap candidate

Assessment date: 2026-11-08. Scope: daily, long-only liquid US midcaps; assessment only.
No purchase, signup, source rollout, gate change or strategy qualification was performed.

**Recommendation:** keep the current snapshot for machinery work. Before paying, obtain a small
source sample proving historical membership, security identity, price vintages and terminal events;
then implement one bounded importer/verifier through the existing store. Neither reviewed retail
vendor alone establishes all of that proof. Under the current no-purchase instruction, historical
investment qualification remains blocked; research and engineering can continue with honest limits.

## What is established today

[Recorded acquisition](midcap-machinery.md) pins `c63d16f44419cb96`: 400 symbols and 201,760 bars,
requested `[2024-11-01,2026-11-08)`, latest observed November 6. The November 8 screen selected 300
current S&P 400 proxy names across 11 current sectors, using price >= $10, 60-session median
`raw close × raw volume` >= $20M, and >=252 observed sessions. This end-date screen is not historical
membership or historical eligibility. The existing demonstration failed PIT and had negative
holdout Sharpe; changing its label or universe metadata cannot repair either result.

All seven `pilot_real_proxy` limitations remain: revisable adjusted close, unverified corporate
actions, absent delisted names, unavailable event timing, unavailable historical market cap,
unavailable PIT universe and survivorship-biased selection. A payload hash proves reproducibility,
not that its values were available at a historical decision time.

The shipped controls are useful but narrower than source certification:

| Existing seam | Proves / does not prove |
|---|---|
| [Promotion PIT check](../../algua/registry/promotion.py#L58) | Named membership timeline starts on/before evaluation start; does not authenticate source membership or price knowledge times. |
| [Universe store](../../algua/data/store/universe.py#L64), [PIT mask](../../algua/backtest/pit_view.py#L34) | Immutable dated membership and per-decision effective-date masking; no announcement/revision-time field in the consumed membership record. |
| [Reserved provenance](../../algua/provenance/research.py#L84), [manifest validation](../../algua/provenance/snapshot.py#L200) | `verified_pit` writes are refused: no verifier exists. Board metadata validity is not PIT certification. |
| [Bars contract](../contracts/bar-schema.md) | Raw OHLCV plus split/dividend-adjusted close, exact snapshot and half-open reads; no historical revision-as-of parameter. UTC-midnight daily labels are session dates, not availability timestamps. |
| [Delistings](../../algua/data/store/delistings.py#L25), [corporate actions](../../algua/data/corpactions.py#L50) | Positive terminal value in adjusted units and split/ordinary-dividend checks; zero write-offs, full merger/spinoff economics and source knowledge-time verification remain uncovered. |

**Important, flag-only:** the gap between `pit_ok` timeline coverage and independently verified PIT
evidence must be resolved through human-reviewed integrity work. Do not backdate a current list to
make the existing boolean pass. No protected code or frozen contract was changed for this assessment.

## Minimum inputs for a genuine candidate

Start with a price-only daily strategy, avoiding unnecessary fundamental/news data dependencies.
For the complete evaluation interval **and its pre-period warmup**, retain:

1. **Historical membership and identity:** baseline members on/before the first decision, every
   addition/removal, re-entries, stable security IDs and dated ticker mappings, including names
   removed or delisted later. Preserve effective dates separately from published/knowable and
   revision timestamps. Membership is an S&P-midcap proxy, not proof of a numerical market-cap band.
2. **Historical eligibility inputs:** raw daily OHLCV, actual listing/tradability history, sufficient
   prior sessions for the approved $10/$20M/60-session/252-session screen. Compute each screen
   using only information available at that decision; keep every failure/missing-name reason.
   The 252 observed-row floor is not independently verified listing age. Reusing sector balancing
   requires dated sectors; today's 11-sector labels cannot determine historical selection.
3. **Prices and corporate actions:** original availability/revision evidence for decision inputs;
   raw bars, split ratios, ordinary/special distributions, ex/effective dates, correction times,
   adjustment anchors and unit conventions. Latest vendor-adjusted history is not a price-vintage
   archive. Keep adjusted close for the frozen contract, but verify that future events/restatements
   cannot enter earlier feature decisions. A download's `as_of` is its collection time.
4. **Terminal economics:** last trade, suspension/delisting date, cash/share consideration,
   successor mapping, payment timing and zero recovery where applicable. Ending bars are not a
   terminal-proceeds record. Separate event outcome accounting from what a signal could know then.
5. **Delivered proof:** retained source bytes/URLs, retrieval clocks, source/version identifiers,
   hashes and license/retention terms, bound to bars, universe and event snapshot IDs. Verify all
   ever-members, not just today's successful downloads. Unresolved coverage keeps the run ineligible.

## Practical sources and cost

Prices below are displayed public personal-use prices observed on the assessment date; taxes,
currency conversion, license eligibility and exact entitlements need confirmation before approval.
No vendor was contacted and no paid payload was acquired or verified.

| Path | Useful delivery | Cost and remaining proof |
|---|---|---|
| Existing yfinance + free primary announcements | Existing bars seam; S&P announcements supply dated adds/drops and future effective dates. SEC filings can substantiate particular merger/distribution terms. | $0 incremental data fee. No complete free midcap membership/price-vintage/terminal package was established in this assessment. Reconstructing every change needs a trustworthy baseline and completeness reconciliation; it does not cure absent prices. [S&P example](https://press.spglobal.com/2024-09-06-Palantir-Technologies%2C-Dell-Technologies%2C-and-Erie-Indemnity-Set-to-Join-S-P-500-Others-to-Join-S-P-MidCap-400-and-S-P-SmallCap-600), [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). |
| EODHD EOD + historical-index add-on | API-accessible MID membership intervals; delisted-symbol discovery and historical EOD/splits/dividends. Core Fundamentals alone provides only current MID members. | Pricing page displayed £19.99/month EOD + £29.99/month constituent add-on: **£49.98 for one month**, subject to confirming the combination/access and billed currency. Cheapest reviewed paid source-evaluation option; no demonstrated original-vintage or terminal-proceeds proof. [Pricing](https://eodhd.com/pricing), [membership coverage/fields](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds), [delisted workflow](https://eodhd.com/financial-apis/delisted-stock-companies-data). |
| Norgate US Platinum | Historical `$MID` membership, delisted/previously major-listed OTC securities, stable asset IDs, raw and adjusted daily series. | **US$346.50/6 months or $630/year**; Windows updater/Python or a Windows VM adds setup. Stronger integrated membership/identity starting point, but not a complete PIT package: historical corrections have no versioning and detailed action/merger terms are not directly supplied. [Packages](https://norgatedata.com/stockmarketpackages.php), [coverage](https://norgatedata.com/data-content-tables.php), [Python requirements/IDs](https://pypi.org/project/norgatedata/), [revision/action FAQ](https://norgatedata.com/data-package-faq.php). |
| FirstRate import already supported | Local raw/adjusted files fit the existing importer. | Its FAQ acknowledges incomplete delisted coverage and historical ticker remapping. No complete historical MID membership or original knowledge-time proof established; do not buy solely because the importer exists. [Official FAQ](https://firstratedata.com/about/FAQ). |

EODHD's personal-use retention FAQ permits keeping downloaded data and provenance after
cancellation for private non-commercial use; it does not establish eligibility for every Algua
deployment or Marketplace license. Its public disclaimer also describes indicative pricing rather
than an exchange feed. Confirm entitlement, volume semantics and the actual sample before selecting
it. [Retention](https://eodhd.com/help/storage), [pricing/disclaimer](https://eodhd.com/pricing).
Norgate's dated membership solves a different problem from its unversioned historical price
corrections. Its capital-event indicator identifies event dates, not complete terms or historical
announcement times. These are source limitations, not reasons to weaken Algua's gate.

## Smallest implementation and decision

1. **No-spend proof first:** use retained/authorized source samples and primary announcements to
   reconcile a baseline plus an add, removal, rename, split/dividend and terminal event in the
   intended interval. Require actual vintage/knowable-time evidence; record an explicit failure
   when unavailable. Do not replace a missing member with a currently surviving stock.
2. **One importer:** normalize stable IDs/dated aliases, constituent intervals and bars through
   existing provider/importer and `data import-universe` seams (`add_date` inclusive, `drop_date`
   exclusive). Retain the full source union and warmup; materialize the approved screen per date.
   Keep source payloads and any restricted evidence outside this public repository.
3. **One verifier, separately reviewed:** bind exact source hashes and all relevant snapshot IDs to
   one bounded evidence result; check session/identity completeness, pre-start coverage, dated
   membership/screen inputs, price revision cutoffs, adjustment consistency and every terminal gap.
   Missing vintage, zero recovery or unmodeled merger/spinoff must refuse, not become a fabricated
   positive terminal value. Reuse snapshot readback and existing pure checks. Enabling verified-PIT
   provenance or binding it into promotion touches integrity controls and needs explicit human
   review; do not add a metadata checkbox that certifies itself. No schema/contract change is assumed.
4. **Only after data proof:** run a new identity-bound, costed evaluation with measured search
   breadth and a fresh, non-reused holdout. Current historical qualification requires PIT without
   override, >=63 holdout observations and positive holdout Sharpe; passing is not evidence of future
   profits. Freeze the eligible artifact, then collect **five actual scheduled paper sessions** for
   the separate experimental route. Historical replay supplies zero elapsed sessions.
   [Qualification implementation](../../algua/registry/experimental_qualification.py#L19),
   [capped route](capped-live.md).

**Remaining human choice:** retain the no-spend boundary, or explicitly approve a capped one-month
EODHD source-evaluation purchase after entitlement/sample confirmation (current displayed combined
cost £49.98, no renewal assumed). Prefer that inexpensive proof attempt over committing $346.50 to
Norgate now; choose Norgate only if integrated membership/identity benefits justify its higher cost
and Windows setup after reviewing its vintage gap. Neither purchase authorizes a waiver or promises
qualification. If original historical price/knowledge evidence cannot be supplied, choose a separately
quoted archival source or accumulate genuine prospective observations; do not rename restated data PIT.

The assessment task is complete. Data acquisition, importer/verifier rollout, a qualifying new
historical result and five real paper sessions remain **not delivered**. Verification here was
read-only source/code inspection and Markdown link/whitespace checks; no runtime suite was needed
for this documentation-only addition.
