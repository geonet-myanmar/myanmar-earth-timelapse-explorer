"""Earth Timelapse access and the analysis maths.

The source is a visual 8-bit RGB product (TOA reflectance stretched 0.02-0.50, gamma 1.7, BRDF-matched,
ocean replaced by ETOPO1 bathymetry), so every index here is indicative, not radiometric.
"""
import json, threading
import ee
from .config import COLLECTION, YEARS, HANSEN, SCALE_FINE, CACHE
from .ee_client import call

BANDS = ["red", "green", "blue"]

# Thresholds from scripts/04_calibrate.py (2026-10-21): WorldCover 2021 classes in 14 boxes across Myanmar
# against the 2021 mosaic, and 558 Hansen stable-forest pixels for 1999-2014 as the no-change noise model.
T = {
    "green_gli": 0.08,      # best vegetation / non-vegetation split (GLI 0.081); tree p10 0.083. Green-tinted water also passes.
    "bare_bright": 0.14,    # best built+bare / other split on brightness (0.143) ...
    "bare_gli": 0.06,       # ... with GLI under the built/bare p90 (0.065)
    # Change thresholds come from NULL comparisons over all land cover (forest-only noise let 25-37 % of Naypyitaw's
    # farmland "change" between 2016 and 2020): adjacent years / adjacent 3-year windows, Landsat and Sentinel-2 eras.
    "de_visible": 17.0,     # single years: dE p95 16.2 (2001 vs 2002), 18.0 (2017 vs 2018)
    "dgli": 0.115,          # single years: |dGLI| p95 0.106 / 0.124
    "dbright": 0.055,       # single years: |d brightness| p95 0.048 / 0.066
    "de_visible_w3": 15.0,  # 3-year means: dE p95 11.6 (2000-02 vs 2003-05), 17.6 (2016-18 vs 2019-21)
    "dgli_w3": 0.09,        # 3-year means: |dGLI| p95 0.069 / 0.104
    "dbright_w3": 0.05,     # 3-year means: |d brightness| p95 0.037 / 0.065
    # Year-of-change keeps each pixel's largest of ~30 windows, so these bound the MAXIMUM, not one window
    # (a per-window p99 of 0.079 let 23 % of Hpakant through).
    "yoc_gli": 0.11,        # max 3-year GLI drop 1988-2022: stable forest p95 0.109, all land p90 0.111
    "yoc_de": 24.0,         # max 3-year window dE: stable forest p95 18.8, all land p90 23.7 (farmland is noisier)
    # Mann-Kendall alone flags 41 % of stable forest (sensor-transition colour drift), so a trend must also leave the
    # stable-forest Sen-slope band (p1 -0.036, p99 +0.037 per decade): together 2-5 % false positives.
    "trend_slope": 0.035,   # |GLI per decade|
    "qa_dn": 2,             # |second difference| <= this in all bands = collinear (gap-filled) triple
}

CLASS_NAMES = ["no visible change", "vegetation loss", "vegetation gain", "brightening", "darkening"]


def image(year):
    return ee.Image(f"{COLLECTION}/{int(year)}").select(BANDS)


# ---------- native grids ----------
_grids, _glock = {}, threading.Lock()


def grids():
    """{year: (crs, transform)} read from the assets once (the 2022 origin differs by one pixel)."""
    with _glock:
        if _grids:
            return _grids
        f = CACHE / "grids.json"
        if f.exists():
            data = json.loads(f.read_text())
        else:
            info = call(ee.List([image(y).select(0).projection() for y in YEARS]).getInfo)
            data = {str(y): [p["crs"], p["transform"]] for y, p in zip(YEARS, info)}
            CACHE.mkdir(exist_ok=True); f.write_text(json.dumps(data))
        _grids.update({int(y): (c, t) for y, (c, t) in data.items()})
        return _grids


def grid(year):
    return grids()[int(year)]


def scale_of(year):
    return grid(year)[1][0]


def common_grid(years):
    """Finest grid shared by all the years: the 19.1 m grid if every year is >= 2015, else the 30 m grid."""
    years = [int(y) for y in years]
    if min(years) >= 2015:
        return grid(max(years))
    return grid(1984)


