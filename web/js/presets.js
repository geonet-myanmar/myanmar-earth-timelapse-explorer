// Places with well-known change, each with suggested before/after years (boxes checked against the imagery).
import {$, esc} from "./util.js";
import {emit} from "./state.js";
import {setAoi} from "./aoi.js";

export let presets = [];

export async function initPresets() {
  presets = await (await fetch("data/presets.json")).json();
  $("#presets").innerHTML = presets.map(p => `<button class="preset" type="button" data-id="${p.id}">
      <b>${esc(p.name)}</b><span>${esc(p.region)} · ${p.years[0]} → ${p.years[1]}</span><span>${esc(p.blurb)}</span></button>`).join("");
  $("#presets").addEventListener("click", e => {
    const b = e.target.closest("[data-id]");
    if (b) usePreset(b.dataset.id).catch(() => {});
  });
}

export async function usePreset(id) {
  const p = presets.find(x => x.id === id);
  if (!p) return;
  const [w, s, e, n] = p.bbox;
  const geometry = {type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]]};
  await setAoi({kind: "geojson", geometry, name: p.name, preset: p.id}, {source: `Place · ${p.region}`});
  emit("years:suggest", {a: p.years[0], b: p.years[1]});
}
