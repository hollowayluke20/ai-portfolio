# 0003 — Investment rules and guardrails

**Date:** 2026-08-28
**Status:** Accepted

## Context

The brief (§4) requires a repeatable investment process and, as a minimum,
that **the system cannot make completely unconstrained trades**. It names the
failures to protect against: investing more money than exists, absurdly
concentrated positions, malformed orders, and trading instruments the system
does not understand.

It leaves the rules themselves open, including whether trades are AI-selected
or rule-based.

## Decision: rule-constrained, AI-reasoned

Deterministic rules define the box. The LLM exercises judgment inside it.

| Rules decide (mechanical, testable) | The AI decides (judgment, documented) |
|---|---|
| What may be traded | Which names, and why |
| How many positions, and how big | The thesis for holding them |
| Minimum cash | The risks it can identify |
| Hard sell triggers | Whether a thesis has broken |
| Whether an order is legal at all | Portfolio commentary |

This reading is drawn from the brief itself rather than invented. §5's decision
format asks for a **thesis** and **risks** — a format that only makes sense if
reasoning produced the decision, not a signal. §3's examples are all analysis
and judgment tasks. And "this is not primarily an investment competition"
means process and reliability are what is being assessed, not returns.

The two extremes both fail the brief: a pure algorithm underuses the LLM (§3),
and unconstrained AI trading breaches §4.

## The rules

| Rule | Value |
|---|---|
| **Universe** | Current S&P 500 constituents **plus a curated list of liquid US-listed ETFs** (see below). US-listed only. No leveraged or inverse ETFs, no OTC, no options, no crypto |
| **Target positions** | 15 (minimum 8, maximum 20) |
| **Sizing** | Equal weight, ~6.3% of portfolio each. The AI does not choose position size |
| **Hard position cap** | 10% of portfolio at entry (backstop; should never bind under equal weighting) |
| **Cash floor** | 5% minimum, enforced at order time — an order that would breach it is rejected |
| **Cash ceiling** | 15%; above this the next cycle must deploy |
| **Decision cadence** | Weekly. Portfolio state and dashboard refreshed daily |
| **Sell — stop loss** | Hard exit at −20% from entry price |
| **Sell — concentration trim** | Position above 12% of portfolio is trimmed back to ~6.3% |
| **Sell — thesis change** | The AI may sell at a decision cycle with written reasoning |
| **Broad-US-equity cap** | SPY, VOO and QQQ **combined** may not exceed 40% of the portfolio |

### The AI sees the entire universe

**Amended 2026-08-29.** Candidate selection previously showed ~30 tickers a
week: the ETF sleeve, held names, and a rotating 15-name slice of the S&P 500.

That rested on an assumption nobody checked — that 518 tickers was too many to
put in front of the model. The whole index with company names and sectors is
about **4,800 tokens, or 0.48% of the context window**.

The rotation was not merely unnecessary, it was harmful: the slice advanced
**alphabetically**, so in a given week the AI could consider Allegion and
A.O. Smith but not Microsoft, and it took 34 weeks to see the index once. The
portfolio's contents were being decided by which letters came up.

The effect was visible immediately. The last rotating cycle proposed
`NVDA AMZN AMAT AMGN AMP AMT AON` alongside eight ETFs. With the whole universe
visible the same machinery proposed `AAPL MSFT NVDA AMZN GOOGL JPM LLY XOM PG`
across six ETFs — a genuinely diversified book rather than an accident of
the alphabet.

### The ETF sleeve

The universe includes a short, fixed list of liquid US-listed ETFs so the AI
can take positions in asset classes and regions, not only individual US large
caps:

| Exposure | Tickers |
|---|---|
| US broad market | SPY, VOO |
| US growth / tech | QQQ |
| International developed | VEA, EFA |
| Emerging markets | VWO, EEM |
| Government / aggregate bonds | IEF, AGG, TLT |
| Gold | GLD |
| Real estate | VNQ, REET |
| Broad commodities | DBC, USO |

The same rules apply to ETFs and single stocks alike — one universe, one
ruleset. An ETF position is sized, stopped and trimmed exactly like a stock.

**Why widen it at all.** With a universe of S&P 500 stocks benchmarked against
the S&P 500, the only thing the system can ever demonstrate is stock selection
inside a single index. Widening it gives the AI genuinely different kinds of
decision to make — the case for emerging markets at a given valuation is a
different sort of reasoning from the case for a single company — which is what
§3 is asking for when it says the LLM should be used meaningfully.

