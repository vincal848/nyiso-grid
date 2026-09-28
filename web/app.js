/* NYISO Grid dashboard — plain JS over /api/*. */
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const api = (p) => fetch(p).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status} ${p}`))));
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const TZ = "America/New_York";
const fmtHM = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
const fmtFull = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ, month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const hm = (iso) => fmtHM.format(new Date(iso));
const num = (v, d = 0) => (v == null ? "–" : v.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
const addDays = (s, n) => { const d = new Date(s + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };

const INTERNAL_ZONES = ["WEST", "GENESE", "CENTRL", "NORTH", "MHK VL", "CAPITL", "HUD VL", "MILLWD", "DUNWOD", "N.Y.C.", "LONGIL"];
// Fuel stack bottom -> top. Order validated for adjacent CVD separation (light + dark).
const FUEL_STACK = [
  ["Nuclear", "--f-nuclear"], ["Dual Fuel", "--f-dual"], ["Hydro", "--f-hydro"], ["Natural Gas", "--f-gas"],
  ["Other Fossil Fuels", "--f-ofossil"], ["BTM Solar", "--f-btm"], ["Other Renewables", "--f-oren"], ["Wind", "--f-wind"],
];
// Price scale (GridStatus-style breakpoints), diverging blue <- gray 0 -> red.
const PRICE_STOPS = () => [
  [-40, css("--d-neg2")], [-10, css("--d-neg1")], [0, css("--d-mid")],
  [50, css("--d-pos1")], [100, css("--d-pos2")], [225, css("--d-pos3")],
];

const state = {
  date: null, min: null, max: null, tab: "conditions",
  summary: null, fuel: null, zones: null, nodes: null, nodeMarket: "rt5", scrub: 0,
  constraints: null, conMkt: "DA", trendDays: "365", trends: null,
};
const charts = {};

// ---------------------------------------------------------------- echarts base
function chart(id) {
  if (!charts[id]) charts[id] = echarts.init(document.getElementById(id), null, { renderer: "canvas" });
  return charts[id];
}
function base(extra = {}) {
  const ink2 = css("--ink-2"), muted = css("--muted"), grid = css("--grid"), axis = css("--axis");
  return {
    animation: false,
    textStyle: { fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif", color: ink2 },
    grid: { left: 52, right: 16, top: 16, bottom: 64 },
    tooltip: {
      trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--border"),
      textStyle: { color: css("--ink"), fontSize: 12 }, axisPointer: { type: "line", lineStyle: { color: axis } },
    },
    legend: { bottom: 0, textStyle: { color: ink2 }, itemWidth: 12, itemHeight: 12, icon: "roundRect" },
    xAxis: { type: "category", axisLine: { lineStyle: { color: axis } }, axisTick: { show: false },
             axisLabel: { color: muted, hideOverlap: true }, splitLine: { show: false } },
    yAxis: { type: "value", axisLabel: { color: muted }, splitLine: { lineStyle: { color: grid } } },
    ...extra,
  };
}
const line = (name, data, color, o = {}) => ({
  name, type: "line", data, showSymbol: false, lineStyle: { width: 2, color }, itemStyle: { color }, ...o,
});

// ---------------------------------------------------------------- date control
function setDate(d) {
  if (!d) return;
  if (d < state.min) d = state.min;
  if (d > state.max) d = state.max;
  state.date = d;
  $("#d-input").value = d;
  const u = new URL(location); u.searchParams.set("date", d); history.replaceState(null, "", u);
  state.summary = state.fuel = state.zones = state.nodes = state.constraints = null;
  render();
}
$("#d-first").onclick = () => setDate(state.min);
$("#d-prev").onclick = () => setDate(addDays(state.date, -1));
$("#d-next").onclick = () => setDate(addDays(state.date, 1));
$("#d-last").onclick = () => setDate(state.max);
$("#d-input").onchange = (e) => setDate(e.target.value);

$$(".tabs > button").forEach((b) => (b.onclick = () => {
  $$(".tabs > button").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + b.dataset.tab));
  state.tab = b.dataset.tab;
  const u = new URL(location); u.searchParams.set("tab", state.tab); history.replaceState(null, "", u);
  if (state.date) render();
  setTimeout(() => Object.values(charts).forEach((c) => c.resize()), 0);
}));

function render() {
  const f = { conditions: renderConditions, pricing: renderPricing, constraints: renderConstraints, trends: renderTrends,
              signal: () => window.renderSignal(state.date) }[state.tab];
  f().catch((e) => console.error(e));
}

// ================================================================ CONDITIONS
async function renderConditions() {
  const d = state.date;
  const [summary, fuel, zones, nodes] = await Promise.all([
    state.summary || api(`/api/summary?date=${d}`),
    state.fuel || api(`/api/fuelmix?date=${d}`),
    state.zones || api(`/api/prices/zones?date=${d}`),
    state.nodes || api(`/api/prices/nodes?date=${d}&market=${state.nodeMarket}`),
  ]);
  if (d !== state.date) return;
  Object.assign(state, { summary, fuel, zones, nodes });
  drawFuel();
  setupScrubber();  // KPIs + chart marker now; map layers update once the map is ready
}

function drawFuel() {
  const { times, series } = state.fuel;
  const c = chart("c-fuel");
  const surface = css("--surface");
  c.setOption(base({
    tooltip: { ...base().tooltip, valueFormatter: (v) => (v == null ? "–" : `${num(v)} MW`) },
    xAxis: { ...base().xAxis, data: times.map(hm), boundaryGap: false },
    yAxis: { ...base().yAxis, axisLabel: { color: css("--muted"), formatter: (v) => `${v / 1000}` }, name: "GW",
             nameTextStyle: { color: css("--muted") } },
    series: FUEL_STACK.map(([name, v], i) => ({
      name, type: "line", stack: "mix", data: series[name] || [], showSymbol: false, smooth: false,
      // surface-colored seam between stacked fills
      lineStyle: { width: 1, color: surface }, areaStyle: { color: css(v), opacity: 1 }, itemStyle: { color: css(v) },
      emphasis: { disabled: true },
      ...(i === 0 ? { markLine: { symbol: "none", silent: true, animation: false, data: [], label: { show: false },
                                  lineStyle: { color: css("--ink-2"), type: "dashed", width: 1 } } } : {}),
    })),
  }), true);
}

function setupScrubber() {
  const { nodes } = state;
  const r = $("#scrub");
  r.max = Math.max(0, nodes.times.length - 1);
  state.scrub = Number(r.max);
  r.value = r.max;
  const note = nodes.market !== nodes.requested ? "5-min nodal data unavailable for this day — showing hourly RT" : "";
  $("#scrub-note").textContent = note;
  applyScrub();
}
$("#scrub").oninput = (e) => { state.scrub = Number(e.target.value); applyScrub(); };

let playTimer = null;
$("#scrub-play").onclick = () => {
  if (playTimer) { clearInterval(playTimer); playTimer = null; $("#scrub-play").innerHTML = "&#9654;"; return; }
  $("#scrub-play").innerHTML = "&#10074;&#10074;";
  if (state.scrub >= Number($("#scrub").max)) state.scrub = 0;
  playTimer = setInterval(() => {
    const max = Number($("#scrub").max);
    if (state.scrub >= max) { $("#scrub-play").click(); return; }
    state.scrub += 1; $("#scrub").value = state.scrub; applyScrub();
  }, 120);
};

$$('input[name="mkt"]').forEach((el) => (el.onchange = async () => {
  state.nodeMarket = el.value;
  state.nodes = await api(`/api/prices/nodes?date=${state.date}&market=${state.nodeMarket}`);
  setupScrubber();
}));
$("#zone-shade").onchange = (e) => mapLoaded && map.setLayoutProperty("zones-fill", "visibility", e.target.checked ? "visible" : "none");

function nearestIdx(isoList, iso) {
  // last index with time <= iso
  const t = Date.parse(iso);
  let lo = 0, hi = isoList.length - 1, ans = 0;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (Date.parse(isoList[m]) <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans;
}

function applyScrub() {
  const { nodes } = state;
  if (!nodes.times.length) { $("#scrub-time").textContent = "no data"; return; }
  const t = nodes.times[state.scrub];
  $("#scrub-time").textContent = fmtFull.format(new Date(t));

  if (mapLoaded) updateMap(t);
  updateKpis(t);
}

function updateMap(t) {
  const { nodes, zones } = state;
  const vals = nodes.values[state.scrub];
  const pidx = new Map(nodes.ptids.map((p, i) => [p, i]));
  nodeFC.features.forEach((f) => {
    const i = pidx.get(f.properties.ptid);
    f.properties.price = i == null ? null : vals[i];
  });
  map.getSource("nodes").setData(nodeFC);

  // zones: 5-min RT or hourly DA at this time
  const zp = {};
  if (nodes.requested === "da" || nodes.market !== "rt5") {
    const key = nodes.market === "da" ? "da_lbmp" : "rt_lbmp";
    const hours = [...new Set(zones.hourly.map((r) => r.ts_utc))];
    const h = hours[nearestIdx(hours, t)];
    zones.hourly.filter((r) => r.ts_utc === h).forEach((r) => (zp[r.zone] = r[key]));
  } else {
    const ts = [...new Set(zones.rt5.map((r) => r.ts_utc))];
    const at = ts[nearestIdx(ts, t)];
    zones.rt5.filter((r) => r.ts_utc === at).forEach((r) => (zp[r.zone] = r.lbmp));
  }
  zoneFC.features.forEach((f) => (f.properties.price = zp[f.properties.zone] ?? null));
  map.getSource("zones").setData(zoneFC);
}

function updateKpis(t) {
  const { summary, fuel } = state;
  const s = summary.series;
  if (s.length) {
    // latest posted value at or before the scrubber time (datasets post with different lags)
    const i0 = nearestIdx(s.map((x) => x.ts_utc), t);
    const at = (f) => { for (let i = i0; i >= 0; i--) if (s[i][f] != null) return s[i]; return null; };
    const kpi = (id, f, d, unit) => {
      const r = at(f);
      $(id).innerHTML = `${num(r?.[f], d)}<small>${unit}</small>`;
      $(id).title = r ? `as of ${fmtFull.format(new Date(r.ts_utc))}` : "";
    };
    kpi("#k-load", "load_mw", 0, "MW");
    kpi("#k-net", "net_load_mw", 0, "MW");
    kpi("#k-price", "rt_lbmp", 2, "/MWh");
    $("#k-at").textContent = `At ${fmtFull.format(new Date(s[i0].ts_utc))} · Price = RT LBMP, simple average of 11 internal zones · Net load = load − wind`;
  }
  const fi = fuel.times.length ? nearestIdx(fuel.times, t) : -1;
  if (fi >= 0) {
    let best = null, bv = -1;
    for (const [name] of FUEL_STACK) { const v = (fuel.series[name] || [])[fi]; if (v != null && v > bv) { bv = v; best = name; } }
    $("#k-source").textContent = best || "–";
    chart("c-fuel").setOption({ series: [{ markLine: { data: [{ xAxis: fi }] } }] });
  }
}

// ---------------------------------------------------------------- map
const nodeFC = { type: "FeatureCollection", features: [] };
let zoneFC = { type: "FeatureCollection", features: [] };
const dark = () => document.documentElement.dataset.theme === "dark" ||
  (document.documentElement.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);

function priceExpr() {
  const stops = PRICE_STOPS().flat();
  return ["case", ["!=", ["typeof", ["get", "price"]], "number"], css("--muted"),
          ["interpolate", ["linear"], ["to-number", ["get", "price"]], ...stops]];
}

const map = new maplibregl.Map({
  container: "map",
  // OpenFreeMap: free vector tiles, no API key
  style: `https://tiles.openfreemap.org/styles/${dark() ? "dark" : "positron"}`,
  bounds: [[-79.9, 40.45], [-71.8, 45.05]], fitBoundsOptions: { padding: 12 }, attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

