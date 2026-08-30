# Task O — fundamentals, the audit, and making the AI reproducible

Self-contained. Everything needed is in this file; no cross-referencing required.
Supersedes the unfinished parts of `TASK-N-evidence-layer.md` (its news half is
done and committed at `966c1d5`).

**Four jobs, four commits, in order.** Commit each before starting the next. A
finished-and-committed part is progress; four half-done parts in a working tree
are not.

**You own:** `src/portfolio/fundamentals.py`,
`scripts/refresh_fundamentals.py`, `scripts/audit_fundamentals.py`,
`data/fundamentals.json`, `tests/test_fundamentals.py`, `tests/test_audit.py`,
and — **for Job 4 only** — `src/portfolio/ai.py` and `tests/test_ai.py`.

**You must not touch:** `config/prompt.md`, `marketdata.py`, `news.py`,
`validator.py`, `executor.py`, `triggers.py`, `rules.json`, `run_cycle.py`.
Putting fundamentals in front of the AI is Phase 9, deliberately separate so a
change in behaviour can be traced to one cause.

---

## Why this exists

The Jan–Mar 2026 backtest produced **four consecutive cycles of `HOLD ×15`** over
nine weeks. The only sale was forced by the stop loss. The model was asked weekly
whether each thesis still held, and given only price to answer with — and "this
company leads in AI accelerators" cannot be falsified by a price chart. A fall
tells you the price fell.

Jobs 1–3 supply evidence that *can* falsify a thesis. Job 4 makes it possible to
measure whether that helped.

---

# JOB 1 — `src/portfolio/fundamentals.py`

## The source, and one route already rejected

**SEC EDGAR.** Free, official, no API key, no quota.

Use **`companyfacts`** — one request returns every measure for one company:
`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` (~3.8 MB for Apple).

The **`frames`** endpoint looks far more attractive — one request returns one
measure for thousands of companies, under a megabyte. It was tested on
2026-08-30 and **rejected**: Apple is entirely absent from the `Revenues` frame
for CY2026Q2, because its fiscal quarters do not align to calendar ones. Only 1
of 3 megacaps appeared. Do not reach for it as an optimisation — patchy
fundamentals are worse than slow ones, and a silently missing Apple is exactly
the gap that produces confident wrong conclusions.

**Required mechanics:**
- Ticker → CIK from `https://www.sec.gov/files/company_tickers.json`
  (10,391 companies). **Pad the CIK to 10 digits.**
- **A `User-Agent` header carrying real contact details is mandatory** — requests
  without one are refused. Use `"Luke Holloway hollowayluke20@gmail.com"`.
- **Keep to ≤10 requests/second.** Sleep between calls. 503 companies takes about
  a minute; that is fine and does not need optimising.
- Each data row carries: `start`, `end`, `val`, `accn`, `fy`, `fp`, `form`,
  `filed`, `frame`.

## The ten measures

Chosen from what actually survives in the literature — Graham's safety tests, the
Piotroski F-Score, and Novy-Marx's gross profitability. Nothing here is
speculative; every one feeds a documented method.

| Concept | Kind |
|---|---|
| `EarningsPerShareDiluted` | **flow** |
| `Revenues` | **flow** |
| `NetIncomeLoss` | **flow** |
| `GrossProfit` | **flow** |
| `NetCashProvidedByUsedInOperatingActivities` | **flow** |
| `Assets` | **instant** |
| `AssetsCurrent` | **instant** |
| `LiabilitiesCurrent` | **instant** |
| `LongTermDebtNoncurrent` | **instant** |
| `CommonStockSharesOutstanding` | **instant** |

### Flow vs instant is not a label. It changes the arithmetic.

- **Flow** measures cover a *period* (`start` → `end`). Four quarters sum to a
  year.
- **Instant** measures are a *snapshot* (`end` only). **Never sum them.** Adding
  four quarters of "total assets" yields a company four times its real size.
  Take the most recent value at or before the as-of date.

Applying flow logic to a balance-sheet item is the single most likely way to get
this wrong, and **nothing will raise** — the number simply comes out four times
too big and entirely plausible.

### Tag fallbacks

Filers do not agree on names. Revenue is the worst offender; Apple files under
two at once. Try in order, and record which was used:

