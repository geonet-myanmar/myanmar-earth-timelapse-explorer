// The Leaflet map: basemaps, the Earth Engine year layer (crossfade, swipe, flicker), the analysis overlay,
// the AOI outline + outside mask, the legend and the year badge.
import {api} from "./api.js";
import {$, esc, fmt, toast} from "./util.js";
import {S, on, emit, era} from "./state.js";

export const isDark = () => {
  const t = document.documentElement.getAttribute("data-theme");
  return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
};

export const map = L.map("map", {zoomSnap: 0.5, zoomDelta: 0.5, minZoom: 4, maxZoom: 18, attributionControl: true})
  .setView([19.4, 96.3], 6);
for (const [name, z] of [["base", 150], ["tl", 250], ["an", 350], ["adm", 410], ["aoi", 420], ["lab", 450]]) {
  map.createPane(name).style.zIndex = z;
}
map.getPane("lab").style.pointerEvents = "none";
map.getPane("tl").classList.add("tl-pane");
map.attributionControl.setPrefix(false);
map.attributionControl.getContainer().addEventListener("click", e => {
  if (e.target.tagName !== "A") e.currentTarget.classList.toggle("open");
});

/* ---------- basemaps & labels (Esri: keyless; CARTO now watermarks tiles without an API key) ---------- */
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/{svc}/MapServer/tile/{z}/{y}/{x}";
const CANVAS_ATTR = "Basemap: Esri, HERE, Garmin, © OpenStreetMap contributors";
const BASES = {
  imagery: () => L.tileLayer(ESRI, {svc: "World_Imagery", pane: "base", maxZoom: 19, attribution: "Basemap: Esri, Maxar, Earthstar Geographics"}),
  light: () => L.tileLayer(ESRI, {svc: "Canvas/World_Light_Gray_Base", pane: "base", maxNativeZoom: 16, maxZoom: 19, attribution: CANVAS_ATTR}),
  dark: () => L.tileLayer(ESRI, {svc: "Canvas/World_Dark_Gray_Base", pane: "base", maxNativeZoom: 16, maxZoom: 19, attribution: CANVAS_ATTR}),
};
let base = null, labels = null;
export function setBasemap(name) {
  base?.remove();
  base = BASES[name] ? BASES[name]().addTo(map) : null;
}
/* Boundaries & Places is drawn for imagery (white text, dark halo), which is what sits under it here. */
export function setLabels(onoff) {
  labels?.remove();
  labels = onoff ? L.tileLayer(ESRI, {svc: "Reference/World_Boundaries_and_Places", pane: "lab", maxZoom: 19,
    attribution: "Labels: Esri"}).addTo(map) : null;
}

/* ---------- Earth Engine year layers ---------- */
const TL_ATTR = 'Imagery: <a href="https://developers.google.com/earth-engine/datasets/catalog/projects_ee-earth-timelapse_assets_annual">Google Earth Timelapse (Google, Landsat, Copernicus)</a>, CC BY 4.0';
const urlCache = new Map();
async function yearUrl(y, force = false) {
  const hit = urlCache.get(y);
  if (hit && !force && Date.now() - hit.t < 40 * 60e3) return hit.url;
  const r = await api("layer", {layer: {type: "year", year: y}});
  urlCache.set(y, {url: r.url, t: Date.now()});
  return r.url;
}

function eeLayer(url, year) {
  const l = L.tileLayer(url, {pane: "tl", maxZoom: 18, attribution: TL_ATTR, keepBuffer: 3});
  l._year = year;
  let last = 0;
  l.on("tileerror", async () => {          // expired map ID: fetch a fresh one, at most once a minute
    if (Date.now() - last < 60e3) return;
    last = Date.now();
    try { l.setUrl(await yearUrl(year, true)); } catch { /* shown elsewhere */ }
  });
  return l;
}

let cur = null, alt = null, showToken = 0, tlVisible = true;
const preloaded = new Map();

function retire(l) {
  if (!l) return;
  l.setOpacity(0);
  setTimeout(() => map.removeLayer(l), 320);
}

async function layerFor(y) {
  if (preloaded.has(y)) { const l = preloaded.get(y); preloaded.delete(y); return l; }
  const l = eeLayer(await yearUrl(y), y);
  l.setOpacity(0);
  l.addTo(map);
  return l;
}

export async function showYear(y) {
  const token = ++showToken;
  let l;
  try { l = await layerFor(y); } catch (e) { toast(e.message, "err"); return; }
  if (token !== showToken) { if (l !== cur) map.removeLayer(l); return; }
  const old = cur;
  cur = l;
  const reveal = () => {
    if (cur !== l || l._shown) return;
    l._shown = true;
    l.setOpacity(tlVisible ? 1 : 0);
    if (old && old !== l) retire(old);
    applyCompare();
  };
  if (l._loaded || l.isLoading?.() === false) reveal();
  l.once("load", () => { l._loaded = true; reveal(); });
  setTimeout(reveal, 1800);
  sentinelNotice(y);
}

