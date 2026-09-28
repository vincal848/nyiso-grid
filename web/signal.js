/* Signal tab: structure learned by the forecasting pipeline and the forecast distributions it produces.
   Reads /api/signal/* (built from data/structure.duckdb and data/experiments). */
"use strict";

const sig = { market: "da", fold: null, key: null, map: null, mapReady: null, models: [], inited: false };
const INTERNAL = ["WEST", "GENESE", "CENTRL", "NORTH", "MHK VL", "CAPITL", "HUD VL", "MILLWD", "DUNWOD", "N.Y.C.", "LONGIL"];

// Diverging scale for shift factors: blue (negative) - neutral - red (positive).
function sfExpr(maxAbs) {
  const m = Math.max(maxAbs, 1e-6);
  return ["case", ["!=", ["typeof", ["get", "a"]], "number"], css("--muted"),
    ["interpolate", ["linear"], ["get", "a"], -m, css("--d-neg2"), -m / 3, css("--d-neg1"), 0, css("--d-mid"),
      m / 3, css("--d-pos1"), m, css("--d-pos3")]];
}

async function sigInit() {
  if (sig.inited) return;
  sig.inited = true;
  $$("#sig-mkt button").forEach((b) => (b.onclick = () => {
    $$("#sig-mkt button").forEach((x) => x.classList.toggle("active", x === b));
    sig.market = b.dataset.v; sig.key = null; loadStructure();
  }));
  $("#sig-fold").onchange = (e) => { sig.fold = e.target.value; sig.key = null; loadStructure(); };
  $("#sig-key").onchange = (e) => { sig.key = e.target.value; drawNodeFactors(); };
  ["fan-model", "fan-zone", "fan-comp"].forEach((id) => ($("#" + id).onchange = () => drawFan(state.date)));

  try {
    const f = await api("/api/signal/folds");
    $("#sig-fold").innerHTML = f.folds.map((x) => `<option>${x}</option>`).join("");
    sig.fold = f.folds[f.folds.length - 1];
    $("#sig-fold").value = sig.fold;
    $("#sig-src").textContent = f.source ? `structure from ${f.source.run_id}` : "";
  } catch (e) {
    $("#sig-src").textContent = "No structure store yet: run `uv run lmp graphs`.";
  }
  sig.models = await api("/api/signal/models").catch(() => []);
  const prefer = ["combo3_eq_aci", "combo2_eq_aci", "lear_clip_aci"];
  const opts = sig.models.map((m) => `<option value="${m.run_id}">${m.model}</option>`).join("");
  $("#fan-model").innerHTML = opts;
  const pick = prefer.map((p) => sig.models.find((m) => m.model === p)).find(Boolean);
  if (pick) $("#fan-model").value = pick.run_id;
  $("#fan-zone").innerHTML = INTERNAL.map((z) => `<option>${z}</option>`).join("");
  $("#fan-zone").value = "N.Y.C.";

  sig.map = new maplibregl.Map({
    container: "sigmap", style: `https://tiles.openfreemap.org/styles/${dark() ? "dark" : "positron"}`,
    bounds: [[-79.9, 40.45], [-71.8, 45.05]], fitBoundsOptions: { padding: 12 }, attributionControl: { compact: true },
  });
  sig.mapReady = new Promise((resolve) => sig.map.on("style.load", async () => {
    sig.zones = await api("/api/geo/zones");
    sig.map.addSource("sz", { type: "geojson", data: sig.zones });
    sig.map.addSource("sn", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    sig.map.addLayer({ id: "sz-fill", type: "fill", source: "sz", paint: { "fill-color": css("--muted"), "fill-opacity": 0.3 } });
    sig.map.addLayer({ id: "sz-line", type: "line", source: "sz", paint: { "line-color": css("--ink-2"), "line-width": 0.8, "line-opacity": 0.6 } });
    sig.map.addLayer({ id: "sn", type: "circle", source: "sn",
      paint: { "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 3.5, 9, 7], "circle-color": css("--muted"),
               "circle-stroke-color": css("--surface"), "circle-stroke-width": 1 } });
    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8 });
    sig.map.on("mousemove", "sn", (e) => {
      const p = e.features[0].properties;
      popup.setLngLat(e.lngLat).setHTML(`<b>${p.name}</b> (${p.zone})<br>shift factor ${Number(p.a).toFixed(3)}` +
        (p.r2 !== "null" && p.r2 != null ? `<br>top-K R² ${Number(p.r2).toFixed(2)}` : "")).addTo(sig.map);
    });
    sig.map.on("mouseleave", "sn", () => popup.remove());
    resolve();
  }));
}

