/* Quant Desk frontend — TradingView Lightweight Charts + live WebSocket + AI agent */
"use strict";

const LC = LightweightCharts;
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const TZ = -new Date().getTimezoneOffset() * 60; // show candles in local time
const C = { up: "#26a69a", down: "#ef5350", text: "#d6dae3", muted: "#7d8597", grid: "#1b2029", border: "#262c38" };
const INTERVALS = [["1m", "1m"], ["5m", "5m"], ["15m", "15m"], ["1h", "1H"], ["4h", "4H"], ["1d", "1D"], ["1w", "1W"]];
const SOURCE = {
  binance: ["live", "LIVE · Binance"],
  yahoo: ["delayed", "TERTUNDA · Yahoo"],
  demo: ["demo", "DEMO · data sintetis"],
};

const state = {
  symbol: "BTC-USD", interval: "1h", names: {}, groups: {}, quotes: {},
  candles: [], source: null, ws: null, analysis: null, account: null, currency: "USD", fx: 1,
  ind: new Set(["sma20", "sma50", "levels", "rsi"]),
  side: "BUY", chat: [], busy: false,
};

/* ------------------------------------------------------------------ formatting */
function decimals(p) { return p < 1 ? 5 : p < 10 ? 4 : p < 100000 ? 2 : 0; }
function fmt(p, d) {
  if (p == null || Number.isNaN(p)) return "—";
  return Number(p).toLocaleString("id-ID", { minimumFractionDigits: d ?? decimals(Math.abs(p)), maximumFractionDigits: d ?? decimals(Math.abs(p)) });
}
const pct = (x, d = 2) => (x == null ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`);
const rp = (x) => "Rp " + Math.round(x).toLocaleString("id-ID");
const cls = (x) => (x > 0 ? "up" : x < 0 ? "down" : "");
const vol = (v) => (v >= 1e9 ? (v / 1e9).toFixed(2) + "B" : v >= 1e6 ? (v / 1e6).toFixed(2) + "M" : v >= 1e3 ? (v / 1e3).toFixed(1) + "K" : v.toFixed(0));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : r.statusText);
  return body;
}

/* ------------------------------------------------------------------ indicators (client-side so they update live) */
function sma(v, n) { const o = Array(v.length).fill(null); let s = 0; for (let i = 0; i < v.length; i++) { s += v[i]; if (i >= n) s -= v[i - n]; if (i >= n - 1) o[i] = s / n; } return o; }
function ema(v, n) { const o = Array(v.length).fill(null); const k = 2 / (n + 1); let e = v[0]; for (let i = 0; i < v.length; i++) { e = i ? v[i] * k + e * (1 - k) : v[0]; o[i] = e; } return o; }
function stdev(v, n) { const m = sma(v, n); return v.map((_, i) => { if (m[i] == null) return null; let s = 0; for (let j = i - n + 1; j <= i; j++) s += (v[j] - m[i]) ** 2; return Math.sqrt(s / (n - 1)); }); }
function rsi(v, n = 14) {
  const o = Array(v.length).fill(null); let up = 0, dn = 0;
  for (let i = 1; i < v.length; i++) {
    const d = v[i] - v[i - 1]; const u = Math.max(d, 0), w = Math.max(-d, 0);
    up = i === 1 ? u : (up * (n - 1) + u) / n; dn = i === 1 ? w : (dn * (n - 1) + w) / n;
    if (i >= n) o[i] = dn === 0 ? 100 : 100 - 100 / (1 + up / dn);
  }
  return o;
}
function computeIndicators(rows) {
  const c = rows.map((r) => r.close);
  const m20 = sma(c, 20), sd = stdev(c, 20), e12 = ema(c, 12), e26 = ema(c, 26);
  const macd = c.map((_, i) => e12[i] - e26[i]); const sig = ema(macd, 9);
  const e200 = ema(c, 200).map((x, i) => (i >= 199 ? x : null));
  return {
    sma20: m20, sma50: sma(c, 50), ema200: e200,
    bbU: m20.map((m, i) => (m == null ? null : m + 2 * sd[i])), bbL: m20.map((m, i) => (m == null ? null : m - 2 * sd[i])),
    rsi: rsi(c), macd, macdSig: sig, macdHist: macd.map((m, i) => m - sig[i]),
  };
}

/* ------------------------------------------------------------------ chart */
const chart = LC.createChart($("#chart"), {
  autoSize: true,
  layout: { background: { type: "solid", color: "#0f1218" }, textColor: C.muted, fontSize: 11, panes: { separatorColor: C.border, separatorHoverColor: "#2962ff55" } },
  grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
  crosshair: { mode: LC.CrosshairMode.Normal, vertLine: { color: "#5b647a", labelBackgroundColor: "#2a303c" }, horzLine: { color: "#5b647a", labelBackgroundColor: "#2a303c" } },
  rightPriceScale: { borderColor: C.border },
  timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false, rightOffset: 8 },
});
const candleSeries = chart.addSeries(LC.CandlestickSeries, {
  upColor: C.up, downColor: C.down, wickUpColor: C.up, wickDownColor: C.down, borderVisible: false,
});
const volumeSeries = chart.addSeries(LC.HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "", lastValueVisible: false, priceLineVisible: false });
volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
const markers = LC.createSeriesMarkers(candleSeries, []);

const lineOpts = (color, extra = {}) => ({ color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, ...extra });
const overlays = {
  sma20: chart.addSeries(LC.LineSeries, lineOpts("#f5a524")),
  sma50: chart.addSeries(LC.LineSeries, lineOpts("#5b8cff")),
  ema200: chart.addSeries(LC.LineSeries, lineOpts("#c084fc", { lineWidth: 2 })),
  bbU: chart.addSeries(LC.LineSeries, lineOpts("#64748b", { lineStyle: LC.LineStyle.Dotted, lineWidth: 1 })),
  bbL: chart.addSeries(LC.LineSeries, lineOpts("#64748b", { lineStyle: LC.LineStyle.Dotted, lineWidth: 1 })),
};
let rsiSeries = null, macdSeries = null, priceLines = [];

function ensurePanes() {
  // RSI and MACD each live in their own pane below the price chart, created on demand.
  if (state.ind.has("rsi") && !rsiSeries) {
    const pane = chart.panes().length;
    rsiSeries = { line: chart.addSeries(LC.LineSeries, lineOpts("#a78bfa", { lastValueVisible: true }), pane) };
    rsiSeries.line.createPriceLine({ price: 70, color: "#ef535088", lineStyle: LC.LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
    rsiSeries.line.createPriceLine({ price: 30, color: "#26a69a88", lineStyle: LC.LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
  }
  if (!state.ind.has("rsi") && rsiSeries) { chart.removeSeries(rsiSeries.line); rsiSeries = null; }
  if (state.ind.has("macd") && !macdSeries) {
    const pane = chart.panes().length;
    macdSeries = {
      hist: chart.addSeries(LC.HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane),
      line: chart.addSeries(LC.LineSeries, lineOpts("#5b8cff"), pane),
      sig: chart.addSeries(LC.LineSeries, lineOpts("#f5a524"), pane),
    };
  }
  if (!state.ind.has("macd") && macdSeries) { Object.values(macdSeries).forEach((s) => chart.removeSeries(s)); macdSeries = null; }
  // drop panes left empty, then size the indicator panes
  for (let i = chart.panes().length - 1; i > 0; i--) if (!chart.panes()[i].getSeries().length) chart.removePane(i);
  chart.panes().forEach((p, i) => p.setStretchFactor(i === 0 ? 4 : 1));
}

const T = (t) => t + TZ;
const pts = (rows, arr) => rows.map((r, i) => (arr[i] == null ? { time: T(r.time) } : { time: T(r.time), value: arr[i] }));
const volPoint = (r) => ({ time: T(r.time), value: r.volume, color: r.close >= r.open ? "#26a69a55" : "#ef535055" });

function drawAll(fit) {
  const rows = state.candles;
  candleSeries.setData(rows.map((r) => ({ ...r, time: T(r.time) })));
  volumeSeries.setData(rows.map(volPoint));
  const ind = computeIndicators(rows);
  for (const [k, s] of Object.entries(overlays)) {
    const on = k.startsWith("bb") ? state.ind.has("bb") : state.ind.has(k);
    s.applyOptions({ visible: on });
    s.setData(pts(rows, ind[k]));
  }
  ensurePanes();
  if (rsiSeries) rsiSeries.line.setData(pts(rows, ind.rsi));
  if (macdSeries) {
    macdSeries.line.setData(pts(rows, ind.macd));
    macdSeries.sig.setData(pts(rows, ind.macdSig));
    macdSeries.hist.setData(rows.map((r, i) => ({ time: T(r.time), value: ind.macdHist[i], color: ind.macdHist[i] >= 0 ? "#26a69a99" : "#ef535099" })));
  }
  const last = rows.at(-1)?.close ?? 1;
  const d = decimals(last);
  candleSeries.applyOptions({ priceFormat: { type: "price", precision: d, minMove: 1 / 10 ** d } });
  overlays.sma20.applyOptions({ priceFormat: { type: "price", precision: d, minMove: 1 / 10 ** d } });
  if (fit) {
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, rows.length - 160), to: rows.length + 8 });
  }
  drawMarkers();
  drawLevels();
  updateLegend();
}

function updateLive(newRows) {
  const rows = state.candles;
  let touched = new Set();
  for (const r of newRows) {
    const last = rows.at(-1);
    if (!last || r.time > last.time) { rows.push(r); touched.add(rows.length - 1); }
    else if (r.time === last.time) { rows[rows.length - 1] = r; touched.add(rows.length - 1); }
  }
  if (!touched.size) return;
  const ind = computeIndicators(rows);
  for (const i of [...touched].sort((a, b) => a - b)) {
    const r = rows[i];
    candleSeries.update({ ...r, time: T(r.time) });
    volumeSeries.update(volPoint(r));
    for (const [k, s] of Object.entries(overlays)) if (ind[k][i] != null) s.update({ time: T(r.time), value: ind[k][i] });
    if (rsiSeries && ind.rsi[i] != null) rsiSeries.line.update({ time: T(r.time), value: ind.rsi[i] });
    if (macdSeries) {
      macdSeries.line.update({ time: T(r.time), value: ind.macd[i] });
      macdSeries.sig.update({ time: T(r.time), value: ind.macdSig[i] });
      macdSeries.hist.update({ time: T(r.time), value: ind.macdHist[i], color: ind.macdHist[i] >= 0 ? "#26a69a99" : "#ef535099" });
    }
  }
  updateHeader();
  updateLegend();
}

function drawLevels() {
  priceLines.forEach((l) => candleSeries.removePriceLine(l));
  priceLines = [];
  const a = state.analysis;
  if (!state.ind.has("levels") || !a || a.symbol !== state.symbol || !a.levels) return;
  for (const p of a.levels.resistance.slice(0, 2)) priceLines.push(candleSeries.createPriceLine({ price: p, color: "#ef5350aa", lineStyle: LC.LineStyle.Dashed, lineWidth: 1, title: "R" }));
  for (const p of a.levels.support.slice(0, 2)) priceLines.push(candleSeries.createPriceLine({ price: p, color: "#26a69aaa", lineStyle: LC.LineStyle.Dashed, lineWidth: 1, title: "S" }));
}

function drawMarkers() {
  const rows = state.candles;
  if (!state.account || !rows.length) return markers.setMarkers([]);
  const m = [];
  for (const j of state.account.journal) {
    if (j.sym !== state.symbol || !j.time) continue;
    const t = Date.parse(j.time) / 1000;
    let bar = rows[0].time;
    for (const r of rows) { if (r.time <= t) bar = r.time; else break; }
    if (t < rows[0].time) continue;
    const buy = j.side === "BUY";
    m.push({ time: T(bar), position: buy ? "belowBar" : "aboveBar", color: buy ? C.up : C.down, shape: buy ? "arrowUp" : "arrowDown", text: `${buy ? "B" : "S"} ${j.qty}` });
  }
  markers.setMarkers(m.sort((a, b) => a.time - b.time));
}

function updateLegend(param) {
  const hovered = param?.seriesData?.get(candleSeries);
  const raw = hovered ? state.candles.find((c) => T(c.time) === hovered.time) ?? hovered : state.candles.at(-1);
  if (!raw) return;
  const d = decimals(raw.close), ch = (raw.close - raw.open) / raw.open;
  $("#legend").innerHTML =
    `O <b>${fmt(raw.open, d)}</b> H <b>${fmt(raw.high, d)}</b> L <b>${fmt(raw.low, d)}</b> C <b class="${cls(ch)}">${fmt(raw.close, d)}</b> <span class="${cls(ch)}">${pct(ch)}</span><br>` +
    `Vol <b>${vol(raw.volume ?? 0)}</b>` +
    (state.ind.has("sma20") ? ` · <span style="color:#f5a524">SMA20</span>` : "") +
    (state.ind.has("sma50") ? ` · <span style="color:#5b8cff">SMA50</span>` : "") +
    (state.ind.has("ema200") ? ` · <span style="color:#c084fc">EMA200</span>` : "");
}
chart.subscribeCrosshairMove((p) => updateLegend(p.time ? p : null));

/* ------------------------------------------------------------------ header & source badge */
function updateHeader() {
  const last = state.candles.at(-1);
  if (!last) return;
  const q = state.quotes[state.symbol];
  const prevClose = q ? q.price / (1 + q.chg) : state.candles.at(-2)?.close;
  const chg = prevClose ? last.close / prevClose - 1 : 0;
  $("#symPrice").textContent = fmt(last.close);
  $("#symPrice").className = "big " + cls(chg);
  $("#symChg").className = "chg " + cls(chg);
  $("#symChg").textContent = `${chg >= 0 ? "+" : ""}${fmt(last.close - prevClose)} (${pct(chg)})`;
  document.title = `${state.symbol} ${fmt(last.close)} · Quant Desk`;
  const row = document.querySelector(`.wl-row[data-s="${CSS.escape(state.symbol)}"]`);
  if (row) setRowPrice(row, last.close, chg);
}

function setSource(src) {
  const [k, label] = SOURCE[src] ?? ["", src];
  const b = $("#sourceBadge");
  b.className = "badge " + k;
  b.textContent = label;
  $("#footerSource").textContent = src === "demo"
    ? "Mode DEMO: harga sintetis untuk latihan, bukan harga pasar asli"
    : src === "yahoo" ? "Saham/indeks/forex: Yahoo Finance, biasanya tertunda 15–20 menit" : "Kripto: Binance real-time";
}

/* ------------------------------------------------------------------ loading a symbol */
async function loadSymbol(symbol, interval = state.interval) {
  state.symbol = symbol; state.interval = interval;
  location.hash = `${encodeURIComponent(symbol)}/${interval}`;
  $$(".intervals button").forEach((b) => b.classList.toggle("active", b.dataset.iv === interval));
  $$(".wl-row").forEach((r) => r.classList.toggle("active", r.dataset.s === symbol));
  $("#symbolInput").value = "";
  $("#chartLoading").classList.add("show");
  try {
    const d = await api(`/api/candles?symbol=${encodeURIComponent(symbol)}&interval=${interval}`);
    if (state.symbol !== symbol || state.interval !== interval) return; // user switched meanwhile
    state.candles = d.candles; state.source = d.source; state.currency = d.currency;
    api(`/api/fx?symbol=${encodeURIComponent(symbol)}`).then((f) => { if (f.symbol === state.symbol) state.fx = f.fx_to_idr; }).catch(() => {});
    $("#symName").textContent = d.name;
    $("#symTicker").textContent = d.name === symbol ? "" : symbol;
    $("#symMarket").textContent = `${marketOf(symbol)} · ${d.currency}`;
    $("#orderSym").textContent = symbol;
    setSource(d.source);
    drawAll(true);
    updateHeader();
    connectLive();
  } catch (e) {
    $("#symName").textContent = "Gagal memuat " + symbol;
    $("#symPrice").textContent = "";
    $("#symChg").textContent = e.message;
  } finally {
    $("#chartLoading").classList.remove("show");
  }
  loadAnalysis();
}

function connectLive() {
  if (state.ws) { state.ws.onclose = null; state.ws.close(); }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/candles?symbol=${encodeURIComponent(state.symbol)}&interval=${state.interval}`);
  const me = { symbol: state.symbol, interval: state.interval };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.symbol === state.symbol && m.interval === state.interval) updateLive(m.candles);
  };
  ws.onclose = () => setTimeout(() => { if (me.symbol === state.symbol && me.interval === state.interval) connectLive(); }, 3000);
  state.ws = ws;
}

