"""Calibrate the indicative thresholds in app/dataset.py on Myanmar pixels.

Class separation: ESA WorldCover 2021 (homogeneous 3x3 windows) sampled against the 2021 mosaic.
Noise: Hansen stable forest (tree cover 2000 >= 80 %, no loss to 2025) gives the year-to-year and
3-year-window variation that a "change" threshold has to clear. Run with the app's EE credentials.
"""
import json, sys
from pathlib import Path
import numpy as np
import ee

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import npmath as M
from app.config import COLLECTION, HANSEN
from app.ee_client import init

init()
# 0.4-degree boxes across Myanmar's main landscapes (a country-wide stratified sample times out interactively).
BOXES = {
    "Yangon": (95.95, 16.70), "Mandalay": (96.00, 21.90), "Naypyitaw": (96.10, 19.70), "Delta Bogale": (95.30, 16.10),
    "Dry zone Magway": (94.90, 20.15), "Bago Yoma": (96.10, 18.70), "Shan Taunggyi": (96.95, 20.75),
    "Kachin Myitkyina": (97.35, 25.35), "Hpakant": (96.30, 25.60), "Tanintharyi Myeik": (98.65, 12.40),
    "Rakhine Sittwe": (92.85, 20.10), "Chin Hakha": (93.60, 22.65), "Sagaing Monywa": (95.10, 22.10),
    "Ayeyarwady sand bars": (95.20, 18.80),
}
REGIONS = [ee.Geometry.Rectangle([x - .2, y - .2, x + .2, y + .2]) for x, y in BOXES.values()]
WC = {10: "tree", 20: "shrub", 30: "grass", 40: "crop", 50: "built", 60: "bare", 80: "water", 95: "mangrove"}
VEG, BRIGHT = {"tree", "shrub", "grass", "crop", "mangrove"}, {"built", "bare"}


def sample_classes():
    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
    mm_ = wc.reduceNeighborhood(ee.Reducer.minMax(), ee.Kernel.square(45, "meters"))
    homo = mm_.select("Map_min").eq(mm_.select("Map_max"))
    img = wc.updateMask(homo).rename("cls").addBands(ee.Image(f"{COLLECTION}/2021"))
    rows = []
    for reg in REGIONS:
        fc = img.stratifiedSample(numPoints=40, classBand="cls", region=reg, scale=30, seed=11,
                                  classValues=list(WC), classPoints=[40] * len(WC), geometries=False, tileScale=8)
        rows += fc.getInfo()["features"]
    out = {}
    for f in rows:
        p = f["properties"]
        name = WC.get(int(p["cls"]))
        if name and p.get("red") is not None:
            out.setdefault(name, []).append((p["red"], p["green"], p["blue"]))
    return {k: np.array(v, float).T for k, v in out.items()}


def sample_stable_forest(n=120, y0=1988, y1=2022):
    h = ee.Image(HANSEN)
    stable = h.select("treecover2000").gte(80).And(h.select("lossyear").unmask(0).eq(0)).And(h.select("datamask").eq(1))
    stack = ee.ImageCollection(COLLECTION).filter(ee.Filter.rangeContains("year", y0, y1)).toBands()
    rows = []
    for reg in REGIONS:
        fc = stack.updateMask(stable).sample(region=reg, scale=30, numPixels=n * 4, seed=5, geometries=False, tileScale=8).limit(n)
        rows += fc.getInfo()["features"]
    yrs = list(range(y0, y1 + 1))
    arr = np.array([[[f["properties"][f"{y}_{b}"] for b in ("red", "green", "blue")] for y in yrs] for f in rows], float)
    return yrs, arr   # (pixels, years, 3)


def sample_all_land(years, n=150):
    """Every land cover (not only forest): the null for change classes, which mostly sit in farmland and scrub."""
    h = ee.Image(HANSEN)
    stack = ee.ImageCollection([ee.Image(f"{COLLECTION}/{y}") for y in years]).toBands()
    rows = []
    for reg in REGIONS:
        fc = stack.updateMask(h.select("datamask").eq(1)).sample(region=reg, scale=30, numPixels=n * 2, seed=9, geometries=False, tileScale=8).limit(n)
        rows += fc.getInfo()["features"]
    keys = sorted({k for f in rows for k in f["properties"]})
    def band(y, b):
        return next(k for k in keys if k.endswith(f"{y}_{b}") or k == f"{years.index(y)}_{b}")
    arr = np.array([[[f["properties"][band(y, b)] for b in ("red", "green", "blue")] for y in years] for f in rows], float)
    return arr


