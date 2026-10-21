// App state, a tiny event bus, and the shareable part of the state in the URL hash.
const handlers = {};
export const on = (evt, fn) => (handlers[evt] ||= []).push(fn);
export const emit = (evt, data) => (handlers[evt] || []).forEach(fn => fn(data));

export const S = {
  meta: null,
  aoi: null,          // {spec, info}: spec is what the API takes; info is the server's cleaned summary
  year: 2022,
  cmpYear: 1990,
  cmpMode: "off",     // off | swipe | flicker
  tab: "area",
  yearStats: {},      // year -> stats for the current AOI (filled by the Analyze tab)
};

export function era(y) {
  return (S.meta?.eras || []).find(e => y >= e.from && y <= e.to) || {label: "", note: ""};
}

/* Share admin units, presets, year and tab; drawn or uploaded shapes stay in this browser. */
export function writeHash() {
  const p = new URLSearchParams();
  p.set("tab", S.tab);
  p.set("y", S.year);
  if (S.cmpMode !== "off") { p.set("cmp", S.cmpMode); p.set("cy", S.cmpYear); }
  const sp = S.aoi?.spec;
  if (sp?.kind === "admin") p.set("aoi", sp.pcode);
  else if (sp?.preset) p.set("place", sp.preset);
  try { history.replaceState(null, "", "#" + p.toString()); } catch { /* ignore */ }
}

export function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  return {tab: p.get("tab"), year: +p.get("y") || null, cmp: p.get("cmp"), cy: +p.get("cy") || null,
          aoi: p.get("aoi"), place: p.get("place")};
}