function marketOf(sym) {
  for (const [g, items] of Object.entries(state.groups)) if (items.some((i) => i.symbol === sym)) return g;
  return "Lainnya";
}

/* ------------------------------------------------------------------ watchlist */
function renderWatchlist() {
  const wl = $("#watchlist");
  wl.innerHTML = "";
  for (const [g, items] of Object.entries(state.groups)) {
    const head = document.createElement("div");
    head.className = "wl-group"; head.textContent = g;
    const box = document.createElement("div");
    head.onclick = () => { head.classList.toggle("collapsed"); box.hidden = !box.hidden; };
    for (const it of items) {
      const row = document.createElement("div");
      row.className = "wl-row"; row.dataset.s = it.symbol;
      row.innerHTML = `<div class="t">${esc(it.symbol.replace(".JK", "").replace("=X", "").replace("=F", ""))}</div><div class="p">—</div><div class="n">${esc(it.name)}</div><div class="c"></div>`;
      row.onclick = () => loadSymbol(it.symbol);
      box.appendChild(row);
    }
    wl.append(head, box);
  }
}
function setRowPrice(row, price, chg) {
  const p = row.querySelector(".p"), c = row.querySelector(".c");
  const old = Number(row.dataset.price);
  const txt = fmt(price);
  if (p.textContent !== txt) {
    if (old) { row.classList.remove("flash-up", "flash-down"); void row.offsetWidth; row.classList.add(price >= old ? "flash-up" : "flash-down"); }
    p.textContent = txt;
  }
  row.dataset.price = price;
  c.textContent = pct(chg); c.className = "c " + cls(chg);
}
async function refreshQuotes() {
  try {
    state.quotes = await api("/api/quotes");
    for (const [s, q] of Object.entries(state.quotes)) {
      if (!q || s === state.symbol) continue;
      const row = document.querySelector(`.wl-row[data-s="${CSS.escape(s)}"]`);
      if (row) setRowPrice(row, q.price, q.chg);
    }
    updateHeader();
  } catch { /* keep last values */ }
  $("#wlClock").textContent = new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/* ------------------------------------------------------------------ analysis tab */
async function loadAnalysis() {
  const sym = state.symbol, iv = ["1m", "5m"].includes(state.interval) ? "15m" : state.interval;
  const body = $("#analysisBody");
  body.innerHTML = `<div class="empty">Menganalisis ${esc(sym)}…</div>`;
  try {
    const [a, bt] = await Promise.all([
      api(`/api/analysis?symbol=${encodeURIComponent(sym)}&interval=${iv}`),
      api(`/api/backtest?symbol=${encodeURIComponent(sym)}&interval=1d`),
    ]);
    if (sym !== state.symbol) return;
    state.analysis = a;
    drawLevels();
    if (a.error) { body.innerHTML = `<div class="empty">${esc(a.error)}</div>`; return; }
    const i = a.indicators, r = a.risk, d = decimals(a.price);
    const biasCls = a.bias === "BULLISH" ? "up" : a.bias === "BEARISH" ? "down" : "";
    const names = { buy_hold: "Buy & hold", sma: "SMA cross", momentum: "Momentum", rsi: "RSI revert" };
    body.innerHTML = `
      <div class="card">
        <h4>Bias teknikal · ${esc(iv)}</h4>
        <div class="bias"><span class="tag ${biasCls}">${a.bias}</span><span class="muted">${Math.round(a.bias_score * 100)}% sinyal positif</span></div>
        <div class="gauge"><i style="left:${a.bias_score * 100}%"></i></div>
      </div>
      <div class="card checks"><h4>Checklist</h4>
        ${Object.entries(a.checks).map(([k, v]) => `<div>${v == null ? "⚪" : v ? "🟢" : "🔴"} ${esc(k)}</div>`).join("")}
      </div>
      <div class="card"><h4>Indikator</h4><div class="kv">
        <span>RSI 14</span><span>${i.rsi14.toFixed(1)}</span>
        <span>MACD / signal</span><span>${fmt(i.macd, d)} / ${fmt(i.macd_signal, d)}</span>
        <span>SMA 20 / 50</span><span>${fmt(i.sma20, d)} / ${fmt(i.sma50, d)}</span>
        <span>EMA 200</span><span>${fmt(i.ema200, d)}</span>
        <span>Bollinger</span><span>${fmt(i.bb_lower, d)} – ${fmt(i.bb_upper, d)}</span>
        <span>ATR 14</span><span>${fmt(i.atr14, d)}</span>
      </div></div>
      <div class="card"><h4>Support & resistance</h4><div class="levels">
        <div><div class="muted small">Resistance</div>${a.levels.resistance.map((x) => `<div class="r">${fmt(x, d)}</div>`).join("") || "—"}</div>
        <div><div class="muted small">Support</div>${a.levels.support.map((x) => `<div class="s">${fmt(x, d)}</div>`).join("") || "—"}</div>
      </div></div>
      <div class="card"><h4>Risiko</h4><div class="kv">
        <span>Rezim volatilitas</span><span>${esc(r.regime)}</span>
        <span>Volatilitas sekarang / rata2</span><span>${pct(r.vol_annual_now, 1)} / ${pct(r.vol_annual_avg, 1)}</span>
        <span>VaR 95% per bar</span><span class="down">-${(r.var95_per_bar * 100).toFixed(2)}%</span>
        <span>CVaR 95% per bar</span><span class="down">-${(r.cvar95_per_bar * 100).toFixed(2)}%</span>
        <span>Stop 2×ATR (beli)</span><span>${fmt(r.atr_stop_long, d)}</span>
      </div></div>
      <div class="card"><h4>Backtest harian (setelah biaya)</h4>
        <table class="bt"><tr><th>Strategi</th><th>Return</th><th>CAGR</th><th>Sharpe</th><th>MaxDD</th></tr>
        ${Object.entries(bt.results).map(([k, s]) => `<tr><td>${names[k] ?? k}</td><td class="${cls(s.total_return)}">${pct(s.total_return, 1)}</td><td>${s.cagr == null ? "—" : pct(s.cagr, 1)}</td><td>${s.sharpe?.toFixed(2)}</td><td class="down">${pct(s.max_drawdown, 1)}</td></tr>`).join("")}
        </table>
        <p class="note">${bt.bars} bar data. Strategi yang tidak mengalahkan buy & hold setelah biaya biasanya tidak layak dipakai.</p>
      </div>
      <div class="card"><h4>Simulasi Monte Carlo · 1 tahun</h4>
        <div id="mcOut" class="note">3000 kemungkinan masa depan dari pola return historis.</div>
        <button class="btn" id="mcBtn" style="margin-top:8px">Jalankan simulasi</button>
      </div>
      <p class="note">Sumber: ${esc(a.source)}${a.delayed ? " (tertunda)" : ""}. Indikator menggambarkan masa lalu, bukan ramalan.</p>`;
    $("#mcBtn").onclick = runMonteCarlo;
  } catch (e) {
    body.innerHTML = `<div class="empty">Analisis gagal: ${esc(e.message)}</div>`;
  }
}
async function runMonteCarlo() {
  const out = $("#mcOut");
  out.textContent = "Mensimulasikan…";
  const m = await api(`/api/montecarlo?symbol=${encodeURIComponent(state.symbol)}&strategy=buy_hold&horizon=252`);
  out.innerHTML = `<div class="kv">
    <span>Median (×modal)</span><span>${m.median.toFixed(2)}×</span>
    <span>Skenario buruk 5%</span><span class="down">${m.p5.toFixed(2)}×</span>
    <span>Skenario bagus 95%</span><span class="up">${m.p95.toFixed(2)}×</span>
    <span>Peluang rugi</span><span>${pct(m.prob_loss, 1).replace("+", "")}</span>
    <span>Peluang rugi &gt;50%</span><span>${pct(m.prob_lose_50pct, 1).replace("+", "")}</span></div>`;
}

/* ------------------------------------------------------------------ trade tab */
async function loadAccount() {
  try { state.account = await api("/api/account"); } catch { return; }
  const a = state.account;
  $("#accEquity").textContent = rp(a.equity);
  $("#accRet").innerHTML = `<span class="${cls(a.equity - a.start)}">${pct(a.equity / a.start - 1)}</span> <span class="muted">dari Rp 10 jt</span>`;
  $("#accCash").textContent = rp(a.cash);
  $("#accPnl").innerHTML = `<span class="${cls(a.realized_pnl)}">${rp(a.realized_pnl)}</span>`;
  $("#accWin").textContent = a.journal.some((j) => j.pnl != null) ? pct(a.win_rate, 0).replace("+", "") : "—";
  $("#positions").innerHTML = a.positions.length ? a.positions.map((p) => `
    <div class="pos"><b>${esc(p.symbol)}</b><span class="${cls(p.pnl)}">${rp(p.pnl)}</span>
    <span class="muted small">${p.qty} unit @ ${rp(p.avg_cost)}</span><span class="muted small">nilai ${rp(p.value)}</span></div>`).join("")
    : `<div class="empty">Belum ada posisi.</div>`;
  $("#journal").innerHTML = a.journal.length ? a.journal.slice(0, 30).map((j) => `
    <div class="j"><span><b class="${j.side === "BUY" ? "up" : "down"}">${j.side === "BUY" ? "BELI" : "JUAL"}</b> ${esc(j.sym)} · ${j.qty} @ ${j.native_price != null && j.currency !== "IDR" ? fmt(j.native_price) + " " + esc(j.currency) : rp(j.price)}</span>
    <span class="${cls(j.pnl)}">${j.pnl == null ? "" : rp(j.pnl)}</span>
    <span class="why">“${esc(j.reason)}” · ${j.time ? new Date(j.time).toLocaleString("id-ID") : ""}</span></div>`).join("")
    : `<div class="empty">Jurnal kosong. Setiap order tercatat di sini beserta alasannya.</div>`;
  drawMarkers();
}

function setSide(side) {
  state.side = side;
  $$(".side-switch button").forEach((b) => b.classList.toggle("active", b.dataset.side === side));
  const s = $("#orderSubmit");
  s.className = "submit " + (side === "BUY" ? "buy" : "sell");
  s.textContent = side === "BUY" ? "Beli di harga pasar" : "Jual di harga pasar";
}

function suggestSize() {
  const a = state.analysis, acc = state.account, hint = $("#sizeHint");
  if (state.side === "SELL") {
    const pos = acc?.positions.find((p) => p.symbol === state.symbol);
    $("#orderQty").value = pos ? pos.qty : 0;
    hint.textContent = pos ? "Diisi dengan seluruh posisimu." : "Kamu belum punya posisi di aset ini.";
    return;
  }
  if (!a || a.symbol !== state.symbol || !acc) { hint.textContent = "Tunggu analisis selesai dimuat…"; return; }
  // account is in Rupiah: convert the asset price with the latest FX rate
  const fx = state.fx, price = state.candles.at(-1).close * fx, stop = a.risk.atr_stop_long, per = (state.candles.at(-1).close - stop) * fx;
  let units = per > 0 ? (acc.equity * 0.01) / per : 0;
  units = Math.min(units, (acc.equity * 0.25) / price, acc.cash / (price * 1.0015));
  units = units >= 10 ? Math.floor(units) : Math.floor(units * 1e4) / 1e4;   // fractional units for expensive assets
  $("#orderQty").value = units;
  const fxNote = state.currency === "IDR" ? "" : ` Kurs 1 ${state.currency} = ${rp(fx)}.`;
  hint.innerHTML = `Stop-loss di <b>${fmt(stop)} ${state.currency}</b> (2×ATR). Jika kena, rugi ±${rp(units * per)} ≈ 1% akun. Posisi maks 25% akun.${fxNote}`;
}

async function submitOrder(ev) {
  ev.preventDefault();
  const msg = $("#orderMsg");
  const qty = Number($("#orderQty").value), reason = $("#orderReason").value.trim();
  if (!(qty > 0)) { msg.className = "hint err"; msg.textContent = "Isi jumlah unit lebih dari 0."; return; }
  if (reason.length < 3) { msg.className = "hint err"; msg.textContent = "Tulis alasanmu dulu. Jurnal adalah cara trader belajar dari kesalahan."; return; }
  try {
    const r = await api("/api/order", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol: state.symbol, side: state.side, qty, reason }) });
    msg.className = "hint ok";
    msg.textContent = `${state.side === "BUY" ? "Beli" : "Jual"} ${qty} ${state.symbol} @ ${fmt(r.price)} ${r.currency}` + (r.currency === "IDR" ? "" : ` (${rp(r.price_idr)})`) + " tercatat.";
    $("#orderReason").value = "";
    await loadAccount();
  } catch (e) { msg.className = "hint err"; msg.textContent = e.message; }
}

