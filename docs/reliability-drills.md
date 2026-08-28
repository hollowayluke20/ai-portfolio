# Reliability drills

Deliberate attempts to break the system, with what actually happened. The
brief (§11) asks what happens when things fail; these are the answers, tested
rather than assumed.

Re-run these after any change to the broker or storage layers.

## Phase 1 — 2026-08-28

| # | Drill | Expected | Actual | Pass |
|---|---|---|---|---|
| 1 | Wrong API secret | Fail loud, no retry, leave state intact | `401 (not retryable)`, exit 1, `state.json` byte-identical | yes |
| 2 | `APCA_API_BASE_URL` set to the **live** host | Refuse to run at all | Import-time `BrokerError`, exit 1, nothing written | yes |
| 3 | Unreachable host | Retry, then fail cleanly | Retried 3x with backoff, then `BrokerError` | yes |
| 4 | Run twice in one day | One history row, not two | 2 rows before, 2 rows after | yes |
| 5 | Corrupt `history.json` | Fail loud, do not overwrite | `JSONDecodeError`, exit 1, corrupt file left in place | yes |
| 6 | Corrupt `state.json` | Recover | Rebuilt from Alpaca, exit 0 | yes |

### The asymmetry in 5 and 6 is deliberate

`state.json` is rebuilt from the broker on every run, so it is disposable — a
corrupt one is simply replaced. `history.json` cannot be reconstructed: Alpaca
will not sell back past portfolio values, so a day not recorded is lost
permanently. The system therefore **refuses to touch a corrupt history file**
rather than risk replacing years of data with a fresh empty one.

Getting this backwards would be the worst kind of bug: silent, and only
discovered when the performance chart is needed.

### Why no retry on 4xx matters

Drill 1 returned `401 (not retryable)` in under a second. A naive retry policy
would have burned three attempts and ~4 seconds of backoff on a credential
that will never start working. This is also what an expired key looks like,
which the brief asks about directly.

## Not yet drilled

- **Market data API returns malformed data** (as opposed to failing) — needs a
  stub server
- **AI returns invalid output** — Phase 2, but the design decision is already
  made: no trades at all, logged
- **Insufficient cash for a trade** — Phase 2, once orders can be placed
- **A GitHub Actions run fails** — observed indirectly; worth forcing once
- **Dashboard cannot fetch fresh data** — Phase 2, once a dashboard exists

## Provider findings worth recording

**Gemini model names are not stable.** `gemini-2.5-flash` appeared in the
account's own model listing but returned `404 NOT_FOUND - no longer available
to new users` when called. The listing is not a reliable guide to what can
actually be invoked, so the model name is pinned in config and a 404 must fail
loudly rather than silently falling back.

**GitHub Models was retired on 2026-07-30**, having been a candidate provider
days earlier. Free tiers are withdrawn with little notice, which is why the LLM
call is isolated behind one narrow interface.