let mapLoaded = false;
map.on("style.load", async () => {
  const [zones, nodes] = await Promise.all([api("/api/geo/zones"), api("/api/geo/nodes")]);
  zoneFC = zones;
  nodeFC.features = nodes.map((n) => ({
    type: "Feature", geometry: { type: "Point", coordinates: [n.lon, n.lat] },
    properties: { ptid: n.ptid, name: n.name, zone: n.zone, price: null },
  }));
  map.addSource("zones", { type: "geojson", data: zoneFC });
  map.addSource("nodes", { type: "geojson", data: nodeFC });
  map.addLayer({ id: "zones-fill", type: "fill", source: "zones", paint: { "fill-color": priceExpr(), "fill-opacity": 0.28 } });
  map.addLayer({ id: "zones-line", type: "line", source: "zones", paint: { "line-color": css("--ink-2"), "line-width": 0.8, "line-opacity": 0.6 } });
  map.addLayer({
    id: "nodes", type: "circle", source: "nodes",
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 3.5, 9, 7],
      "circle-color": priceExpr(), "circle-stroke-color": css("--surface"), "circle-stroke-width": 1,
    },
  });
  const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
  map.on("mousemove", "nodes", (e) => {
    map.getCanvas().style.cursor = "pointer";
    const p = e.features[0].properties;
    const price = p.price === "null" || p.price == null ? "–" : `$${Number(p.price).toFixed(2)}/MWh`;
    popup.setLngLat(e.lngLat).setHTML(`<b>${p.name}</b><br>PTID ${p.ptid} · ${p.zone}<br>${price}`).addTo(map);
  });
  map.on("mouseleave", "nodes", () => { map.getCanvas().style.cursor = ""; popup.remove(); });
  map.on("mousemove", "zones-fill", (e) => {
    if (map.queryRenderedFeatures(e.point, { layers: ["nodes"] }).length) return;
    const p = e.features[0].properties;
    const price = p.price === "null" || p.price == null ? "–" : `$${Number(p.price).toFixed(2)}/MWh`;
    popup.setLngLat(e.lngLat).setHTML(`<b>Zone ${p.zone}</b> (approx. boundary)<br>${price}`).addTo(map);
  });
  map.on("mouseleave", "zones-fill", () => popup.remove());
  mapLoaded = true;
  if (state.nodes && state.nodes.times.length) updateMap(state.nodes.times[state.scrub]);
});
drawLegend();

