# Task L — the market data layer

Read `INTERFACE.md` first. It holds the data contract and the verified facts
about Alpaca's API. Do not re-probe the API to confirm them; they were measured.

**You own:** `src/portfolio/marketdata.py`, `tests/test_marketdata.py`
**You must not touch:** anything else. Especially not `ai.py`, `prompt.md`,
`validator.py`, `executor.py`, `triggers.py`, `rules.json`.

## Build

### 1. `fetch_bars(tickers, start, end) -> dict[str, list[dict]]`

- `GET {DATA_HOST}/v2/stocks/bars`
- Chunk `tickers` at **200 per request**.
- Params: `symbols`, `timeframe=1Day`, `start`, `end`, `limit=10000`,
  **`adjustment=all`**.
- Follow `next_page_token` until absent, merging into the same symbol lists.
  It *is* returned at full-universe size — a version that ignores it silently
  loses most of the history.
- Reuse `alpaca._request` if its signature allows a `data.alpaca.markets` URL
  and gives you the status code and JSON. If it does not, write a local helper
  rather than changing `alpaca.py` — that file is outside your boundary.
- Missing symbols are omitted by the API rather than erroring. Do not invent
  empty lists for them; let the caller see they are absent.

### 2. `compute_features(bars, as_of) -> dict[str, TickerFeatures]`

Pure. No network, no `datetime.now()`, no file reads. The test suite will call
it with a fixed dict and a fixed date and expect the same answer forever.

**Filter first.** Drop every bar whose date is after `as_of` before computing
anything. Bar timestamps arrive as `"2026-08-28T04:00:00Z"`; compare on the
first 10 characters.

Then, per ticker, from the adjusted closes:

| Field | How |
|---|---|
| `price` | last close at or before `as_of` |
| `ret_1m` | vs the close ~21 trading bars back |
| `ret_12m` | vs the close ~252 trading bars back |
| `pct_off_52w_high` | `price / max(closes[-252:]) - 1` — always `<= 0` |
| `vol_60d` | stdev of the last 60 daily returns, × `sqrt(252)` |
| `above_200d_ma` | `price > mean(closes[-200:])` |
| `bars_available` | count after filtering |

**Insufficient history returns `None`, not a default.** A ticker with 53 bars
has no 12-month return and no 200-day average. Returning `0.0` or `False` there
would tell the AI something false, which is worse than telling it nothing —
`False` for `above_200d_ma` reads as "in a downtrend" when the truth is "listed
four months ago." Use the exact thresholds: `ret_1m` needs 22 bars, `ret_12m`
needs 253, `pct_off_52w_high` needs 2, `vol_60d` needs 61, `above_200d_ma`
needs 200.

Use `statistics.fmean` and `statistics.stdev` — no new dependencies. This
project runs on `requests` and `pytest` and that is worth keeping.

### 3. `compute_breadth(features) -> float | None`

Fraction of tickers where `above_200d_ma is True`, over those where it is not
`None`. `None` if the denominator is zero. (Measured 71.4% on 2026-08-29 —
a sanity check, not a test fixture.)

## Tests

Hand-built bar dicts, no network, no recorded fixtures big enough to be
unreadable. Cover:

- A known series where every number is checkable by hand.
- **`as_of` actually excludes later bars** — pass bars running past `as_of` and
  assert the answer matches the truncated series exactly. This is the test that
  protects the replay harness.
- A short-history ticker: the right fields are `None`, `bars_available` is
  correct, and nothing raises.
- A ticker at its 52-week high: `pct_off_52w_high == 0.0`, and confirm the
  value is never positive.
- `compute_breadth` on a mixed set including `None`s, and on an all-`None` set.
- `fetch_bars` chunking and pagination against a stubbed HTTP layer: 518
  tickers produces 3 chunks, and a response carrying `next_page_token` is
  followed and merged.

## Done when

`pytest` passes, and this prints a plausible table:

```bash
python -c "from src.portfolio.marketdata import *; b=fetch_bars(['AAPL','NVDA','SPY'],'2025-08-20','2026-08-28'); f=compute_features(b,'2026-08-28'); [print(v) for v in f.values()]"
```
