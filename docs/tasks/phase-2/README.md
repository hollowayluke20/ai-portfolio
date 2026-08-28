# Phase 2 — the decision engine

Where the system stops observing and starts acting. **The first code that can
spend money.**

| | Task D | Task E |
|---|---|---|
| Builds | the decision engine | the validator and executor |
| Owns | `ai.py`, `candidates.py`, `config/prompt.md` | `validator.py`, `executor.py`, `decisions.py` |
| Can place an order? | never | yes — and only via `dry_run=False` |

Neither agent commits. Integration — the cycle entrypoint and the Friday
workflow — happens once both land and both test suites pass.

**The first live cycle runs in dry-run mode.** A real decision file gets
written from real data and a real AI call, with nothing submitted, so it can be
read by a human before any money moves.
