// Analyze tab: the 39-year profile of the area, analysis layers (change, year of change, trend, gap-fill QA) with their
// native-resolution area statistics, GeoTIFF / image export, and the pixel inspector.
import {api} from "./api.js";
import {$, $$, esc, fmt, fmtArea, pool, download, slug, toast, openModal} from "./util.js";
import {S, on, emit} from "./state.js";
import {map, setAnalysisLayer} from "./map.js";
import {lineChart, barChart, stripChart} from "./charts.js";
import {composeStill} from "./video.js";

const YEARS = () => S.meta.years;
let tsAbort = null, tsKey = null, tsFailed = [];

/* ---------- 39-year profile ---------- */
export async function loadSeries(force = false) {
  if (!S.aoi) return;
  const key = S.aoi.info.key;
  const missing = YEARS().filter(y => !S.yearStats[y]);
  if (!missing.length) { draw(); return; }
  if (tsKey === key && tsAbort && !force) return;          // already running for this area
  tsAbort?.abort();
  const ctl = new AbortController();
  tsAbort = ctl;
  tsKey = key;
  tsFailed = [];
  const bar = $("#ts-progress");
  bar.hidden = false;
  let done = YEARS().length - missing.length;
  const tick = () => { bar.firstElementChild.style.width = (100 * done / YEARS().length) + "%"; };
  tick();
  let pending = false;
  const redraw = () => { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; draw(); }); } };
  try {
    await pool(missing, 6, async y => {
      try { return await api("stats/year", {aoi: S.aoi.spec, year: y}, {signal: ctl.signal}); }
      catch (e) { if (e.name !== "AbortError") tsFailed.push([y, e.message]); return null; }
    }, r => {
      done++;
      tick();
      if (r && S.aoi?.info.key === key) { S.yearStats[r.year] = r; emit("stats:year", r); redraw(); }
    }, ctl.signal);
  } catch { /* aborted */ }
  if (tsAbort === ctl) tsAbort = null;
  if (S.aoi?.info.key !== key) return;
  bar.hidden = true;
  draw();
  if (tsFailed.length) {
    toast(`${tsFailed.length} year(s) failed: ${tsFailed[0][1]}`, "err", 9000);
    $("#ch-gli").insertAdjacentHTML("afterbegin", `<div class="btnrow"><button class="btn" type="button" id="ts-retry">Retry ${tsFailed.length} missing year(s)</button></div>`);
    $("#ts-retry").onclick = () => loadSeries(true);
  }
}

function series(k) { return YEARS().map(y => S.yearStats[y]?.[k] ?? null); }