- **Revenues:** `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`,
  `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueNet`
- **EPS:** `EarningsPerShareDiluted`, `EarningsPerShareBasic`,
  `EarningsPerShareBasicAndDiluted`
- **Debt:** `LongTermDebtNoncurrent`, `LongTermDebt`
- **Shares:** `CommonStockSharesOutstanding`,
  `dei:EntityCommonStockSharesOutstanding`

A measure with no matching tag is `None` — not zero, and not silently omitted.
Record that it is missing so coverage is visible.

## The two traps

**TRAP 1 — quarterly and cumulative figures sit in the same list.** For one period
end, EDGAR publishes both the quarter and the year-to-date running total. They
look identical apart from `start`. Summing the last four rows double-counts:

```
AAPL   correct TTM EPS   8.44  ->  P/E 37.9   (at price 319.70)
AAPL   naive   TTM EPS  15.76  ->  P/E 20.3   <- wrong, and it looks fine
```

One says expensive, the other says reasonable. **A wrong valuation is worse than
no valuation**, because a number carries authority a blank does not.
Keep only rows whose `end - start` span is **under 110 days**.

**TRAP 2 — `filed` is not `end`.** Apple's quarter ending **2025-12-27** was not
public until **2026-01-30** — a 34-day gap, consistent across filings. A backtest
replaying mid-January that keys off `end` is reading results nobody had yet, and
will look brilliant for reasons that never existed. **Filter on `filed`.**

## Store the series, not a computed number

**Do not store one TTM figure per measure.** Store the last **12 periods** of raw
values. Derived numbers — this year's total, last year's total, trends — are then
computed later without re-fetching. The Piotroski score is *entirely* about this
year versus last year, so storing only a current value would force a full
re-fetch to add it.

```json
{
  "schema_version": 1,
  "generated_at": "2026-08-30T...",
  "tickers": {
    "AAPL": {
      "cik": "0000320193",
      "measures": {
        "EarningsPerShareDiluted": {
          "concept": "EarningsPerShareDiluted",
          "kind": "flow",
          "points": [
            {"end": "2026-06-27", "filed": "2026-07-31", "start": "2026-03-29", "val": 2.02}
          ]
        }
      }
    }
  }
}
```

## Functions

```python
def compute_ttm(points: list[dict], as_of: str) -> float | None:
    """Flow measures only. Pure — no network, no clock, no file access."""
```

1. Keep rows where `filed <= as_of` (Trap 2).
2. Keep rows where `end - start` is under 110 days (Trap 1).
3. Deduplicate by `(start, end)`, keeping the latest `filed` — quarters get
   restated in later filings.
4. Sum the four most recent by `end`. Fewer than four available → `None`.
   **Never sum three and present it as a year.**

```python
def latest_instant(points: list[dict], as_of: str) -> float | None:
    """Most recent value with filed <= as_of. No summing, ever."""

def pe_ratio(price: float, ttm_eps: float | None) -> float | None:
    """None if ttm_eps is None or <= 0. A loss-making company has no meaningful
    P/E, and a negative one rendered as a number reads as cheap."""
```

## Tests — no network anywhere, hand-built point lists

**The pinned test, which is the point of this job:**

```
AAPL four most recent quarterly EPS: 1.57, 2.84, 2.01, 2.02
    correct TTM  8.44
    naive   TTM 15.76   (cumulative rows double-counted)
```

Assert `8.44`. **Then remove the under-110-days filter, watch the test go red,
put it back, and say in your report that you saw it fail.** A test never seen
failing guards nothing.

Do the same for the `filed` filter: build points where the newest quarter was
filed a month after `as_of`, assert the result uses the four quarters *before*
it, then remove the filter and watch it go red.

Also cover:
- A restated quarter — same `(start, end)` filed twice with different values: the
  later filing wins and it is not counted twice.
- Three quarters available → `None`, not a sum of three.
- `latest_instant` never sums, and respects `filed`.
- `pe_ratio` → `None` for negative EPS, `None` for `None`, correct otherwise.
- A ticker with no CIK (an ETF) produces no measures and does not raise.

**Commit.**

---

