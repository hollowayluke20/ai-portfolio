/* ==========================================================================
   AI Portfolio Ledger — reads the JSON the pipeline committed and displays it.
   It computes nothing: every figure and every sentence here was calculated and
   validated before being written (ADR 0004).

   Data, three fixed relative paths:
     data/state.json               required
     data/history.json             required
     data/decisions/latest.json    optional — a 404 is a NORMAL state

   The most important behaviour on this page is the staleness check. A static
   page shows whatever was last written, so a pipeline that broke weeks ago
   looks perfectly healthy. The freshness stamp is the only thing between the
   reader and a confident lie, so when it fires it must be impossible to miss.
   ========================================================================== */
"use strict";

const STALE_HOURS = 26; // a daily cycle plus margin (ADR 0004)

/* How old the data is allowed to get before it counts as stale.

   26 hours covers a normal weekday gap. But update-state runs Mon-Fri only,
   so from Friday's close to Monday's is about 72 hours with nothing wrong at
   all - and a flat 26-hour rule put a red STALE banner on this page from
   Saturday lunchtime until Monday evening, every single week.

   That is worse than no warning. A banner that is always on during the
   weekend is one the reader learns to scroll past, and then it is not there
   on the Tuesday the pipeline actually breaks. Each intervening weekend day
   buys another 24 hours, because no cycle was ever due to run. */