function draw() {
  const ys = YEARS();
  const got = ys.filter(y => S.yearStats[y]);
  const has = got.length > 0;
  ["#ts-csv", "#ts-json", "#ts-table"].forEach(id => { $(id).disabled = got.length < ys.length; });
  if (!has) { ["#ch-gli", "#ch-cover", "#ch-de", "#ch-qa", "#ch-strip"].forEach(id => { $(id).innerHTML = ""; }); return; }
  const qa = series("qa_pct");
  const g0 = S.yearStats[ys.find(y => S.yearStats[y])];
  const T = S.meta.thresholds;
  lineChart($("#ch-gli"), {
    title: "Greenness (mean GLI)", years: ys, qa,
    sub: `Area-weighted mean over ${fmtArea(g0.valid_km2)} of real imagery${g0.ocean_km2 > 0.5 ? ` (${fmtArea(g0.ocean_km2)} of synthetic ocean excluded)` : ""}. Tinted years are mostly gap-filled; bands mark sensor eras. Dashed: the median of ${S.meta.reference?.n_pixels || ""} stable-forest pixels across Myanmar, so dataset-wide drift (e.g. the 2013–16 dip) is not read as local change.`,
    series: [{name: "GLI", values: series("gli"), color: "var(--s1)"}], yfmt: v => fmt(v, 2), tfmt: v => fmt(v, 3),
    ref: S.meta.reference ? {values: S.meta.reference.stable_forest_gli, label: "Myanmar stable forest (median)", short: "forest ref."} : null});
  lineChart($("#ch-cover"), {
    title: "Green cover and bright/bare surface (% of area)", years: ys, qa, ymin: 0,
    sub: `Green: GLI > ${T.green_gli}. Bright/bare: brightness > ${T.bare_bright} and GLI < ${T.bare_gli} (built-up, bare soil, sand, mining).`,
    series: [{name: "Green", values: series("green_pct"), color: "var(--s1)"}, {name: "Bright/bare", values: series("bare_pct"), color: "var(--s2)"}],
    yfmt: v => fmt(v, 0) + "%", tfmt: v => fmt(v, 1) + "%"});
  barChart($("#ch-de"), {
    title: "Visibly changed since the previous year (% of area)", x: ys, y: series("de_visible_pct"), qa,
    sub: `Colour change ΔE ≥ ${T.de_visible}, which nearby years exceed on ~5% of land by chance. The 2015 jump includes the 30 → 19 m grid change.`,
    yfmt: v => fmt(v, 0) + "%", tip: i => `<b>${ys[i]}</b><br>${fmt(series("de_visible_pct")[i], 1)}% changed<br>mean ΔE ${fmt(series("de_prev")[i], 1)}`});
  const base = ys.filter(y => y >= 2000 && y <= 2014).map(y => S.yearStats[y]?.qa_pct).filter(v => v != null).sort((a, b) => a - b);
  const med = base.length ? base[Math.floor(base.length / 2)] : null;
  barChart($("#ch-qa"), {
    title: "Gap-fill check: area on a linear segment (%)", x: ys, y: qa, color: "var(--warn)", ymaxMin: 10,
    sub: "Share of pixels whose year sits on a straight line with its neighbours in all three bands (≤ 2 DN): the signature of linear gap-filling.",
    yfmt: v => fmt(v, 0) + "%", ref: med != null ? {v: med, label: `2000–14 median ${fmt(med, 1)}%`} : null,
    tip: i => `<b>${ys[i]}</b><br>${fmt(qa[i], 1)}% on a linear segment`});
  stripChart($("#ch-strip"), {
    title: "Mean colour of the area, year by year", years: ys,
    sub: "Each bar is the area's mean displayed colour. An orange tick marks a mostly gap-filled year.",
    colors: ys.map(y => { const c = S.yearStats[y]?.rgb; return c ? `rgb(${c.map(Math.round).join(",")})` : null; }),
    flags: qa.map(v => v != null && v >= 20),
    tip: i => { const st = S.yearStats[ys[i]]; return st ? `GLI ${fmt(st.gli, 3)} · green ${fmt(st.green_pct, 1)}%` : ""; }});
}

function rows() {
  return YEARS().map(y => {
    const s = S.yearStats[y] || {};
    return {year: y, grid_m: s.grid_m, area_km2: s.area_km2, valid_km2: s.valid_km2, ocean_km2: s.ocean_km2, gli: s.gli,
            brightness: s.bright, red: s.rgb?.[0], green: s.rgb?.[1], blue: s.rgb?.[2], green_pct: s.green_pct, bare_pct: s.bare_pct,
            visible_change_pct: s.de_visible_pct, mean_de_prev: s.de_prev, gapfill_pct: s.qa_pct};
  });
}

function meta() {
  return {area: S.aoi.info.name, area_my: S.aoi.info.name_my, pcode: S.aoi.info.pcode, area_km2: S.aoi.info.area_km2,
          dataset: "projects/ee-earth-timelapse/assets/annual", attribution: S.meta.attribution, licence: "CC BY 4.0",
          algorithm_version: S.meta.algo_version, thresholds: S.meta.thresholds,
          note: "Indices derive from an 8-bit visual RGB product and are indicative; statistics use each year's native grid (30 m to 2014, 19.1 m from 2015)."};
}

function exportCsv() {
  const r = rows(), cols = Object.keys(r[0]);
  const csv = [`# ${S.aoi.info.name} | ${S.meta.attribution} | CC BY 4.0 | algorithm ${S.meta.algo_version}`, cols.join(","),
    ...r.map(o => cols.map(c => o[c] == null ? "" : typeof o[c] === "number" ? +o[c].toFixed(6) : o[c]).join(","))].join("\n");
  download(csv, slug(S.aoi.info.name) + "_1984-2022.csv", "text/csv");
}

