# What broke, and how it was fixed

A running log, written as things happen rather than reconstructed afterwards.
Entries are kept even when the fix was trivial — the pattern of failures is
more useful than any single one.

---

## 2026-08-27 — A working Claude Code did not mean a working `claude` command

**Symptom.** Agents launched by a wrapper tool reported "Login expired · Please
run /login", while Claude Code was demonstrably working in another window.

**What we assumed.** That the wrapper was spawning processes with a mangled
environment, so the CLI could not find its credentials. Two rounds of
theorising went into this, including a planned fix using the wrapper's
environment-override settings.

**What was actually true.** `~/.claude/.credentials.json` contained empty
access and refresh tokens, and the refresh token had expired **18 days
earlier**. The CLI was simply logged out. The desktop app authenticates through
a different path, so one had been working and the other dead for over a
fortnight with no visible symptom.

**Fix.** Sign in again.

**Lesson, which is the point of this entry.** *The error message was accurate
the entire time.* It said "login expired" and it meant "login expired". Before
theorising about why an error is misleading, check whether it is simply true.
This applies directly to the automation: a GitHub Actions log at 7am says what
it says.

---

## 2026-08-27 — Multi-agent orchestration tool adopted and dropped the same day

**What happened.** A GUI orchestration tool was installed to run Claude Code
and Codex together. It worked, and was dropped within hours.

**Why it was dropped.** It created a cloud account on first launch without
asking, and auto-imported a skill unprompted. It wrapped every message in a
large injected protocol, so a bare "hello" cost roughly four minutes of agent
reasoning and produced a reply about the protocol rather than a greeting. And
its UI displayed "Thinking..." for minutes *after* the agent had finished and
replied — the status display was simply wrong.

**Fix.** Two agents in split terminals in VS Code. The coordination the tool
provided (agents messaging each other) solved a problem we had already designed
away by coordinating through a data contract instead.

**Cost.** Half a day. **Kept from it**: the contract-first split, which then
worked first time on real work.

---

## 2026-08-28 — Phase 1 integration: five defects, all at the boundaries

Two agents built the broker layer and state layer in parallel against a written
interface. **The halves integrated with no change to either side.** Every defect
found in review was at a seam, not inside a component.

### 1. Missing money silently became zero

```python
if value is None:
    return 0.0
```

A `null` from Alpaca became `$0.00` and would have flowed into position
weights, portfolio totals and the performance chart — rendering as a
catastrophic loss that never happened, with `health.ok` still reporting `true`.

**Fix.** Raise. A missing price is an unknown price, not a price of nothing.
The error names the offending field.

### 2. History rows dated by when the file was written

`build_history_row` took its date from `generated_at` — when the run happened —
rather than `market_data_as_of`, when the prices are from. Harmless on the
scheduled run where the two coincide; wrong for any run before the day's data
exists, which would file yesterday's prices under today's date and shift the
whole chart by a day.

**Fix.** Date the row by the data.

### 3. The interface asked for a field the broker does not provide

ADR 0004 lists `opened_at` on every position. Alpaca's `/v2/positions` endpoint
has no such field, and the interface spec did not include it either. Both
agents implemented their specs correctly; **the specification contradicted
itself.** This is exactly the class of error the contract existed to prevent.

**Fix.** `opened_at` is nullable and will be populated from our own decision
records once trading begins, since we are the only party who knows when we
bought.

### 4. Health could never report ill

`"health": {"ok": True, "warnings": []}` was hardcoded. The field the dashboard
relies on to tell you something is wrong could not ever say so.

**Fix.** Health is now computed by the entrypoint and passed in — currently
flagging stale market data and a non-ACTIVE account.

### 5. Benchmark prices were not recorded before inception

Pre-inception history rows stored `benchmark_price: null`, because the
benchmark block is null until the first trade. But we *have* the price, and
ADR 0004 states plainly that history cannot be reconstructed. Every day not
recorded would have been lost permanently.

**Fix.** The price is passed explicitly, so the benchmark series is unbroken
from the first run.

---

## 2026-08-28 — A guard that cannot fire

The `update-state` workflow checks for changes before committing, so that a
quiet day exits green rather than failing on an empty commit.

**It can never fire.** `generated_at` and `run.id` differ on every run, so
`state.json` always has a diff.

**Not fixed, deliberately.** A commit on every run is what keeps the repository
active, and GitHub disables scheduled workflows in public repos after 60 days
of inactivity. The daily commit is load-bearing. Recorded here so the guard is
not mistaken for working protection.
