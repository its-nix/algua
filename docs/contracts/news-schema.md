# News schema (the non-tabular PIT seam — hindsight slice)

Tidy/long, bitemporal. One row = one mentioned symbol of one article revision, stamped with when
it became knowable.

| column | type | meaning |
|---|---|---|
| `source` | str (lower-cased, non-null) | publisher / wire; part of the identity (article ids are unique only within a source) |
| `article_id` | str (non-null) | the source's stable article id (or URL) |
| `symbol` | str (upper-cased, non-null) | one mentioned issuer (an article with N symbols → N rows) |
| `published_at` | tz-aware UTC datetime (non-null) | original publication time (invariant per article) |
| `knowable_at` | tz-aware UTC datetime (non-null) | when this row became knowable; the PIT key |
| `headline` | str (non-null) | the headline text |
| `url` | str or null | article link |
| `body` | str or null | full article text |

## Point-in-time rule
A record is knowable at `t` iff `knowable_at <= t`. **Hindsight access is removed** — the `query-news`
command no longer exists. A future as-of signal lane would mask on
`knowable_at` exactly as fundamentals does.

## Identity & revisions
- As-of identity key: `(source, article_id, symbol)`; unique row key adds `knowable_at`.
- A **content** revision (corrected headline/body) is a new row sharing the identity key with a
  later `knowable_at`. Symbol-set revisions (adding/removing tagged tickers) need tombstones and are
  deferred with the signal lane.
- `published_at` is invariant per `(source, article_id)`; `headline`/`url`/`body` are invariant per
  `(source, article_id, knowable_at)` (one revision exploded across symbols).

## Validation floor
`knowable_at >= published_at`. Unique `(source, article_id, symbol, knowable_at)` within a snapshot.

## Two access modes
- **As-of (signal):** DEFERRED (no `NewsProvider`/`needs_news` this slice).
- **Hindsight (analysis):** removed (redesign pending); `algua.data.hindsight` no longer exists.

## Ingest
Removed: `algua data ingest-news` and the Yahoo RSS fetcher are gone (redesign pending). Existing
snapshots stay readable through the store read path.
