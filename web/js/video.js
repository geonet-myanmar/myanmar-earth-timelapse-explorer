// Timelapse videos and stills, composed in the browser. Earth Engine renders one JPEG per year on a grid-snapped
// region (CORS-enabled), the canvas adds the mask, outline and annotations, and WebCodecs (mediabunny) encodes
// MP4 or WebM frame by frame, so 4K frames are never all held decoded at once. GIF goes through gifenc.
import {api} from "./api.js";
import {$, esc, fmt, fmtArea, pool, download, slug, toast, debounce} from "./util.js";
import {S, on, era} from "./state.js";
import {filterString} from "./map.js";

const R = 6378137;
const merc = (lon, lat) => [R * lon * Math.PI / 180, R * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360))];
const even = n => Math.max(2, Math.floor(n / 2) * 2);
const GIF_MAX = 1600;
let enhance = {b: 100, c: 100, s: 100};
on("enhance", f => { enhance = f; });

function settings() {
  return {
    from: +$("#v-from").value, to: +$("#v-to").value, step: +$("#v-step").value, fps: +$("#v-fps").value,
    preset: $("#v-preset").value, aspect: $("#v-aspect").value, title: $("#v-title").value.trim(), sub: $("#v-sub").value.trim(),
    outside: $("#v-outside").value, fade: +$("#v-fade").value, hold0: +$("#v-hold0").value, hold1: +$("#v-hold1").value,
    format: $("#v-format").value,
    show: Object.fromEntries(["year", "era", "qa", "timeline", "scale", "north", "outline", "filter"].map(k => [k, $("#v-" + k).checked])),
  };
}

function yearsOf(s) {
  const a = Math.min(s.from, s.to), b = Math.max(s.from, s.to), ys = [];
  for (let y = a; y <= b; y += s.step) ys.push(y);
  if (ys[ys.length - 1] !== b) ys.push(b);
  return ys;
}

/* ---------- plan line ---------- */
const updatePlan = debounce(async () => {
  if (!S.aoi) return;
  const s = settings(), n = yearsOf(s).length;
  try {
    const p = await api("frames/plan", {aoi: S.aoi.spec, preset: s.preset, aspect: s.aspect});
    let w = p.width, h = p.height, note = p.native ? "native 2015+ pixels" : p.upsampled ? "finer than the data: pixels are enlarged" : "coarser than native";
    if (s.format === "gif" && Math.max(w, h) > GIF_MAX) { const k = GIF_MAX / Math.max(w, h); w = even(w * k); h = even(h * k); note += `; GIF capped at ${GIF_MAX} px`; }
    const mb = n * p.width * p.height * 0.28 / 1e6;
    $("#v-plan").textContent = `${w.toLocaleString()} × ${h.toLocaleString()} px · ${fmt(p.ground_m, 1)} m per pixel on the ground (${note}) · ${n} frames · about ${fmt(mb, mb < 10 ? 1 : 0)} MB to download`;
  } catch (e) {
    $("#v-plan").textContent = e.message;
  }
}, 250);

/* ---------- drawing ---------- */
async function fontsReady() {
  try {
    await Promise.all(["700 40px 'IBM Plex Sans Condensed'", "600 20px 'IBM Plex Sans'", "400 20px 'Noto Sans Myanmar'", "500 14px 'IBM Plex Mono'"]
      .map(f => document.fonts.load(f, "1984 Aa ဖ")));
  } catch { /* system fonts are fine */ }
}

function aoiPaths(region, W, H) {
  const [x0, y0, x1, y1] = region, path = new Path2D(), mask = new Path2D();
  mask.rect(0, 0, W, H);
  const geo = S.aoi?.display;
  if (geo) turf.flattenEach(geo, f => {
    if (f.geometry?.type !== "Polygon") return;
    for (const ring of f.geometry.coordinates) {
      ring.forEach(([lon, lat], i) => {
        const [mx, my] = merc(lon, lat), px = (mx - x0) / (x1 - x0) * W, py = (y1 - my) / (y1 - y0) * H;
        if (i) { path.lineTo(px, py); mask.lineTo(px, py); } else { path.moveTo(px, py); mask.moveTo(px, py); }
      });
      path.closePath(); mask.closePath();
    }
  });
  return {path, mask};
}

