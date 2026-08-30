# Task P — news into the prompt, and fundamentals worth trusting

Two jobs. **Do not run `git add` or `git commit` at any point** — the sandbox
denies writes to `.git` and no prompt changes that. Write files, run things,
report what actually happened. Committing is handled outside your session.
Never treat an uncommitted file as unfinished, and never stop between jobs.

---

# JOB 1 — re-fetch the fundamentals and get the audit clean

## Why a re-fetch is needed

`data/fundamentals.json` was fetched **before** two fixes that changed what
gets stored, so the file on disk is wrong even though the code is now right:

1. Only 12 periods were kept per measure. Each period end appears twice — once
   as the quarter, once inside a year-to-date cumulative row — so 12 periods
   yielded about six quarters, with gaps. It is now 24.
2. **The fourth quarter is never filed as a quarter.** A US filer reports
   Q1–Q3 on 10-Qs and the whole year on a 10-K, so Q4 exists only as the
   annual figure minus the nine-month one. `_derive_missing_quarters` now
   recovers it by subtraction.

Together these made *every* measure for *every* company come back `None`.
Apple now computes a trailing-year EPS of **8.71** against an independent
source's **8.72**; before the fix it read 8.44.

**Re-run `scripts/refresh_fundamentals.py` in full and leave the new file in
place.** It takes about ten minutes for 506 companies at the SEC's rate limit.

## Then get the audit honest

`scripts/audit_fundamentals.py` currently fails on a flat 90% coverage rule
applied to every measure. That rule is wrong, and a check that cries wolf
every week is one nobody reads.

**Set per-measure expectations** and say why in the code:

- `GrossProfit` ~50% is **legitimate**. Banks, insurers and property trusts do
  not report a gross profit line at all. Expect 45%.
- `AssetsCurrent` / `LiabilitiesCurrent` ~84% is **legitimate**. Banks do not
  use a classified balance sheet. Expect 80%.
- `EarningsPerShareDiluted`, `Revenues`, `NetIncomeLoss`, `Assets`,
  `NetCashProvidedByUsedInOperatingActivities` should all clear 95%.
- `LongTermDebtNoncurrent`, `CommonStockSharesOutstanding`: expect 88%.

Anything below its own expectation is a real finding. Anything above is fine.

## Investigate three specific results

A spot check after the fix produced figures that look wrong. Find out whether
each is a bug or a real property of the filing, and say which:

```
MSFT   revenue growth +40.3%   and net margin 40.3%  <- identical, suspicious
JPM    net margin 68.4%        revenue growth +0.0%
XOM    everything n/a
```

Identical numbers for two unrelated measures usually means one is being read
into the other. A 68% net margin is implausible for a bank unless "revenue"
is being picked up as net interest income rather than total revenue. Exxon
returning nothing at all suggests a tag that is not in the fallback list.

**Do not tune the code until a printed comparison agrees with a public
source.** Chasing a third party's number is how a correct implementation gets
broken — but three implausible results in a five-company sample is not noise.

## Extend the audit

Add a section that runs `summarise()` for `AAPL, MSFT, NVDA, JPM, XOM, KO,
UNH, PG` and prints P/E, revenue growth and net margin as a plain table, so a
human can compare against a public source. Do not hardcode expected values.

Reference, checked 2026-08-30: Apple EPS 8.72, P/E 36.68.

**Report the real audit output**, including any identity violations.

---

# JOB 2 — put news in front of the AI

`src/portfolio/news.py` is built, tested and committed, and **nothing uses
it.** Wire it in. Fundamentals stay out of the prompt until Job 1's audit is
clean — do not add them.

## The prompt

Add a `{NEWS}` placeholder to `config/prompt.md`, in the **Current portfolio**
section immediately after the positions block. News is evidence about what you
own, so it belongs beside the holdings, not in a distant appendix.

Render it grouped by ticker, newest first:

```
NVDA
  2026-08-30  Benzinga   Nvidia Q2 beat, data-centre revenue up
  2026-08-28  Reuters    Export licence decision delayed again
GLD
  2026-08-28  Benzinga   Gold sinks as rate-hike odds jump to 60%
```

Headline, date and source. Summaries too if they fit — check the total against
the existing 80,000-character tripwire and trim `per_ticker` before trimming
the fields.

## The instruction that matters most

Say plainly in the prompt what news is *for*: it is the evidence that can
break a thesis. Price cannot. A reason like "this company leads in AI chips"
is not falsified by the share price falling — it is falsified by a competitor
launching, a regulator moving, or an earnings miss. Those arrive as news.

**And distinguish "nothing found" from "could not look".** These are completely
different and must never render the same way:

- No articles for a ticker: `NVDA — no articles in the last 7 days`
- The fetch failed: `News unavailable this cycle — the fetch failed. Do not
  read the absence of news as the absence of events.`

An AI shown a blank news section will assume nothing happened. That is a
silent lie in exactly the situation where you most want it cautious.

## Wiring

- `render_prompt` gains a `news` parameter; `propose` accepts it and passes it
  through, exactly as `features` and `metadata` already are.
- `scripts/run_cycle.py`: fetch news for **held tickers only** over the last 7
  days, ending at the cycle date.
- `scripts/backtest.py`: same, but `end` must be **the cycle's own date**, not
  today. The backtest replays past Fridays and must never see an article that
  had not been published yet. `fetch_news` enforces this itself, but passing
  today's date would still leak.
- **Do not abort the cycle if news fails.** Market data aborts because a
  decision without prices is worthless; a decision without news is merely
  poorer. Log the failure, render the "could not look" line, carry on.

## Tests

- The `{NEWS}` placeholder is filled and no placeholder survives.
- A ticker with no articles renders the "no articles" line, and a failed fetch
  renders the "unavailable" line — **assert the two produce different text.**
- The prompt actually sent to the model contains a real headline. Monkeypatch
  `ai._call_gemini`, capture its argument, assert on it. Not a test of
  `render_prompt` — a test of what crosses the boundary. That distinction is
  what Phase 7's worst bug turned on.
- Prompt stays under the 80,000-character tripwire with 15 holdings of news.

---

# Reporting

After each job: **do not summarise what you intended to do.** Show
`git status --short`, the files you changed, and the real output of anything
you ran — the audit table, the test results, a sample of the rendered news
block. If a job is unfinished, name exactly which parts.
