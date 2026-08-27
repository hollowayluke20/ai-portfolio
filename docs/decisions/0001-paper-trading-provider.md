# 0001 — Paper trading provider: Alpaca

**Date:** 2026-08-27
**Status:** Accepted

## Context

The brief requires a real paper-trading provider controllable programmatically,
not simulated trades in a CSV. It must expose: account access, order
submission, order status, positions, cash/buying power, portfolio value, and
transaction history. It must be callable from an automated job, must suit an
LLM-driven system, and **must never be able to place real-money trades**.

The binding constraint turned out not to be API quality. It is that the system
runs on **GitHub Actions** — a fresh, headless machine every run, with nothing
persisted between runs and no GUI. Any provider requiring a resident session or
a desktop gateway is unusable regardless of how good its API is.

## Decision

**Alpaca**, paper trading endpoint.

## Rationale

- **Starting equity is $100k by default**, matching the brief with no setup.
- **UK residents are eligible.** Paper trading is available regardless of tax
  residence; the UK is a supported country.
- **Authentication is two HTTP headers** — `APCA-API-KEY-ID` and
  `APCA-API-SECRET-KEY`. No OAuth flow, no refresh tokens, no session to keep
  alive. Two GitHub Actions secrets and a scheduled job can trade.
- **Stateless REST fits the runtime.** Each Actions run starts clean; a REST
  API doesn't care, a gateway-based one would be impossible.
- **The broker is the source of truth.** Every run re-reads positions and cash
  from Alpaca rather than trusting a local record, so the AI can never act on a
  stale idea of what it holds. This is a safety property, not just tidiness.
- **Orders are a single POST with a small JSON body**, so every trade can be
  validated against the guardrails before it is sent.

## How real-money trading is prevented

Structurally, not by a flag:

| | |
|---|---|
| Paper | `https://paper-api.alpaca.markets` |
| Live | `https://api.alpaca.markets` |

Different base URLs **and different API keys** — paper keys do not
authenticate against the live endpoint. No live account will be opened and no
live credentials will exist anywhere in the system. A startup assertion on the
base URL is added as a second layer, but the primary protection is that the
capability is absent.

## Alternatives considered

**Interactive Brokers — rejected.** IBKR documents that a headless session of
TWS or IB Gateway is not supported; both are Java GUI applications requiring
graphical login. Automating it means an always-on VPS running IBController
purely to hold a session open — a second machine to maintain and pay for,
against a brief whose standard is "a simple system that reliably works."
Better data and better execution modelling, but unusable from GitHub Actions.

**Tradier — runner-up, viable fallback.** Free sandbox, clean REST API
(`sandbox.tradier.com/v1`). Architecturally it would work. Loses on unclear UK
eligibility for a US brokerage, delayed sandbox data, and a smaller ecosystem
of worked examples. Worth revisiting if Alpaca ever declines the account.

**TradeStation / E*TRADE / Schwab — rejected.** US-resident brokerage accounts
plus OAuth with refresh-token management. More complexity, worse eligibility,
no compensating advantage.

**Simulated trades in a local file — rejected.** Explicitly discouraged by the
brief, and it removes every failure mode the project exists to teach.

## Consequences and limitations

- **Free market data is delayed 15 minutes and uses the IEX feed only**, not
  the consolidated tape. Prices will differ slightly from public quote sites.
  **This rules out intraday or reactive trading** — adopted deliberately as a
  design constraint, not a workaround. Decisions run on a fixed schedule.
- **Rate limit: 200 requests/minute.** Not a constraint at our volume.
- **Paper fills are unrealistically favourable** — no market impact, no
  slippage, no queue position, no check that the market could supply the order.
  Partial fills occur only ~10% of the time. Reported returns will flatter what
  live execution would produce, and the README should say so.
- **Paper accounts do not pay dividends.** This affects benchmarking: the
  portfolio must be compared against the benchmark's **price return**, not
  total return, or the comparison is not like-for-like.
- Full consolidated data costs $99/month. Needing it would be a design smell.

## Sources

- https://alpaca.markets/support/countries-alpaca-is-available
- https://docs.alpaca.markets/docs/paper-trading
- https://docs.alpaca.markets/docs/about-market-data-api
- https://docs.alpaca.markets/reference/getaccount-1
- https://interactivebrokers.github.io/tws-api/initial_setup.html
- https://docs.tradier.com/docs/getting-started
