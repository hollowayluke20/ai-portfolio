# Task N — the evidence layer: news and fundamentals

Read `INTERFACE.md` first for the verified API facts and the two traps. Do not
re-probe them; they were measured on 2026-08-30.

One agent, **three commits, in this order**. Commit each part before starting the
next. A part that is finished and committed is progress; three parts half-done in
a working tree is not.

**You own:** `src/portfolio/news.py`, `src/portfolio/fundamentals.py`,
`scripts/refresh_fundamentals.py`, `data/fundamentals.json`,
`tests/test_news.py`, `tests/test_fundamentals.py`

**You must not touch:** `ai.py`, `config/prompt.md`, `marketdata.py`,
`validator.py`, `executor.py`, `triggers.py`, `rules.json`, `run_cycle.py`.
Putting any of this in front of the AI is Phase 9, deliberately separate so a
change in behaviour can be traced to one cause.

---

## Why this exists

The Jan–Mar 2026 backtest produced **four consecutive cycles of `HOLD ×15`**. The
only sale in nine weeks was forced by the stop loss. The model was asked weekly
whether a thesis still held and given only price to answer with — and a thesis
like "this company leads in AI accelerators" cannot be falsified by a price
chart. This task supplies the evidence that can falsify one.

---

# Commit 1 — news

### `fetch_news(tickers, start, end, per_ticker=5) -> dict[str, list[Article]]`

`GET {DATA_HOST}/v1beta1/news`, params `symbols` (comma-separated), `start`,
`end`, `limit=50`, `sort=desc`. Follow `next_page_token` as
`marketdata.fetch_bars` does; stop early once every ticker has `per_ticker`
articles. Chunk tickers at 50.

```python
@dataclass(frozen=True)
class Article:
    headline: str
    summary: str      # "" when absent, never None
    created_at: str
    source: str
    url: str
```

- An article's `symbols` may list several tickers — file it under **every**
  requested ticker it mentions. Do not deduplicate across tickers; a story about
  Nvidia and Tesla is evidence about both.
- **`end` is a hard boundary.** Filter locally on `created_at` as well as passing
  the parameter — never trust the API to have honoured it. This is what lets the
  backtest replay honestly.
- Trim to `per_ticker` **after** grouping and sorting, or a ticker sharing a story
  with a noisier one loses its own coverage.
- Tickers with no news are **absent from the dict**, not present with `[]`.

### Tests (no network — stub the HTTP layer)

- Grouping and newest-first ordering across two tickers.
- **An article dated after `end` is excluded.** Include one in the stub and assert
  it is gone. Remove the filter and watch this go red before you commit.
- A two-symbol article appears under both.
- `per_ticker=2` trims correctly, including for a ticker sharing a noisy story.
- A ticker with no articles is absent.
- `next_page_token` is followed and merged.
- Missing `summary` becomes `""`.

---

# Commit 2 — fundamentals: fetch and store

### Ten measures, chosen from what actually survives

These are what Graham's safety tests, the Piotroski F-Score and Novy-Marx's
gross profitability all need. Nothing here is speculative — every one feeds a
documented method.

| Concept | Kind |
|---|---|
| `EarningsPerShareDiluted` | flow |
| `Revenues` | flow |
| `NetIncomeLoss` | flow |
| `GrossProfit` | flow |
| `NetCashProvidedByUsedInOperatingActivities` | flow |
| `Assets` | instant |
| `AssetsCurrent` | instant |
| `LiabilitiesCurrent` | instant |
| `LongTermDebtNoncurrent` | instant |
| `CommonStockSharesOutstanding` | instant |

**Flow vs instant is not decoration — it changes the maths.**

- **Flow** measures cover a *period* (`start` → `end`). Four quarters sum to a
  year. The cumulative trap in `INTERFACE.md` applies to these.
- **Instant** measures are a *snapshot* (`end` only). **Never sum them.** Adding
  four quarters of "total assets" produces a company four times its real size.
  Take the most recent value at or before the as-of date.

Applying flow logic to a balance-sheet item is the single most likely way to
get this wrong, and nothing will error — the number will just be four times too
big.

**Tag fallbacks.** Filers do not agree on names, and revenue is the worst
offender — Apple files under two at once. Try in order and record which was used:

- Revenues: `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`,
  `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet`
- EPS: `EarningsPerShareDiluted`, `EarningsPerShareBasic`,
  `EarningsPerShareBasicAndDiluted`
