# Phase 1 — the read-only spine

Prove the system can see reality before it is allowed to change anything.
**Nothing in Phase 1 can place an order.** If a task appears to require one,
the task has been misread.

Two halves, built in parallel by two agents, meeting at `INTERFACE.md`:

| | Task A | Task B |
|---|---|---|
| Builds | the broker layer | the state layer |
| Talks to | Alpaca, the constituents CSV | nothing |
| Owns | `alpaca.py`, `config.py`, `config/`, `refresh_universe.py` | `state.py`, `storage.py` |
| Provable without the other? | yes | yes |

Neither agent commits. Integration — wiring the halves into a runnable
entrypoint, plus the scheduled workflow — happens once both land and both test
suites pass.