# JOB 2 — `scripts/refresh_fundamentals.py`

Shaped like `scripts/refresh_universe.py`: read the universe, fetch, write
`data/fundamentals.json` atomically, print a summary.

The summary must report **per-measure coverage counts**, so thin data is visible
now rather than discovered in three weeks.

ETFs have no CIK. SPY, GLD, TLT and the rest come out with no measures — that is
correct output, not a failure. Print the count so a reviewer sees roughly 15, not
roughly 300.

Then **run it for real** and commit the resulting file.

**Done when** the file holds roughly 503 companies with real measures and ~15
ETFs with none, and no measure sits below 90% coverage. If revenue lands under
90%, the fallback list needs another tag — **say so rather than accepting it.**

**Commit.**

---

# JOB 3 — `scripts/audit_fundamentals.py`

Unit tests check the code against numbers you made up. **Nothing currently checks
the real data.** The tests will pass perfectly against a half-empty file. This is
the missing check: it reads `data/fundamentals.json`, prints a report, fetches
nothing and changes nothing.

### 1. Coverage
Per measure: count and percentage of companies that have it. Flag anything under
90%.

### 2. Accounting identities — the most valuable part, and needs no outside source
Report every company violating one:
- gross profit must not exceed revenue
- net income must not exceed revenue
- current assets must not exceed total assets
- total assets, shares outstanding and revenue must all be positive

**These catch Trap 1 directly.** If revenue is being double-counted but net income
is not, net income stops exceeding revenue and nothing looks wrong from the
outside; if it is the other way round, this fires immediately. It is the closest
thing to a free correctness proof available here.

### 3. Sanity ranges
Count and list: P/E above 200 or below −200; profit margin outside −100%..+100%;
any TTM value more than 10× its prior-year equivalent.

### 4. Cross-check printout
For `AAPL, MSFT, NVDA, JPM, XOM, KO, UNH, PG` print our computed TTM EPS, TTM
revenue and P/E as a plain table, so a human can compare against a public source.

**Do not hardcode expected values — they go stale.** For reference only: on
2026-08-30 a public source showed Apple at EPS 8.72, P/E 36.68, revenue 466.82B,
against our 8.44. A gap of a few percent is expected and explainable (a newer
filing, a different earnings definition). **Do not change the calculation to make
these match** — the SEC filing is the authority, and chasing a third party's
number is how a correct implementation gets broken.

### 5. Determinism
- A unit test that `compute_ttm` and `latest_instant` return identical answers
  when the input points are shuffled into a different order.
- Re-fetch **10 tickers only**, rebuild their entries, and assert they are
  identical to what is stored, ignoring timestamps.

Exit non-zero if any identity is violated or any measure is under 90% coverage,
so this can later run unattended in CI.

**Commit.**

---

# JOB 4 — make the AI reproducible

`src/portfolio/ai.py`, `_call_gemini`, sets no temperature, so Gemini uses its
default and **the same prompt produces different decisions on every run.**

That quietly destroys measurement. The backtest cannot be run before and after a
change and compared, because the difference might simply be the dice. Every
improvement becomes unmeasurable, and no past decision can be reproduced.

- Add `"temperature": 0` to the `generationConfig` block.
- If the API version in use also supports a `seed` field, set it to a fixed value
  and note that in the docstring.
- Add a test asserting the request body **actually sent** carries temperature 0 —
  monkeypatch the HTTP layer, capture the body, assert on it. Not a test of a
  config dict; a test of what crosses the boundary. That distinction is what
  Phase 7's worst bug turned on.

**Commit.**

---

# Housekeeping, blockage, and reporting

**Do not install packages into the project folder.** A previous run vendored
pytest into `.test-deps/`, which is now git-ignored. If a dependency is missing,
say so and stop.

**If the sandbox refuses to write to `.git`:** do not retry, do not work around
it, and do not continue to the next job. Stop, name the exact command refused,
and leave the files in place — they can be committed separately. A prompt cannot
grant a permission the operating system is denying.

**Reporting, after every commit and at the end:** do not summarise what you
intended to do. Show `git log --oneline -1`, `git status --short`, and the lines
changed. State explicitly which protective tests you saw fail. If a job is
unfinished, name exactly which parts.
