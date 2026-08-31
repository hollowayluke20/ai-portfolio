#!/usr/bin/env python3
"""Replay the REAL prompt and the REAL rules through REAL historical prices.

Answers one question: does the AI ever sell a position on judgement?

The return number this produces is CONTAMINATED and is not evidence of skill -
the model's training data covers the window. See docs/tasks/task-k.
"""
from __future__ import annotations
import argparse, datetime, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.portfolio import executor, state as state_mod
from src.portfolio.ai import propose, render_prompt
from src.portfolio.candidates import select_candidates
from src.portfolio.config import load_rules, load_universe
from src.portfolio.marketdata import fetch_bars, compute_features, compute_breadth
from src.portfolio.news import fetch_news
from src.portfolio.triggers import mechanical_decisions
from sim.broker import FakeBroker

REPO = Path(__file__).resolve().parents[1]
BENCHMARK = "SPY"


def load_clean_bars(tickers, start, end):
    """Fetch bars and drop impossible prints.

    The feed contains decimal slips: SPY 2026-02-02 reported a low of 68.64
    against a 691.70 close on 79M shares. We only ever read closes, but a bad
    CLOSE would be fatal, so filter on close-to-close moves.
    """
    raw = fetch_bars(tickers, start, end)
    clean, dropped = {}, []
    for ticker, rows in raw.items():
        rows = sorted(rows, key=lambda r: r["t"])
        keep, prev = [], None
        for r in rows:
            c = float(r["c"])
            if c <= 0 or (prev and (c / prev > 1.5 or c / prev < 0.5)):
                dropped.append((ticker, r["t"][:10], c, prev))
                continue
            keep.append({"d": r["t"][:10], "c": c})
            prev = c
        if keep:
            clean[ticker] = keep
    return clean, dropped


class HistoricalMarket:
    """Same four-method interface as sim.market.Market, backed by real bars."""

    def __init__(self, bars, sessions):
        self.by_ticker = {t: {b["d"]: b["c"] for b in rows} for t, rows in bars.items()}
        self.last_seen = {t: max(rows) for t, rows in self.by_ticker.items()}
        self.sessions, self.i = sessions, -1

    def advance(self):
        self.i += 1
        return self.today()

    def today(self):
        return datetime.date.fromisoformat(self.sessions[self.i])

    def price(self, ticker):
        return self.by_ticker.get(ticker, {}).get(self.sessions[self.i])

    def is_delisted(self, ticker):
        return ticker in self.last_seen and self.sessions[self.i] > self.last_seen[ticker]


