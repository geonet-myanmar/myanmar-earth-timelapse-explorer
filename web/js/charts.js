// Hand-written SVG charts (dataviz specs: 2px lines, 4px rounded bar ends on the baseline, 2px gaps between bars,
// recessive grid, crosshair + tooltip on lines, per-bar tooltips). Colours are CSS variables so themes repaint.
import {esc, fmt, showTip, hideTip} from "./util.js";
import {S} from "./state.js";

const NS = "http://www.w3.org/2000/svg";
function svg(w, h) { const s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", `0 0 ${w} ${h}`); s.setAttribute("role", "img"); return s; }
function add(p, tag, at = {}, txt) {
  const e = document.createElementNS(NS, tag);
  for (const k in at) e.setAttribute(k, at[k]);
  if (txt != null) e.textContent = txt;
  p.appendChild(e);
  return e;
}
function nice(lo, hi, n = 4) {
  if (hi === lo) { hi += 1; lo -= 1; }
  const span = hi - lo, p = Math.pow(10, Math.floor(Math.log10(span / n)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * p).find(s => span / s <= n) || p * 10;
  return {lo: Math.floor(lo / step) * step, hi: Math.ceil(hi / step) * step, step};
}
function head(el, o) {
  el.innerHTML = `<div class="ttl">${esc(o.title)}</div>${o.sub ? `<div class="sub">${o.sub}</div>` : ""}`;
}
const W = 420;

/* Era bands (alternating tint), the 2015 grid change, and gap-filled years (warning tint). */
function backdrop(s, x, m, H, years, qa) {
  const g = add(s, "g");
  (S.meta?.eras || []).forEach((e, i) => {
    if (i % 2) add(g, "rect", {x: x(e.from - 0.5), y: m.t, width: x(e.to + 0.5) - x(e.from - 0.5), height: H - m.t - m.b, style: "fill:var(--era)"});
  });
  if (qa) years.forEach((y, i) => {
    if (qa[i] != null && qa[i] >= 20) add(g, "rect", {x: x(y - 0.5), y: m.t, width: x(y + 0.5) - x(y - 0.5), height: H - m.t - m.b, style: "fill:var(--shade)"});
  });
  if (years[0] < 2015 && years[years.length - 1] >= 2015) {
    add(g, "line", {x1: x(2014.5), x2: x(2014.5), y1: m.t, y2: H - m.b, style: "stroke:var(--muted)", "stroke-dasharray": "2 3", "stroke-width": 1});
    add(g, "text", {x: x(2014.5) + 3, y: m.t + 9}, "19 m grid →");
  }
}

function xAxis(s, x, H, m, years) {
  for (const y of [1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020]) {
    if (y >= years[0] && y <= years[years.length - 1]) add(s, "text", {x: x(y), y: H - 6, "text-anchor": "middle"}, y);
  }
}

export function lineChart(el, o) {
  head(el, o);
  const H = o.height || 170, m = {l: 40, r: o.series.length > 1 || o.ref ? 60 : 12, t: 12, b: 20};
  const years = o.years;
  const vals = [...o.series.flatMap(sr => sr.values), ...(o.ref?.values || [])].filter(v => v != null && !Number.isNaN(v));
  if (!vals.length) return;
  const sc = nice(o.ymin ?? Math.min(...vals), o.ymax ?? Math.max(...vals));
  const s = svg(W, H);
  el.appendChild(s);
  const x = y => m.l + (W - m.l - m.r) * (y - years[0]) / Math.max(1, years[years.length - 1] - years[0]);
  const yv = v => m.t + (H - m.t - m.b) * (1 - (v - sc.lo) / (sc.hi - sc.lo));
  backdrop(s, x, m, H, years, o.qa);
  for (let v = sc.lo; v <= sc.hi + 1e-9; v += sc.step) {
    add(s, "line", {x1: m.l, x2: W - m.r, y1: yv(v), y2: yv(v), class: Math.abs(v - sc.lo) < 1e-9 ? "ax" : "gl"});
    add(s, "text", {x: m.l - 6, y: yv(v) + 3.5, "text-anchor": "end"}, o.yfmt ? o.yfmt(v) : fmt(v, 2));
  }
  xAxis(s, x, H, m, years);
  if (o.ref) {                                        // context line (e.g. national stable forest), drawn under the data
    const d = o.ref.values.map((v, i) => v == null ? "" : `${i ? "L" : "M"}${x(years[i]).toFixed(1)},${yv(v).toFixed(1)}`).join("");
    add(s, "path", {d, fill: "none", style: "stroke:var(--muted)", "stroke-width": 1.5, "stroke-dasharray": "4 3"});
    const i = o.ref.values.length - 1;
    add(s, "text", {x: x(years[i]) + 5, y: yv(o.ref.values[i]) + 3.5}, o.ref.short || "ref");
  }
  o.series.forEach(sr => {
    let d = "", pen = false;
    sr.values.forEach((v, i) => {
      if (v == null || Number.isNaN(v)) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(years[i]).toFixed(1)},${yv(v).toFixed(1)}`;
      pen = true;
    });
    add(s, "path", {d, fill: "none", style: `stroke:${sr.color}`, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round"});
    if (o.series.length > 1) {                       // direct label at the line end
      const i = sr.values.map((v, k) => v == null ? -1 : k).filter(k => k >= 0).pop();
      if (i != null) add(s, "text", {x: x(years[i]) + 5, y: yv(sr.values[i]) + 3.5, class: "lab"}, sr.name);
    }
  });
  // crosshair
  const cross = add(s, "line", {y1: m.t, y2: H - m.b, style: "stroke:var(--ink2)", "stroke-width": 1, opacity: 0});
  const dots = o.series.map(sr => add(s, "circle", {r: 4, style: `fill:${sr.color};stroke:var(--panel)`, "stroke-width": 2, opacity: 0}));
  const hit = add(s, "rect", {x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent"});
  hit.addEventListener("mousemove", e => {
    const r = s.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(years.length - 1, Math.round((px - m.l) / (W - m.l - m.r) * (years.length - 1))));
    cross.setAttribute("x1", x(years[i])); cross.setAttribute("x2", x(years[i])); cross.setAttribute("opacity", 1);
    o.series.forEach((sr, k) => {
      const v = sr.values[i];
      dots[k].setAttribute("opacity", v == null ? 0 : 1);
      if (v != null) { dots[k].setAttribute("cx", x(years[i])); dots[k].setAttribute("cy", yv(v)); }
    });
    showTip(e, `<b>${years[i]}</b>` + o.series.map(sr => `<br>${o.series.length > 1 ? `<span class="sw" style="background:${sr.color}"></span> ${esc(sr.name)}: ` : ""}${sr.values[i] == null ? "–" : (o.tfmt || o.yfmt || (v => fmt(v, 3)))(sr.values[i])}`).join("") +
      (o.ref?.values[i] != null ? `<br><span class="note">${esc(o.ref.label)}: ${(o.tfmt || o.yfmt || (v => fmt(v, 3)))(o.ref.values[i])}</span>` : "") +
      (o.qa?.[i] != null && o.qa[i] >= 20 ? `<br><span class="note">${Math.round(o.qa[i])}% gap-filled</span>` : ""));
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("opacity", 0); dots.forEach(d => d.setAttribute("opacity", 0)); hideTip(); });
  if (o.series.length > 1) {
    const lg = document.createElement("div");
    lg.className = "leg";
    lg.innerHTML = o.series.map(sr => `<span><i class="sw" style="background:${sr.color}"></i>${esc(sr.name)}</span>`).join("");
    el.appendChild(lg);
  }
}

export function barChart(el, o) {
  head(el, o);
  const H = o.height || 150, m = {l: 40, r: 12, t: 12, b: 20};
  const xs = o.x, ys = o.y.map(v => v ?? 0);
  const sc = nice(0, Math.max(o.ymaxMin || 0, ...ys, o.ref?.v || 0));
  const s = svg(W, H);
  el.appendChild(s);
  const n = xs.length, bw = (W - m.l - m.r) / n, w = Math.max(1, Math.min(14, bw - 2));
  const xc = i => m.l + bw * (i + 0.5);
  const xOfYear = y => xc(xs.indexOf(y) >= 0 ? xs.indexOf(y) : (y - xs[0]));
  const yv = v => m.t + (H - m.t - m.b) * (1 - v / sc.hi);
  if (o.years !== false) backdrop(s, y => m.l + bw * (y - xs[0] + 0.5), m, H, xs, o.qa);
  for (let v = 0; v <= sc.hi + 1e-9; v += sc.step) {
    add(s, "line", {x1: m.l, x2: W - m.r, y1: yv(v), y2: yv(v), class: v === 0 ? "ax" : "gl"});
    add(s, "text", {x: m.l - 6, y: yv(v) + 3.5, "text-anchor": "end"}, o.yfmt ? o.yfmt(v) : fmt(v, 1));
  }
  if (o.years !== false) xAxis(s, y => xOfYear(y), H, m, xs);
  ys.forEach((v, i) => {
    const h = Math.max(0, yv(0) - yv(v)), r = Math.min(4, w / 2, h), x0 = xc(i) - w / 2;
    if (h > 0) add(s, "path", {d: `M${x0},${yv(0)} V${yv(v) + r} q0,-${r} ${r},-${r} H${x0 + w - r} q${r},0 ${r},${r} V${yv(0)} Z`,
      style: `fill:${(o.colorOf && o.colorOf(i)) || o.color || "var(--s1)"}`});
    const hit = add(s, "rect", {x: xc(i) - bw / 2, y: m.t, width: bw, height: H - m.t - m.b, fill: "transparent"});
    hit.addEventListener("mouseenter", e => showTip(e, o.tip ? o.tip(i) : `<b>${xs[i]}</b><br>${fmt(v, 2)}`));
    hit.addEventListener("mouseleave", hideTip);
  });
  if (o.ref) {
    add(s, "line", {x1: m.l, x2: W - m.r, y1: yv(o.ref.v), y2: yv(o.ref.v), style: "stroke:var(--ink2)", "stroke-dasharray": "4 3", "stroke-width": 1});
    add(s, "text", {x: W - m.r, y: yv(o.ref.v) - 4, "text-anchor": "end", class: "lab"}, o.ref.label);
  }
}

/* One swatch per year in the area's mean colour: the "colour barcode" of four decades. */
export function stripChart(el, o) {
  head(el, o);
  const H = 54, m = {l: 4, r: 4, t: 4, b: 18};
  const s = svg(W, H);
  el.appendChild(s);
  const n = o.years.length, bw = (W - m.l - m.r) / n;
  o.years.forEach((y, i) => {
    const c = o.colors[i];
    if (c) add(s, "rect", {x: m.l + i * bw, y: m.t, width: Math.max(1, bw - 1), height: H - m.t - m.b, fill: c});
    if (o.flags?.[i]) add(s, "rect", {x: m.l + i * bw, y: H - m.b + 2, width: Math.max(1, bw - 1), height: 3, style: "fill:var(--warn)"});
    const hit = add(s, "rect", {x: m.l + i * bw, y: m.t, width: bw, height: H - m.t - m.b, fill: "transparent"});
    hit.addEventListener("mouseenter", e => showTip(e, `<b>${y}</b>${o.tip ? "<br>" + o.tip(i) : ""}`));
    hit.addEventListener("mouseleave", hideTip);
    if (y % 10 === 0 || i === 0 || i === n - 1) add(s, "text", {x: m.l + i * bw + bw / 2, y: H - 3, "text-anchor": "middle"}, y);
  });
}