export async function preload(y) {
  if (y == null || preloaded.has(y) || cur?._year === y) return;
  try {
    const l = eeLayer(await yearUrl(y), y);
    l.setOpacity(0);
    l.addTo(map);
    l.once("load", () => { l._loaded = true; });
    preloaded.set(y, l);
    while (preloaded.size > 2) {
      const [k, v] = preloaded.entries().next().value;
      preloaded.delete(k);
      map.removeLayer(v);
    }
  } catch { /* preloading is best-effort */ }
}

export function setTimelapseVisible(v) {
  tlVisible = v;
  cur?.setOpacity(v ? 1 : 0);
  if (alt) alt.setOpacity(v && S.cmpMode !== "off" ? 1 : 0);
}

let sentinelOn = false;
function sentinelNotice(y) {
  const want = y >= 2015 || (S.cmpMode !== "off" && S.cmpYear >= 2015);
  const txt = S.meta?.sentinel_notice || "Contains modified Copernicus Sentinel data";
  if (want && !sentinelOn) map.attributionControl.addAttribution(txt);
  if (!want && sentinelOn) map.attributionControl.removeAttribution(txt);
  sentinelOn = want;
}

/* ---------- compare: swipe & flicker ---------- */
let swipeFrac = 0.5, flickTimer = null, flickShowAlt = false;

export async function setCompare(mode, cmpYear) {
  S.cmpMode = mode;
  S.cmpYear = cmpYear;
  clearInterval(flickTimer);
  flickTimer = null;
  if (mode === "off") {
    if (alt) { map.removeLayer(alt); alt = null; }
  } else if (!alt || alt._year !== cmpYear) {
    const prev = alt;
    try { alt = eeLayer(await yearUrl(cmpYear), cmpYear); } catch (e) { toast(e.message, "err"); return; }
    alt.addTo(map);
    if (prev) map.removeLayer(prev);
  }
  if (mode === "flicker") {
    flickTimer = setInterval(() => { flickShowAlt = !flickShowAlt; applyCompare(); renderBadge(); }, 1000);
  }
  $("#swipe").hidden = $("#swipelabels").hidden = mode !== "swipe";
  applyCompare();
  renderBadge();
  sentinelNotice(S.year);
}

function clipRect(l, x0, x1) {
  const c = l?.getContainer?.();
  if (!c) return;
  if (x0 == null) { c.style.clip = ""; return; }
  const nw = map.containerPointToLayerPoint([0, 0]), se = map.containerPointToLayerPoint(map.getSize());
  c.style.clip = `rect(${nw.y}px, ${nw.x + x1}px, ${se.y}px, ${nw.x + x0}px)`;
}

function applyCompare() {
  const w = map.getSize().x, x = Math.round(w * swipeFrac);
  if (S.cmpMode === "swipe" && alt && cur) {
    alt.setOpacity(tlVisible ? 1 : 0);
    clipRect(alt, 0, x);
    clipRect(cur, x, w);
    $("#swipe").style.left = x + "px";
    $("#swipeL").textContent = S.cmpYear;
    $("#swipeL").style.right = (w - x + 10) + "px";
    $("#swipeR").textContent = S.year;
    $("#swipeR").style.left = (x + 10) + "px";
  } else {
    clipRect(cur, null);
    if (alt) {
      clipRect(alt, null);
      alt.setOpacity(tlVisible && S.cmpMode === "flicker" && flickShowAlt ? 1 : 0);
      alt.bringToFront?.();
    }
  }
}
map.on("move zoom resize zoomend moveend", applyCompare);

(function swipeDrag() {
  const h = $("#swipe .swipe-handle");
  const setFrac = clientX => {
    const r = $("#map").getBoundingClientRect();
    swipeFrac = Math.min(0.98, Math.max(0.02, (clientX - r.left) / r.width));
    h.setAttribute("aria-valuenow", Math.round(swipeFrac * 100));
    applyCompare();
  };
  h.addEventListener("pointerdown", e => {
    e.preventDefault();
    h.setPointerCapture(e.pointerId);
    map.dragging.disable();
    const move = ev => setFrac(ev.clientX);
    const up = () => { h.removeEventListener("pointermove", move); map.dragging.enable(); };
    h.addEventListener("pointermove", move);
    h.addEventListener("pointerup", up, {once: true});
    h.addEventListener("pointercancel", up, {once: true});
  });
  h.addEventListener("keydown", e => {
    const d = e.key === "ArrowLeft" ? -0.02 : e.key === "ArrowRight" ? 0.02 : 0;
    if (d) { swipeFrac = Math.min(0.98, Math.max(0.02, swipeFrac + d)); applyCompare(); e.preventDefault(); }
  });
})();

