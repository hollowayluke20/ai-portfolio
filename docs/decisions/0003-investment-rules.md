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
| **Universe** | Current S&P 500 constituents. US-listed only. No leveraged or inverse ETFs, no OTC, no options, no crypto |
| **Target positions** | 15 (minimum 8, maximum 20) |
| **Sizing** | Equal weight, ~6.3% of portfolio each. The AI does not choose position size |
| **Hard position cap** | 10% of portfolio at entry (backstop; should never bind under equal weighting) |
| **Cash floor** | 5% minimum, enforced at order time — an order that would breach it is rejected |
| **Cash ceiling** | 15%; above this the next cycle must deploy |
| **Decision cadence** | Weekly. Portfolio state and dashboard refreshed daily |
| **Sell — stop loss** | Hard exit at −20% from entry price |
| **Sell — concentration trim** | Position above 12% of portfolio is trimmed back to ~6.3% |
| **Sell — thesis change** | The AI may sell at a decision cycle with written reasoning |

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
