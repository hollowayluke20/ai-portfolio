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

## Dashboard — 2026-08-29

The dashboard had only ever been rendered against one state: today's nearly
empty portfolio. Every other state it will reach was untested until the day it
happened live. `scripts/dashboard_scenarios.py` builds those states now and
serves the real page against them, so this is repeatable rather than a one-off.

```
python scripts/dashboard_scenarios.py --list
python scripts/dashboard_scenarios.py hostile --serve 8100
```

| # | Drill | Expected | Actual | Pass |
|---|---|---|---|---|
| 7 | `generated_at` backdated 48h | Loud staleness banner | Full-width banner, plus health warnings surfaced above the fold | yes |
| 8 | `state.json` removed | Name the file, render nothing partial | "Data unavailable — data/state.json HTTP 404" | yes |
| 9 | `decisions/latest.json` 404 | Treated as normal | "No decision cycle has run yet — the expected state, not an error" | yes |
| 10 | Mature book: 6 positions, 53 history rows, live decision record | Chart, ranges, commentary, blocked trades | All render; 3M/1Y/5Y correctly disabled for 75 days of data | yes |
| 11 | **Hostile input** — `<script>`, `<img onerror>` and anchors in AI-authored fields | Escaped as text | 0 script tags, 0 img tags, 0 rich tags injected; markup visible as literal text | yes |
| 12 | Overlong company name and thesis | Truncate, stay readable | `text-overflow: ellipsis`, layout holds | yes |
| 13 | `history.json` with **zero rows** | No division by zero | No `NaN`, no `undefined`, no `Infinity`; holdings still render | yes |
| 14 | Sub-cent position, and one at 88% weight | Render honestly | Both render; the oversized bar reads as wrong, which is correct | yes |

### The failure this page could not report about itself

Drill 11 was run while the test server was restarting, and the page rendered
**section headings above nothing, in silence.** The fetch error handling is
thorough — network, HTTP and parse failures throw distinctly and `fatal()`
draws a panel — but none of it ran, because **`assets/dashboard.js` itself had
failed to load.** No error handling inside a file that never loaded can report
that the file never loaded.

An empty ledger reads as a portfolio holding nothing, not as a broken page.

**Fix:** `index.html` now ships a boot notice that `dashboard.js` removes as its
first action, plus a `<noscript>` block. If the script does not load, the
message stays and says so. Verified: present in the served HTML, and gone once
the script runs.

**Why hostile input matters here.** The `thesis`, `risks`, `business`,
`commentary` and `rejection_reason` fields are **written by an LLM** and
injected into the page. A hallucinated tag, or a prompt-injection reaching the
model through news text, would otherwise execute in the browser of anyone
reading the dashboard. Every one of those fields is escaped, and drill 11 now
proves it rather than assuming it.

## Broker smoke test — repeatable, any time

`scripts/submit_notional_order` and `close_position` cannot be unit-tested:
mocking them only proves the mock works. Until 2026-08-29 the only evidence
they worked was that someone had run them once by hand — and when they finally
ran for real, they failed twice.

`scripts/smoke_test_broker.py` exercises the whole broker layer against the
real API. **Manual only, never in a workflow.**

```
python scripts/smoke_test_broker.py
```

| Check |
|---|
| Order accepted |
| Order fills and becomes a position |
| Quantity is fractional |
| Company name resolves |
| Market value matches the amount ordered |
| Cash falls by the amount ordered |
| `build_state` handles a live position |
| Weights plus cash sum to 1.0 |
| Totals reconcile |
| The probe cannot stamp inception (it has no thesis) |
| Position closes and is gone |
| Cash returns to where it started |

**Crypto is the instrument, not a holding.** It trades 24/7, so this runs on a
Saturday with the equity market shut, and ADR 0003 excludes crypto from the
investable universe. The close runs in a `finally` block, so a failed check
still cleans up — a leftover position would appear on the public dashboard and
in Friday's email as a real holding. The script also refuses to start if a
probe position already exists, rather than adding to one it did not create.

Expect roughly 15—20p of drift on a $25 round trip. That is the bid-ask
spread, and it is real.

### What this cannot test

Crypto fills in seconds; equities queue and fill at the next open, which is
what the whole Friday-decide/Monday-fill design rests on. Crypto also requires
`time_in_force: gtc` where equities use `day`, so the parameter exercised here
is not the one production uses. And because crypto is outside the universe, the
validator rejects it — this calls the broker functions directly, bypassing the
guardrails.

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