function showTable() {
  const wrap = $("#ts-tablewrap");
  if (!wrap.hidden) { wrap.hidden = true; $("#ts-table").textContent = "Show table"; return; }
  const r = rows();
  wrap.innerHTML = `<table><thead><tr><th>Year</th><th class="num">GLI</th><th class="num">Green %</th><th class="num">Bare %</th><th class="num">Changed %</th><th class="num">Gap-filled %</th></tr></thead><tbody>` +
    r.map(o => `<tr><td>${o.year}</td><td class="num">${fmt(o.gli, 3)}</td><td class="num">${fmt(o.green_pct, 1)}</td><td class="num">${fmt(o.bare_pct, 1)}</td><td class="num">${fmt(o.visible_change_pct, 1)}</td><td class="num">${fmt(o.gapfill_pct, 1)}</td></tr>`).join("") +
    "</tbody></table>";
  wrap.hidden = false;
  $("#ts-table").textContent = "Hide table";
}

/* ---------- analysis layers ---------- */
let anMode = "none", anToken = 0;

function spec() {
  switch (anMode) {
    case "change": return {type: "change", a: +$("#ch-a").value, b: +$("#ch-b").value, metric: $("#ch-metric").value, window: +$("#ch-window").value};
    case "yoc": return {type: "yoc", start: +$("#yoc-s").value, end: +$("#yoc-e").value, metric: $("#yoc-m").value};
    case "trend": return {type: "trend", start: +$("#tr-s").value, end: +$("#tr-e").value, alpha: +$("#tr-alpha").value};
    case "qa": { const v = $("#qa-mode").value; return v === "count" ? {type: "qa", mode: "count"} : {type: "qa", year: +v}; }
    default: return null;
  }
}

export async function refreshLayer() {
  const token = ++anToken;
  const sp = spec();
  $("#an-actions").hidden = !sp;
  if (!sp || !S.aoi) { setAnalysisLayer(null); return; }
  try {
    const r = await api("layer", {layer: sp, aoi: S.aoi.spec});
    if (token === anToken) setAnalysisLayer(r.url, r.legend);
  } catch (e) { toast(e.message, "err", 8000); return; }
  const out = {change: "#ch-stats", yoc: "#ch-yoc", trend: "#tr-stats"}[anMode];
  if (!out) return;
  $(out).innerHTML = `<p class="note">Computing at native resolution…</p>`;
  try {
    const body = {aoi: S.aoi.spec, ...(anMode === "change" ? {a: sp.a, b: sp.b, window: sp.window} : {start: sp.start, end: sp.end, metric: sp.metric || "gli", alpha: sp.alpha ?? 0.05})};
    const st = await api("stats/" + anMode, body);
    if (token !== anToken) return;
    if (anMode === "change") changeTable(st);
    if (anMode === "yoc") yocChart(st);
    if (anMode === "trend") trendSummary(st);
  } catch (e) {
    if (token === anToken) $(out).innerHTML = `<div class="warnline">${esc(e.message)}</div>`;
  }
}

function changeTable(st) {
  const colors = ["transparent", ...S.meta.class_colors];
  $("#ch-stats").innerHTML = `<table class="stattable"><thead><tr><th>${st.a} → ${st.b}</th><th class="num">Area</th><th class="num">Share</th></tr></thead><tbody>` +
    st.classes.map((c, i) => `<tr><td><span class="sw" style="background:${colors[i]};${i ? "" : "border:1px solid var(--line)"}"></span>${esc(c.name)}</td><td class="num">${fmtArea(c.km2)}</td><td class="num">${fmt(c.pct, 1)}%</td></tr>`).join("") +
    `</tbody></table><p class="note">${st.window === 3 ? "3-year means around each year, on" : "On"} the ${fmt(st.grid_m, 1)} m grid${st.grid_m > 25 ? " (2015+ pixels averaged onto the 30 m grid)" : ""}. Mean ΔGLI ${fmt(st.dgli, 3)}, mean ΔE ${fmt(st.de, 1)}.
      A class needs ΔE ≥ ${st.thresholds.de} and |ΔGLI| ≥ ${st.thresholds.dgli} (vegetation) or |Δbrightness| ≥ ${st.thresholds.dbright}, which nearby years exceed on only ~5% of land. Vegetation classes take precedence.</p>`;
}

