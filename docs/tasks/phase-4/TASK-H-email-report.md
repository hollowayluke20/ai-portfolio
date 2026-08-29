# Task H — the weekly email report

**Read first:** ADR 0004 for the shape of `state.json`, `history.json` and the
decision records. Then `scripts/update_state.py` for house style — argument
parsing, failing loud, and exit codes.

## What this is

Brief §7: an automated report, generated and sent without anyone asking. One
email a week, after the decision cycle, to Luke.

## The rule that shapes everything

**The email reads the committed JSON files. It never calls Alpaca or Gemini.**

It reports what the pipeline wrote and the dashboard is displaying, so the
email and the website cannot disagree. An email that fetched its own figures
could state numbers nobody can check against the record — and the record is the
whole point of this system.

## Files you own — create ONLY these

```
src/portfolio/report.py
scripts/send_report.py
.github/workflows/weekly-report.yml
tests/test_report.py
```

Do not touch `alpaca.py`, `state.py`, `storage.py`, `validator.py`,
`executor.py`, `decisions.py`, `index.html`, `assets/`, `config/`, `data/`, or
any ADR. **Do not commit or push.**

## 1. `src/portfolio/report.py` — build the text

```python
build_report(state, history, decisions) -> tuple[str, str]   # (subject, body)
```

**A pure function.** No file reads, no network, no clock. Everything arrives as
an argument, exactly like `build_state`. That is what makes it testable.

`decisions` may be `None` — no cycle has run. Handle it.

**Plain text, not HTML.** It reads correctly in every client, cannot render
broken, and the dashboard is where the visual version lives. The email's job is
to say what happened and link to the detail.

Subject line carries the news, so it is readable in a notification without
opening anything:

```
AI Portfolio — $103,421 (+3.42%) — 3 decisions
```

Body, in this order:

- **Headline** — total value, return since inception, benchmark return, the
  difference between them
- **This week** — change since the last history row seven days back
- **Holdings** — ticker, weight, and since-entry return, largest first
- **Notable** — largest position, best and worst performer
- **Decisions this cycle** — action, ticker, and the reason for action
- **Blocked** — any rejected order with the check that stopped it. **Include
  this even when empty**, stated as "none this cycle" — a guardrail that never
  reports is a guardrail nobody trusts
- **AI commentary** — the positioning text, verbatim
- **Link** to https://hollowayluke20.github.io/ai-portfolio/
- **Health warnings**, if `health.ok` is false — at the top, not the bottom

### Empty and degraded states

| Condition | Behaviour |
|---|---|
| `performance` is `null` | Say the system has not started trading yet. **Never print 0.00%** |
| No decision record | Say no cycle has run; still send the portfolio figures |
| Fewer than 5 history rows | Omit the weekly-change line rather than comparing against nothing |
| `health.ok` false | Lead with the warnings |

## 2. `scripts/send_report.py`

Reads the three files, calls `build_report`, sends via SMTP with `smtplib` and
`email.message` — both standard library, **no new dependency**.

Credentials from the environment: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`.
Never hardcode, never log. `smtplib.SMTP` to `smtp.gmail.com:587` with
`starttls()`.

- `--dry-run` prints the email to stdout and sends nothing. **This is the
  default.** Sending requires `--send`, mirroring `run_cycle.py`.
- Missing credentials is a clear error, not a stack trace.
- SMTP failure exits non-zero so the workflow goes red and GitHub emails Luke
  about the failed run — which is a working fallback for a broken mailer.

## 3. `.github/workflows/weekly-report.yml`

Runs after the market close on Friday, pinned to the market's timezone the way
`update-state.yml` is:

```yaml
on:
  schedule:
    - cron: '15 17 * * 5'
      timezone: America/New_York
  workflow_dispatch:
```

Secrets `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`; runs
`python scripts/send_report.py --send`. Needs no write permissions — it commits
nothing.

**Note the observed reality:** a scheduled run on 2026-08-28 fired 6.4 hours
late. Do not assume this lands on time. The report must state which data it is
reporting on, using `market_data_as_of`, rather than saying "today".

## Tests

- Subject contains the value and return
- `performance: null` produces "not yet trading", never `0.00%`
- `decisions=None` still produces a valid report
- Blocked section appears with "none this cycle" when there are none
- Health warnings appear at the top when `ok` is false
- The weekly-change line is omitted with fewer than 5 history rows
- `build_report` performs no I/O

## Success criteria

```
pytest tests/ -q
python scripts/send_report.py            # dry run, prints the email
python scripts/send_report.py --send     # actually sends
```

The dry run against **current real data** must read as a sensible email about a
system that has started but not yet traded — not a wall of zeros and blanks.