def on_grid(year, grid_):
    """The year's image, aggregated by mean when it is finer than the target grid (never resampled coarser)."""
    img = image(year)
    if scale_of(year) < grid_[1][0] - 1e-6:
        img = img.reduceResolution(ee.Reducer.mean(), maxPixels=64)
    return img


# ---------- indices (all indicative) ----------
def rho(img):
    """Pseudo-reflectance: inverse of the documented 0.02-0.50, gamma 1.7 stretch (ignores post-processing)."""
    return img.toFloat().divide(255).pow(1.7).multiply(0.48).add(0.02)


def gli(img):
    r = rho(img)
    R, G, B = r.select("red"), r.select("green"), r.select("blue")
    return G.multiply(2).subtract(R).subtract(B).divide(G.multiply(2).add(R).add(B)).rename("gli")


def brightness(img):
    return rho(img).reduce(ee.Reducer.mean()).rename("bright")


def lab(img):
    """CIELAB (D65) of the colours as displayed: DN treated as sRGB."""
    c = img.toFloat().divide(255)
    lin = c.divide(12.92).where(c.gt(0.04045), c.add(0.055).divide(1.055).pow(2.4))
    R, G, B = lin.select("red"), lin.select("green"), lin.select("blue")
    X = R.multiply(0.4124564).add(G.multiply(0.3575761)).add(B.multiply(0.1804375)).divide(0.95047)
    Y = R.multiply(0.2126729).add(G.multiply(0.7151522)).add(B.multiply(0.0721750))
    Z = R.multiply(0.0193339).add(G.multiply(0.1191920)).add(B.multiply(0.9503041)).divide(1.08883)

    def f(t):
        return t.pow(1 / 3).where(t.lte(216 / 24389), t.multiply(24389 / 27).add(16).divide(116))

    fx, fy, fz = f(X), f(Y), f(Z)
    return ee.Image.cat([fy.multiply(116).subtract(16), fx.subtract(fy).multiply(500), fy.subtract(fz).multiply(200)]).rename(["L", "a", "b"])


def delta_e(img_a, img_b):
    return lab(img_a).subtract(lab(img_b)).pow(2).reduce(ee.Reducer.sum()).sqrt().rename("de")


# ---------- masks ----------
def synthetic_ocean():
    """The ETOPO bathymetry fill is bit-identical every year; real land and inland water never are.
    Three distant years are enough, and Hansen land (datamask 1) is always kept."""
    a, b, c = image(1990), image(2005), image(2020)
    same = a.eq(b).And(b.eq(c)).reduce(ee.Reducer.min())
    land = ee.Image(HANSEN).select("datamask").unmask(0).eq(1)
    return same.And(land.Not()).rename("ocean")


def valid():
    return synthetic_ocean().Not().rename("valid")


# ---------- gap-fill QA ----------
def collinear(t):
    """1 where years (t-1, t, t+1) lie on a straight line within T['qa_dn'] DN in all three bands."""
    a, b, c = image(t - 1).toInt16(), image(t).toInt16(), image(t + 1).toInt16()
    return c.subtract(b.multiply(2)).add(a).abs().lte(T["qa_dn"]).reduce(ee.Reducer.min()).rename("lin")


def in_linear_segment(t):
    """1 where year t belongs to any collinear triple, i.e. it sits on a linearly reconstructed segment."""
    centres = [u for u in (t - 1, t, t + 1) if YEARS[0] < u < YEARS[-1]]
    out = collinear(centres[0])
    for u in centres[1:]:
        out = out.Or(collinear(u))
    return out.rename("qa")


def linear_year_count():
    """How many of the 39 years sit on a linearly reconstructed segment, per pixel."""
    c = {u: collinear(u) for u in YEARS[1:-1]}
    total = None
    for t in YEARS:
        seg = None
        for u in (t - 1, t, t + 1):
            if u in c:
                seg = c[u] if seg is None else seg.Or(c[u])
        total = seg if total is None else total.add(seg)
    return total.rename("qa_count")