async function loadStructure() {
  if (!sig.fold) return;
  const c = await api(`/api/signal/constraints?market=${sig.market}&fold=${sig.fold}`);
  const esc = (s) => String(s ?? "").replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
  $("#t-sig tbody").innerHTML = c.constraints.map((r) => `<tr data-key="${esc(r.key)}">
    <td class="num">${r.rank}</td><td>${esc(r.key)}</td><td class="num">${(100 * r.bind_rate).toFixed(1)}%</td>
    <td class="num">${num(r.sum_abs_shadow)}</td><td>${esc(r.most_sensitive_zone)}</td></tr>`).join("");
  $$("#t-sig tbody tr").forEach((tr) => (tr.onclick = () => { sig.key = tr.dataset.key; $("#sig-key").value = sig.key; drawNodeFactors(); }));
  $("#sig-key").innerHTML = c.constraints.map((r) => `<option value="${esc(r.key)}">${r.rank}. ${esc(r.key)}</option>`).join("");
  sig.key = sig.key || c.constraints[0]?.key;
  $("#sig-key").value = sig.key;
  await Promise.all([drawNodeFactors(), drawCobinding(), drawDrift()]);
}

async function drawNodeFactors() {
  if (!sig.key) return;
  await sig.mapReady;
  const d = await api(`/api/signal/node_factors?market=${sig.market}&fold=${sig.fold}&key=${encodeURIComponent(sig.key)}`);
  const maxAbs = Math.max(...d.nodes.map((n) => Math.abs(n.a)), ...d.zones.map((z) => Math.abs(z.a)), 1e-6);
  sig.map.getSource("sn").setData({ type: "FeatureCollection", features: d.nodes.map((n) => ({
    type: "Feature", geometry: { type: "Point", coordinates: [n.lon, n.lat] },
    properties: { a: n.a, name: n.name, zone: n.zone, r2: n.r2_in_window } })) });
  const za = Object.fromEntries(d.zones.map((z) => [z.zone, z.a]));
  sig.zones.features.forEach((f) => (f.properties.a = za[f.properties.zone] ?? null));
  sig.map.getSource("sz").setData(sig.zones);
  sig.map.setPaintProperty("sn", "circle-color", sfExpr(maxAbs));
  sig.map.setPaintProperty("sz-fill", "fill-color", sfExpr(maxAbs));
  $("#sig-legend").innerHTML = `<b>Shift factor</b><div class="small muted" style="max-width:180px">$/MWh of ${sig.market.toUpperCase()} congestion per $/MWh of this constraint's shadow price (fold ${sig.fold})</div>` +
    [[maxAbs, "--d-pos3"], [maxAbs / 3, "--d-pos1"], [0, "--d-mid"], [-maxAbs / 3, "--d-neg1"], [-maxAbs, "--d-neg2"]]
      .map(([v, c]) => `<div class="row"><span class="sw" style="background:${css(c)}"></span>${v.toFixed(2)}</div>`).join("");
}