def main(start, end, out_dir, verbose):
    rules, universe = load_rules(), load_universe()
    meta = json.loads((REPO / "config" / "universe.json").read_text(encoding="utf-8")).get("metadata", {})
    try:
        fundamentals = json.loads((REPO / "data" / "fundamentals.json").read_text(encoding="utf-8"))["tickers"]
    except Exception:
        fundamentals = {}

    fetch_from = (datetime.date.fromisoformat(start) - datetime.timedelta(days=400)).isoformat()
    print(f"fetching bars {fetch_from} -> {end} for {len(universe) + 1} tickers ...", flush=True)
    bars, dropped = load_clean_bars(universe + [BENCHMARK], fetch_from, end)
    print(f"  {len(bars)} tickers, {sum(len(v) for v in bars.values()):,} bars, "
          f"{len(dropped)} bad prints dropped")
    for t, d, c, p in dropped[:6]:
        print(f"    dropped {t} {d}: close {c} against previous {p}")

    sessions = [b["d"] for b in bars[BENCHMARK] if start <= b["d"] <= end]
    print(f"  {len(sessions)} sessions {sessions[0]} -> {sessions[-1]}\n")

    # compute_features expects rows keyed like Alpaca bars
    feature_bars = {t: [{"t": b["d"], "c": b["c"]} for b in rows] for t, rows in bars.items()}

    market = HistoricalMarket(bars, sessions)
    broker = FakeBroker(100000.0, market)
    records, log, hist, skipped = {}, [], [], []
    inception = None

    for _ in sessions:
        day = market.advance()
        iso = day.isoformat()
        broker.settle()                      # yesterday's orders fill at today's close

        features = compute_features(feature_bars, iso)
        spy = market.price(BENCHMARK)
        positions = broker.positions()
        held = [p["symbol"] for p in positions]
        pending = [{"order_id": o["order_id"], "symbol": o["symbol"], "side": o["side"],
                    "notional": o["notional"], "qty": None, "status": o["status"],
                    "submitted_at": f"{iso}T00:00:00Z", "filled_qty": 0.0}
                   for o in broker.open_orders()]

        st = state_mod.build_state(
            account=broker.account(), positions=positions, pending_orders=pending,
            spy_price=spy, spy_as_of=f"{iso}T21:00:00Z", rules=rules, inception=inception,
            generated_at=f"{iso}T21:05:00Z",
            run={"id": f"bt-{iso}", "trigger": "backtest", "workflow": "backtest"},
            active_records={t: records[t] for t in held if t in records})

        if inception is None and any(p.get("thesis") for p in st["positions"]):
            inception = {"inception_date": iso, "inception_value": st["totals"]["total_value"],
                         "benchmark_ticker": BENCHMARK, "benchmark_inception_price": spy}

        hist.append({"date": iso, "value": st["totals"]["total_value"], "spy": spy,
                     "n": st["totals"]["position_count"], "cash_w": st["totals"]["cash_weight"]})

        def submit(*, ticker, side, notional):
            return broker.submit(ticker, side, notional)

        def close(*, ticker):
            # Close the position, never a notional sell of its market value -
            # see FakeBroker.close. Production uses DELETE /v2/positions here.
            return broker.close(ticker)

        triggered = mechanical_decisions(st, rules)
        decisions_today, ai_out = list(triggered), None

        if day.weekday() == 4:               # Friday: the AI cycle
            exiting = {d["ticker"] for d in triggered}
            cands = [c for c in select_candidates(universe, held, day.isocalendar().week)
                     if c not in exiting]
            theses = {t: r.get("thesis") for t, r in records.items() if t in held}
            breadth = compute_breadth(features)
            try:
                recent_news = fetch_news(
                    held, (day - datetime.timedelta(days=7)).isoformat(), iso
                )
                news_unavailable = False
            except Exception as exc:
                print(f"{iso} news fetch failed; continuing without it: {exc}", file=sys.stderr)
                recent_news, news_unavailable = {}, True
            # `iso` as the as-of date, not today: a January replay must read
            # the accounts that were public in January.
            prompt = render_prompt(st, rules, cands, theses, features, meta, breadth,
                                   recent_news, news_unavailable, fundamentals, iso)
            try:
                ai_out = propose(st, rules, cands, theses, features, meta, breadth,
                                 recent_news, news_unavailable, prompt=prompt)
                decisions_today += ai_out["decisions"]
            except Exception as exc:
                # One bad cycle must not destroy the run.
                #
                # A backtest is a hundred-odd independent decisions; production
                # is one, and there aborting is right - better no trade than a
                # half-informed one. Here the same behaviour meant a single
                # slow API response threw away every cycle that came before it.
                # Five runs died that way and produced nothing at all.
                #
                # A skipped week is a gap in the record, so it is logged as one
                # rather than passed over silently.
                print(f"{iso} AI cycle failed, skipping this week: {exc}",
                      file=sys.stderr)
                skipped.append(iso)

        done = []
        if decisions_today:
            done = executor.execute(decisions_today, st, rules, universe,
                                    dry_run=False, submit=submit, close=close)
            for d in done:
                if d["action"] == "BUY" and d["status"] == "executed":
                    records[d["ticker"]] = {**d, "decided_at": f"{iso}T21:05:00Z"}
                if d["action"] == "SELL" and d["status"] == "executed":
                    records.pop(d["ticker"], None)

        # Log every cycle the AI ran, not only the ones that traded.
        #
        # A quiet week used to leave no trace at all, which made "it reviewed
        # everything and held" indistinguishable from "the cycle never fired"
        # or "the API call failed". The commentary and the ranked review were
        # produced and then thrown away for want of a trade to attach them to
        # - and on a week where nothing happens, the reasoning for why nothing
        # happened is the only output worth having.
        if ai_out or decisions_today:
            log.append({"date": iso,
                        "commentary": (ai_out or {}).get("commentary"),
                        "target_bond_weight": (ai_out or {}).get("target_bond_weight"),
                        "allocation_reason": (ai_out or {}).get("allocation_reason"),
                        "review": (ai_out or {}).get("review"),
                        "considered": (ai_out or {}).get("considered"),
                        "decisions": done})
            if verbose:
                print(f"{iso}  ${st['totals']['total_value']:>11,.0f}  "
                      f"{st['totals']['position_count']:>2} pos  cash {st['totals']['cash_weight']:.1%}")
                for d in done:
                    mark = "OK " if d["status"] == "executed" else "-- "
                    why = d.get("rejection_reason") or d.get("reason_for_action") or ""
                    print(f"   {mark}{d['action']:<5}{d['ticker']:<6}"
                          f"{(d.get('trigger') or d.get('basis') or ''):<15}{why[:64]}")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    (out / "history.json").write_text(json.dumps(hist, indent=2), encoding="utf-8")
    if skipped:
        # Loud, and in the output rather than only in stderr. A run with holes
        # in it is still useful, but only if the holes are visible - a quietly
        # shorter result reads exactly like a quiet market.
        print(f"\n{len(skipped)} CYCLE(S) SKIPPED after an AI failure: "
              f"{', '.join(skipped)}")
    print(f"\nwrote {out}/log.json and {out}/history.json")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-02")
    ap.add_argument("--end", default="2026-03-31")
    ap.add_argument("--out", default="data/backtests/jan-mar-2026")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.start, a.end, a.out, not a.quiet))