function niceLen(m) {
  const p = Math.pow(10, Math.floor(Math.log10(m)));
  return [1, 2, 5, 10].map(k => k * p).filter(v => v <= m).pop() || p;
}

function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }

function attribution(years) {
  const parts = [S.meta.attribution + " · CC BY 4.0"];
  if (years.some(y => y >= 2015)) parts.push(S.meta.sentinel_notice);
  if (S.aoi?.spec.kind === "admin") parts.push(S.meta.mimu);
  return parts.join(" · ");
}

/* Static parts that depend only on the frame geometry. */
function makeScene(plan, W, H, s, years) {
  const u = Math.max(0.55, Math.min(W, H) / 1080);
  const {path, mask} = aoiPaths(plan.region, W, H);
  const mPerPx = plan.ground_m * plan.width / W;
  return {u, path, mask, mPerPx, W, H, s, years, attr: attribution(years)};
}

function drawFrame(ctx, sc, bmpA, bmpB, t, year, idx) {
  const {u, W, H, s} = sc;
  ctx.save();
  ctx.filter = s.show.filter ? filterString(enhance) : "none";
  ctx.drawImage(bmpA, 0, 0, W, H);
  if (bmpB && t > 0) { ctx.globalAlpha = t; ctx.drawImage(bmpB, 0, 0, W, H); }
  ctx.restore();
  if (s.outside !== "show") {
    ctx.fillStyle = s.outside === "black" ? "#000" : "rgba(8,10,9,.55)";
    ctx.fill(sc.mask, "evenodd");
  }
  if (s.show.outline) {
    ctx.lineJoin = "round";
    ctx.strokeStyle = "rgba(0,0,0,.55)"; ctx.lineWidth = 4 * u; ctx.stroke(sc.path);
    ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.8 * u; ctx.stroke(sc.path);
  }
  const shownYear = t > 0.5 && sc.years[idx + 1] ? sc.years[idx + 1] : year;
  const st = S.yearStats[shownYear];
  const pad = 28 * u;
  // title block, top left
  const lines = [];
  if (s.show.year) lines.push({text: String(shownYear), font: `700 ${86 * u}px 'IBM Plex Sans Condensed', sans-serif`, h: 82 * u});
  if (s.title) lines.push({text: s.title, font: `600 ${30 * u}px 'IBM Plex Sans', sans-serif`, h: 38 * u});
  if (s.sub) lines.push({text: s.sub, font: `400 ${26 * u}px 'Noto Sans Myanmar', 'IBM Plex Sans', sans-serif`, h: 40 * u});
  if (s.show.era) lines.push({text: era(shownYear).label, font: `500 ${21 * u}px 'IBM Plex Sans', sans-serif`, h: 30 * u, dim: true});
  const gap = st?.qa_pct != null ? st.qa_pct >= 20 : shownYear <= 1986;
  if (lines.length) {
    let w = 0;
    for (const l of lines) { ctx.font = l.font; w = Math.max(w, ctx.measureText(l.text).width); }
    const badge = s.show.qa && gap ? 1 : 0;
    const boxH = lines.reduce((a, l) => a + l.h, 0) + 22 * u + badge * 40 * u;
    ctx.fillStyle = "rgba(10,14,12,.62)";
    roundRect(ctx, pad, pad, w + 40 * u, boxH, 14 * u); ctx.fill();
    let y = pad + 14 * u;
    ctx.textBaseline = "top";
    for (const l of lines) {
      ctx.font = l.font; ctx.fillStyle = l.dim ? "rgba(255,255,255,.78)" : "#fff";
      ctx.fillText(l.text, pad + 20 * u, y + (l === lines[0] && s.show.year ? -4 * u : 0));
      y += l.h;
    }
    if (badge) {
      const label = st?.qa_pct != null ? `${Math.round(st.qa_pct)}% gap-filled` : "likely gap-filled";
      ctx.font = `600 ${19 * u}px 'IBM Plex Sans', sans-serif`;
      const bw = ctx.measureText(label).width + 26 * u;
      ctx.fillStyle = "#fab219"; roundRect(ctx, pad + 20 * u, y + 4 * u, bw, 30 * u, 15 * u); ctx.fill();
      ctx.fillStyle = "#15201b"; ctx.fillText(label, pad + 33 * u, y + 9 * u);
    }
  }
  // north arrow, top right
  if (s.show.north) {
    const cx = W - pad - 22 * u, cy = pad + 30 * u;
    ctx.fillStyle = "rgba(10,14,12,.55)"; ctx.beginPath(); ctx.arc(cx, cy, 28 * u, 0, 7); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.moveTo(cx, cy - 20 * u); ctx.lineTo(cx + 10 * u, cy + 12 * u); ctx.lineTo(cx, cy + 6 * u); ctx.lineTo(cx - 10 * u, cy + 12 * u); ctx.closePath(); ctx.fill();
    ctx.font = `700 ${13 * u}px 'IBM Plex Sans', sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.fillText("N", cx, cy + 14 * u); ctx.textAlign = "left";
  }
  // attribution strip, bottom
  const ah = 30 * u;
  ctx.fillStyle = "rgba(10,14,12,.62)"; ctx.fillRect(0, H - ah, W, ah);
  ctx.font = `400 ${14.5 * u}px 'IBM Plex Sans', sans-serif`; ctx.fillStyle = "rgba(255,255,255,.88)"; ctx.textBaseline = "middle";
  ctx.fillText(sc.attr, 12 * u, H - ah / 2, W - 24 * u);
  // scale bar, bottom right
  let barTop = H - ah - 14 * u;
  if (s.show.scale) {
    const L = niceLen(W * 0.18 * sc.mPerPx), px = L / sc.mPerPx;
    const x1 = W - pad, x0 = x1 - px, y0 = barTop - 10 * u;
    const label = L >= 1000 ? `${fmt(L / 1000)} km` : `${fmt(L)} m`;
    ctx.font = `600 ${17 * u}px 'IBM Plex Sans', sans-serif`;
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = "rgba(10,14,12,.55)"; roundRect(ctx, x0 - 12 * u, y0 - 30 * u, px + 24 * u, 44 * u, 8 * u); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.fillRect(x0, y0, px, 5 * u);
    ctx.fillRect(x0, y0 - 6 * u, 2 * u, 11 * u); ctx.fillRect(x1 - 2 * u, y0 - 6 * u, 2 * u, 11 * u);
    ctx.textBaseline = "bottom"; ctx.fillText(label, x0 + (px - tw) / 2, y0 - 6 * u);
  }
  // timeline, bottom left
  if (s.show.timeline && sc.years.length > 1) {
    const x0 = pad, x1 = s.show.scale ? W - pad - W * 0.18 - 60 * u : W - pad, y = barTop - 12 * u;
    const ys = sc.years, n = ys.length, pos = i => x0 + (x1 - x0) * i / (n - 1);
    const at = idx + (t > 0 ? t : 0);
    ctx.fillStyle = "rgba(10,14,12,.55)"; roundRect(ctx, x0 - 12 * u, y - 34 * u, x1 - x0 + 24 * u, 50 * u, 8 * u); ctx.fill();
    ctx.fillStyle = "rgba(255,255,255,.35)"; ctx.fillRect(x0, y - 2 * u, x1 - x0, 4 * u);
    ctx.fillStyle = "#fff"; ctx.fillRect(x0, y - 2 * u, (x1 - x0) * at / (n - 1), 4 * u);
    ctx.font = `500 ${14 * u}px 'IBM Plex Mono', monospace`; ctx.textBaseline = "bottom"; ctx.textAlign = "center";
    ys.forEach((yy, i) => {
      const q = S.yearStats[yy];
      const flagged = q?.qa_pct != null ? q.qa_pct >= 20 : yy <= 1986;
      ctx.fillStyle = flagged ? "#fab219" : "rgba(255,255,255,.8)";
      ctx.fillRect(pos(i) - 1 * u, y - 7 * u, 2 * u, 5 * u);
      if (yy % 10 === 0 || i === 0 || i === n - 1) ctx.fillText(yy, Math.min(Math.max(pos(i), x0 + 18 * u), x1 - 18 * u), y - 10 * u);
    });
    ctx.textAlign = "left";
    ctx.beginPath(); ctx.arc(x0 + (x1 - x0) * at / (n - 1), y, 7 * u, 0, 7); ctx.fillStyle = "#fff"; ctx.fill();
  }
}

/* ---------- fetching ---------- */
async function fetchFrames(fr, signal, onProgress) {
  const blobs = new Array(fr.frames.length);
  let got = 0;
  await pool(fr.frames, 4, async (f, i) => {
    for (let attempt = 0; ; attempt++) {
      try {
        const r = await fetch(f.url, {signal});
        if (!r.ok) throw new Error(`Earth Engine returned ${r.status} for ${f.year}`);
        blobs[i] = await r.blob();
        break;
      } catch (e) {
        if (e.name === "AbortError" || attempt >= 2) throw e;
        await new Promise(res => setTimeout(res, 1500 * (attempt + 1)));
      }
    }
    onProgress(++got / fr.frames.length);
  }, null, signal);
  return blobs;
}

/* ---------- render ---------- */
let ctl = null, lastUrl = null;

function progress(frac, text) {
  const b = $("#v-progress");
  b.hidden = frac == null;
  if (frac != null) b.firstElementChild.style.width = Math.round(frac * 100) + "%";
  if (text != null) $("#v-status").textContent = text;
}

async function render() {
  const s = settings(), years = yearsOf(s);
  ctl = new AbortController();
  const signal = ctl.signal;
  $("#v-render").disabled = true; $("#v-cancel").hidden = false;
  if (lastUrl) { URL.revokeObjectURL(lastUrl); lastUrl = null; }
  $("#v-out").hidden = true;
  try {
    progress(0, "Asking Earth Engine for the frames…");
    const fr = await api("frames", {aoi: S.aoi.spec, years, preset: s.preset, aspect: s.aspect, format: "jpg"}, {signal});
    let W = fr.width, H = fr.height, format = s.format;
    const blobs = await fetchFrames(fr, signal, f => progress(f * 0.55, `Downloading frames from Earth Engine… ${Math.round(f * years.length)}/${years.length}`));
    await fontsReady();
    let mb = null, codec = null;
    if (format !== "gif") {
      mb = await import("../vendor/mediabunny/bundles/mediabunny.min.mjs");
      for (const [f, c] of format === "mp4" ? [["mp4", "avc"], ["webm", "vp9"]] : [["webm", "vp9"], ["webm", "vp8"]]) {
        if (await mb.canEncodeVideo(c, {width: W, height: H})) { format = f; codec = c; break; }
      }
      if (!codec) { toast("This browser can't encode video at this size; making a GIF instead.", "", 7000); format = "gif"; }
    }
    if (format === "gif" && Math.max(W, H) > GIF_MAX) { const k = GIF_MAX / Math.max(W, H); W = even(W * k); H = even(H * k); }
    const canvas = document.createElement("canvas");
    canvas.width = W; canvas.height = H;
    const ctx = canvas.getContext("2d", {willReadFrequently: format === "gif"});
    const sc = makeScene(fr, W, H, s, years);
    const D = 1 / s.fps, k = format === "gif" ? 0 : s.fade;
    const steps = [];                                     // [index, blend t, duration]
    years.forEach((y, i) => {
      const last = i === years.length - 1;
      const solid = k && !last ? D * 0.6 : D;
      steps.push([i, 0, solid + (i === 0 ? s.hold0 : 0) + (last ? s.hold1 : 0)]);
      if (k && !last) for (let j = 1; j <= k; j++) steps.push([i, j / (k + 1), D * 0.4 / k]);
    });
    const bitmaps = new Map();
    const bmp = async i => {
      if (!bitmaps.has(i)) bitmaps.set(i, await createImageBitmap(blobs[i]));
      return bitmaps.get(i);
    };
    const release = i => {                              // frames before i are never drawn again
      for (const key of [...bitmaps.keys()]) if (key < i) { bitmaps.get(key).close(); bitmaps.delete(key); }
    };
    let blob, ext;
    if (format === "gif") {
      const {GIFEncoder, quantize, applyPalette} = await import("../vendor/gifenc/gifenc.esm.js");
      const gif = GIFEncoder();
      for (let n = 0; n < steps.length; n++) {
        if (signal.aborted) throw new DOMException("Cancelled", "AbortError");
        const [i, t, dur] = steps[n];
        drawFrame(ctx, sc, await bmp(i), t ? await bmp(i + 1) : null, t, years[i], i);
        release(i);
        const {data} = ctx.getImageData(0, 0, W, H);
        const palette = quantize(data, 256);
        gif.writeFrame(applyPalette(data, palette), W, H, {palette, delay: Math.round(dur * 1000)});
        progress(0.55 + 0.45 * (n + 1) / steps.length, `Encoding GIF… ${n + 1}/${steps.length}`);
        await new Promise(r => setTimeout(r, 0));
      }
      gif.finish();
      blob = new Blob([gif.bytes()], {type: "image/gif"}); ext = "gif";
    } else {
      const output = new mb.Output({format: format === "mp4" ? new mb.Mp4OutputFormat({fastStart: "in-memory"}) : new mb.WebMOutputFormat(),
                                    target: new mb.BufferTarget()});
      const source = new mb.CanvasSource(canvas, {codec, bitrate: mb.QUALITY_VERY_HIGH, keyFrameInterval: 2});
      output.addVideoTrack(source, {frameRate: Math.max(1, Math.round(k ? s.fps * (k + 1) : s.fps))});
      await output.start();
      let ts = 0;
      for (let n = 0; n < steps.length; n++) {
        if (signal.aborted) { await output.cancel(); throw new DOMException("Cancelled", "AbortError"); }
        const [i, t, dur] = steps[n];
        drawFrame(ctx, sc, await bmp(i), t ? await bmp(i + 1) : null, t, years[i], i);
        release(i);
        await source.add(ts, dur);
        ts += dur;
        progress(0.55 + 0.45 * (n + 1) / steps.length, `Encoding ${format.toUpperCase()} (${codec})… ${n + 1}/${steps.length}`);
      }
      await output.finalize();
      blob = new Blob([output.target.buffer], {type: format === "mp4" ? "video/mp4" : "video/webm"}); ext = format;
    }
    bitmaps.forEach(b => b.close());
    lastUrl = URL.createObjectURL(blob);
    const name = `timelapse_${slug(S.aoi.info.name)}_${years[0]}-${years[years.length - 1]}_${W}x${H}.${ext}`;
    $("#v-out").innerHTML = (ext === "gif" ? `<img src="${lastUrl}" alt="Timelapse GIF">` : `<video src="${lastUrl}" controls loop playsinline></video>`) +
      `<div class="btnrow"><button class="btn primary" type="button" id="v-dl">Download ${ext.toUpperCase()} (${fmt(blob.size / 1e6, 1)} MB)</button></div>`;
    $("#v-out").hidden = false;
    $("#v-dl").onclick = () => download(blob, name, blob.type);
    progress(null, `${W} × ${H} px, ${years.length} years, ${fmt(fr.ground_m * fr.width / W, 1)} m per pixel on the ground.`);
  } catch (e) {
    progress(null, e.name === "AbortError" ? "Cancelled." : e.message);
    if (e.name !== "AbortError") toast(e.message, "err", 9000);
  } finally {
    $("#v-render").disabled = false; $("#v-cancel").hidden = true; ctl = null;
  }
}

async function quick() {
  const s = settings(), years = yearsOf(s);
  progress(null, "Asking Earth Engine for a GIF (no annotations, up to about 820 px)…");
  try {
    const r = await api("gif", {aoi: S.aoi.spec, years, fps: s.fps, aspect: s.aspect});
    $("#v-out").innerHTML = `<img src="${r.url}" alt="Earth Engine preview GIF" width="${r.width}" height="${r.height}">
      <p class="note">Earth Engine's own GIF: ${r.width} × ${r.height} px (${fmt(r.ground_m, 0)} m per pixel), limited to 26.2 Mpx across all frames.
      Right-click to save. ${esc(S.meta.attribution)}, CC BY 4.0.</p>`;
    $("#v-out").hidden = false;
    $("#v-status").textContent = "";
  } catch (e) { progress(null, e.message); }
}

/* ---------- stills ---------- */
async function loadBitmap(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Earth Engine returned ${r.status}`);
  return createImageBitmap(await r.blob());
}