async function drawCobinding() {
  const d = await api(`/api/signal/cobinding?market=${sig.market}&fold=${sig.fold}&top=80`);
  const used = new Set(d.edges.flatMap((e) => [e.key_a, e.key_b]));
  const nodes = d.nodes.filter((n) => used.has(n.key)).map((n) => ({
    name: n.key, value: n.bind_rate, symbolSize: 6 + 40 * Math.sqrt(n.bind_rate),
    itemStyle: { color: css("--s1") }, label: { show: n.rank <= 8, color: css("--ink-2"), fontSize: 10,
      formatter: n.key.split(" | ")[0].slice(0, 22) } }));
  chart("c-cobind").setOption({
    animation: false,
    tooltip: { formatter: (p) => p.dataType === "edge" ? `${p.data.source}<br>${p.data.target}<br>co-bind Jaccard ${p.data.value.toFixed(2)}`
      : `${p.data.name}<br>bind rate ${(100 * p.data.value).toFixed(1)}%` },
    series: [{ type: "graph", layout: "force", roam: true, data: nodes, force: { repulsion: 120, edgeLength: [30, 140] },
      edges: d.edges.map((e) => ({ source: e.key_a, target: e.key_b, value: e.jaccard,
        lineStyle: { width: 0.5 + 5 * e.jaccard, color: css("--axis"), opacity: 0.8 } })) }],
  }, true);
}

async function drawDrift() {
  const d = await api("/api/signal/drift");
  const rows = d.filter((r) => r.market === sig.market);
  chart("c-drift").setOption(base({
    tooltip: { ...base().tooltip, valueFormatter: (v) => (v == null ? "–" : Number(v).toFixed(2)) },
    xAxis: { ...base().xAxis, data: rows.map((r) => r.fold) },
    yAxis: [{ ...base().yAxis, name: "relative change", nameTextStyle: { color: css("--muted") } }],
    series: [line("Node shift-factor change", rows.map((r) => r.node_sf_rel_change), css("--s1")),
             line("Catalog overlap (Jaccard)", rows.map((r) => r.catalog_jaccard), css("--s2"))],
  }), true);
}

async function drawFan(date) {
  const run = $("#fan-model").value, zone = $("#fan-zone").value, comp = $("#fan-comp").value;
  if (!run || !date) return;
  const d = await api(`/api/signal/forecast?run_id=${encodeURIComponent(run)}&zone=${encodeURIComponent(zone)}&date=${date}&market=${sig.market}&component=${comp}`);
  const model = $("#fan-model").selectedOptions[0]?.textContent;
  $("#fan-title").textContent = `${sig.market.toUpperCase()} ${comp} forecast distribution vs actual — ${zone}, ${date} (${model})`;
  const rows = d.rows;
  if (!rows.length) { chart("c-fan").clear(); return; }
  const x = rows.map((r) => hm(r.ts_utc));
  const band = (lo, hi, color, name) => [
    { name, type: "line", stack: name, data: rows.map((r) => r[lo]), lineStyle: { width: 0 }, showSymbol: false, silent: true,
      itemStyle: { color } },
    { name, type: "line", stack: name, data: rows.map((r) => (r[hi] == null || r[lo] == null ? null : r[hi] - r[lo])),
      lineStyle: { width: 0 }, showSymbol: false, areaStyle: { color, opacity: 0.25 }, itemStyle: { color }, silent: true },
  ];
  chart("c-fan").setOption(base({
    tooltip: { ...base().tooltip, valueFormatter: (v) => (v == null ? "–" : `$${num(v, 2)}`) },
    legend: { ...base().legend, data: ["90% interval", "50% interval", "Forecast mean", "Actual"] },
    xAxis: { ...base().xAxis, data: x, boundaryGap: false },
    series: [...band("q05", "q95", css("--s1"), "90% interval"), ...band("q25", "q75", css("--s1"), "50% interval"),
             line("Forecast mean", rows.map((r) => r.mean), css("--s1")),
             line("Actual", rows.map((r) => r.y), css("--s2"), { lineStyle: { width: 2, type: "dashed", color: css("--s2") } })],
  }), true);
}

window.renderSignal = async function (date) {
  await sigInit();
  if (!$("#t-sig tbody").children.length) await loadStructure().catch(() => {});
  await drawFan(date).catch(() => {});
  setTimeout(() => { sig.map && sig.map.resize(); Object.values(charts).forEach((c) => c.resize()); }, 0);
};
