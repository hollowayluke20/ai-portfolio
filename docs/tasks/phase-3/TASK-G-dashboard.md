# Task G — the live dashboard

**Read first:** `docs/tasks/phase-3/dashboard-mockup.html` — the approved
design, already built. Then ADR 0004, particularly the staleness section and the
two additions dated 2026-08-29.

## What this is

A static page served by GitHub Pages from the repo root at
**https://hollowayluke20.github.io/ai-portfolio/**. It fetches JSON the pipeline
committed and displays it. **No server, no build step, no credentials, and it
computes nothing** — every figure it shows was calculated and validated before
being written.

Any commit to `main` republishes it, including the daily bot commits. That is
how brief §9 is satisfied.

## Files you own — create ONLY these

```
index.html
assets/dashboard.css
assets/dashboard.js
```

Do not touch anything under `src/`, `scripts/`, `config/`, `data/`, `docs/`, or
`.github/`. **Do not commit or push.**

## The design is settled — do not redesign it

`dashboard-mockup.html` went through fifteen rounds of review and is approved.
Split it into the three files above and keep **all** of it:

- The ledger palette, both light and dark themes
- Newsreader for prose, IBM Plex Mono for every number and label — the split by
  role is the design idea, not decoration
- Theses as `<details>` dropdowns with the three registers: **the business**,
  **thesis**, **risk**
- Sortable columns, the filter, and their single combined view function
- The chart with labelled axes, range selector, and in-page hover readout
- Marginalia hanging off a rule; tickers rather than logos
- `market_data_as_of` and `generated_at` shown as separate facts

Remove: the `SAMPLE DATA` stamp, the hardcoded arrays, and `returnOver()` —
per-holding returns are **since entry only** for v1.

## Data

Three fixed relative paths:

```
data/state.json               required
data/history.json             required
data/decisions/latest.json    optional — 404 is a NORMAL state
```

`latest.json` supplies the positioning commentary and the blocked trades.

## The actual work: the states the mockup does not show

**The live portfolio looks nothing like the mockup.** Today it is two dust
positions worth $24, no inception stamped, two history rows with null returns,
and no decision file at all. A page built only for the mockup's mature book
would render as broken zeros.

**It must look deliberate on day one**, then fill in as the system runs.

| Condition | Required behaviour |
|---|---|
| `performance` / `benchmark` are `null` | Show value and cash normally. Replace the return figures with *"Not yet trading — measurement starts at the first trade."* **Never render 0.00%** — a zero return is a claim, and an untrue one |
| Fewer than two history rows carrying returns | The chart area states that performance tracking begins at the first trade. Do not draw a line through one point |
| `data/decisions/latest.json` returns 404 | Positioning and blocked sections state plainly that no decision cycle has run yet. **This is normal, not an error** |
| A position has `thesis: null` | The dropdown says the holding predates the system's records. True of both current holdings |
| `business` is null | Omit that block entirely; show thesis and risk |
| `health.ok` is false | Display every string in `health.warnings` prominently, near the top |
| **`generated_at` older than 26 hours** | A loud, unmissable staleness banner |
| `state.json` or `history.json` fails to load | Say **which file** could not be loaded. Never render a partial page as though it were whole |

### Staleness is the most important behaviour on this page

A static page shows whatever was last written. **A pipeline that broke three
weeks ago produces a page that looks perfectly healthy and is entirely wrong.**
The freshness stamp is the only thing standing between the reader and a
confident lie, so it must be impossible to miss when it fires — not a grey
subtitle.

## Quality floor

Keyboard operable throughout (the mockup's `<details>`, sort buttons and range
tabs already are — keep the focus styles). Responsive to phone width. Both
themes. `prefers-reduced-motion` respected. No external requests except Google
Fonts.

## Success criteria

```
python -m http.server 8000
```

Open `http://localhost:8000/` against the **current real data** — the hardest
case, since nearly everything is null. Confirm: no `NaN`, no `undefined`, no
`$0.00` returns, no broken chart, both dust positions rendering honestly.

Then break it deliberately:
- Rename `data/state.json` — the page says so rather than rendering blank
- Backdate `generated_at` by 48 hours — the staleness banner fires

If the page looks empty and sad on real data, it is not finished. It should
read as a system that has started rather than one that is broken.