/* items: [{url, label}] laid out side by side (2) or as a grid (many); legend optional. Returns a PNG blob. */
export async function composeStill(items, {title = "", sub = "", legend = null, cols = null, years = null} = {}) {
  await fontsReady();
  const bms = await pool(items, 4, it => loadBitmap(it.url));
  const w = bms[0].width, h = bms[0].height, n = bms.length;
  const c = cols || (n <= 2 ? n : Math.min(8, Math.ceil(Math.sqrt(n * 1.6))));
  const rows = Math.ceil(n / c), u = Math.max(0.6, Math.min(w * c, 2400) / 1600), gap = Math.round(8 * u);
  const headH = Math.round((title ? 64 : 0) * u + (sub ? 28 : 0) * u + 16 * u), footH = Math.round(36 * u) + (legend ? Math.round(56 * u) : 0);
  const W = c * w + (c + 1) * gap, H = headH + rows * (h + gap) + gap + footH;
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  ctx.fillStyle = "#101513"; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = "#fff"; ctx.textBaseline = "top";
  if (title) { ctx.font = `700 ${40 * u}px 'IBM Plex Sans Condensed', sans-serif`; ctx.fillText(title, gap * 2, 14 * u); }
  if (sub) { ctx.font = `500 ${20 * u}px 'IBM Plex Sans', sans-serif`; ctx.fillStyle = "rgba(255,255,255,.75)"; ctx.fillText(sub, gap * 2, (title ? 62 : 14) * u); }
  bms.forEach((b, i) => {
    const x = gap + (i % c) * (w + gap), y = headH + Math.floor(i / c) * (h + gap);
    ctx.drawImage(b, x, y);
    if (items[i].label) {
      ctx.font = `700 ${(n > 4 ? 22 : 34) * u}px 'IBM Plex Sans Condensed', sans-serif`;
      const tw = ctx.measureText(items[i].label).width;
      ctx.fillStyle = "rgba(10,14,12,.65)"; ctx.beginPath(); ctx.roundRect(x + 8 * u, y + 8 * u, tw + 20 * u, (n > 4 ? 32 : 46) * u, 7 * u); ctx.fill();
      ctx.fillStyle = "#fff"; ctx.fillText(items[i].label, x + 18 * u, y + 13 * u);
    }
    b.close();
  });
  let fy = H - footH + 10 * u;
  if (legend) {
    ctx.font = `600 ${17 * u}px 'IBM Plex Sans', sans-serif`; ctx.fillStyle = "#fff"; ctx.fillText(legend.title, gap * 2, fy);
    const ly = fy + 26 * u;
    if (legend.kind === "categorical") {
      let x = gap * 2;
      for (const [col, name] of legend.items) {
        ctx.fillStyle = col; ctx.fillRect(x, ly, 16 * u, 16 * u);
        ctx.fillStyle = "rgba(255,255,255,.85)"; ctx.font = `400 ${15 * u}px 'IBM Plex Sans', sans-serif`; ctx.fillText(name, x + 22 * u, ly);
        x += ctx.measureText(name).width + 50 * u;
      }
    } else {
      const gw = 320 * u, g = ctx.createLinearGradient(gap * 2, 0, gap * 2 + gw, 0);
      legend.colors.forEach((col, i) => g.addColorStop(i / (legend.colors.length - 1), col));
      ctx.fillStyle = g; ctx.fillRect(gap * 2, ly, gw, 14 * u);
      ctx.fillStyle = "rgba(255,255,255,.85)"; ctx.font = `400 ${14 * u}px 'IBM Plex Sans', sans-serif`;
      ctx.fillText(`${legend.min}${legend.low ? " " + legend.low : ""}`, gap * 2 + gw + 12 * u, ly - 2 * u);
      ctx.fillText(`${legend.max}${legend.high ? " " + legend.high : ""}`, gap * 2 + gw + 12 * u, ly + 14 * u);
    }
    fy += 56 * u;
  }
  ctx.font = `400 ${14 * u}px 'IBM Plex Sans', sans-serif`; ctx.fillStyle = "rgba(255,255,255,.8)";
  ctx.fillText(attribution(years || [2022]), gap * 2, fy, W - gap * 4);
  return await new Promise(res => cv.toBlob(res, "image/png"));
}

