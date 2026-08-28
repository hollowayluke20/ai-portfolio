# 0002 — Portfolio state lives in the repo

**Date:** 2026-08-28
**Status:** Accepted

## Context

The dashboard must be deployed, must show real data from the system, and must
**stay current without anyone touching it** (brief §8, §9). That requires
deciding where portfolio state lives between the system producing it and the
website displaying it.

Two constraints rule out the obvious approach of having the dashboard call
Alpaca directly:

1. **GitHub Pages serves static files.** No code of ours runs when a visitor
   loads the page. Nothing can fetch, think, or decide at view time.
2. **Credentials cannot go in a web page.** For a browser to call Alpaca, the
   API key and secret would have to be in the shipped JavaScript, readable by
   anyone via View Source, and committed to a public repo.

So something must sit between Alpaca and the browser. That something is state:
a written record the system produces and the dashboard only reads.

State must cover more than a current snapshot. A performance chart and a
benchmark comparison need **history**, and history exists only if it is
recorded as it happens — Alpaca will not sell back past portfolio values.

## Decision

**The repository is the database.** GitHub Actions writes JSON files and
commits them back; GitHub Pages serves the dashboard, which reads those files.

```
Alpaca ──▶ Actions (scheduled, ephemeral) ──▶ commit JSON to repo ──▶ Pages ──▶ dashboard
```

Actions provides **compute, not storage** — every run gets a fresh machine that
is destroyed afterwards. The commit-and-push step is what makes a run
persistent; without it the run happens and vanishes.

## Rationale

- **One system, not three.** No database to run, no second provider with its
  own account, billing, and outages. The store is infrastructure we already
  have.
- **It keeps the automation alive.** GitHub disables scheduled workflows in
  public repos after 60 days of repository inactivity. Every run commits, and a
  commit is activity, so **the system stays enabled by doing its job**. With an
  external database the repo would sit untouched and the schedule would die
  silently around day 60.
- **Decision history comes free.** Git already records every change with an
  immutable timestamp, author and message. Brief §5 — reconstructing what the
  system decided and why, weeks later — is satisfied by the storage layer
  rather than by extra code.
- **The dashboard becomes trivially safe.** It reads a JSON file. No
  credentials, no auth, nothing to leak, because nothing sensitive is there.

## Alternatives considered

**Hosted database (Supabase/Postgres) — rejected.** Real queries and a proper
schema, but a second service to maintain and monitor, and it would leave the
repo inactive, reintroducing the 60-day failure. Solves problems we do not
have.

**Serverless functions (Vercel) proxying Alpaca — rejected.** Keys stay
server-side and data is live rather than last-run-old, but it is more
infrastructure and still needs a store behind it for history. Freshness is not
worth it for a system that decides on a daily cadence.

## Consequences and limitations

- **Not a database.** Querying means loading a file and filtering in code. Fine
  at one decision cycle per day; would not be at high frequency.
- **The repo grows**, slowly — daily JSON snapshots are a few KB, single-digit
  MB after a year.
- **An automated commit lands every run.** Needs clear commit messages to keep
  history readable; data can be moved to its own branch if it becomes noise.
- **Pages rebuild lag** of a minute or two after each commit. Irrelevant here.
- **Concurrent runs can collide** on push. Workflows must be prevented from
  overlapping, or handle a rejected push by re-pulling and retrying.
- **The dashboard can only ever show what was written down earlier.** If a run
  fails silently, the dashboard displays stale data while looking healthy.
  Every state file must therefore carry a generation timestamp, and the
  dashboard must show it and visibly flag staleness rather than hide it.