function yocChart(st) {
  const el = $("#ch-yoc");
  barChart(el, {title: `Area whose largest change falls in each year (${fmtArea(st.total_km2)} in all)`, x: st.years, y: st.km2,
    sub: `First year of the later 3-year window; ${st.metric === "gli" ? "greenness drop" : "colour change"} beyond the stable-forest maximum (p95). Years before ${st.start + 3} can't be dated.`,
    yfmt: v => fmt(v, v < 10 ? 1 : 0), tip: i => `<b>${st.years[i]}</b><br>${fmtArea(st.km2[i])}`, qa: null, years: true});
}

function trendSummary(st) {
  $("#tr-stats").innerHTML = `<table class="stattable"><tbody>
    <tr><td><span class="sw" style="background:#2a78d6"></span>Greening</td><td class="num">${fmtArea(st.greening_km2)}</td><td class="num">${fmt(st.greening_pct, 1)}%</td></tr>
    <tr><td><span class="sw" style="background:#d2383a"></span>Browning</td><td class="num">${fmtArea(st.browning_km2)}</td><td class="num">${fmt(st.browning_pct, 1)}%</td></tr>
    </tbody></table><p class="note">${st.start}–${st.end}, mean slope ${fmt(st.slope_per_decade, 4)} GLI per decade. A pixel counts when its Sen slope leaves the stable-forest range (±${S.meta.thresholds.trend_slope}/decade)${st.alpha < 1 ? ` and Mann–Kendall p < ${st.alpha}` : ""}.</p>`;
}

async function downloadTif() {
  const sp = spec() || {type: "year", year: S.year};
  await geotiff(sp);
}

export async function geotiff(sp) {
  openModal(`<h3>Preparing GeoTIFF…</h3><p class="note">Requesting native-resolution download links from Earth Engine.</p>`);
  try {
    const r = await api("download", {aoi: S.aoi.spec, layer: sp});
    const vrt = r.vrt ? `<div class="btnrow"><button class="btn" type="button" id="dlvrt">Download ${esc(r.name)}.vrt</button></div>` : "";
    openModal(`<h3>${esc(r.name)}</h3>
      <p class="note">${r.cols.toLocaleString()} × ${r.rows.toLocaleString()} px at ${fmt(r.scale, 3)} m (EPSG:3857, native grid)${r.chunks.length > 1 ? ` in ${r.chunks.length} tiles. Open the .vrt in QGIS once all tiles are in one folder.` : "."}
      Links work for about two hours. ${r.bands === 4 ? "Band 4 is an alpha mask of the area." : ""}</p>
      <div class="dl-list">${r.chunks.map(c => `<a href="${c.url}" download="${esc(c.file)}">${esc(c.file)}</a>`).join("")}</div>${vrt}
      <p class="note">${esc(S.meta.attribution)}, CC BY 4.0. ${esc(S.meta.sentinel_notice)}.</p>`);
    if (r.vrt) $("#dlvrt").onclick = () => download(r.vrt, r.name + ".vrt", "application/xml");
  } catch (e) {
    openModal(`<h3>Download failed</h3><div class="warnline">${esc(e.message)}</div>`);
  }
}

async function saveImage() {
  const sp = spec();
  if (!sp) return;
  try {
    const r = await api("thumb", {aoi: S.aoi.spec, layer: sp, preset: "1440p"});
    const blob = await composeStill([{url: r.url}], {legend: r.legend, title: S.aoi.info.name, sub: r.title, years: [r.base_year]});
    download(blob, `${slug(S.aoi.info.name)}_${sp.type}.png`, "image/png");
  } catch (e) { toast(e.message, "err", 8000); }
}

