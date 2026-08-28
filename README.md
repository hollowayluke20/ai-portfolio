# AI Investment Portfolio System

An AI-assisted investment portfolio that runs unattended. A $100,000 paper
account at a real broker, decisions made weekly by an LLM working inside
hard-coded guardrails, every decision recorded with its reasoning, and the
whole thing driven by scheduled jobs on GitHub's servers rather than a laptop.

Built to a brief set by Alex, starting 2026-08-27.

**Status:** the pipeline runs end to end in dry-run mode. Dashboard and email
reporting are not yet built — see [What is not done yet](#what-is-not-done-yet).

---

## The chain

```
Alpaca (paper broker)
     |  read account, positions, open orders, prices
     v
GitHub Actions  (scheduled, ephemeral — no laptop involved)
     |
     +-- daily 16:25 New York --> build state --> commit to repo
     |
     +-- weekly               --> candidates --> LLM --> validate --> execute
                                                    |
                                                    v
                                          decision record committed
```

Everything downstream reads from the repo. Nothing reads the broker directly
except the pipeline.

## How the AI talks to the broker

It doesn't. That separation is deliberate.

1. The pipeline reads the portfolio from Alpaca and builds a **state document**
2. The LLM receives that document, the rules, its own previous theses, and a
   candidate list — and returns **proposals**, as schema-validated JSON
3. A **validator** checks every proposal against the rules
4. Only proposals that survive reach an **executor**, which submits orders

The model never sees a credential and never issues an instruction to Alpaca. It
produces text; deterministic code decides whether any of it becomes an order.

## The paper trading provider

**Alpaca**, paper endpoint. Full reasoning in
[ADR 0001](docs/decisions/0001-paper-trading-provider.md).

**Why:** a paper account opens with $100,000 by default, UK residents are
eligible, and authentication is two HTTP headers — no OAuth flow, no refresh
tokens, no session to maintain. That last point decided it. The system runs on
GitHub Actions, which gives a **fresh, headless machine every run with nothing
persisted**, so any provider requiring a resident session or a desktop gateway
is unusable regardless of how good its API is.

**How the system communicates with it:** raw HTTP from
[src/portfolio/alpaca.py](src/portfolio/alpaca.py) — no SDK, so every request
sent to the broker is written in this repository in plain sight.

**Why it suits an LLM system:** stateless REST means each scheduled run starts
clean. The broker is the **source of truth** — every run re-reads positions and
cash rather than trusting a local record, so the AI can never act on a stale
idea of what it holds. And an order is a single POST with a small JSON body,
which means every proposed trade can be validated *before* it is sent.

**Alternatives considered:** Interactive Brokers was rejected outright — IBKR
documents that headless operation of TWS or IB Gateway is unsupported, so
automating it means an always-on VPS purely to hold a login session open.
Tradier was the runner-up and remains a viable fallback; it lost on unclear UK
eligibility and a smaller ecosystem of worked examples. TradeStation, E-TRADE
and Schwab all require US-resident accounts plus OAuth refresh management.

**Limitations:**

- Free market data is **delayed 15 minutes** and uses the IEX feed only, not
  the consolidated tape. This rules out intraday or reactive trading — adopted
  as a deliberate design constraint rather than worked around.
- **Paper fills are unrealistically favourable**: no market impact, no
  slippage, no queue position. Reported returns will flatter what live
  execution would produce.
- **Paper accounts pay no dividends**, so the portfolio is compared against the
  benchmark's price return, not total return.
- Alpaca grants **4x margin by default**. The system never uses it — sizing
  reads available cash, never buying power. This is enforced in code.

## Never real money

Structural, not a configuration flag:

| | |
|---|---|
| Paper | `https://paper-api.alpaca.markets` |
| Live | `https://api.alpaca.markets` |

Different base URLs **and different API keys** — paper keys do not authenticate
against the live endpoint. No live account exists and no live credentials exist
anywhere in this system. `alpaca.py` additionally **refuses to import** if
pointed at the live host.

## The investment process

Full rules in [ADR 0003](docs/decisions/0003-investment-rules.md), and as
machine-readable data in [config/rules.json](config/rules.json) — one file read
by both the validator that enforces the rules and the prompt that tells the AI
about them, so the two cannot drift apart.

| | |
|---|---|
| Universe | S&P 500 constituents plus a curated ETF sleeve (regions, bonds, gold, real estate, commodities) |
| Positions | 15 target, 8 minimum, 20 maximum |
| Sizing | Equal weight, ~6.3% each. The AI does not choose position size |
| Cash | 5% floor, 15% ceiling |
| Cadence | Decisions weekly; state refreshed daily |
| Sell triggers | −20% stop, trim above 12%, or the AI closing a broken thesis |

**Rules constrain, the AI reasons.** The model chooses which names and writes
the thesis; it cannot choose to spend money that does not exist. Every order
passes eight static checks plus a cash check evaluated at the moment it runs.

**Malformed AI output produces no trades at all**, logged. There is no
best-guess path.

## Repository layout

```
config/          rules, investable universe, the prompt template
data/            state.json, history.json, decisions/  (written by the system)
docs/decisions/  architecture decision records, with reasoning
docs/tasks/      the specs each build phase was written against
src/portfolio/   alpaca, state, storage, ai, candidates, validator, executor
scripts/         update_state, run_cycle, refresh_universe
.github/         scheduled workflows
```

## Setup

```
git clone https://github.com/hollowayluke20/ai-portfolio
cd ai-portfolio
pip install -r requirements.txt
cp .env.example .env
```

Then add your own Alpaca **paper** keys and a Gemini key to `.env`. Paper keys
start with `PK`; if yours starts with `AK` it is a live key, so regenerate it.
Nothing in `.env` is ever committed.

```
python scripts/refresh_universe.py   # build config/universe.json
python scripts/update_state.py       # read the portfolio, write state
python scripts/run_cycle.py          # a full decision cycle, DRY RUN
python scripts/run_cycle.py --live   # the same, actually submitting orders
```

`run_cycle.py` is **dry by default**. It must be given `--live` explicitly
before anything is submitted.

For automation the same credentials go in GitHub Actions secrets. The base URL
is stored as a public **variable** rather than a secret, deliberately, so that
anyone auditing this repository can confirm for themselves that it points at
paper.

## Reliability

Failure cases are tested rather than assumed —
[docs/reliability-drills.md](docs/reliability-drills.md) records six deliberate
attempts to break the system and what each one actually did.

The principle throughout: **stale-but-correct beats fresh-but-broken.**
`state.json` is assembled and validated fully in memory, then written to a temp
file and atomically renamed, so a failed run leaves the previous good copy
untouched. `history.json` is treated differently — it cannot be reconstructed,
so a corrupt one causes a loud failure rather than being silently overwritten.

## What broke

[docs/what-broke.md](docs/what-broke.md) — a running log written as things
happened rather than reconstructed afterwards. Includes a misdiagnosis that
cost two rounds of debugging, an orchestration tool adopted and dropped in a
day, and the four defects found integrating Phase 2, three of which were errors
in the specification rather than in the code.

## What is not done yet

- **Live dashboard** — the state layer already commits fresh data on a
  schedule, so the mechanism exists; the page does not
- **Automated email reports**
- **Weekly decision workflow** — the code runs, the cron is not yet wired
- **Inception baseline** — stamped at the first live trade, which has not
  happened
- **No live trade has been placed.** Every link in the chain is proven except
  the one where money actually moves

## Decisions

| ADR | |
|---|---|
| [0001](docs/decisions/0001-paper-trading-provider.md) | Paper trading provider: Alpaca |
| [0002](docs/decisions/0002-portfolio-state-storage.md) | Portfolio state lives in the repo |
| [0003](docs/decisions/0003-investment-rules.md) | Investment rules and guardrails |
| [0004](docs/decisions/0004-data-contract.md) | The data contract |