- Debt: `LongTermDebtNoncurrent`, `LongTermDebt`
- Shares: `CommonStockSharesOutstanding`, `dei:EntityCommonStockSharesOutstanding`

A measure with no matching tag is `None`. Not zero, not omitted silently — record
that it is missing so a reviewer can see coverage.

### Store the series, not a single computed number

**Do not store one TTM figure per measure.** Store the last **12 periods** of raw
values. Derived numbers — this year's total, last year's total for comparison,
trends — are then computed later without re-fetching anything. Piotroski is
entirely about *this year versus last year*, so a single current value would
force a full re-fetch to add it.

```json
{
  "schema_version": 1,
  "generated_at": "...",
  "tickers": {
    "AAPL": {
      "cik": "0000320193",
      "measures": {
        "EarningsPerShareDiluted": {
          "concept": "EarningsPerShareDiluted",
          "kind": "flow",
          "points": [{"end": "2026-06-27", "filed": "2026-07-31", "val": 2.02}]
        }
      }
    }
  }
}
```

### Fetching

Use **`companyfacts`** — one request per company returns every measure at once:
`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` (~3.8 MB for Apple).

The `frames` endpoint looks tempting — one request for all companies, under a
megabyte — and it was tested and **rejected**: Apple is absent from the revenue
frame entirely, because its fiscal quarters do not align to calendar ones. Only
1 of 3 megacaps appeared. Patchy fundamentals are worse than slow ones.

- Ticker → CIK from `https://www.sec.gov/files/company_tickers.json`, **padded to
  10 digits**.
- **A `User-Agent` header with real contact details is mandatory** — requests
  without one are refused. Use `"Luke Holloway hollowayluke20@gmail.com"`.
- **≤10 requests/second.** Sleep between calls.
- ETFs have no CIK. SPY, GLD, TLT and the rest come out with no measures. That is
  correct output — print the count so a reviewer sees ~15, not ~300.

### `compute_ttm(points, as_of) -> float | None` — flow measures only

Pure. No network, no clock. Both traps live here:

1. **Drop anything not yet public**: keep `filed <= as_of`. Not `end` — Apple's
   quarter ending 2025-12-27 was not filed until 2026-01-30, a 34-day gap. Keying
   off `end` reads the future.
2. **Quarterly rows only**: keep `end - start` under 110 days. The year-to-date
   cumulative rows sit in the same list and look identical.
3. **Deduplicate by `(start, end)`**, keeping the latest `filed` — quarters get
   restated.
4. Sum the four most recent by `end`. Fewer than four → `None`. Never sum three
   and present it as a year.

### `latest_instant(points, as_of) -> float | None`

Most recent value with `filed <= as_of`. No summing, ever.

### `pe_ratio(price, ttm_eps) -> float | None`

`None` if `ttm_eps` is `None` or `<= 0`. A loss-making company has no meaningful
P/E, and a negative one rendered as a number reads as cheap.

### Tests (no network — hand-built point lists)

**The pinned test, which is the point of this commit:**

```
AAPL four most recent quarterly EPS: 1.57, 2.84, 2.01, 2.02
    correct TTM  8.44  ->  P/E 37.9 at price 319.70
    naive   TTM 15.76  ->  P/E 20.3      (cumulative rows double-counted)
```

Assert `8.44`. **Remove the cumulative filter, watch it go red, put it back, and
say in your report that you saw it fail.** A test never seen failing guards
nothing.

Do the same for the `filed` filter: points filed after `as_of` must be excluded,
and removing that filter must turn the test red.

Also cover: a restated quarter (later filing wins, not counted twice); three
quarters → `None` ; `latest_instant` never sums and respects `filed`; `pe_ratio`
returns `None` for negative and for `None`; a ticker with no CIK does not raise.

---

# Commit 3 — the refresh script

`scripts/refresh_fundamentals.py`, shaped like `scripts/refresh_universe.py`:
read the universe, fetch, write `data/fundamentals.json` atomically, print a
summary — tickers kept, tickers with no CIK, and **per-measure coverage counts**,
so thin data is visible rather than discovered later.

Then run it for real and commit the output.

**Done when** the file exists with roughly 503 companies carrying real measures
and ~15 ETFs carrying none, and the coverage summary shows no measure that is
mostly missing. If revenue lands under 90% coverage, the fallback list needs
another tag — say so rather than accepting it.

---

## Reporting

After each commit, and at the end: **do not summarise what you intended to do.**
Show `git log --oneline -1`, `git status --short`, and the lines changed. State
explicitly that you saw the two protective tests fail. If a part is unfinished,
name exactly which.