/* ------------------------------------------------------------------ AI agent */
const md = (t) => DOMPurify.sanitize(marked.parse(t ?? "", { breaks: true }));
const TOOL_LABEL = {
  get_market_overview: "pasar dunia", get_technical_analysis: "analisis teknikal", run_backtest: "backtest",
  monte_carlo_risk: "Monte Carlo", position_size: "ukuran posisi", get_paper_account: "akun latihan",
};

function addMsg(role, html) {
  const el = document.createElement("div");
  el.className = "msg " + role;
  el.innerHTML = html;
  $("#chatLog").appendChild(el);
  $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
  return el;
}

async function sendChat(text) {
  if (state.busy || !text.trim()) return;
  state.busy = true; $("#chatSend").disabled = true;
  state.chat.push({ role: "user", content: text });
  addMsg("user", esc(text).replace(/\n/g, "<br>"));
  const el = addMsg("assistant", `<div class="tools"></div><div class="content"><span class="typing"><span></span><span></span><span></span></span></div>`);
  const tools = el.querySelector(".tools"), content = el.querySelector(".content");
  let acc = "";
  try {
    const r = await fetch("/api/agent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: state.chat, symbol: state.symbol, interval: state.interval }) });
    const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!line.startsWith("data:")) continue;
        const ev = JSON.parse(line.slice(5));
        if (ev.type === "tool") {
          const sym = ev.input?.symbol ? ` ${ev.input.symbol}` : ev.input?.group ? ` ${ev.input.group}` : "";
          tools.insertAdjacentHTML("beforeend", `<span class="tool-chip">🔧 ${TOOL_LABEL[ev.name] ?? ev.name}${esc(sym)}</span>`);
        } else if (ev.type === "text") {
          acc += ev.text; content.innerHTML = md(acc);
        } else if (ev.type === "error") {
          el.classList.add("error");
          content.innerHTML = `<b>AI agent error.</b> ${esc(ev.text)}<br><span class="small muted">Cek ANTHROPIC_API_KEY dan koneksi internet.</span>`;
        }
        $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
      }
    }
  } catch (e) {
    el.classList.add("error"); content.textContent = "Gagal menghubungi server: " + e.message;
  }
  if (acc) state.chat.push({ role: "assistant", content: acc });
  else state.chat.pop(); // keep history valid (user/assistant alternating)
  state.busy = false; $("#chatSend").disabled = false;
}

