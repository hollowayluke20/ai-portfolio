# The first live cycle — what to watch

**Monday 2026-08-31.** The first time this system spends money.

The first *scheduled* cycle is Friday 2026-09-04. Neither date is a US
market holiday - Labor Day falls on 7 September this year.

Everything else has been tested. This is the only test of whether **Alpaca
behaves the way the simulator assumed** — the fake broker is a model of the
real one, and if that model is wrong, every simulation has been confirming the
same mistake very efficiently.

**Run it by hand, watching.** Do not schedule the first one. A supervised
failure is a lesson; an unsupervised one at 21:25 on a Friday is a mystery.

Times are UK. US market: **14:30 open, 21:00 close.**

---

## Before you start

```
git pull
python -m pytest tests/ -q          # 47 passing
python scripts/update_state.py      # fresh state, health ok
```

Check `data/state.json` shows `"status": "ACTIVE"` and cash near $100,000.
If `health.ok` is false, **stop and read the warnings** rather than trading on
a degraded read.

## Step 1 — dry run first, every time

```
python scripts/run_cycle.py
```

Read the output properly. This is the last point at which nothing has happened.

| Look for | Wrong looks like |
|---|---|
| 8–20 proposals, mostly BUY | One proposal, or forty |
| Notionals near $6,300 each | Wildly uneven sizes, or values under $1 |
| Total committed **under $95,000** | Anything that would leave cash below 5% |
| Theses that read like reasoning | Repetition, filler, or "n/a" |
| Rejections, if any, with real reasons | A rejection you cannot explain |

**If a rejection appears you do not understand, stop.** The guardrails firing
is good; not knowing why they fired is not.

## Step 2 — go live

```
python scripts/run_cycle.py --live
```

Orders are **market, day** — they queue until the open and fill at a price
nobody knows yet. That is expected and documented; it is not a bug.

Expect: `executed` statuses, order IDs, and no exceptions.

## Step 3 — confirm the broker agrees

```
python scripts/update_state.py
```

The count of `pending_orders` must match the orders just submitted. **This is
the first real check of the simulator's central assumption:** `cash` should be
unchanged while `available_cash` drops by the committed amount.

**If `cash` moved instead, the model was wrong** and the cash-floor logic needs
re-examining before the next cycle.

## Step 4 — the open, 14:30

Wait about five minutes, then:

```
python scripts/update_state.py
```

| Check | Why it matters |
|---|---|
| Positions appear with fractional quantities | Confirms notional orders work live |
| `pending_orders` empties | Orders filled rather than lingering |
| Weights plus `cash_weight` sum to 1.0 | The invariant, against real data |
| Fill prices differ from Friday's close | Expected — this is the overnight gap |
| **Any order partially filled** | **Untested territory.** Alpaca does this ~10% of the time and the simulator never modelled it |

Partial fills are the most likely place reality diverges from the simulation.
If one appears, note the ticker and how the weights ended up.

## Step 5 — inception

Inception stamps the first time the system's **own** orders leave it holding
something. Check `config/inception.json` exists and the value looks right.

It should **not** have been triggered by the manual NVDA and MSTR test trades.
If it stamped earlier than this cycle, that logic is wrong and the benchmark
comparison will be measured from the wrong point forever.

## Step 6 — commit and watch the chain

```
git add data/ config/inception.json && git commit -m "data: first live cycle" && git push
```

Then, roughly a minute later, open
**https://hollowayluke20.github.io/ai-portfolio/**

Positions, theses, the decision record, and any blocked orders should all be
there. This is the full chain — broker to website — running for real.

## Step 7 — the scheduled run, ~21:25

The daily job fires after the close. **It has been up to 6.4 hours late once**,
so do not treat lateness as failure. Confirm it eventually ran, committed, and
that the dashboard updated itself.

---

## If something goes wrong

**Everything is paper money.** Nothing here costs anything except untangling.

| Problem | Do this |
|---|---|
| Orders rejected by Alpaca | Read the message. It is usually the honest reason |
| Nothing fills after 30 minutes | Check `/v2/orders` status; a `day` order can expire unfilled |
| Weights do not sum to 1.0 | Stop. Do not run another cycle. This is a real bug |
| Inception stamped wrongly | Delete `config/inception.json` before the next state run |
| Everything looks wrong | Positions can be closed in Alpaca's web dashboard by hand |

**Do not run a second cycle to fix a first.** Understand what happened first —
the decision record is immutable and will still be there.

---

## After it works

Two things remain before this is genuinely unattended:

1. **The decision cycle has no workflow.** It runs only when typed. Until that
   is scheduled, "the process repeats automatically" is not true of the part
   that makes decisions.
2. **Simulate partial fills**, once you have seen how Alpaca really behaves.