### The overlap problem, and why the cap is a stopgap

Position count measures **tickers, not exposures**. SPY + QQQ + MSFT + NVDA
reads as four diversified positions and is substantially one bet on US mega-cap
technology. Nothing in the position-count or per-position-weight rules catches
this.

The 40% combined cap on SPY/VOO/QQQ is a **crude mechanical stopgap**, not a
solution. Alongside it, the AI is required to state, in any thesis for opening a
position, **what existing exposure the new position overlaps with**. That is a
prompt-level requirement, not a validation check.

**Deferred to a later ADR: proper diversification mathematics.** Measuring
correlation between holdings and constraining the portfolio on that basis is
the real answer, and it is deliberately not being built yet — it belongs after
the pipeline exists to feed it, not before. Recorded here so the stopgap is not
mistaken for the intended design.

### Available cash is not the same as cash

Discovered by testing on 2026-08-28, before any of this was implemented.

Two manual orders were placed while the market was closed. Alpaca's response:

```
cash                         100000      unchanged
buying_power                 399975      dropped by exactly the order value
non_marginable_buying_power  99987.50
```

**`cash` does not move for a pending order. `buying_power` does.**

The original rule — *size from `cash`, never `buying_power`* — protects against
4x margin but has a hole: `cash` is blind to money already committed. A second
run before the first order fills would read the full cash balance, conclude it
was all available, and commit it again. Every individual check would pass while
the position was ordered twice.

The rule is therefore:

```
available_cash = cash - (total notional of pending BUY orders)
```

Still never `buying_power`. But `cash` alone is not enough either. **All sizing
and the 5% cash floor are computed against `available_cash`.**

### Told is not enforced — the gap found on 2026-08-29

Simulating a year exposed that **four configured rules were never enforced in
code**: the stop loss, both halves of the concentration trim, the broad-US-
equity cap and the cash ceiling. Each appears in `config/rules.json`, in this
ADR and in the README, and each was injected into the AI's prompt — so the
model was told, and nothing checked.

That is exactly the distinction this project settled deliberately: an LLM told
a rule can still break it, so every rule is **told and enforced**. Four of them
were told only. In the crash simulation a portfolio fell 28.6% with individual
holdings well past —20% and **no stop ever fired**, because no code existed to
fire one.

The cause was a specification gap rather than an implementation error. The
Phase 2 tasks defined validation of *proposals the AI makes*; nothing was ever
assigned to **generate mechanical decisions from the portfolio's own state**.

### Mechanical triggers run before the AI

Stop losses and trims are not the AI's to propose. They are computed from state
by deterministic code, prepended to the decision list, and the AI is told which
positions are already being exited so it does not fight them.

| Trigger | Condition | Action |
|---|---|---|
| `stop_loss` | `unrealized_pl_pct` at or below `stop_loss_pct` | SELL the whole position |
| `concentration_trim` | `weight` above `concentration_trim_threshold` | TRIM back to `concentration_trim_target` |

**A stop loss is never blocked.** Not by the universe, not by the minimum
position count, not by anything. A safety exit gated by a diversification rule
is not a safety exit.

### The broad-US-equity cap is a validation check

SPY, VOO and QQQ combined may not exceed `broad_us_equity_cap.limit`. This
gates **buys** only, like the universe check — an existing overweight position
must remain sellable.

### The cash floor drifts, and that is not a breach

The floor is a percentage of total value, so a **rising market can push cash
below it with no trade at all**: the cash did not move, the target did. Found
in the meltup simulation, where cash fell under the floor on a day nothing was
bought.

This is not a violation. The rule is that **an order which would breach the
floor is rejected**, not that cash must always sit above it. The practical
consequence, undocumented until now: when cash drifts below the floor the
system cannot buy until something is sold. It is not stuck — trims and stops
free cash — but it will hold rather than deploy, and that is intended.

The cash **ceiling** is guidance to the AI plus a health warning, not a
rejection. There is no sensible order to refuse for holding too much cash.

### The triggers run daily; the AI runs weekly

**Amended 2026-08-29.** Both were originally on the weekly cycle, which made
the stop far weaker than this ADR claims. "Hard exit at —20%" was in practice
"hard exit at —20%, checked once a week" — a holding could fall 35% on a Tuesday
and sit until Friday evening.