/* ------------------------------------------------------------------ wiring */
function wire() {
  $("#intervals").innerHTML = INTERVALS.map(([iv, label]) => `<button data-iv="${iv}">${label}</button>`).join("");
  $$(".intervals button").forEach((b) => (b.onclick = () => loadSymbol(state.symbol, b.dataset.iv)));
  $$(".toggles button").forEach((b) => {
    b.classList.toggle("on", state.ind.has(b.dataset.ind));
    b.onclick = () => {
      const k = b.dataset.ind;
      state.ind.has(k) ? state.ind.delete(k) : state.ind.add(k);
      b.classList.toggle("on", state.ind.has(k));
      drawAll(false);
    };
  });
  $$(".tabs button").forEach((b) => (b.onclick = () => {
    $$(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab-body").forEach((x) => x.classList.toggle("active", x.id === "tab-" + b.dataset.tab));
    if (b.dataset.tab === "trade") loadAccount();
  }));
  const inp = $("#symbolInput");
  inp.addEventListener("change", () => { const v = inp.value.trim(); if (v) loadSymbol(v.split(" ")[0].toUpperCase()); });
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.dispatchEvent(new Event("change")); });

  $$(".side-switch button").forEach((b) => (b.onclick = () => setSide(b.dataset.side)));
  $("#sizeBtn").onclick = suggestSize;
  $("#orderForm").onsubmit = submitOrder;
  $("#resetAcct").onclick = async () => {
    if (!confirmReset()) return;
    await api("/api/account/reset", { method: "POST" }); loadAccount();
  };

  $("#chatForm").onsubmit = (e) => { e.preventDefault(); const t = $("#chatInput").value; $("#chatInput").value = ""; sendChat(t); };
  $("#chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#chatForm").requestSubmit(); } });
  $$("#quick button").forEach((b) => (b.onclick = () => sendChat(b.dataset.q)));
}
// inline two-click confirmation instead of a blocking browser dialog
let resetArmed = 0;
function confirmReset() {
  const b = $("#resetAcct");
  if (Date.now() - resetArmed < 4000) { b.textContent = "reset akun"; resetArmed = 0; return true; }
  resetArmed = Date.now(); b.textContent = "klik lagi untuk reset";
  setTimeout(() => { b.textContent = "reset akun"; }, 4000);
  return false;
}