# ---------- analysis images ----------
def window_years(year, window):
    h = window // 2
    return [y for y in range(year - h, year + h + 1) if YEARS[0] <= y <= YEARS[-1]]


def composite(year, window=1, grid_=None):
    """The year itself, or the mean of the years around it (window 3), which damps single-mosaic quirks."""
    imgs = [on_grid(y, grid_) if grid_ else image(y) for y in window_years(year, window)]
    # Float throughout: reduceResolution returns float and a collection must be homogeneous (2014-2016 windows mix both).
    return imgs[0] if len(imgs) == 1 else ee.ImageCollection([i.toFloat() for i in imgs]).mean()


def change_thresholds(window):
    k = "" if window == 1 else "_w3"
    return T["de_visible" + k], T["dgli" + k], T["dbright" + k]


def change(a, b, grid_=None, window=3):
    """Bands dgli, dbright, de, cls for year a -> year b (or 3-year means around them).
    With grid_, inputs are aggregated onto that grid first."""
    ia, ib = composite(a, window, grid_), composite(b, window, grid_)
    t_de, t_g, t_b = change_thresholds(window)
    dg = gli(ib).subtract(gli(ia)).rename("dgli")
    db = brightness(ib).subtract(brightness(ia)).rename("dbright")
    de = delta_e(ib, ia)
    vis = de.gte(t_de)
    cls = (ee.Image(0)
           .where(vis.And(db.gte(t_b)), 3).where(vis.And(db.lte(-t_b)), 4)
           .where(vis.And(dg.lte(-t_g)), 1).where(vis.And(dg.gte(t_g)), 2)
           .toUint8().rename("cls"))
    return ee.Image.cat([dg, db, de, cls])


def yoc(start, end, metric="gli", grid_=None):
    """Year of the largest change between consecutive 3-year windows: bands year (first year after) and mag."""
    src = {y: (on_grid(y, grid_) if grid_ else image(y)) for y in range(start, end + 1)}
    imgs = []
    if metric == "gli":
        g = {y: gli(i) for y, i in src.items()}
        for t in range(start + 3, end - 1):
            before = g[t - 3].add(g[t - 2]).add(g[t - 1]).divide(3)
            after = g[t].add(g[t + 1]).add(g[t + 2]).divide(3)
            imgs.append(before.subtract(after).rename("mag").addBands(ee.Image.constant(t).toInt16().rename("year")))
        thr = T["yoc_gli"]
    else:
        f = {y: i.toFloat() for y, i in src.items()}
        for t in range(start + 3, end - 1):
            before = f[t - 3].add(f[t - 2]).add(f[t - 1]).divide(3)
            after = f[t].add(f[t + 1]).add(f[t + 2]).divide(3)
            imgs.append(delta_e(after, before).rename("mag").addBands(ee.Image.constant(t).toInt16().rename("year")))
        thr = T["yoc_de"]
    best = ee.ImageCollection(imgs).qualityMosaic("mag")
    return best.updateMask(best.select("mag").gte(thr))


def trend(start, end, grid_=None):
    """Sen's slope of GLI per year, Kendall's tau, and the Mann-Kendall two-sided p-value.

    The reducer's own p-value band comes back fully masked, so p is computed from tau:
    S = tau * n(n-1)/2, Var(S) = n(n-1)(2n+5)/18, Z = (|S| - 1) / sqrt(Var(S)), p = erfc(|Z| / sqrt 2).
    """
    years = range(start, end + 1)
    col = ee.ImageCollection([
        ee.Image.constant(y).toFloat().rename("t").addBands(gli(on_grid(y, grid_) if grid_ else image(y)))
        for y in years])
    n = len(years)
    sens = col.reduce(ee.Reducer.sensSlope())              # slope, offset
    tau = col.reduce(ee.Reducer.kendallsCorrelation(2)).select("tau")
    z = tau.multiply(n * (n - 1) / 2).abs().subtract(1).max(0).divide((n * (n - 1) * (2 * n + 5) / 18) ** 0.5)
    p = z.divide(2 ** 0.5).erfc().rename("p-value")
    return sens.select("slope").addBands(tau).addBands(p)
