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

---

## 2026-08-29 — Four guardrails were documented, configured, and never built

**Symptom.** None, which is the point. 45 tests passed, the dashboard was live,
the email worked, and a simulated year reported no violations.

**What was actually true.** The stop loss, both halves of the concentration
trim, the broad-US-equity cap and the cash ceiling existed in
`config/rules.json`, in ADR 0003, in the README, and in the prompt injected
into the AI — and in **no production code at all**. A position could fall 90%
and nothing would sell it.

**How it was found.** By simulating a year of trading rather than testing the
current state. The crash scenario ran the portfolio down 28.6% with holdings
well past the —20% line and **no stop ever fired**. A grep confirmed it:
`stop_loss` appeared nowhere outside a test fixture.

**Root cause: a specification gap, not an implementation error.** The Phase 2
tasks defined validating *proposals the AI makes* and executing them. Nothing
was ever assigned to **generate decisions from the portfolio's own state**. Two
agents built their specs correctly. The specification had a hole where a
guardrail should be, and every test written from that specification passed.

**Fix.** `src/portfolio/triggers.py` computes stop-loss and trim decisions from
state before the AI runs, and the broad-equity cap became a validation check.
The same crash scenario now fires 14 stops and ends at —22.4% instead of
—28.6%.

### Two more bugs the same simulation found

**The minimum position count made the portfolio impossible to build.** It was
enforced on buys, so from an empty book any cycle proposing fewer than 8 names
had every one rejected — and after stops reduced a book below 8, it could never
be rebuilt. It now gates discretionary sells only. Friday's dry run missed this
purely because the AI happened to propose 15 names at once.

**The cash floor drifts without a trade.** It is a percentage, so a rising
market pushes cash under it while the cash itself has not moved. That is not a
breach — the rule is that an *order* breaching the floor is rejected — so the
simulation reports it as an observation rather than a failure. Undocumented
until the meltup scenario flagged it.

### The lesson

**A green test suite proves the code that exists is correct. It says nothing
about the code that does not.** Every test here was written from the same
specification that omitted the guardrails, so the tests agreed with the gap.

Only running the system through conditions it had never seen — a crash, a
melt-up, a year — surfaced the absence.