/* ---------- pixel inspector ---------- */
let pin = null;
async function inspect(ll) {
  if (!$("#inspect").checked) return;
  pin?.remove();
  pin = L.circleMarker(ll, {radius: 7, color: "#fff", weight: 2.5, fillColor: "#2a78d6", fillOpacity: 1, pane: "aoi"}).addTo(map);
  const el = $("#ch-pixel");
  el.innerHTML = `<p class="note">Reading 39 years at ${ll.lat.toFixed(5)}, ${ll.lng.toFixed(5)}…</p>`;
  try {
    const r = await api("point", {lon: ll.lng, lat: ll.lat});
    const ys = r.years.map(d => d.year);
    el.innerHTML = "";
    const strip = document.createElement("div"), line = document.createElement("div");
    strip.className = line.className = "chart";
    el.append(strip, line);
    stripChart(strip, {title: `Pixel at ${r.lat.toFixed(5)}, ${r.lon.toFixed(5)}`, years: ys,
      sub: r.synthetic_ocean ? "Synthetic ocean fill: these colours are styled bathymetry, not imagery." :
        "Displayed colour each year; orange ticks mark years on a linearly gap-filled segment.",
      colors: r.years.map(d => `rgb(${d.rgb.join(",")})`), flags: r.years.map(d => d.linear),
      tip: i => `RGB ${r.years[i].rgb.join(", ")}<br>GLI ${fmt(r.years[i].gli, 3)}${r.years[i].de_prev != null ? `<br>ΔE from previous year ${fmt(r.years[i].de_prev, 1)}` : ""}${r.years[i].linear ? "<br>on a linear segment" : ""}`});
    lineChart(line, {title: "Greenness (GLI) at this pixel", years: ys, qa: r.years.map(d => d.linear ? 100 : 0),
      series: [{name: "GLI", values: r.years.map(d => d.gli), color: "var(--s1)"}], yfmt: v => fmt(v, 2), height: 140});
  } catch (e) {
    el.innerHTML = `<div class="warnline">${esc(e.message)}</div>`;
  }
}

/* ---------- wiring ---------- */
function fill(sel, from, to, value) {
  sel.innerHTML = S.meta.years.filter(y => y >= from && y <= to).map(y => `<option value="${y}">${y}</option>`).join("");
  sel.value = value;
}

export function initAnalyze() {
  const ys = S.meta.years;
  fill($("#ch-a"), 1984, 2022, 1990); fill($("#ch-b"), 1984, 2022, 2022);
  fill($("#yoc-s"), 1984, 2015, 1988); fill($("#yoc-e"), 1991, 2022, 2022);
  fill($("#tr-s"), 1984, 2015, 1988); fill($("#tr-e"), 1991, 2022, 2022);
  $("#qa-mode").innerHTML = `<option value="count">Number of gap-filled years per pixel</option>` +
    ys.map(y => `<option value="${y}">${y}: pixels on a linear segment</option>`).join("");
  $("#qa-mode").value = "1985";
  $$("#anmode button").forEach(b => b.addEventListener("click", () => {
    anMode = b.dataset.an;
    $$("#anmode button").forEach(x => x.setAttribute("aria-pressed", x === b));
    for (const m of ["change", "yoc", "trend", "qa"]) $("#an-" + m).hidden = m !== anMode;
    refreshLayer();
  }));
  ["#ch-a", "#ch-b", "#ch-window", "#ch-metric", "#yoc-s", "#yoc-e", "#yoc-m", "#tr-s", "#tr-e", "#tr-alpha", "#qa-mode"]
    .forEach(id => $(id).addEventListener("change", refreshLayer));
  $("#ts-csv").addEventListener("click", exportCsv);
  $("#ts-json").addEventListener("click", () => download(JSON.stringify({meta: meta(), years: rows()}, null, 1), slug(S.aoi.info.name) + "_1984-2022.json", "application/json"));
  $("#ts-table").addEventListener("click", showTable);
  $("#an-tif").addEventListener("click", downloadTif);
  $("#an-png").addEventListener("click", saveImage);
  $("#inspect").addEventListener("change", e => {
    $("#map").style.cursor = e.target.checked ? "crosshair" : "";
    if (!e.target.checked) { pin?.remove(); pin = null; }
  });
  on("map:click", inspect);
  on("analysis:refresh", refreshLayer);
  on("aoi", a => {
    tsAbort?.abort();
    tsAbort = null;
    $("#ts-tablewrap").hidden = true;
    $("#ts-table").textContent = "Show table";
    ["#ch-gli", "#ch-cover", "#ch-de", "#ch-qa", "#ch-strip", "#ch-stats", "#ch-yoc", "#tr-stats"].forEach(id => { $(id).innerHTML = ""; });
    if (!a) { setAnalysisLayer(null); return; }
    if (S.tab === "analyze") loadSeries();
    if (anMode !== "none") refreshLayer();
  });
  on("tab", t => { if (t === "analyze" && S.aoi) loadSeries(); });
  on("years:suggest", ({a, b}) => { $("#ch-a").value = a; $("#ch-b").value = b; if (anMode === "change") refreshLayer(); });
}
