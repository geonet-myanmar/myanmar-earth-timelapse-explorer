// Boot: metadata, map, modules, tabs, theme, and restoring the last view.
import {api} from "./api.js";
import {$, $$, toast, store} from "./util.js";
import {S, on, emit, readHash, writeHash} from "./state.js";
import {setBasemap, setLabels, setDim, setGrey, setTimelapseVisible, onTheme, renderBadge} from "./map.js";
import {setAoi} from "./aoi.js";
import {initAdmin, useAdmin, setAdminOutline} from "./aoi-admin.js";
import {initDraw} from "./aoi-draw.js";
import {initUpload} from "./aoi-upload.js";
import {initPresets, usePreset} from "./presets.js";
import {initExplore, setYear, restoreCompare} from "./explore.js";
import {initAnalyze, geotiff} from "./analyze.js";
import {initVideo} from "./video.js";
import {renderAbout} from "./about.js";

/* ---------- theme ---------- */
const THEMES = ["auto", "light", "dark"];
function applyTheme(t) {
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  const b = $("#themebtn");
  b.textContent = t === "dark" ? "☾" : t === "light" ? "☀" : "◐";
  b.title = `Theme: ${t === "auto" ? "follow system" : t}`;
  store.set("theme", t);
  onTheme();
  emit("theme", t);
}
$("#themebtn").addEventListener("click", () => {
  const cur = store.get("theme", "auto");
  applyTheme(THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length]);
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { onTheme(); emit("theme"); });

/* ---------- tabs ---------- */
const tabs = $$("#tabs button");
export function openTab(name) {
  if (!tabs.some(b => b.dataset.tab === name)) name = "area";
  S.tab = name;
  tabs.forEach(b => b.setAttribute("aria-selected", b.dataset.tab === name));
  $$(".tab").forEach(t => { t.hidden = t.id !== "tab-" + name; });
  writeHash();
  emit("tab", name);
}
tabs.forEach((b, i) => {
  b.addEventListener("click", () => openTab(b.dataset.tab));
  b.addEventListener("keydown", e => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    n.focus();
    openTab(n.dataset.tab);
  });
});
on("tab", t => { if (t !== S.tab) openTab(t); });

/* ---------- area mode switch ---------- */
$$("#aoimode button").forEach(b => b.addEventListener("click", () => {
  $$("#aoimode button").forEach(x => x.setAttribute("aria-pressed", x === b));
  for (const m of ["admin", "draw", "upload", "presets"]) $("#mode-" + m).hidden = m !== b.dataset.mode;
}));

/* Tabs that need an area show a hint until one is chosen. */
on("aoi", a => {
  $$("[data-needaoi]").forEach(e => { e.hidden = !!a; });
  $$("[data-hasaoi]").forEach(e => { e.hidden = !a; });
});

/* ---------- layer panel ---------- */
function wireLayers() {
  const bm = $("#basemap");
  bm.value = store.get("basemap", "imagery");
  setBasemap(bm.value);
  bm.addEventListener("change", () => { setBasemap(bm.value); store.set("basemap", bm.value); });
  const chk = (id, fn, def) => {
    const el = $(id);
    el.checked = store.get(id, def);
    fn(el.checked);
    el.addEventListener("change", () => { fn(el.checked); store.set(id, el.checked); });
  };
  chk("#ly-timelapse", setTimelapseVisible, true);
  chk("#ly-labels", setLabels, true);
  chk("#ly-admin", setAdminOutline, false);
  chk("#ly-dim", setDim, true);
  chk("#ly-grey", setGrey, true);
  if (innerWidth < 700) $("#layers").open = false;
}

/* ---------- boot ---------- */
async function boot() {
  applyTheme(store.get("theme", "auto"));
  try {
    S.meta = await api("meta");
  } catch (e) {
    toast(e.message, "err", 0);
    return;
  }
  await initAdmin();
  wireLayers();
  initDraw();
  initUpload();
  await initPresets();
  initExplore();
  initAnalyze();
  initVideo(geotiff);
  renderAbout();

  const h = readHash();
  S.year = h.year && h.year >= 1984 && h.year <= 2022 ? h.year : 2022;
  setYear(S.year);
  try {
    if (h.aoi) await useAdmin(h.aoi);
    else if (h.place) await usePreset(h.place);
    else {
      const c = store.get("customAoi");
      if (c?.spec) await setAoi(c.spec, {source: c.source});
    }
  } catch { /* the toast explains */ }
  if (h.year) setYear(h.year);
  restoreCompare(h.cmp, h.cy);
  openTab(h.tab || "area");
  if (!S.aoi) emit("aoi", null);
  renderBadge();
}
boot();
addEventListener("hashchange", () => {
  const h = readHash();
  if (h.tab && h.tab !== S.tab) openTab(h.tab);
});