They are different kinds of work and belong on different clocks:

| | Cadence | Why |
|---|---|---|
| Stop loss, concentration trim | **Daily** | Pure arithmetic on data already fetched. No AI call, no cost, no judgement. A safety rail checked weekly is barely a rail |
| AI decisions: what to buy, thesis review | **Weekly** | Judgement does not improve by exercising it more often against a 15-minute-delayed feed, and 250 entries a year mostly reading "hold, thesis intact" makes the decision history less readable, not more |

Triggers run from `scripts/run_triggers.py` on the daily workflow, deliberately
**not** from `update_state.py` — that script is read-only and safe to run at any
time, and quietly giving it the ability to place orders would be a trap.

A triggered sell is written to `data/decisions/<date>-triggers.json`, so a stop
that fires appears in the permanent record rather than only in a workflow log,
and is distinguishable from a weekly AI cycle when read back.

### Why a concentration trim rather than a take-profit

Selling a position *because it rose* systematically removes the best holdings.
The instinct behind "sell when it gets too big" is really about concentration,
so the rule expresses that directly: trim an oversized position back to target
weight and let winners keep running. This also answers §4's "absurdly
concentrated positions" guardrail directly.

### Why three sell paths

If every sell were mechanical the LLM would only ever be a buying assistant,
which weakens §3. Two mechanical guardrails plus one reasoned exit keeps the AI
genuinely involved in the whole decision, while ensuring a broken or absent AI
response can still never prevent a stop-loss from firing.

### Why a 5% cash floor

Operational, not a market view. At full investment the system cannot buy
without selling first, and orders fail on ordinary rounding when a price ticks
between calculation and submission. 5% is slack that keeps the system working
on a bad Tuesday.

## Order mechanics

- **Notional orders** (dollar amounts, e.g. "$6,300 of MSFT") rather than share
  counts. Alpaca supports fractional shares; this removes rounding error and
  the cash-floor breaches it causes.
- **Market orders, day time-in-force, regular hours only.** No extended-hours
  trading — free market data is 15 minutes delayed (ADR 0001), so the system is
  in no position to trade thin sessions.

## Validation — every order, before submission

An order is submitted only if all of these pass:

1. Ticker is in the universe list
2. Ticker is tradeable per Alpaca's `/v2/assets`
3. Resulting position weight is at or under 10%
4. Resulting cash is at or above the 5% floor, computed from **`cash`, never
   `buying_power`** — Alpaca grants 4x margin by default, and sizing from
   buying power would allow a $400k portfolio on $100k while staying inside the
   API's own limits
5. Resulting position count is within 8–20
6. Notional value is positive and above Alpaca's minimum

**Any failure means no trade, logged with the reason.** A rejected order is a
recorded event, never a retried-with-different-numbers event.

If the AI returns malformed output, or output failing schema validation, the
cycle makes **no trades at all** and logs the failure. The system's default
behaviour under uncertainty is to do nothing.

## Consequences

- Returns will be unremarkable, by design. Equal-weighted S&P 500 names with a
  20% stop is a deliberately boring strategy, which is the point.
- The AI cannot express conviction through size. If that becomes limiting it is
  a future ADR, not a silent change.
- A −20% stop on a single stock is loose enough to survive normal volatility
  and will rarely fire; it is a catastrophe guard, not a trading rule.
- Weekly decisions mean roughly 50 decision cycles a year — enough history for
  the dashboard to be interesting, few enough that each can be reasoned about
  properly.

---

## Amendments

**2026-08-28** — Universe widened from S&P 500 constituents only to include a
curated ETF list; added the 40% combined broad-US-equity cap and the
overlap-disclosure requirement in theses. Prompted by Luke's observation that a
portfolio drawn from the S&P and benchmarked against the S&P leaves the system
playing an artificially narrow game. Correlation-based diversification
constraints deferred to a later ADR.

**2026-08-28 (second amendment)** — Position sizing and the cash floor now use
`available_cash` (cash net of pending buy orders) rather than `cash`. Found by
placing two orders outside market hours and observing that `cash` did not move.

**2026-08-29 (third amendment)** — Mechanical stop-loss and concentration-trim
triggers specified, the broad-US-equity cap made a validation check, and the
cash floor's drift documented as intended behaviour rather than a breach. All
found by simulating a year of trading before going live.