function drawLegend() {
  const rows = [[">225", "--d-pos3"], ["100", "--d-pos2"], ["50", "--d-pos1"], ["0", "--d-mid"], ["-10", "--d-neg1"], ["<-40", "--d-neg2"]];
  $("#map-legend").innerHTML = `<b>$/MWh</b>` + rows.map(([l, v]) =>
    `<div class="row"><span class="sw" style="background:${css(v)}"></span>${l}</div>`).join("");
}

// ================================================================ PRICING
async function renderPricing() {
  const d = state.date;
  const zones = state.zones || (await api(`/api/prices/zones?date=${d}`));
  if (d !== state.date) return;
  state.zones = zones;
  const sel = $("#p-zone");
  if (!sel.options.length) {
    [...INTERNAL_ZONES, ...zones.external].forEach((z) => sel.add(new Option(z, z)));
    sel.value = "N.Y.C.";
    sel.onchange = drawPricing;
  }
  drawPricing();
}

function drawPricing() {
  const z = $("#p-zone").value, { hourly, rt5 } = state.zones;
  $("#p-title").textContent = `LBMP — ${z}`;
  const rt = rt5.filter((r) => r.zone === z);
  const hr = hourly.filter((r) => r.zone === z);
  const times = rt.length ? rt.map((r) => r.ts_utc) : hr.map((r) => r.ts_utc);
  const daByHour = new Map(hr.map((r) => [r.ts_utc.slice(0, 13), r.da_lbmp]));
  const da = times.map((t) => daByHour.get(new Date(t).toISOString().slice(0, 13)) ?? null);
  const money = (v) => (v == null ? "–" : `$${num(v, 2)}`);
  chart("c-price").setOption(base({
    tooltip: { ...base().tooltip, valueFormatter: money },
    xAxis: { ...base().xAxis, data: times.map(hm), boundaryGap: false },
    series: [
      line("Day-ahead (hourly)", da, css("--s1"), { step: "start" }),
      line("Real-time (5-min)", rt.map((r) => r.lbmp), css("--s2")),
    ],
  }), true);

  const pos = css("--d-pos2"), neg = css("--d-neg1");
  chart("c-spread").setOption(base({
    tooltip: { ...base().tooltip, valueFormatter: money },
    legend: { show: false },
    grid: { left: 52, right: 16, top: 16, bottom: 32 },
    xAxis: { ...base().xAxis, data: hr.map((r) => hm(r.ts_utc)) },
    series: [{
      name: "DA − RT", type: "bar", barMaxWidth: 18,
      data: hr.map((r) => ({ value: r.da_rt_spread, itemStyle: { color: r.da_rt_spread >= 0 ? pos : neg, borderRadius: r.da_rt_spread >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] } })),
    }],
  }), true);

  const hours = [...new Set(hourly.map((r) => r.ts_utc))];
  const data = hourly.filter((r) => INTERNAL_ZONES.includes(r.zone) && r.rt_lbmp != null)
    .map((r) => [hours.indexOf(r.ts_utc), INTERNAL_ZONES.indexOf(r.zone), r.rt_lbmp]);
  const [n2, n1, mid, p1, p2, p3] = PRICE_STOPS().map((s) => s[1]);
  const pieces = [
    { lt: -40, color: n2 }, { gte: -40, lt: -10, color: mix(n2, n1, 0.5) }, { gte: -10, lt: 0, color: n1 },
    { gte: 0, lt: 25, color: mix(mid, p1, 0.5) }, { gte: 25, lt: 50, color: p1 }, { gte: 50, lt: 100, color: mix(p1, p2, 0.5) },
    { gte: 100, lt: 225, color: p2 }, { gte: 225, color: p3 },
  ];
  chart("c-heat").setOption(base({
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--border"), textStyle: { color: css("--ink") },
               formatter: (p) => `${INTERNAL_ZONES[p.value[1]]} · ${hm(hours[p.value[0]])}<br>${money(p.value[2])}` },
    grid: { left: 70, right: 16, top: 8, bottom: 70 },
    legend: { show: false },
    xAxis: { ...base().xAxis, data: hours.map(hm) },
    yAxis: { type: "category", data: INTERNAL_ZONES, axisLabel: { color: css("--muted") }, axisLine: { show: false }, axisTick: { show: false } },
    visualMap: { type: "piecewise", pieces, orient: "horizontal", bottom: 0, left: "center", textStyle: { color: css("--ink-2") }, itemWidth: 14 },
    series: [{ type: "heatmap", data, itemStyle: { borderColor: css("--surface"), borderWidth: 2, borderRadius: 3 } }],
  }), true);
}

