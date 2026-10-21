"""Map layers: Earth Engine map IDs plus the legend the page draws for each.

Palettes come from the dataviz reference instance (validated 2026-10-21): change classes are red / aqua / yellow /
blue (all-pairs gates pass; CVD 6.9 is carried by legend labels and the class table), diverging maps use the blue
ramp against a red arm derived at the blue ramp's OKLCH lightness, sequential maps use the blue ramp.
"""
from . import dataset as D
from .cache import TTL, digest
from .ee_client import call
from .config import YEARS

RED = ["#7e1519", "#a72528", "#d2383a", "#e76762", "#f2958e"]          # dark -> light
BLUE = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]         # light -> dark
MID = "#f0efec"
DIV_NEG_RED = RED + [MID] + BLUE                                       # negative = red, positive = blue
DIV_NEG_BLUE = BLUE[::-1] + [MID] + RED[::-1]                          # negative = blue, positive = red
SEQ = ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
CLASS_COLORS = ["#e34948", "#1baf7a", "#eda100", "#2a78d6"]           # loss, gain, brightening, darkening
QA_COLOR = "#fab219"                                                   # status: warning

_maps = TTL(45 * 60, 512)   # map IDs outlive this comfortably; the page also refreshes on tile errors


def _year(y):
    y = int(y)
    if y not in YEARS:
        raise ValueError(f"Year {y} is outside 1984-2022.")
    return y


def _span(spec, lo, hi):
    s, e = _year(spec.get("start", lo)), _year(spec.get("end", hi))
    if e - s < 6:
        raise ValueError("Choose a span of at least 7 years.")
    return s, e


def build(spec, aoi=None):
    """Return (ee.Image ready for getMapId, vis params, legend) for a layer spec."""
    t = spec.get("type")
    if t == "year":
        y = _year(spec["year"])
        return D.image(y), {"bands": D.BANDS, "min": 0, "max": 255}, None
    if aoi is None:
        raise ValueError("Analysis layers need an area of interest.")
    clip = lambda img: img.updateMask(D.valid()).clip(aoi.ee())
    if t == "change":
        a, b = _year(spec["a"]), _year(spec["b"])
        w = int(spec.get("window", 3))
        if w not in (1, 3):
            raise ValueError("window must be 1 or 3")
        if abs(b - a) < w:
            raise ValueError("With 3-year means the two years must be at least 3 years apart.")
        ch = D.change(a, b, window=w)
        t_de, t_g, t_b = D.change_thresholds(w)
        how = " (3-year means)" if w == 3 else ""
        m = spec.get("metric", "classes")
        if m == "classes":
            cls = ch.select("cls")
            return clip(cls.updateMask(cls.gt(0))), {"min": 1, "max": 4, "palette": CLASS_COLORS}, {
                "kind": "categorical", "title": f"Visible change {a} → {b}{how}",
                "items": [[c, n] for c, n in zip(CLASS_COLORS, D.CLASS_NAMES[1:])]}
        if m == "dgli":
            v = ch.select("dgli")
            return clip(v.updateMask(v.abs().gte(t_g))), {"min": -0.4, "max": 0.4, "palette": DIV_NEG_RED}, {
                "kind": "diverging", "title": f"Greenness change {a} → {b}{how} (ΔGLI)", "colors": DIV_NEG_RED,
                "min": -0.4, "max": 0.4, "low": "less green", "high": "greener", "masked": f"|ΔGLI| < {t_g}"}
        if m == "dbright":
            v = ch.select("dbright")
            return clip(v.updateMask(v.abs().gte(t_b))), {"min": -0.15, "max": 0.15, "palette": DIV_NEG_BLUE}, {
                "kind": "diverging", "title": f"Brightness change {a} → {b}{how}", "colors": DIV_NEG_BLUE,
                "min": -0.15, "max": 0.15, "low": "darker", "high": "brighter", "masked": f"|Δ| < {t_b}"}
        if m == "de":
            v = ch.select("de")
            return clip(v.updateMask(v.gte(t_de))), {"min": t_de, "max": 60, "palette": SEQ}, {
                "kind": "sequential", "title": f"Colour change {a} → {b}{how} (ΔE)", "colors": SEQ,
                "min": t_de, "max": 60, "masked": f"ΔE < {t_de:g}"}
        raise ValueError(f"Unknown change metric {m!r}.")
    if t == "yoc":
        s, e = _span(spec, 1988, 2022)
        metric = spec.get("metric", "gli")
        y = D.yoc(s, e, metric).select("year")
        return clip(y), {"min": s + 3, "max": e - 2, "palette": SEQ}, {
            "kind": "sequential", "title": ("Year of largest greenness drop" if metric == "gli" else "Year of largest colour change"),
            "colors": SEQ, "min": s + 3, "max": e - 2, "integer": True,
            "masked": ("3-year drop < %.2f GLI" % D.T["yoc_gli"]) if metric == "gli" else ("3-year ΔE < %g" % D.T["yoc_de"])}
    if t == "trend":
        s, e = _span(spec, 1988, 2022)
        alpha = float(spec.get("alpha", 0.05))
        tr = D.trend(s, e)
        slope = tr.select("slope").multiply(10)
        keep = slope.abs().gte(D.T["trend_slope"])
        if alpha < 1:
            keep = keep.And(tr.select("p-value").lt(alpha))
        return clip(slope.updateMask(keep)), {"min": -0.12, "max": 0.12, "palette": DIV_NEG_RED}, {
            "kind": "diverging", "title": f"Greenness trend {s}–{e} (GLI per decade)", "colors": DIV_NEG_RED,
            "min": -0.12, "max": 0.12, "low": "browning", "high": "greening",
            "masked": f"|slope| < {D.T['trend_slope']}/decade (stable-forest range)" + (f" or p ≥ {alpha:g}" if alpha < 1 else "")}
    if t == "qa":
        if spec.get("mode") == "count":
            c = D.linear_year_count()
            return clip(c.updateMask(c.gt(0))), {"min": 1, "max": 12, "palette": SEQ}, {
                "kind": "sequential", "title": "Years on a gap-filled (linear) segment", "colors": SEQ, "min": 1, "max": 12,
                "integer": True, "masked": "none"}
        y = _year(spec["year"])
        q = D.in_linear_segment(y)
        return clip(q.updateMask(q)), {"min": 0, "max": 1, "palette": [QA_COLOR, QA_COLOR]}, {
            "kind": "categorical", "title": f"{y}: on a gap-filled (linear) segment", "items": [[QA_COLOR, "likely interpolated"]]}
    raise ValueError(f"Unknown layer type {t!r}.")


def map_url(spec, aoi=None):
    key = digest("map", spec, aoi.key if aoi and spec.get("type") != "year" else None)
    hit = _maps.get(key)
    if hit:
        return hit
    img, vis, legend = build(spec, aoi)
    mid = call(img.getMapId, vis)
    return _maps.set(key, {"url": mid["tile_fetcher"].url_format, "legend": legend})
