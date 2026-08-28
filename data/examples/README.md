# Example data — NOT real portfolio data

Worked examples of the three file formats defined in
[ADR 0004](../../docs/decisions/0004-data-contract.md). Numbers are invented
but internally consistent: position weights plus `cash_weight` sum to exactly
1.0, and totals reconcile.

Their purpose is to let the dashboard be built and tested **before** the
pipeline exists to produce real files. Build against these, then swap the path
to `data/state.json` when the pipeline lands.

Real files live at `data/state.json`, `data/history.json` and
`data/decisions/<date>.json`. These examples are never read by the running
system.

`decisions.example.json` deliberately includes one **rejected** order, to show
how a failed validation check is recorded rather than discarded.