def best_split(pos, neg, lo, hi, above=True):
    best = (0, None)
    for t in np.linspace(lo, hi, 401):
        tp = (pos > t).mean() if above else (pos < t).mean()
        tn = (neg <= t).mean() if above else (neg >= t).mean()
        if (tp + tn) / 2 > best[0]:
            best = ((tp + tn) / 2, t)
    return best


def pct(a, q):
    return float(np.nanpercentile(a, q))


def main():
    cls = sample_classes()
    print("== WorldCover 2021 classes vs the 2021 mosaic (homogeneous 90 m windows)")
    print(f"{'class':9s} {'n':>4s}  GLI p10/p50/p90          brightness p10/p50/p90")
    stats = {}
    for k, (r, g, b) in sorted(cls.items(), key=lambda kv: -len(kv[1][0])):
        gl, br = M.gli(r, g, b), M.brightness(r, g, b)
        stats[k] = (gl, br)
        print(f"{k:9s} {len(r):4d}  {pct(gl,10):+.3f} {pct(gl,50):+.3f} {pct(gl,90):+.3f}    {pct(br,10):.3f} {pct(br,50):.3f} {pct(br,90):.3f}")
    veg = np.concatenate([stats[k][0] for k in VEG if k in stats])
    non = np.concatenate([stats[k][0] for k in stats if k not in VEG])
    acc, t_green = best_split(veg, non, -0.2, 0.3)
    print(f"\ngreen_gli: GLI > {t_green:.3f} separates vegetation from built/bare/water, balanced acc {acc:.3f}")
    bpos = np.concatenate([stats[k][1] for k in BRIGHT if k in stats])
    bneg = np.concatenate([stats[k][1] for k in stats if k not in BRIGHT])
    acc_b, t_bright = best_split(bpos, bneg, 0.03, 0.4)
    gpos = np.concatenate([stats[k][0] for k in BRIGHT if k in stats])
    print(f"bare_bright: brightness > {t_bright:.3f} (balanced acc {acc_b:.3f}); built/bare GLI p90 {pct(gpos, 90):+.3f}")

    yrs_all, arr_all = sample_stable_forest()
    i0, i1 = yrs_all.index(1999), yrs_all.index(2014) + 1
    yrs, arr = yrs_all[i0:i1], arr_all[:, i0:i1]                  # one sensor family, same 30 m grid
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    gl, br = M.gli(r, g, b), M.brightness(r, g, b)
    de1 = np.stack([M.delta_e(arr[:, i].T, arr[:, i + 1].T) for i in range(len(yrs) - 1)], 1)
    dg1, db1 = np.abs(np.diff(gl, axis=1)), np.abs(np.diff(br, axis=1))
    win = [(gl[:, t - 3:t].mean(1) - gl[:, t:t + 3].mean(1)) for t in range(3, len(yrs) - 2)]
    wde = [M.delta_e(arr[:, t:t + 3].mean(1).T, arr[:, t - 3:t].mean(1).T) for t in range(3, len(yrs) - 2)]
    print(f"\n== Stable forest, {arr.shape[0]} pixels, {yrs[0]}-{yrs[-1]} (no Hansen loss to 2025)")
    for name, a in [("year-to-year dE", de1), ("|dGLI|", dg1), ("|d brightness|", db1),
                    ("3-yr window GLI drop", np.stack(win, 1)), ("3-yr window dE", np.stack(wde, 1))]:
        print(f"{name:22s} p50 {pct(a,50):.4f}  p95 {pct(a,95):.4f}  p99 {pct(a,99):.4f}")

    # Year-of-change keeps each pixel's LARGEST window out of ~30, so its threshold must control the maximum,
    # not a single window (1 - 0.99^30 = 26 % of stable pixels would pass a per-window p99).
    A = arr_all
    gl_all = M.gli(A[..., 0], A[..., 1], A[..., 2])
    ts = range(3, len(yrs_all) - 2)
    drop = np.stack([gl_all[:, t - 3:t].mean(1) - gl_all[:, t:t + 3].mean(1) for t in ts], 1)
    wde = np.stack([M.delta_e(A[:, t:t + 3].mean(1).T, A[:, t - 3:t].mean(1).T) for t in ts], 1)
    print(f"\n== Stable forest {yrs_all[0]}-{yrs_all[-1]}: per-pixel MAXIMUM over {len(ts)} windows (year-of-change)")
    for name, a in [("max 3-yr GLI drop", drop.max(1)), ("max 3-yr window dE", wde.max(1))]:
        print(f"{name:22s} p50 {pct(a,50):.4f}  p90 {pct(a,90):.4f}  p95 {pct(a,95):.4f}  p99 {pct(a,99):.4f}")
    # Change classes: null comparisons of nearby years / 3-year windows over ALL land, both sensor eras.
    for label, yrs in [("Landsat era", [2000, 2001, 2002, 2003, 2004, 2005]), ("Sentinel-2 era", [2016, 2017, 2018, 2019, 2020, 2021])]:
        A = sample_all_land(yrs)
        a1, b1 = A[:, 1], A[:, 2]                              # adjacent single years
        a3, b3 = A[:, 0:3].mean(1), A[:, 3:6].mean(1)          # adjacent 3-year windows
        for name, (pa, pb) in [("single years", (a1, b1)), ("3-year means", (a3, b3))]:
            de = M.delta_e(pb.T, pa.T)
            dg = np.abs(M.gli(*pb.T) - M.gli(*pa.T))
            db = np.abs(M.brightness(*pb.T) - M.brightness(*pa.T))
            print(f"null {label:14s} {name:13s} n={len(de)}: dE p90 {pct(de,90):5.2f} p95 {pct(de,95):5.2f} | "
                  f"|dGLI| p90 {pct(dg,90):.3f} p95 {pct(dg,95):.3f} | |dBright| p90 {pct(db,90):.4f} p95 {pct(db,95):.4f}")
    # Year of change over ALL land: the per-pixel maximum over every window, 1988-2022.
    yrs = list(range(1988, 2023))
    A = sample_all_land(yrs, n=120)
    G = M.gli(A[..., 0], A[..., 1], A[..., 2])
    ts = range(3, len(yrs) - 2)
    drop = np.stack([G[:, t - 3:t].mean(1) - G[:, t:t + 3].mean(1) for t in ts], 1).max(1)
    wde = np.stack([M.delta_e(A[:, t:t + 3].mean(1).T, A[:, t - 3:t].mean(1).T) for t in ts], 1).max(1)
    print(f"all-land max 3-yr GLI drop  n={len(drop)}: p50 {pct(drop,50):.3f} p80 {pct(drop,80):.3f} p90 {pct(drop,90):.3f} p95 {pct(drop,95):.3f}")
    print(f"all-land max 3-yr window dE n={len(wde)}: p50 {pct(wde,50):.2f} p80 {pct(wde,80):.2f} p90 {pct(wde,90):.2f} p95 {pct(wde,95):.2f}")
    taus = []
    from scipy.stats import kendalltau
    for px in gl_all:
        taus.append(kendalltau(np.arange(len(px)), px).pvalue)
    taus = np.array(taus)
    print(f"Mann-Kendall p < 0.05 on {100 * (taus < 0.05).mean():.1f}% of stable-forest pixels (trend false-positive rate)")
    # Sen's slope (GLI per decade) of stable forest: the dataset's own drift + noise band a real trend must leave.
    x = np.arange(len(yrs_all))
    i, j = np.triu_indices(len(x), 1)
    sen = np.array([np.median((px[j] - px[i]) / (x[j] - x[i])) for px in gl_all]) * 10
    print("Sen slope / decade      " + "  ".join(f"p{q:g} {pct(sen, q):+.4f}" for q in (1, 2.5, 5, 50, 95, 97.5, 99)))
    for lo, hi in [(pct(sen, 2.5), pct(sen, 97.5)), (pct(sen, 1), pct(sen, 99))]:
        fp = ((taus < 0.05) & ((sen < lo) | (sen > hi))).mean() * 100
        print(f"  outside [{lo:+.4f}, {hi:+.4f}] and p < 0.05: {fp:.1f}% of stable forest")
    write_reference()


def write_reference():
    """National stable-forest median GLI per year: the dataset's own drift (sensor eras, compositing), drawn as a
    reference line on the app's greenness chart. Written to data/calibration.json."""
    yrs, arr = sample_stable_forest(n=120, y0=1984, y1=2022)
    G = M.gli(arr[..., 0], arr[..., 1], arr[..., 2])
    ref = {"stable_forest_gli_median": {str(y): round(float(v), 4) for y, v in zip(yrs, np.median(G, axis=0))},
           "n_pixels": int(G.shape[0]), "boxes": list(BOXES),
           "source": "Hansen GFC 2025 tree cover 2000 >= 80 % and no loss to 2025, 14 boxes across Myanmar"}
    out = ROOT / "data/calibration.json"
    out.write_text(json.dumps(ref, indent=1), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} ({ref['n_pixels']} pixels)")


if __name__ == "__main__":
    write_reference() if "--reference" in sys.argv else main()
