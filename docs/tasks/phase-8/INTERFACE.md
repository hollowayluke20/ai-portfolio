# Phase 8 — evidence beyond price: interface

**Reference only — the agent does not edit this file.**

Originally split as Task N (news) and Task O (fundamentals) for two agents.
**Merged into a single `TASK-N-evidence-layer.md` run by one agent**, in three
sequential commits. The verified facts and the two traps below are unchanged and
are the reason this file still exists.

Nothing in this phase **touches the prompt** — that is Phase 9's job, kept
separate so a change in behaviour can be attributed to one thing.

## The point

The Jan–Mar 2026 backtest produced **four consecutive cycles of `HOLD ×15`**.
The only sale in nine weeks was forced by the stop loss. The AI never once
judged a position to have gone bad.

That was the correct answer to an impossible question. It was asked weekly
whether a thesis still held, and given only price to answer with. A thesis like
"this company leads in AI accelerators" cannot be falsified by a price chart —
a fall tells you the price fell, not that the reason broke. `docs/what-broke.md`
2026-08-30 has the full finding.

Phase 7 gave the model eyes. This gives it **grounds**.

## Verified facts this design rests on

Probed live on 2026-08-30. Do not re-derive these.

**News** — `GET https://data.alpaca.markets/v1beta1/news`
- `symbols` comma-separated, `start`, `end`, `limit` (50 max), `sort=desc`,
  `page_token`. Returns `{"news": [...], "next_page_token": ...}`.
- Per article: `headline`, `summary`, `created_at`, `source`, `url`, `symbols`.
- **`content` is empty on this plan.** Headline and summary are what exist.
- **History goes back to at least March 2020**, which is what makes the
  backtest able to replay with news rather than without it.
- 50 articles across 15 tickers over 7 days ≈ **10,600 characters** of headline
  + summary. The prompt is currently 61,626, so this is affordable.

**Fundamentals** — SEC EDGAR. Free, official, no API key, no quota.
- Ticker → CIK map: `https://www.sec.gov/files/company_tickers.json` (10,391
  companies). CIK must be zero-padded to 10 digits.
- `https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/EarningsPerShareDiluted.json`
- **A `User-Agent` header with real contact details is required** or requests
  are refused. Keep to **≤10 requests/second** — the SEC asks for it.
- Each row: `start`, `end`, `val`, `accn`, `fy`, `fp`, `form`, `filed`, `frame`.

## The two traps. Both are silent, both produce a confident wrong number.

**1. Quarterly and cumulative figures sit in the same list.** For one period end
EDGAR publishes both the quarter and the year-to-date running total, and they
look identical apart from `start`. Summing the last four rows double-counts:

```
AAPL   correct TTM EPS  8.44  ->  P/E 37.9   (price 319.70)
AAPL   naive TTM EPS   15.76  ->  P/E 20.3   <- wrong, and it looks fine
```

One says expensive, the other says reasonable. **A wrong valuation is worse
than none**, because a number carries authority a blank does not.
Filter to rows whose `end - start` span is **under 110 days**.

**2. `filed` is not `end`.** Apple's quarter ending **2025-12-27** was not public
until **2026-01-30** — a 34-day gap, consistent across filings. A backtest
replaying mid-January that keys off `end` is reading results nobody had yet, and
will look brilliant for reasons that never existed. **Filter on `filed`.**

## The contracts

```python
# src/portfolio/news.py            (Task N)

@dataclass(frozen=True)
class Article:
    headline: str
    summary: str
    created_at: str   # ISO timestamp
    source: str
    url: str

def fetch_news(
    tickers: list[str], start: str, end: str, per_ticker: int = 5
) -> dict[str, list[Article]]:
    """Recent articles per ticker, newest first, capped at `per_ticker`.

    An article can carry several symbols; it appears under each ticker in
    `tickers` that it mentions. Tickers with no news are absent from the dict,
    not present with an empty list.

    `end` is the as-of date and is a hard boundary: never return an article
    created after it. This is what lets the backtest replay honestly."""
```

```python
# src/portfolio/fundamentals.py    (Task O)

@dataclass(frozen=True)
class Fundamentals:
    ticker: str
    ttm_eps: float | None    # sum of the last four QUARTERLY figures
    period_end: str | None   # end date of the newest quarter used
    filed: str | None        # when that quarter became public
    quarters_used: int
    concept: str | None      # which XBRL tag was used

def refresh_fundamentals(tickers: list[str]) -> dict[str, Fundamentals]:
    """Network. Fetches and returns everything; the caller writes the file."""

def compute_ttm_eps(rows: list[dict], as_of: str) -> Fundamentals | None:
    """Pure. No network, no clock. Applies both traps above."""

def pe_ratio(price: float, ttm_eps: float | None) -> float | None:
    """None if ttm_eps is missing or <= 0. A negative P/E is meaningless and
    must never be rendered as if it were a valuation."""
```

Anything missing is `None`, never `0` and never a default. A gold fund has no
earnings; that is a fact to report, not a gap to fill.

## Boundaries

- The task owns `src/portfolio/news.py`, `src/portfolio/fundamentals.py`,
  `scripts/refresh_fundamentals.py`, `data/fundamentals.json`,
  `tests/test_news.py`, `tests/test_fundamentals.py`.
- It does **not** touch `ai.py`, `config/prompt.md`, `marketdata.py`,
  `validator.py`, `executor.py`, `triggers.py`, `rules.json`, `run_cycle.py`.

Nothing in this phase changes what the AI sees or is allowed to do. If
behaviour shifts after Phase 9, it must be clear which change caused it.