function mix(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

// ================================================================ CONSTRAINTS
async function renderConstraints() {
  const d = state.date;
  const data = state.constraints || (await api(`/api/constraints?date=${d}`));
  if (d !== state.date) return;
  state.constraints = data;
  drawConstraintTable();
  const sel = $("#f-iface");
  const ifaces = [...new Set(data.flows.map((r) => r.interface))].sort();
  const keep = sel.value;
  sel.innerHTML = "";
  ifaces.forEach((i) => sel.add(new Option(i, i)));
  sel.value = ifaces.includes(keep) ? keep : (ifaces.includes("CENTRAL EAST - VC") ? "CENTRAL EAST - VC" : ifaces[0]);
  sel.onchange = drawFlows;
  drawFlows();
}
$$("#con-mkt button").forEach((b) => (b.onclick = () => {
  $$("#con-mkt button").forEach((x) => x.classList.toggle("active", x === b));
  state.conMkt = b.dataset.v; drawConstraintTable();
}));

function drawConstraintTable() {
  const rows = state.constraints.constraints.filter((r) => r.market === state.conMkt);
  const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  $("#t-con tbody").innerHTML = rows.length ? rows.map((r) => `<tr>
    <td>${esc(r.facility)}</td><td>${esc(r.contingency)}</td>
    <td class="num">${num(r.hours_binding, 2)}</td><td class="num">${num(r.sum_cost, 2)}</td><td class="num">${num(r.max_abs_cost, 2)}</td>
  </tr>`).join("") : `<tr><td colspan="5" class="muted">No binding ${state.conMkt} constraints on this day.</td></tr>`;
}

function drawFlows() {
  const i = $("#f-iface").value;
  const rows = state.constraints.flows.filter((r) => r.interface === i);
  const lim = (v) => (v == null || Math.abs(v) >= 9999 ? null : v);
  const muted = css("--muted");
  chart("c-flow").setOption(base({
    tooltip: { ...base().tooltip, valueFormatter: (v) => (v == null ? "–" : `${num(v)} MW`) },
    xAxis: { ...base().xAxis, data: rows.map((r) => hm(r.ts_utc)) },
    series: [
      line("Flow", rows.map((r) => r.flow_mw), css("--s1")),
      line("Positive limit", rows.map((r) => lim(r.pos_limit_mw)), muted, { lineStyle: { width: 1.5, color: muted, type: "dashed" } }),
      line("Negative limit", rows.map((r) => lim(r.neg_limit_mw)), muted, { lineStyle: { width: 1.5, color: muted, type: "dotted" } }),
    ],
  }), true);
}

// ================================================================ TRENDS
$$("#tr-range button").forEach((b) => (b.onclick = () => {
  $$("#tr-range button").forEach((x) => x.classList.toggle("active", x === b));
  state.trendDays = b.dataset.v; state.trends = null; renderTrends();
}));

async function renderTrends() {
  const end = state.date;
  const start = state.trendDays === "all" ? state.min : addDays(end, -Number(state.trendDays));
  const t = state.trends && state.trends.end === end ? state.trends : await api(`/api/trends?start=${start}&end=${end}`);
  state.trends = t;
  const days = t.daily.map((r) => r.day);
  const zoom = [{ type: "inside" }, { type: "slider", height: 18, bottom: 28, borderColor: css("--border"), textStyle: { color: css("--muted") } }];
  const g = { left: 60, right: 16, top: 16, bottom: 84 };
  chart("c-tload").setOption(base({
    grid: g, dataZoom: zoom,
    tooltip: { ...base().tooltip, valueFormatter: (v) => (v == null ? "–" : `${num(v)} MW`) },
    xAxis: { ...base().xAxis, data: days },
    series: [line("Average", t.daily.map((r) => r.avg_load_mw), css("--s1")),
             line("Peak", t.daily.map((r) => r.peak_load_mw), css("--s2"))],
  }), true);
  chart("c-tprice").setOption(base({
    grid: g, dataZoom: zoom,
    tooltip: { ...base().tooltip, valueFormatter: (v) => (v == null ? "–" : `$${num(v, 2)}`) },
    xAxis: { ...base().xAxis, data: days },
    series: [line("Day-ahead", t.daily.map((r) => r.avg_da_lbmp), css("--s1")),
             line("Real-time", t.daily.map((r) => r.avg_rt_lbmp), css("--s2"))],
  }), true);

  const byDay = new Map();
  t.fuel.forEach((r) => { if (!byDay.has(r.day)) byDay.set(r.day, {}); byDay.get(r.day)[r.fuel] = r.avg_mw; });
  const fdays = [...byDay.keys()].sort();
  const share = (d, f) => { const o = byDay.get(d); const tot = Object.values(o).reduce((a, b) => a + (b || 0), 0); return tot ? (100 * (o[f] || 0)) / tot : null; };
  const surface = css("--surface");
  chart("c-tfuel").setOption(base({
    grid: g, dataZoom: zoom,
    tooltip: { ...base().tooltip, valueFormatter: (v) => (v == null ? "–" : `${num(v, 1)}%`) },
    xAxis: { ...base().xAxis, data: fdays, boundaryGap: false },
    yAxis: { ...base().yAxis, max: 100, axisLabel: { color: css("--muted"), formatter: "{value}%" } },
    series: FUEL_STACK.map(([name, v]) => ({
      name, type: "line", stack: "share", showSymbol: false, data: fdays.map((d) => share(d, name)),
      areaStyle: { color: css(v), opacity: 1 }, itemStyle: { color: css(v) }, lineStyle: { width: 1, color: surface },
    })),
  }), true);
}

// ---------------------------------------------------------------- boot
addEventListener("resize", () => { Object.values(charts).forEach((c) => c.resize()); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => location.reload());

(async function boot() {
  const meta = await api("/api/meta");
  state.min = meta.min_date; state.max = meta.max_date;
  $("#d-input").min = state.min; $("#d-input").max = state.max;
  const bad = meta.coverage.reduce((a, c) => a + c.bad_days, 0);
  const avg = meta.coverage.length ? meta.coverage.reduce((a, c) => a + c.coverage, 0) / meta.coverage.length : null;
  const badge = $("#coverage-badge");
  badge.textContent = avg == null ? "coverage: run nyiso validate"
    : `${state.min} → ${state.max} · coverage ${(avg * 100).toFixed(2)}%` + (bad ? ` · ${bad} partial dataset-days` : "");
  badge.classList.toggle("warn", bad > 0);
  badge.title = meta.coverage.map((c) => `${c.dataset}: ${(c.coverage * 100).toFixed(2)}% (${c.bad_days} partial days)`).join("\n");
  const params = new URL(location).searchParams;
  const tab = params.get("tab");
  state.date = params.get("date") || state.max;
  if (tab) $(`.tabs > button[data-tab="${tab}"]`)?.click();
  setDate(state.date);
})();
