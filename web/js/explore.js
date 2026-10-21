// Year slider and playback, two-year comparison (swipe / flicker), display enhancement.
import {$, $$, store} from "./util.js";
import {S, on, emit, era, writeHash} from "./state.js";
import {showYear, preload, setCompare, setEnhance, renderBadge} from "./map.js";

let playTimer = null;

export function setYear(y, {fromPlay = false} = {}) {
  y = Math.max(1984, Math.min(2022, y | 0));
  S.year = y;
  $("#yearslider").value = y;
  $("#yearout").textContent = y;
  $("#ex-year").textContent = y;
  const e = era(y);
  $("#ex-era").textContent = e.label + (e.note ? ` · ${e.note}` : "");
  qaNote();
  showYear(y);
  renderBadge();
  if (!fromPlay) writeHash();
  emit("year", y);
}

function qaNote() {
  const st = S.yearStats[S.year];
  $("#ex-qa").textContent = st?.qa_pct != null
    ? `${Math.round(st.qa_pct)}% of the area sits on a linearly gap-filled segment in ${S.year}.`
    : S.year <= 1986 ? "1984–1986 are mostly reconstructed by linear gap-filling in Myanmar; treat them as estimates." : "";
}
on("stats:year", qaNote);

function step() {
  let y = S.year + 1;
  if (y > 2022) {
    if (!$("#loop").checked) return stop();
    y = 1984;
  }
  setYear(y, {fromPlay: true});
  preload(y === 2022 ? 1984 : y + 1);
}

export function play() {
  stop();
  $("#playbtn").classList.add("on");
  $("#playbtn").setAttribute("aria-label", "Pause timelapse");
  if (S.year >= 2022) setYear(1984, {fromPlay: true});
  preload(S.year + 1);
  playTimer = setInterval(step, +$("#speed").value);
}

export function stop() {
  clearInterval(playTimer);
  playTimer = null;
  $("#playbtn").classList.remove("on");
  $("#playbtn").setAttribute("aria-label", "Play timelapse");
  writeHash();
}

function fillYears(sel, value) {
  sel.innerHTML = S.meta.years.map(y => `<option value="${y}">${y}</option>`).join("");
  sel.value = value;
}

function setCmpMode(mode) {
  $$("#cmpmode button").forEach(b => b.setAttribute("aria-pressed", b.dataset.cmp === mode));
  setCompare(mode, +$("#cmpyear").value);
  writeHash();
}

export function initExplore() {
  const sl = $("#yearslider");
  sl.addEventListener("input", () => { stop(); setYear(+sl.value); });
  $("#playbtn").addEventListener("click", () => (playTimer ? stop() : play()));
  $("#speed").addEventListener("change", () => { if (playTimer) play(); });
  document.addEventListener("keydown", e => {
    if (e.target.closest("input,select,textarea") || !$("#modal").hidden) return;
    if (e.key === " " && e.target === document.body) { e.preventDefault(); playTimer ? stop() : play(); }
    if (e.key === "ArrowRight" && e.altKey) setYear(S.year + 1);
    if (e.key === "ArrowLeft" && e.altKey) setYear(S.year - 1);
  });

  fillYears($("#cmpyear"), S.cmpYear);
  $$("#cmpmode button").forEach(b => b.addEventListener("click", () => setCmpMode(b.dataset.cmp)));
  $("#cmpyear").addEventListener("change", () => { if (S.cmpMode !== "off") setCompare(S.cmpMode, +$("#cmpyear").value); S.cmpYear = +$("#cmpyear").value; writeHash(); });

  const f = store.get("enhance", {b: 100, c: 100, s: 100});
  const ids = {b: "bright", c: "contrast", s: "sat"};
  const paint = () => {
    for (const k in ids) $("#o-" + ids[k]).textContent = f[k] + "%";
    setEnhance({...f});
    store.set("enhance", f);
    emit("enhance", {...f});
  };
  for (const k in ids) {
    const el = $("#f-" + ids[k]);
    el.value = f[k];
    el.addEventListener("input", () => { f[k] = +el.value; paint(); });
  }
  $("#f-reset").addEventListener("click", () => { for (const k in ids) { f[k] = 100; $("#f-" + ids[k]).value = 100; } paint(); });
  paint();

  on("years:suggest", ({a, b}) => {
    $("#cmpyear").value = a;
    S.cmpYear = a;
    stop();
    setYear(b);
    setCmpMode("swipe");
  });
}

export function restoreCompare(mode, cy) {
  if (cy) { $("#cmpyear").value = cy; S.cmpYear = cy; }
  if (mode && mode !== "off") setCmpMode(mode);
}
