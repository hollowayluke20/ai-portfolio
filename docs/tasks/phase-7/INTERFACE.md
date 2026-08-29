# Phase 7 — market data ("the eyes"): interface

**Neither agent edits this file.**

Task L builds the **data layer**: fetch bars, compute features. Task M builds
the **prompt integration**: universe metadata, rendering, the new decision
field. They meet here.

## The point

Until now the AI has been trading blind. `render_prompt` fills `{CANDIDATES}`
with `", ".join(candidates)` — 518 bare ticker symbols, no price, no return, no
name, no sector, nothing. Every stock pick has therefore come from the model's
pre-training memory of what a company was like before its cutoff, not from
anything true about the market today.

This phase gives it the market. It does not make it cleverer; it makes it
informed. Those are different jobs and this is the first one.

## Verified facts this design rests on

Probed live against the paper account on 2026-08-29:

- `GET https://data.alpaca.markets/v2/stocks/bars` accepts **200 symbols per
  request** via `symbols=A,B,C`, returns `{"bars": {"AAPL": [...], ...}}`.
- A full year of daily bars for all **518 tickers** took **16 requests and
  15.8 seconds**, **0 missing symbols**, 133,192 bars.
- `next_page_token` **is** returned at this size and must be followed.
- `adjustment=all` gives split- and dividend-adjusted closes. Use it. Without
  it a 2-for-1 split reads as a −50% return and the stop loss fires on nothing.
- Some tickers return far fewer bars than the rest (min observed: 53) because
  they listed recently. Features that need more history than exists must be
  `None`, never zero and never a silent default.

## What Alpaca does not have

**No fundamentals.** No P/E, no earnings, no market cap, no revenue. It is a
price API. Nothing in this phase is a valuation measure — `pct_off_52w_high`
is a *price* anchor, not a cheapness one. Do not describe it as valuation in
the prompt or the AI will treat it as one.

A news endpoint exists and works on this plan. It is **out of scope here**.

## The data contract

Task L produces this; Task M consumes it and touches nothing else.

```python
# src/portfolio/marketdata.py
#
# Named marketdata.py, NOT market.py — sim/market.py already exists and is the
# fake market. Two files called market.py in one project is a trap.

@dataclass(frozen=True)
class TickerFeatures:
    ticker: str
    price: float                    # adjusted close as of `as_of`
    ret_1m: float | None            # decimal fraction: 0.032 == +3.2%
    ret_12m: float | None
    pct_off_52w_high: float | None  # <= 0.0; -0.041 == 4.1% below the high
    vol_60d: float | None           # annualised stdev of daily returns
    above_200d_ma: bool | None
    bars_available: int             # so a caller can see why a field is None
```

```python
def fetch_bars(
    tickers: list[str], start: str, end: str
) -> dict[str, list[dict]]:
    """Adjusted daily bars. Chunks at 200 symbols, follows next_page_token.
    Does IO. No computation."""

def compute_features(
    bars: dict[str, list[dict]], as_of: str
) -> dict[str, TickerFeatures]:
    """Pure. No network, no clock, no file access.

    MUST ignore every bar dated after `as_of`. This is the whole reason the
    parameter exists — it is what lets the replay harness wind this layer back
    to any past date without a rewrite. A version that reads "today" from the
    system clock is wrong even when it produces the same answer today."""

def compute_breadth(features: dict[str, TickerFeatures]) -> float | None:
    """Fraction of tickers with above_200d_ma is True, over those where it is
    not None. Returns None if nothing qualifies."""
```

Weights and returns are decimal fractions throughout, per ADR 0004. `0.032`
means +3.2%. This is the same convention the rules and the validator already
use and it must not vary here.

## Boundaries

- **Task L** owns `src/portfolio/marketdata.py` and its tests. It does not
  import `ai.py`, does not read `prompt.md`, does not know a prompt exists.
- **Task M** owns `config/prompt.md`, `src/portfolio/ai.py`,
  `scripts/refresh_universe.py`, `config/universe.json`. It calls Task L's
  three functions and does not reimplement any of them.
- **Neither** touches `validator.py`, `executor.py`, `triggers.py` or
  `rules.json`. The guardrails are not part of this change. A phase that gives
  the AI new information must not also alter what it is allowed to do — if
  behaviour changes, we need to know which of the two caused it.
