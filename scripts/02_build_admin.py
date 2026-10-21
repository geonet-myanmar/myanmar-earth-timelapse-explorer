"""Normalise the MIMU boundaries and build the two products the app needs.

data/mimu/adm{0..3}.geojson   full resolution, used by the backend as Earth Engine AOIs
web/data/admin.topo.json      display copy (shared arcs, simplified with mapshaper), used by the map
"""
import json, shutil, subprocess, sys, tempfile, unicodedata
from pathlib import Path
from pyproj import Geod
from shapely.geometry import shape, mapping
from shapely.validation import make_valid
from shapely import set_precision

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/mimu"
OUT = ROOT / "data/mimu"; OUT.mkdir(parents=True, exist_ok=True)
TOPO = ROOT / "web/data/admin.topo.json"
MAPSHAPER = "mapshaper@0.7.79"
GEOD = Geod(ellps="WGS84")


def my(s):
    """NFC, and spell ဦ one way (MIMU mixes U+1026 with U+1025 U+102E)."""
    if not s:
        return ""
    return unicodedata.normalize("NFC", s).replace("ဦ", "ဦ").strip()


def clean(geom):
    g = make_valid(shape(geom))
    if g.geom_type == "GeometryCollection":           # keep the areal part only
        from shapely.geometry import MultiPolygon
        polys = [p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
        g = MultiPolygon([q for p in polys for q in (p.geoms if p.geom_type == "MultiPolygon" else [p])])
    return set_precision(g, 1e-7)                      # ~1 cm; trims float noise, keeps every vertex


def area_km2(g):
    return round(abs(GEOD.geometry_area_perimeter(g)[0]) / 1e6, 2)


def props(level, p):
    if level == 0:
        return dict(level=0, pcode="MMR", name_en="Myanmar", name_my="မြန်မာ")
    if level == 1:
        return dict(level=1, pcode=p["ST_PCODE"], name_en=p["ST"], name_my=my(p.get("ST_MMR")), type=p.get("ST_RG", ""))
    if level == 2:
        return dict(level=2, pcode=p["DT_PCODE"], name_en=p["DT"], name_my=my(p.get("DT_MMR")),
                    st_pcode=p["ST_PCODE"], st=p["ST"])
    return dict(level=3, pcode=p["TS_PCODE"], name_en=p["TS"], name_my=my(p.get("TS_MMR")),
                dt_pcode=p["DT_PCODE"], dt=p["DT"], st_pcode=p["ST_PCODE"], st=p["ST"])


def main():
    tmp = Path(tempfile.mkdtemp(prefix="admin_"))
    summary = {}
    for level in range(4):
        src = json.loads((RAW / f"adm{level}.geojson").read_text(encoding="utf-8"))
        feats, light = [], []
        for ft in src["features"]:
            g = clean(ft["geometry"])
            pr = props(level, ft["properties"])
            pr["area_km2"] = area_km2(g)
            feats.append({"type": "Feature", "properties": pr, "geometry": mapping(g)})
            light.append({"type": "Feature", "properties": {k: v for k, v in pr.items() if k != "level"}, "geometry": mapping(g)})
        feats.sort(key=lambda f: f["properties"]["pcode"])
        fc = {"type": "FeatureCollection", "name": f"adm{level}", "source": "MIMU PCode v9.4", "features": feats}
        (OUT / f"adm{level}.geojson").write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        (tmp / f"adm{level}.json").write_text(json.dumps({"type": "FeatureCollection", "features": light}, ensure_ascii=False), encoding="utf-8")
        nv = sum(len(shape(f["geometry"]).exterior.coords) if f["geometry"]["type"] == "Polygon" else
                 sum(len(p.exterior.coords) + sum(len(i.coords) for i in p.interiors) for p in shape(f["geometry"]).geoms)
                 for f in feats)
        big = max(feats, key=lambda f: len(json.dumps(f["geometry"])))
        summary[level] = (len(feats), nv, round(sum(f["properties"]["area_km2"] for f in feats)),
                          big["properties"]["name_en"], round(len(json.dumps(big["geometry"])) / 1e6, 2))
    for lv, (n, nv, a, bn, bmb) in summary.items():
        print(f"adm{lv}: {n:3d} features  ~{nv:7d} vertices  {a:9,d} km2  largest payload {bn} {bmb} MB")

    # Display topology: one TopoJSON, four layers with shared arcs. Display only - analysis uses data/mimu.
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    cmd = [npx, "-y", MAPSHAPER, "-i", *[str(tmp / f"adm{l}.json") for l in range(4)], "combine-files",
           "-simplify", "interval=40", "weighted", "keep-shapes",
           "-o", "format=topojson", "quantization=200000", str(TOPO)]
    print(" ".join(cmd[1:]))
    subprocess.run(cmd, check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    topo = json.loads(TOPO.read_text(encoding="utf-8"))
    print(f"{TOPO.relative_to(ROOT)}: {TOPO.stat().st_size / 1e6:.2f} MB, layers {list(topo['objects'])}")


if __name__ == "__main__":
    sys.exit(main())