async function init() {
  wire();
  const [cfg, groups] = await Promise.all([api("/api/config"), api("/api/markets")]);
  state.groups = groups;
  for (const items of Object.values(groups)) for (const i of items) state.names[i.symbol] = i.name;
  $("#symbolList").innerHTML = Object.entries(state.names).map(([s, n]) => `<option value="${esc(s)}">${esc(n)}</option>`).join("");
  const ai = $("#aiBadge");
  ai.classList.toggle("on", cfg.ai === "claude");
  ai.textContent = cfg.ai === "claude" ? `AI · ${cfg.model}` : "AI · offline";
  ai.title = cfg.ai === "claude" ? "AI agent memakai Claude" : "Set ANTHROPIC_API_KEY untuk AI agent penuh";
  renderWatchlist();
  const [hs, hi] = decodeURIComponent(location.hash.slice(1)).split("/");
  await loadSymbol(hs || state.symbol, INTERVALS.some(([i]) => i === hi) ? hi : state.interval);
  refreshQuotes(); loadAccount();
  setInterval(refreshQuotes, cfg.data_mode === "demo" ? 5000 : 15000);
  setInterval(loadAccount, 30000);
  setInterval(() => { if (state.analysis?.symbol === state.symbol) loadAnalysis(); }, 120000);
}
init();
