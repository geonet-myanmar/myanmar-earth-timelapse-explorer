"""AOI statistics at native resolution, plus the per-pixel profile.

Every reduction runs on a native grid (crs + crsTransform from the asset), never on a coarser `scale`.
Areas are true areas (pixelArea, km2) with the synthetic ETOPO ocean excluded and reported.
"""
import math, threading
from concurrent.futures import ThreadPoolExecutor
import ee
from shapely.geometry import shape, box
from . import dataset as D
from . import npmath as M
from .cache import digest, disk_get, disk_set
from .config import YEARS
from .ee_client import call, EEError


CELL_KM2 = 1500     # large AOIs are reduced as parallel cells of about this size (each its own EE request)
_slots = threading.BoundedSemaphore(24)   # all reductions share this, so parallel cells x years stay under EE's limit


def _reduce_one(img, geom, grid_, reducer):
    def run(tile_scale):
        with _slots:
            return call(img.reduceRegion(reducer, geom, crs=grid_[0], crsTransform=grid_[1],
                                         maxPixels=1e11, tileScale=tile_scale).getInfo)
    try:
        return run(4)
    except EEError as e:
        if "memory" in str(e).lower():
            return run(16)
        raise


def _cells(aoi):
    n = min(64, math.ceil(aoi.area_km2 / CELL_KM2))
    if n <= 1:
        return [aoi.ee()]
    minx, miny, maxx, maxy = aoi.bbox
    k = math.ceil(math.sqrt(n))
    g = shape(aoi.geometry)
    out = []
    for i in range(k):
        for j in range(k):
            c = (minx + (maxx - minx) * i / k, miny + (maxy - miny) * j / k,
                 minx + (maxx - minx) * (i + 1) / k, miny + (maxy - miny) * (j + 1) / k)
            if g.intersects(box(*c)):
                out.append(aoi.ee().intersection(ee.Geometry.Rectangle(list(c), "EPSG:4326", False), ee.ErrorMargin(1)))
    return out


def _reduce(img, aoi, grid_, reducer=None, grouped=False):
    """Weighted sums over the AOI on a native grid. Edge pixels are split by coverage, so cell sums add up."""
    reducer = reducer or ee.Reducer.sum()
    cells = _cells(aoi)
    with ThreadPoolExecutor(max_workers=min(16, len(cells))) as ex:
        parts = list(ex.map(lambda g: _reduce_one(img, g, grid_, reducer), cells))
    if len(parts) == 1:
        return parts[0]
    if grouped:
        acc = {}
        for p in parts:
            for grp in p.get("groups", []):
                acc[grp["year"]] = acc.get(grp["year"], 0) + grp["sum"]
        return {"groups": [{"year": y, "sum": v} for y, v in sorted(acc.items())]}
    acc = {}
    for p in parts:
        for k_, v in p.items():
            if v is not None:
                acc[k_] = acc.get(k_, 0) + v
    return acc


def _cached(ns, aoi, params, fn):
    key = digest(ns, aoi.key, params)
    hit = disk_get(ns, key)
    if hit is not None:
        return hit
    return disk_set(ns, key, fn())


def year_stats(aoi, year):
    year = int(year)

    def compute():
        img = D.image(year)
        area = ee.Image.pixelArea().divide(1e6)
        w = area.updateMask(D.valid())
        g, br = D.gli(img), D.brightness(img)
        bands = [area.rename("a_all"), w.rename("a_valid"),
                 g.multiply(w).rename("s_gli"), br.multiply(w).rename("s_bright"),
                 img.select("red").multiply(w).rename("s_r"), img.select("green").multiply(w).rename("s_g"),
                 img.select("blue").multiply(w).rename("s_b"),
                 w.updateMask(g.gt(D.T["green_gli"])).rename("a_green"),
                 w.updateMask(br.gt(D.T["bare_bright"]).And(g.lt(D.T["bare_gli"]))).rename("a_bare"),
                 w.updateMask(D.in_linear_segment(year)).rename("a_qa")]
        if year > YEARS[0]:
            de = D.delta_e(img, D.image(year - 1))
            bands += [de.multiply(w).rename("s_de"), w.updateMask(de.gte(D.T["de_visible"])).rename("a_de")]
        r = _reduce(ee.Image.cat(bands), aoi, D.grid(year))
        av = r.get("a_valid") or 0
        mean = lambda k: (r.get(k) or 0) / av if av else None
        pct = lambda k: 100 * (r.get(k) or 0) / av if av else None
        return {"year": year, "grid_m": round(D.scale_of(year), 3), "area_km2": round(r.get("a_all") or 0, 3),
                "valid_km2": round(av, 3), "ocean_km2": round(max(0.0, (r.get("a_all") or 0) - av), 3),
                "gli": mean("s_gli"), "bright": mean("s_bright"),
                "rgb": [mean("s_r"), mean("s_g"), mean("s_b")],
                "green_pct": pct("a_green"), "bare_pct": pct("a_bare"), "qa_pct": pct("a_qa"),
                "de_prev": mean("s_de") if year > YEARS[0] else None,
                "de_visible_pct": pct("a_de") if year > YEARS[0] else None}

    return _cached("year", aoi, {"y": year, "T": D.T}, compute)


