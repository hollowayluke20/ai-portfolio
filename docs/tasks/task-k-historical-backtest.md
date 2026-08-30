# Task K — historical backtest: run the real bot through Jan–Mar 2026

## Why

We cannot answer the question that matters: **will the AI ever decide a
position has gone bad and sell it?** The live portfolio is two days old and
holds nothing but dust. The existing simulation (`sim/`) uses synthetic random
prices and a stubbed AI, so it proves the plumbing and nothing about judgement.

This task replays **real historical prices** through the **real Gemini prompt**
and records what it actually does.

## Window: 2026-01-02 → 2026-03-31

Not January–February. Evidence gathered 2026-08-30:

| Fact | Value |
|---|---|
| SPY worst peak-to-trough (15 months) | **−8.88%**, 2026-01-27 → 2026-03-30 |
| SPY return over Jan–Feb only | +0.04% — nothing happens |
| Names falling past the −20% stop, Jan–Mar | **189 of 516** |
| Worst names | RDDT −53%, HOOD −47%, TTD −47%, APP −45%, COIN −45% |

Stopping at February ends the test one month before the drawdown bottoms.
Jan–Mar is ~62 sessions and ~13 Friday cycles.

## What this test CAN and CANNOT establish

**Can:** whether the AI ever sells a full-weight position and on what basis;
whether the −20% stop and 12% trim fire on real price paths; whether the book
churns or freezes; whether invariants hold over 62 real sessions; whether the
executor survives repeated multi-order cycles.

**Cannot: the return number is not evidence of skill.** Gemini's training data
covers this window — it knows what happened. Report the return, label it
contaminated, and never present it as a backtest result. The behavioural
findings are the deliverable.

## Data integrity — non-negotiable

**Use `c` (close) or `o` (open) only. Never `h`/`l`.** The feed contains bad
prints. Confirmed example:

```
SPY 2026-02-02   o=685.90  h=693.21  l=68.64  c=691.70   vol=79,286,521
```

A low of $68.64 against a $691 close — a decimal slip on 79M shares. Anything
reading `low` sees a 90% crash and fires every stop in the book.

Add a sanity filter when loading bars: reject any bar where
`c <= 0` or `c` moves more than 50% from the prior close, and log what was
dropped. Do not silently skip.

## Build

The seams already exist. `sim/run.py` runs weekly cycles on Fridays, daily
triggers, and invariant checks. Three pieces are new.

**1. `sim/historical.py` — `HistoricalMarket`**

Same interface as `sim/market.py`: `advance()`, `price(ticker)`,
`is_delisted(ticker)`, `today()`. Backed by bars from
`marketdata.fetch_bars`, fetched once and held in memory.

- `price(t)` returns the close for the current session, `None` if the ticker
  has no bar that day (which `FakeBroker` already treats as unavailable).
- `is_delisted(t)` — true once a ticker stops producing bars before the window
  ends.
- Sessions come from the actual bar dates, so the calendar is real: no
  weekend or holiday handling needed.

**2. Real AI instead of the stub**

Replace `sim.ai_stub.propose` with `src.portfolio.ai.decide`. Features must be
computed **point-in-time**:

```python
features = compute_features(bars, as_of=day.isoformat())
```

`compute_features` already filters `r["t"][:10] <= as_of`, so there is no data
lookahead by construction. Do not change that filter.

**3. `scripts/backtest.py`**

Drives the window, writes one decision record per cycle to
`data/backtests/<run>/decisions/`, a history row per session, and a summary.

Must not write to `data/state.json`, `data/history.json`, or
`data/decisions/`. The backtest is not the live portfolio.

## Report at the end

```
sessions, cycles run
orders submitted / filled / rejected (with reasons)
stop_loss fires        — ticker, date, entry, exit
concentration trims    — ticker, date
discretionary SELLs    — ticker, date, basis, reason_for_action
positions never touched after purchase
turnover: % of book changed per month
invariant violations   — must be zero
final value vs SPY     — LABELLED CONTAMINATED
```

The single most important line: **discretionary SELLs**. If that list is empty
across 13 cycles while 189 names fell past −20%, the AI does not sell on
judgement and the mechanical stop is the only real risk control. That is a
finding worth having before Friday.

## Cost

~13 Gemini calls. Daily trigger checks are free arithmetic. Bars are one fetch.
