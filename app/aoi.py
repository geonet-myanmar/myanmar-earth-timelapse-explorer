"""Areas of interest: a MIMU unit by PCode, or a GeoJSON polygon drawn or uploaded in the browser.

Admin AOIs always use the full-resolution MIMU polygon from data/mimu (the map shows a simplified copy).
"""
import json, threading
from dataclasses import dataclass, field, asdict
import ee
from pyproj import Geod
from shapely import set_precision
from shapely.geometry import shape, mapping, MultiPolygon
from shapely.prepared import prep
from shapely.validation import make_valid
from .cache import TTL, digest
from .config import MIMU, AOI_MAX_KM2, AOI_WARN_KM2, AOI_MAX_VERTICES

GEOD = Geod(ellps="WGS84")
LEVELS = {1: "State/Region", 2: "District", 3: "Township"}
_admin, _mm, _lock = {}, {}, threading.Lock()
# GEOS prepared geometries (the shared Myanmar outline) are not thread-safe: 16 threads validating at once segfault.
# Requests run in a threadpool (and share one Vercel instance), so all GEOS / pyproj work goes through this lock.
GEOS_LOCK = threading.Lock()
_resolved = TTL(3600, 256)


def _load():
    with _lock:
        if _admin:
            return
        for lv in range(4):
            fc = json.loads((MIMU / f"adm{lv}.geojson").read_text(encoding="utf-8"))
            for f in fc["features"]:
                _admin[f["properties"]["pcode"]] = f
        g = shape(_admin["MMR"]["geometry"])
        _mm["geom"], _mm["prep"] = g, prep(g)


def admin_feature(pcode):
    _load()
    return _admin.get(pcode)


@dataclass
class AOI:
    key: str
    kind: str
    name: str
    geometry: dict
    area_km2: float
    bbox: list
    name_my: str = ""
    pcode: str = ""
    level: int = 0
    inside_pct: float = 100.0
    vertices: int = 0
    warnings: list = field(default_factory=list)

    def ee(self):
        return ee.Geometry(self.geometry, "EPSG:4326", False)

    def public(self, with_geometry=True):
        d = asdict(self)
        if not with_geometry:
            d.pop("geometry")
        return d


def area_km2(g):
    return abs(GEOD.geometry_area_perimeter(g)[0]) / 1e6


def _polygonal(g):
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    parts = [p for p in getattr(g, "geoms", []) if p.geom_type in ("Polygon", "MultiPolygon")]
    polys = [q for p in parts for q in (p.geoms if p.geom_type == "MultiPolygon" else [p])]
    return MultiPolygon(polys) if polys else None


def _count_vertices(g):
    polys = g.geoms if g.geom_type == "MultiPolygon" else [g]
    return sum(len(p.exterior.coords) + sum(len(i.coords) for i in p.interiors) for p in polys)


def resolve(spec):
    """spec: {"kind": "admin", "pcode": ...} or {"kind": "geojson", "geometry": {...}, "name": ...}."""
    if not isinstance(spec, dict):
        raise ValueError("Missing area of interest.")
    _load()
    kind = spec.get("kind")
    if kind == "admin":
        f = _admin.get(spec.get("pcode", ""))
        if not f or f["properties"]["level"] == 0:
            raise ValueError(f"Unknown MIMU PCode {spec.get('pcode')!r}.")
        key = f"adm:{f['properties']['pcode']}"
        hit = _resolved.get(key)
        if hit:
            return hit
        p = f["properties"]
        with GEOS_LOCK:
            g = shape(f["geometry"])
            bbox, nv = [round(v, 6) for v in g.bounds], _count_vertices(g)
        parent = p.get("dt") or p.get("st") or ""
        return _resolved.set(key, AOI(key=key, kind="admin", geometry=f["geometry"], area_km2=p["area_km2"], bbox=bbox,
                                      name=f"{p['name_en']} {LEVELS[p['level']]}" + (f", {parent}" if parent else ""),
                                      name_my=p.get("name_my", ""), pcode=p["pcode"], level=p["level"], vertices=nv))
    if kind != "geojson":
        raise ValueError("Area of interest must be an admin unit or a GeoJSON polygon.")

    raw_key = digest("aoi", spec.get("geometry"))
    hit = _resolved.get(raw_key)
    if hit:
        return AOI(**{**asdict(hit), "name": spec.get("name") or hit.name})
    with GEOS_LOCK:
        return _resolved.set(raw_key, _validate(spec))


def _validate(spec):
    try:
        g = shape(spec["geometry"])
    except Exception as e:
        raise ValueError(f"Not a valid GeoJSON geometry: {e}")
    minx, miny, maxx, maxy = g.bounds
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        raise ValueError("Coordinates are not longitude/latitude. Reproject the file to WGS 84 (EPSG:4326).")
    g = _polygonal(make_valid(g))
    if g is None or g.is_empty:
        raise ValueError("The area has no polygon. Points and lines need a buffer first.")
    g = set_precision(g, 1e-7)
    nv = _count_vertices(g)
    if nv > AOI_MAX_VERTICES:
        raise ValueError(f"The polygon has {nv:,} vertices; simplify it below {AOI_MAX_VERTICES:,}.")
    a = area_km2(g)
    if a < 0.01:
        raise ValueError("The area is smaller than 0.01 km² (about 11 pixels).")
    if a > AOI_MAX_KM2:
        raise ValueError(f"The area is {a:,.0f} km²; the limit is {AOI_MAX_KM2:,} km² (Shan State is about 156,000).")
    if not _mm["prep"].intersects(g):
        raise ValueError("The area does not overlap Myanmar.")
    inside = 100.0 if _mm["prep"].contains(g) else 100.0 * area_km2(g.intersection(_mm["geom"])) / a
    warnings = []
    if inside < 99.9:
        warnings.append(f"{100 - inside:.1f}% of the area lies outside Myanmar; it is still analysed.")
    if a > AOI_WARN_KM2:
        warnings.append(f"Large area ({a:,.0f} km²): native-resolution statistics can take several minutes.")
    geom = mapping(g)
    return AOI(key="geo:" + digest("geom", geom)[:16], kind="geojson", name=spec.get("name") or "Custom area",
               geometry=json.loads(json.dumps(geom)), area_km2=round(a, 3), bbox=[round(v, 6) for v in g.bounds],
               inside_pct=round(inside, 2), vertices=nv, warnings=warnings)