def change_stats(aoi, a, b, window=3):
    a, b, window = int(a), int(b), int(window)

    def compute():
        grid_ = D.common_grid(D.window_years(a, window) + D.window_years(b, window))
        ch = D.change(a, b, grid_, window)
        area = ee.Image.pixelArea().divide(1e6)
        w = area.updateMask(D.valid())
        cls = ch.select("cls")
        bands = [w.rename("a_valid"), ch.select("dgli").multiply(w).rename("s_dgli"),
                 ch.select("dbright").multiply(w).rename("s_db"), ch.select("de").multiply(w).rename("s_de")]
        bands += [w.updateMask(cls.eq(i)).rename(f"a_c{i}") for i in range(5)]
        r = _reduce(ee.Image.cat(bands), aoi, grid_)
        av = r.get("a_valid") or 0
        return {"a": a, "b": b, "window": window, "grid_m": round(grid_[1][0], 3), "valid_km2": round(av, 3),
                "thresholds": dict(zip(("de", "dgli", "dbright"), D.change_thresholds(window))),
                "dgli": (r.get("s_dgli") or 0) / av if av else None,
                "dbright": (r.get("s_db") or 0) / av if av else None,
                "de": (r.get("s_de") or 0) / av if av else None,
                "classes": [{"name": n, "km2": round(r.get(f"a_c{i}") or 0, 3),
                             "pct": 100 * (r.get(f"a_c{i}") or 0) / av if av else None}
                            for i, n in enumerate(D.CLASS_NAMES)]}

    return _cached("change", aoi, {"a": a, "b": b, "w": window, "T": D.T}, compute)


def yoc_stats(aoi, start, end, metric):
    start, end = int(start), int(end)

    def compute():
        grid_ = D.common_grid(range(start, end + 1))
        y = D.yoc(start, end, metric, grid_)
        area = ee.Image.pixelArea().divide(1e6).updateMask(D.valid())
        img = area.rename("area").addBands(y.select("year").rename("year"))
        r = _reduce(img, aoi, grid_, ee.Reducer.sum().group(groupField=1, groupName="year"), grouped=True)
        per = {int(g["year"]): g["sum"] for g in r.get("groups", [])}
        valid = _reduce(area.rename("a"), aoi, grid_).get("a") or 0
        years = list(range(start + 3, end - 1))
        return {"start": start, "end": end, "metric": metric, "grid_m": round(grid_[1][0], 3),
                "valid_km2": round(valid, 3), "years": years, "km2": [round(per.get(t, 0), 4) for t in years],
                "total_km2": round(sum(per.values()), 3)}

    return _cached("yoc", aoi, {"s": start, "e": end, "m": metric, "T": D.T}, compute)


def trend_stats(aoi, start, end, alpha):
    start, end = int(start), int(end)

    def compute():
        grid_ = D.common_grid(range(start, end + 1))
        tr = D.trend(start, end, grid_)
        slope = tr.select("slope").multiply(10)
        sig = tr.select("p-value").lt(alpha).And(slope.abs().gte(D.T["trend_slope"]))
        w = ee.Image.pixelArea().divide(1e6).updateMask(D.valid())
        bands = [w.rename("a_valid"), slope.multiply(w).rename("s_slope"),
                 w.updateMask(sig.And(slope.gt(0))).rename("a_up"), w.updateMask(sig.And(slope.lt(0))).rename("a_down")]
        r = _reduce(ee.Image.cat(bands), aoi, grid_)
        av = r.get("a_valid") or 0
        return {"start": start, "end": end, "alpha": alpha, "grid_m": round(grid_[1][0], 3), "valid_km2": round(av, 3),
                "slope_per_decade": (r.get("s_slope") or 0) / av if av else None,
                "greening_km2": round(r.get("a_up") or 0, 3), "browning_km2": round(r.get("a_down") or 0, 3),
                "greening_pct": 100 * (r.get("a_up") or 0) / av if av else None,
                "browning_pct": 100 * (r.get("a_down") or 0) / av if av else None}

    return _cached("trend", aoi, {"s": start, "e": end, "a": alpha, "T": D.T}, compute)


def point_profile(lon, lat):
    pt = ee.Geometry.Point([float(lon), float(lat)])

    def sample(img):
        v = img.select(D.BANDS).reduceRegion(ee.Reducer.first(), pt, crs=img.select(0).projection())
        return ee.Feature(None, v).set("year", img.get("year"))

    feats = call(ee.FeatureCollection(ee.ImageCollection(D.COLLECTION).map(sample)).getInfo)["features"]
    rows = sorted((f["properties"] for f in feats), key=lambda p: p["year"])
    ocean = call(D.synthetic_ocean().reduceRegion(ee.Reducer.first(), pt, 30).getInfo).get("ocean")
    rgb = [[p.get("red"), p.get("green"), p.get("blue")] for p in rows]
    if any(None in c for c in rgb):
        raise ValueError("No imagery at this point.")
    flags = M.linear_segment_flags(rgb, D.T["qa_dn"])
    out = []
    for i, p in enumerate(rows):
        r, g, b = rgb[i]
        de = float(M.delta_e(rgb[i], rgb[i - 1])) if i else None
        out.append({"year": p["year"], "rgb": rgb[i], "gli": float(M.gli(r, g, b)), "bright": float(M.brightness(r, g, b)),
                    "de_prev": de, "linear": bool(flags[i])})
    return {"lon": float(lon), "lat": float(lat), "synthetic_ocean": bool(ocean), "years": out}