/* ---------- display filter on the timelapse pane ---------- */
let enhance = {b: 100, c: 100, s: 100}, grey = false;
export function filterString(f = enhance) {
  return `brightness(${f.b / 100}) contrast(${f.c / 100}) saturate(${f.s / 100})`;
}
export function setEnhance(f) { enhance = f; paintFilter(); }
export function setGrey(v) { grey = v; paintFilter(); }
function paintFilter() {
  const parts = [];
  if (enhance.b !== 100 || enhance.c !== 100 || enhance.s !== 100) parts.push(filterString());
  if (grey && anLayer) parts.push("grayscale(1) brightness(.9)");
  map.getPane("tl").style.filter = parts.join(" ");
}

/* ---------- analysis overlay ---------- */
let anLayer = null;
export function setAnalysisLayer(url, legend) {
  anLayer?.remove();
  anLayer = null;
  if (url) {
    anLayer = L.tileLayer(url, {pane: "an", maxZoom: 18, attribution: TL_ATTR});
    let last = 0;
    anLayer.on("tileerror", () => { if (Date.now() - last > 60e3) { last = Date.now(); emit("analysis:refresh"); } });
    anLayer.addTo(map);
  }
  renderLegend(url ? legend : null);
  paintFilter();
}

function renderLegend(lg) {
  const el = $("#legend");
  if (!lg) { el.hidden = true; el.innerHTML = ""; return; }
  let h = `<b>${esc(lg.title)}</b>`;
  if (lg.kind === "categorical") {
    h += lg.items.map(([c, n]) => `<div class="row"><span class="sw" style="background:${c}"></span>${esc(n)}</div>`).join("");
  } else {
    const f = v => lg.integer ? Math.round(v) : (Math.abs(v) < 1 ? fmt(v, 2) : fmt(v, 0));
    h += `<div class="ramp" style="background:linear-gradient(90deg,${lg.colors.join(",")})"></div>
      <div class="ends"><span>${f(lg.min)}${lg.low ? " " + esc(lg.low) : ""}</span><span>${f(lg.max)}${lg.high ? " " + esc(lg.high) : ""}</span></div>`;
  }
  if (lg.masked) h += `<div class="note">Transparent: ${esc(lg.masked)}</div>`;
  el.innerHTML = h;
  el.hidden = false;
}

/* ---------- AOI outline and outside mask ---------- */
let aoiGroup = null, dimOn = true, aoiGeo = null;
export function setAoiShape(geojson, fit = true) {
  aoiGroup?.remove();
  aoiGroup = null;
  aoiGeo = geojson;
  if (!geojson) return;
  aoiGroup = L.layerGroup().addTo(map);
  const polys = [];
  turf.flattenEach(geojson, f => { if (f.geometry?.type === "Polygon") polys.push(f.geometry.coordinates); });
  if (dimOn) {
    const world = [[-89, -360], [-89, 360], [89, 360], [89, -360]];
    const holes = polys.map(p => p[0].map(([x, y]) => [y, x]));
    L.polygon([world, ...holes], {pane: "aoi", stroke: false, fillColor: "#0b0f0d", fillOpacity: 0.45, interactive: false}).addTo(aoiGroup);
  }
  const style = [{color: "#0b0f0d", weight: 4.5, opacity: 0.55}, {color: "#ffffff", weight: 2, opacity: 0.95}];
  for (const st of style) L.geoJSON(geojson, {pane: "aoi", interactive: false, style: {...st, fill: false}}).addTo(aoiGroup);
  if (fit) {
    const b = L.geoJSON(geojson).getBounds();
    map.fitBounds(b, {padding: [40, 40], maxZoom: 14});
  }
}
export function setDim(v) { dimOn = v; if (aoiGeo) setAoiShape(aoiGeo, false); }

/* ---------- year badge ---------- */
export function renderBadge() {
  const y = S.cmpMode === "flicker" && flickShowAlt ? S.cmpYear : S.year;
  const e = era(y);
  const st = S.yearStats[y];
  let q = "";
  if (st && st.qa_pct != null && st.qa_pct >= 20) q = `<span class="q" title="Share of the area on a linearly gap-filled segment">${Math.round(st.qa_pct)}% gap-filled</span>`;
  else if (!st && y <= 1986) q = `<span class="q" title="In Myanmar these years are mostly reconstructed by linear gap-filling">likely gap-filled</span>`;
  const label = S.cmpMode === "flicker" ? (flickShowAlt ? "compare" : "slider") : "";
  $("#yearbadge").innerHTML = `<span class="y">${y}</span><span class="e">${esc(e.label)}${label ? " · " + label : ""}</span>${q}`;
}
on("stats:year", renderBadge);

/* ---------- clicks ---------- */
map.on("click", e => emit("map:click", e.latlng));

export function onTheme() {
  if (labels) setLabels(true);
}
