# 0004 — The data contract

**Date:** 2026-08-28
**Status:** Accepted

## Context

ADR 0002 established that the repo is the database: the pipeline writes JSON,
the dashboard reads it, and the two never talk directly. That only works if the
shape of those files is fixed **before** either side is built. Once fixed, the
pipeline and the dashboard can be built simultaneously by different agents
without touching each other's code.

A precedent from the same day: a throwaway two-agent test used a `CONTRACT.md`
that never said whether cash counted toward position weights. Both agents
picked an interpretation, they happened to be compatible, and it went unnoticed.
That ambiguity would not be harmless here.

## The three files

| File | Written by | Read by | Lifecycle |
|---|---|---|---|
| `data/state.json` | every run | dashboard, email | **Replaced** wholesale each run |
| `data/history.json` | daily run | dashboard chart | **Append-only**, idempotent by date |
| `data/decisions/<date>.json` | decision cycles | dashboard, email | **Immutable** once written |

## Universal rules

1. **Currency is USD throughout.** Alpaca is a US broker; the paper account is
   USD. No GBP conversion anywhere in this system. (Luke's personal £10k book
   is a separate thing and must not be conflated with it.)
2. **Weights and percentages are decimal fractions, never percentages.**
   `0.0636` means 6.36%. There is no field anywhere holding `6.36`. This
   eliminates the single most common bug of this kind.
3. **Weight denominator is `total_value`, which includes cash.** So all
   position weights plus `cash_weight` sum to 1.0. This is the ambiguity that
   the earlier test contract left open; it is now closed.
4. **All timestamps are ISO 8601 UTC with a trailing `Z`.** Dates without a
   time are `YYYY-MM-DD`. No local time, no BST, anywhere in stored data.
5. **Monetary values are JSON numbers, not strings**, rounded to 2 decimal
   places. Share quantities may carry more precision (fractional shares).
6. **Every file carries `schema_version`.** A reader encountering a version it
   does not know must fail loudly rather than guess.

## `state.json` — the current snapshot

Fully replaced every run. Never appended to.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | int | Currently `1` |
| `generated_at` | timestamp | When this file was written |
| `market_data_as_of` | timestamp | When the *prices* are from. **Differs from `generated_at`** because the free data feed is 15 minutes delayed (ADR 0001) |
| `currency` | string | Always `"USD"` |
| `run` | object | `id`, `trigger` (`schedule`/`manual`), `workflow` |
| `account.cash` | number | Settled cash |
| `account.equity` | number | Cash + market value of positions |
| `account.buying_power` | number | **Recorded for visibility, never used for sizing.** Alpaca grants 4x margin; sizing from this would permit a $400k portfolio on $100k |
| `totals.total_value` | number | The weight denominator |
| `totals.invested_value` | number | Sum of position market values |
| `totals.cash_weight` | number | Decimal fraction |
| `totals.position_count` | int | |
| `positions[]` | array | One per holding, see below |
| `performance` | object | `inception_date`, `inception_value`, `total_return_pct` |
| `benchmark` | object | `ticker`, `inception_price`, `current_price`, `total_return_pct`, `difference_pct` |
| `health.ok` | bool | False if the run degraded in any way |
| `health.warnings[]` | string[] | Human-readable; the dashboard must display these |

Each `positions[]` entry: `ticker`, `qty`, `avg_entry_price`, `current_price`,
`market_value`, `weight`, `unrealized_pl`, `unrealized_pl_pct`, `opened_at`.

### Staleness is a first-class concern

A static dashboard shows whatever was last written, and a silently failed
pipeline therefore looks identical to a healthy one. Two requirements follow:

- `generated_at` is **mandatory** and must always be real.
- The dashboard **must display it**, and must visibly flag data older than
  **26 hours** (a daily cycle plus margin) rather than rendering stale numbers
  as if current.

## `history.json` — the time series

Append-only, one row per trading day. Powers the performance chart and the
benchmark comparison.

Each row: `date`, `portfolio_value`, `portfolio_return_pct`, `benchmark_price`,
`benchmark_return_pct`, `cash`.

**Idempotent by date.** Re-running on a day that already has a row **replaces
that row**; it never appends a duplicate. A workflow that runs twice, or a
manual re-run, must not corrupt the chart.

**Rows are never deleted.** History cannot be reconstructed after the fact —
Alpaca will not sell back past portfolio values — so a missing day is missing
permanently.

### Benchmark baselines are stored once, never recomputed

`performance.inception_value` and `benchmark.inception_price` are written at
inception and then treated as constants. Recomputing a baseline each run is how
a benchmark comparison silently drifts.

Comparison is **price return against price return**. Alpaca paper accounts do
not pay dividends (ADR 0001), so measuring the portfolio ex-dividend against a
total-return benchmark would understate performance for no real reason.

## `data/decisions/<YYYY-MM-DD>.json` — the decision record

One file per decision cycle. **Immutable once written** — a later cycle never
edits an earlier file. This is the brief's §5 requirement: that weeks later
someone can reconstruct what the system decided and why.

Top level: `schema_version`, `cycle_id`, `decided_at`,
`portfolio_value_at_decision`, `commentary` (the AI's portfolio-level
narrative), `decisions[]`.

Each entry in `decisions[]`:

| Field | Notes |
|---|---|
| `ticker` | |
| `action` | `BUY` \| `SELL` \| `TRIM` \| `HOLD` |
| `target_weight` | Decimal fraction |
| `notional` | USD amount ordered; `null` for `HOLD` |
| `thesis` | Why this position should exist |
| `risks` | What would make it wrong |
| `reason_for_action` | Why act *now*, as opposed to the thesis itself |
| `trigger` | `ai` \| `stop_loss` \| `concentration_trim` |
| `status` | `executed` \| `rejected` \| `skipped` |
| `order_id` | Alpaca order id, or `null` |
| `rejection_reason` | Which validation check failed, or `null` |

**`HOLD` decisions are recorded.** The brief's own example email lists holds
alongside buys and sells, and "we looked and chose not to act" is a decision.

**Rejected orders are recorded, not discarded.** A validation failure is
evidence the guardrails worked and belongs in the history.

`thesis` / `risks` / `reason_for_action` are separate fields rather than one
blob so the dashboard and email can render them without parsing prose.

## Consequences

- The dashboard can be built against a hand-written example `state.json` before
  the pipeline exists. That is the point.
- Adding a field is backwards-compatible; changing or removing one requires a
  `schema_version` bump and a new ADR.
- Every file is independently readable. Opening `data/state.json` on GitHub
  should tell a human the state of the portfolio with no tooling.
