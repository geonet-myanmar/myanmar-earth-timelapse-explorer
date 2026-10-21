"""Build upload test fixtures (every supported format) from the MIMU polygons, with reference areas.

tests/fixtures/
  hpakant_4326.geojson      Feature, WGS 84
  hpakant_32647.geojson     legacy "crs" member, UTM 47N  -> reprojected by the page
  hpakant_utm_nocrs.geojson UTM coordinates, no crs      -> the page asks for the CRS
  nyaungshwe.kml / .kmz     KML Placemark with MultiGeometry; KMZ = zipped doc.kml
  taunggyi_pair_shp.zip     two townships, UTM 47N .prj  -> union of both
  loose/taunggyi_pair.*     the same as a loose .shp/.shx/.dbf/.prj set
  points.kml                three points                 -> buffer step
  outside.geojson           a box in Thailand            -> rejected
  expected.json             geodesic reference areas (km2)
"""
import json, zipfile
from pathlib import Path
import geopandas as gpd
from pyproj import Geod
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/fixtures"; (OUT / "loose").mkdir(parents=True, exist_ok=True)
GEOD = Geod(ellps="WGS84")
adm3 = gpd.read_file(ROOT / "data/mimu/adm3.geojson")
pick = lambda pc: adm3[adm3["pcode"] == pc]
area = lambda g: round(abs(GEOD.geometry_area_perimeter(g)[0]) / 1e6, 3)
expected = {}

hp = pick("MMR001009")
hp[["name_en", "geometry"]].to_file(OUT / "hpakant_4326.geojson", driver="GeoJSON")
expected["hpakant_4326.geojson"] = area(hp.geometry.iloc[0])

utm = hp[["name_en", "geometry"]].to_crs(32647)
gj = json.loads(utm.to_json())
gj["crs"] = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32647"}}
(OUT / "hpakant_32647.geojson").write_text(json.dumps(gj), encoding="utf-8")
expected["hpakant_32647.geojson"] = expected["hpakant_4326.geojson"]
gj.pop("crs")
(OUT / "hpakant_utm_nocrs.geojson").write_text(json.dumps(gj), encoding="utf-8")
expected["hpakant_utm_nocrs.geojson"] = expected["hpakant_4326.geojson"]

ny = pick("MMR014002")
g = ny.geometry.iloc[0]
polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
ring = lambda r: " ".join(f"{x:.7f},{y:.7f},0" for x, y in r.coords)
pm = "".join(f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{ring(p.exterior)}</coordinates></LinearRing></outerBoundaryIs>"
             + "".join(f"<innerBoundaryIs><LinearRing><coordinates>{ring(i)}</coordinates></LinearRing></innerBoundaryIs>" for i in p.interiors)
             + "</Polygon>" for p in polys)
kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Nyaungshwe</name><Folder><name>Townships</name>
<Placemark><name>Nyaungshwe</name><MultiGeometry>{pm}</MultiGeometry></Placemark></Folder></Document></kml>"""
(OUT / "nyaungshwe.kml").write_text(kml, encoding="utf-8")
with zipfile.ZipFile(OUT / "nyaungshwe.kmz", "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("doc.kml", kml)
expected["nyaungshwe.kml"] = expected["nyaungshwe.kmz"] = area(g)

pair = adm3[adm3["pcode"].isin(["MMR014001", "MMR014002"])][["name_en", "pcode", "geometry"]].to_crs(32647)
pair.to_file(OUT / "loose/taunggyi_pair.shp")
with zipfile.ZipFile(OUT / "taunggyi_pair_shp.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in (OUT / "loose").glob("taunggyi_pair.*"):
        z.write(f, f.name)
u = unary_union(adm3[adm3["pcode"].isin(["MMR014001", "MMR014002"])].geometry)
expected["taunggyi_pair_shp.zip"] = expected["loose"] = area(u)

pts = [(96.905, 20.55, "Inle centre"), (96.95, 20.66, "Nyaungshwe town"), (97.04, 20.78, "Taunggyi")]
pk = "".join(f"<Placemark><name>{n}</name><Point><coordinates>{x},{y},0</coordinates></Point></Placemark>" for x, y, n in pts)
(OUT / "points.kml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>{pk}</Document></kml>', encoding="utf-8")

(OUT / "outside.geojson").write_text(json.dumps({"type": "Feature", "properties": {"name": "Bangkok"},
                                                 "geometry": mapping(box(100.4, 13.6, 100.7, 13.9))}), encoding="utf-8")
(OUT / "expected.json").write_text(json.dumps(expected, indent=1), encoding="utf-8")
print(json.dumps(expected, indent=1))