async function beforeAfter() {
  const a = +$("#ba-a").value, b = +$("#ba-b").value;
  $("#st-status").textContent = "Rendering before/after…";
  try {
    const fr = await api("frames", {aoi: S.aoi.spec, years: [a, b], preset: "1080p", aspect: $("#v-aspect").value, format: "png"});
    const blob = await composeStill(fr.frames.map(f => ({url: f.url, label: String(f.year)})),
      {title: S.aoi.info.name, sub: `${a} and ${b} · ${fmt(fr.ground_m, 1)} m per pixel`, years: [a, b]});
    download(blob, `${slug(S.aoi.info.name)}_${a}_${b}.png`, "image/png");
    $("#st-status").textContent = "";
  } catch (e) { $("#st-status").textContent = e.message; }
}

async function filmstrip() {
  const s = settings(), years = yearsOf(s);
  $("#st-status").textContent = `Rendering a filmstrip of ${years.length} years…`;
  try {
    const fr = await api("frames", {aoi: S.aoi.spec, years, preset: "strip", aspect: s.aspect, format: "jpg"});
    const blob = await composeStill(fr.frames.map(f => ({url: f.url, label: String(f.year)})),
      {title: S.aoi.info.name, sub: `${years[0]}–${years[years.length - 1]}`, years});
    download(blob, `${slug(S.aoi.info.name)}_filmstrip_${years[0]}-${years[years.length - 1]}.png`, "image/png");
    $("#st-status").textContent = "";
  } catch (e) { $("#st-status").textContent = e.message; }
}