function staleAfterHours(iso) {
  const from = new Date(iso);
  if (isNaN(from)) return STALE_HOURS;
  const now = new Date();
  let closedDays = 0;
  const cursor = new Date(from);
  while (cursor < now) {
    const day = cursor.getUTCDay();
    if (day === 0 || day === 6) closedDays++;
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return STALE_HOURS + closedDays * 24;
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const $ = id => document.getElementById(id);

/* ---- formatting -------------------------------------------------------- */

const money = n => (n == null || !isFinite(Number(n)))
  ? "—"
  : "$" + Number(n).toLocaleString("en-US",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// decimal fraction -> signed percent, e.g. 0.0117 -> "+1.17%"
const pctFrac = n => (n == null || !isFinite(n))
  ? "—"
  : (n >= 0 ? "+" : "−") + Math.abs(n * 100).toFixed(2) + "%";

// decimal fraction -> unsigned percent, e.g. 0.9998 -> "99.98%"
const pctPlain = n => (n == null || !isFinite(n)) ? "—" : (n * 100).toFixed(2) + "%";

const clsOf = n => (n == null || !isFinite(n)) ? "" : (n >= 0 ? "pos" : "neg");

const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function parseTs(iso) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

function fmtStamp(iso) {
  const d = parseTs(iso);
  if (!d) return "unknown";
  const p = n => String(n).padStart(2, "0");
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} `
    + `${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

function fmtDateOnly(iso) {
  const d = parseTs(iso);
  if (!d) return "an earlier date";
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

function ageHoursOf(iso) {
  const d = parseTs(iso);
  return d ? (Date.now() - d.getTime()) / 3.6e6 : Infinity;
}

function fmtAge(h) {
  if (!isFinite(h)) return "age unknown";
  // Units are spelled out deliberately. This line is uppercased by the
  // stylesheet, so "1m old" renders as "1M OLD" and reads as one MONTH — the
  // single worst misreading available on a freshness stamp.
  const plural = (n, unit) => `${n} ${unit}${n === 1 ? "" : "s"} old`;
  if (h < 1) return plural(Math.max(1, Math.round(h * 60)), "min");
  if (h < 48) return plural(Math.round(h), "hour");
  return plural(Math.round(h / 24), "day");
}

/* ---- loading --------------------------------------------------------- */

async function loadJSON(path) {
  let res;
  try {
    res = await fetch(path, { cache: "no-store" });
  } catch (e) {
    throw { path, kind: "network" };
  }
  if (!res.ok) throw { path, kind: "http", status: res.status };
  try {
    return await res.json();
  } catch (e) {
    throw { path, kind: "parse" };
  }
}

function loadDetail(err) {
  if (err && err.kind === "http") return `HTTP ${err.status}`;
  if (err && err.kind === "network") return "could not be reached";
  if (err && err.kind === "parse") return "is not valid JSON";
  return "could not be read";
}

// A required file failed. Never render a partial page — say which file, stop.
function fatal(path, detail) {
  document.querySelector(".wrap").innerHTML =
    `<div class="fatal" role="alert">
       <span class="btitle">Data unavailable</span>
       <p><code>${esc(path)}</code> ${esc(detail)}. This page shows only figures
       the pipeline has written and validated, so it will not render a partial
       view from what did load. If this keeps happening, the daily pipeline has
       most likely stopped.</p>
     </div>`;
}

/* ---- orchestration -------------------------------------------------- */

async function main() {
  // The boot notice exists to cover the one failure this file cannot report:
  // itself not loading. Clearing it first means everything after here is
  // handled by fatal() instead.
  document.getElementById("boot")?.remove();

  let state, history;

  try {
    state = await loadJSON("data/state.json");
  } catch (e) {
    return fatal("data/state.json", loadDetail(e));
  }
  try {
    history = await loadJSON("data/history.json");
  } catch (e) {
    return fatal("data/history.json", loadDetail(e));
  }

  // Fail loud on a schema version this page was not written for (ADR 0004).
  if (state.schema_version !== 1) {
    return fatal("data/state.json", `is schema version ${state.schema_version}, which this page cannot read`);
  }
  if (history.schema_version !== 1) {
    return fatal("data/history.json", `is schema version ${history.schema_version}, which this page cannot read`);
  }

  // Absent decision file is normal: it just means no cycle has run yet.
  let decisions = null;
  try {
    decisions = await loadJSON("data/decisions/latest.json");
  } catch (e) {
    decisions = null;
  }

  renderAlerts(state);
  renderStamp(state);
  renderHero(state, decisions);
  renderPerformance(history);
  renderHoldings(state);
  renderBlocked(decisions);
}

/* ---- staleness + health -------------------------------------------- */

function renderAlerts(state) {
  const parts = [];

  const age = ageHoursOf(state.generated_at);
  if (age > staleAfterHours(state.generated_at)) {
    parts.push(
      `<div class="banner" role="alert">
         <span class="btitle">Stale data — ${esc(fmtAge(age))}</span>
         <p>This page was last written ${esc(fmtStamp(state.generated_at))}. The
         daily pipeline has not produced a fresh <code>state.json</code> since
         then, so every figure below is out of date and may no longer be true.
         Read it as a historical snapshot, not the current portfolio.</p>
       </div>`);
  }

  const health = state.health || {};
  const warnings = Array.isArray(health.warnings) ? health.warnings : [];
  if (health.ok === false || warnings.length) {
    const body = warnings.length
      ? warnings.map(w => `<p>${esc(w)}</p>`).join("")
      : `<p>The pipeline flagged this run as degraded but recorded no detail.</p>`;
    parts.push(
      `<div class="banner" role="alert">
         <span class="btitle">Pipeline health warning${warnings.length === 1 ? "" : "s"}</span>
         ${body}
       </div>`);
  }

  $("alerts").innerHTML = parts.join("");
}

function renderStamp(state) {
  const age = ageHoursOf(state.generated_at);
  const stale = age > staleAfterHours(state.generated_at);
  $("stamp").innerHTML =
    `<span>Prices — ${esc(fmtStamp(state.market_data_as_of))}</span>
     <span>Written — ${esc(fmtStamp(state.generated_at))}</span>
     <span class="${stale ? "stale" : "fresh"}">● ${stale ? "Stale" : "Fresh"} · ${esc(fmtAge(age))}</span>`;
}

/* ---- hero: the figure and the argument ---------------------------- */

function renderHero(state, decisions) {
  const totals = state.totals || {};
  const account = state.account || {};
  const cashLine = `${money(account.cash)} · ${pctPlain(totals.cash_weight)}`;

  let against;
  if (!state.performance || !state.benchmark) {
    // Never render 0.00% — a zero return is a claim, and an untrue one.
    against =
      `<div class="notyet">Not yet trading — measurement starts at the first trade.</div>
       <div><span>Cash</span><span>${cashLine}</span></div>`;
  } else {
    const p = state.performance.total_return_pct;
    const b = state.benchmark.total_return_pct;
    const diff = state.benchmark.difference_pct;
    against =
      `<div><span>Since inception</span><span class="${clsOf(p)}">${pctFrac(p)}</span></div>
       <div><span>${esc(state.benchmark.ticker || "S&P 500")}</span><span class="${clsOf(b)}">${pctFrac(b)}</span></div>
       <div><span>Difference</span><span class="${clsOf(diff)}">${pctFrac(diff)}</span></div>
       <div><span>Cash</span><span>${cashLine}</span></div>`;
  }

  let who, argument;
  if (decisions && decisions.commentary) {
    // Say WHEN, and say that it describes the book as it was BEFORE the trade.
    //
    // The commentary is the reasoning that produced these holdings, so it
    // necessarily describes the portfolio it inherited, not the one it left.
    // Labelled "Positioning — set 31 Aug" and sat above a live holdings table,
    // a sentence beginning "the portfolio is currently holding near 100% cash"
    // reads as broken data. It was correct; the page was not saying so.
    who = `Reasoning from the ${fmtStamp(decisions.decided_at)} cycle`;
    const target = decisions.target_bond_weight;
    const chose = (typeof target === "number")
      ? ` It chose a ${pctPlain(target)} bond sleeve.`
      : "";
    argument =
      `<span class="asof">Describes the portfolio as it stood <em>before</em> `
      + `this cycle traded — it is the argument for the holdings below, not a `
      + `description of them.${esc(chose)}</span>`
      + esc(decisions.commentary);
  } else {
    who = "Positioning";
    argument = "No decision cycle has run yet. The portfolio holds its current "
      + "positions until the first weekly cycle runs — the expected state before "
      + "the system has started trading.";
  }

  $("hero").innerHTML =
    `<div class="figure">
       <span class="value">${money(totals.total_value)}</span>
       <div class="against">${against}</div>
     </div>
     <div class="argument">
       <span class="who">${esc(who)}</span>
       ${argument}
     </div>`;
}

/* ---- performance chart -------------------------------------------- */

function renderPerformance(history) {
  const rows = Array.isArray(history.rows) ? history.rows.slice() : [];
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));

  const usable = rows.filter(r =>
    r.portfolio_return_pct != null && r.benchmark_return_pct != null);

  if (usable.length < 2) {
    // Do not draw a line through one point.
    $("ranges").innerHTML = "";
    $("readout").innerHTML = "";
    $("legend").innerHTML = "";
    const seen = rows.length
      ? ` So far ${rows.length} trading day${rows.length === 1 ? "" : "s"} `
        + `${rows.length === 1 ? "has" : "have"} been recorded, with returns not yet running.`
      : "";
    $("chartBox").innerHTML =
      `<p class="empty">Performance tracking begins at the first trade. Once there
       are at least two trading days of returns, this area plots the portfolio
       against the S&amp;P 500.${seen}</p>`;
    return;
  }

  setupChart(usable);
}

function setupChart(dataRows) {
  const readout = $("readout");
  const rangeBar = $("ranges");

  $("chartBox").innerHTML =
    '<svg id="chart" viewBox="0 0 900 210" role="img" '
    + 'aria-label="Portfolio performance against the S&P 500"></svg>';
  const svg = $("chart");

  $("legend").innerHTML =
    '<span><i></i><b>Portfolio</b> <span id="lp"></span></span>'
    + '<span class="bm"><i></i>S&amp;P 500 <span id="lb"></span></span>';

  // percent returns, straight from the pipeline — nothing computed here
  const series = dataRows.map(r => ({
    d: new Date(r.date + "T00:00:00Z"),
    p: r.portfolio_return_pct * 100,
    b: r.benchmark_return_pct * 100,
  }));

  const RANGES = [["1W", 7], ["1M", 31], ["3M", 93], ["1Y", 365], ["5Y", 1826], ["ALL", null]];
  const last = series[series.length - 1].d;
  const spanDays = (last - series[0].d) / 864e5;
  let active = "ALL";

  const fmtDate = d => `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`
    + (d.getUTCFullYear() !== last.getUTCFullYear() ? " " + d.getUTCFullYear() : "");
  const sign = v => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(2) + "%";

  // a range longer than the data we hold is offered but disabled, not hidden:
  // the reader should see the portfolio is young, not wonder why 5Y is missing
  rangeBar.innerHTML = RANGES.map(([label, days]) => {
    const ok = days === null || days <= spanDays + 1;
    return `<button type="button" data-r="${label}" aria-pressed="${label === active}" `
      + `${ok ? "" : 'disabled title="Not enough history yet"'}>${label}</button>`;
  }).join("");

  function slice() {
    const days = (RANGES.find(r => r[0] === active) || [])[1];
    if (!days) return series;
    const cut = new Date(last);
    cut.setUTCDate(cut.getUTCDate() - days);
    const s = series.filter(pt => pt.d >= cut);
    return s.length > 1 ? s : series.slice(-2);
  }

  const W = 900, H = 210, L = 48, R = 14, T = 14, B = 30;
  let geom = null;

  function draw() {
    const data = slice();
    // rebase so every range reads as "return over THIS window"
    const p0 = data[0].p, b0 = data[0].b;
    const P = data.map(pt => pt.p - p0), Bm = data.map(pt => pt.b - b0);
    const all = P.concat(Bm);
    const pad = Math.max(0.25, (Math.max(...all) - Math.min(...all)) * 0.15);
    const lo = Math.min(...all, 0) - pad, hi = Math.max(...all, 0) + pad;

    const x = i => L + (data.length < 2 ? 0 : (i / (data.length - 1)) * (W - L - R));
    const y = v => H - B - ((v - lo) / (hi - lo)) * (H - T - B);
    geom = { data, P, Bm, x, y };

    const step = Math.max(0.25, Math.ceil((hi - lo) / 4 * 4) / 4);
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(+v.toFixed(2));
    if (!ticks.some(v => Math.abs(v) < 1e-9) && lo < 0 && hi > 0) ticks.push(0);

    const grid = ticks.map(v => {
      const yy = y(v).toFixed(1), zero = Math.abs(v) < 1e-9;
      return `<line x1="${L}" y1="${yy}" x2="${W - R}" y2="${yy}"
                stroke="${zero ? "var(--rule)" : "var(--rule-faint)"}" stroke-width="1"/>
              <text x="${L - 8}" y="${yy}" text-anchor="end" dominant-baseline="middle"
                class="ax">${v > 0 ? "+" : ""}${v.toFixed(2).replace(/\.00$/, ".0")}%</text>`;
    }).join("");

    const marks = [0, Math.floor((data.length - 1) / 2), data.length - 1];
    const xlabels = marks.map((i, n) =>
      `<text x="${x(i).toFixed(1)}" y="${H - 10}"
         text-anchor="${n === 0 ? "start" : n === 2 ? "end" : "middle"}"
         class="ax">${fmtDate(data[i].d)}</text>`).join("");

    const line = a => a.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
    svg.innerHTML = grid + xlabels +
      `<path d="${line(Bm)}" fill="none" stroke="var(--annotation)" stroke-width="1.5"
             stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>
       <path d="${line(P)}" fill="none" stroke="var(--ink)" stroke-width="2"
             vector-effect="non-scaling-stroke"/>
       <circle cx="${x(P.length - 1)}" cy="${y(P[P.length - 1])}" r="3.5" fill="var(--gain)"/>
       <g id="cross" style="display:none">
         <line class="hair" y1="${T}" y2="${H - B}"/>
         <circle class="dot" r="3"/>
       </g>`;

    const lp = $("lp"), lb = $("lb");
    if (lp) lp.textContent = sign(P[P.length - 1]);
    if (lb) lb.textContent = sign(Bm[Bm.length - 1]);
    svg.setAttribute("aria-label",
      `Portfolio ${sign(P[P.length - 1])} against the S and P 500 ${sign(Bm[Bm.length - 1])} over the selected range`);
    idle();
  }

  function idle() {
    if (!geom) return;
    const { data } = geom;
    readout.innerHTML = `<span class="idle">${fmtDate(data[0].d)} — ${fmtDate(data[data.length - 1].d)}
      · hover the chart for a single day</span>`;
  }

  function hover(ev) {
    if (!geom) return;
    const { data, P, Bm, x, y } = geom;
    const box = svg.getBoundingClientRect();
    const px = (ev.clientX - box.left) / box.width * W;
    let i = Math.round((px - L) / ((W - L - R) / Math.max(1, data.length - 1)));
    i = Math.max(0, Math.min(data.length - 1, i));
    const g = $("cross");
    if (!g) return;
    g.style.display = "";
    g.querySelector("line").setAttribute("x1", x(i));
    g.querySelector("line").setAttribute("x2", x(i));
    g.querySelector("circle").setAttribute("cx", x(i));
    g.querySelector("circle").setAttribute("cy", y(P[i]));
    const dayP = i ? P[i] - P[i - 1] : 0;
    readout.innerHTML =
      `<span><b>${fmtDate(data[i].d)}</b></span>
       <span>Portfolio <b class="${P[i] >= 0 ? "pos" : "neg"}">${sign(P[i])}</b></span>
       <span>S&amp;P 500 <b>${sign(Bm[i])}</b></span>
       <span>On the day <b class="${dayP >= 0 ? "pos" : "neg"}">${sign(dayP)}</b></span>`;
  }

  svg.addEventListener("pointermove", hover);
  svg.addEventListener("pointerleave", () => {
    const g = $("cross");
    if (g) g.style.display = "none";
    idle();
  });
  rangeBar.addEventListener("click", e => {
    const b = e.target.closest("button[data-r]");
    if (!b || b.disabled) return;
    active = b.dataset.r;
    [...rangeBar.querySelectorAll("button")].forEach(x => x.setAttribute("aria-pressed", x === b));
    draw();
  });

  draw();
}

/* ---- holdings ledger --------------------------------------------- */

function renderHoldings(state) {
  const positions = Array.isArray(state.positions) ? state.positions : [];
  const totals = state.totals || {};
  const total = totals.total_value;
  const invested = totals.invested_value;
  const count = totals.position_count != null ? totals.position_count : positions.length;

  $("holdcount").textContent =
    `${count} position${count === 1 ? "" : "s"} · `
    + `${pctPlain(total ? invested / total : null)} invested`;

  const holdings = $("holdings");
  const input = $("filter");
  const msg = $("filtermsg");
  const sortbar = $("sortbar");

  if (!positions.length) {
    $("filterbar").style.display = "none";
    sortbar.style.display = "none";
    holdings.innerHTML =
      `<p class="empty">No open positions — the portfolio is entirely in cash.</p>`;
    return;
  }

  const rowHTML = p => {
    const w = p.weight != null ? p.weight : 0;
    const pl = p.unrealized_pl_pct;
    const bar = Math.max(0, Math.min(100, (w / 0.07) * 100)).toFixed(1);

    let body;
    if (p.thesis == null) {
      // true of both current holdings — bought outside the system
      body = `<p class="predates">This holding predates the system's records. It
        was bought outside the pipeline, so no thesis, risk or opening rationale
        was recorded for it.</p>`;
    } else {
      const biz = p.business != null
        ? `<span class="notehead">The business</span><p class="biz">${esc(p.business)}</p>`
        : "";
      const opened = p.opened_at
        ? ` — opened ${fmtDateOnly(p.opened_at)}`
          + (p.avg_entry_price != null ? ` at ${money(p.avg_entry_price)}` : "")
        : "";
      const risk = p.risks != null
        ? `<span class="notehead">Risk</span><p class="risk">${esc(p.risks)}</p>`
        : "";
      body = `${biz}<span class="notehead">Thesis${opened}</span><p>${esc(p.thesis)}</p>${risk}`;
    }

    return `<details class="row">
      <summary class="line">
        <span class="tick">${esc(p.ticker)}</span>
        <span class="name">${esc(p.name || "")}</span>
        <span class="num">${pctPlain(w)}</span>
        <span class="num">${money(p.market_value)}</span>
        <span class="num ${clsOf(pl)}">${pctFrac(pl)}</span>
        <span class="bar"><span style="width:${bar}%"></span></span>
      </summary>
      <div class="note">${body}</div>
    </details>`;
  };

  // one view: filter, then sort, then render — kept together so the two cannot
  // fight each other (sorting a filtered list must keep the filter applied)
  const KEY = {
    tick: h => h.ticker || "", name: h => h.name || "",
    w: h => h.weight || 0, mv: h => h.market_value || 0,
    pl: h => (h.unrealized_pl_pct == null ? -Infinity : h.unrealized_pl_pct),
  };
  const TEXT = new Set(["tick", "name"]);
  let sortKey = "w", dir = "desc"; // biggest position first is the useful default

  function apply() {
    const q = input.value.trim().toLowerCase();
    let list = q
      ? positions.filter(h =>
          (h.ticker || "").toLowerCase().includes(q)
          || (h.name || "").toLowerCase().includes(q))
      : positions.slice();

    const get = KEY[sortKey], mult = dir === "asc" ? 1 : -1;
    list.sort((a, b) => TEXT.has(sortKey)
      ? mult * get(a).localeCompare(get(b))
      : mult * (get(a) - get(b)));

    holdings.innerHTML = list.map(rowHTML).join("");

    msg.textContent = !q ? ""
      : list.length ? `${list.length} of ${positions.length}`
      : `No holding matches “${input.value.trim()}”`;
    if (q && list.length === 1) {
      const d = holdings.querySelector("details");
      if (d) d.open = true;
    }

    sortbar.querySelectorAll("button").forEach(b => {
      if (b.dataset.k === sortKey) b.dataset.dir = dir;
      else delete b.dataset.dir;
      b.setAttribute("aria-label",
        `${b.textContent.replace(/[↑↓]/g, "").trim()} — sort `
        + `${b.dataset.k === sortKey && dir === "asc" ? "descending" : "ascending"}`);
    });
  }

  sortbar.addEventListener("click", e => {
    const b = e.target.closest("button[data-k]");
    if (!b) return;
    if (sortKey === b.dataset.k) dir = dir === "asc" ? "desc" : "asc";
    else { sortKey = b.dataset.k; dir = TEXT.has(sortKey) ? "asc" : "desc"; }
    apply();
  });
  input.addEventListener("input", apply);
  apply();
}

/* ---- blocked by rules ------------------------------------------- */

function renderBlocked(decisions) {
  const head = $("blockedHead");
  const colhead = $("blockedColhead");
  const box = $("blocked");

  if (!decisions) {
    head.textContent = "";
    colhead.style.display = "none";
    box.innerHTML =
      `<p class="empty">No decision cycle has run yet, so nothing has been
       proposed or blocked. The first weekly cycle will fill this in — this is
       the expected state, not an error.</p>`;
    return;
  }

  const rejected = (decisions.decisions || []).filter(d => d.status === "rejected");
  head.textContent = `${rejected.length} this cycle`;

  if (!rejected.length) {
    colhead.style.display = "none";
    box.innerHTML =
      `<p class="empty">Every proposed order passed the guardrails this cycle.
       Nothing was blocked.</p>`;
    return;
  }

  colhead.style.display = "";
  box.innerHTML = rejected.map(d => {
    const reason = d.rejection_reason || "";
    const ci = reason.indexOf(":");
    const tag = ci > 0 ? reason.slice(0, ci).trim() : "";
    const why = ci > 0 ? reason.slice(ci + 1).trim() : reason
      || "The pipeline recorded this order as rejected without a reason.";
    return `<div class="row">
      <div class="line">
        <span class="tick">${esc(d.ticker)}</span>
        <span class="name">${esc(d.action)} · blocked${tag ? `<span class="rule-tag">${esc(tag)}</span>` : ""}</span>
        <span class="num"></span>
        <span class="num">${d.notional != null ? money(d.notional) : "—"}</span>
        <span class="num neg">—</span>
      </div>
      <p class="why">${esc(why)}</p>
    </div>`;
  }).join("");
}

/* -------------------------------------------------------------------- */

main().catch(err => {
  console.error(err);
  fatal("the dashboard data", "could not be rendered because of an unexpected error");
});