/* ---------- wiring ---------- */
function fill(sel, value) {
  sel.innerHTML = S.meta.years.map(y => `<option value="${y}">${y}</option>`).join("");
  sel.value = value;
}

export function initVideo(geotiff) {
  fill($("#v-from"), 1984); fill($("#v-to"), 2022); fill($("#ba-a"), 1990); fill($("#ba-b"), 2022);
  ["#v-from", "#v-to", "#v-step", "#v-preset", "#v-aspect", "#v-format"].forEach(id => $(id).addEventListener("change", updatePlan));
  $("#v-render").addEventListener("click", render);
  $("#v-cancel").addEventListener("click", () => ctl?.abort());
  $("#v-quick").addEventListener("click", quick);
  $("#ba-png").addEventListener("click", beforeAfter);
  $("#fs-png").addEventListener("click", filmstrip);
  $("#yr-tif").addEventListener("click", () => geotiff({type: "year", year: +$("#ba-b").value}));
  on("aoi", a => {
    if (!a) return;
    $("#v-title").value = a.info.name.replace(/ Township, .*/, " Township");
    $("#v-sub").value = a.info.name_my || "";
    updatePlan();
  });
  on("tab", t => { if (t === "timelapse") updatePlan(); });
  on("years:suggest", ({a, b}) => { $("#ba-a").value = a; $("#ba-b").value = b; });
}
