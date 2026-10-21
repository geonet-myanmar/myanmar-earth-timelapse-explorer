"""Timelapse frames, Earth Engine's own GIF, and native-grid GeoTIFF downloads.

Frames: the AOI box in EPSG:3857, padded to the frame aspect and snapped to the 19.109 m grid, so at native size
every frame pixel is exactly one 2015-2022 pixel. Each request must stay under 8,388,597 px (6 bytes/px budget).
"""
import math
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape
import ee
from . import dataset as D
from .cache import TTL, digest
from .config import SCALE_FINE, MAX_REQUEST_PX, MAX_VIDEO_PX, WEBMERC_HALF, YEARS, EE_REQUEST_BYTES
from .ee_client import call

R = 6378137.0
PRESETS = {"native": None, "4k": 3840, "1440p": 2560, "1080p": 1920, "720p": 1280, "480p": 854, "strip": 480}
ASPECTS = {"16:9": 16 / 9, "1:1": 1.0, "9:16": 9 / 16, "4:5": 0.8, "4:3": 4 / 3}
LONG_MAX = 3840
_urls = TTL(100 * 60, 256)   # EE thumbnail tokens last 2 h


def merc(lon, lat):
    lat = max(min(lat, 85.0), -85.0)
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def inv_merc(x, y):
    return math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)


def _even(n):
    return max(2, int(n) // 2 * 2)


def frame_plan(aoi, preset="native", aspect="auto", margin=0.04):
    x0, y0 = merc(aoi.bbox[0], aoi.bbox[1])
    x1, y1 = merc(aoi.bbox[2], aoi.bbox[3])
    w, h = (x1 - x0) * (1 + 2 * margin), (y1 - y0) * (1 + 2 * margin)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    a = ASPECTS.get(aspect) or min(max(w / h, 0.5), 2.0)
    if w / h < a:
        w = h * a
    else:
        h = w / a
    long_px = PRESETS.get(preset)
    if long_px is None:                                   # native: one frame pixel per 19.109 m pixel, if it fits
        s = SCALE_FINE
        s = max(s, max(w, h) / LONG_MAX, math.sqrt(w * h / MAX_REQUEST_PX))
    else:
        s = max(w, h) / long_px
        if (w / s) * (h / s) > MAX_REQUEST_PX:
            s = math.sqrt(w * h / MAX_REQUEST_PX)
    W, H = _even(round(w / s)), _even(round(h / s))
    while W * H > MAX_REQUEST_PX:
        W, H = _even(W - 2), _even(H * (W - 2) / W)
    w, h = W * s, H * s
    left, top = cx - w / 2, cy + h / 2
    if abs(s - SCALE_FINE) < 1e-9:                        # snap onto the native 2015+ lattice
        left = -WEBMERC_HALF + math.floor((left + WEBMERC_HALF) / s) * s
        top = 18483639.10403697 - math.floor((18483639.10403697 - top) / s) * s
    lat_c = inv_merc(cx, cy)[1]
    return {"region": [left, top - H * s, left + W * s, top], "width": W, "height": H, "scale": s,
            "ground_m": s * math.cos(math.radians(lat_c)), "native": abs(s - SCALE_FINE) < 1e-9,
            "upsampled": s < SCALE_FINE - 1e-9, "lat": lat_c}


def _rect(region):
    return ee.Geometry.Rectangle(region, "EPSG:3857", False)


def frame_urls(aoi, years, preset="native", aspect="auto", fmt="jpg"):
    plan = frame_plan(aoi, preset, aspect)
    years = [int(y) for y in years if int(y) in YEARS]
    key = digest("frames", aoi.key, plan["region"], plan["width"], plan["height"], years, fmt)
    hit = _urls.get(key)
    if hit:
        return hit
    rect = _rect(plan["region"])
    params = {"region": rect, "dimensions": f"{plan['width']}x{plan['height']}", "crs": "EPSG:3857",
              "format": "png" if fmt == "png" else "jpg", "bands": D.BANDS, "min": 0, "max": 255}

    def one(y):
        return {"year": y, "url": call(D.image(y).getThumbURL, params)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        frames = list(ex.map(one, years))
    return _urls.set(key, {**plan, "frames": frames, "format": params["format"]})


def gif_dims(aspect, n, long_max=1000):
    """Largest W x H with that aspect whose n frames stay within getVideoThumbURL's 26,214,400 px."""
    W = int(min(long_max if aspect >= 1 else long_max * aspect, math.sqrt(MAX_VIDEO_PX * aspect / n)))
    H = int(W / aspect)
    while W * H * n > MAX_VIDEO_PX:
        W, H = W - 2, int((W - 2) / aspect)
    return W, H


def gif_url(aoi, years, fps=4, aspect="auto"):
    years = [int(y) for y in years if int(y) in YEARS]
    plan = frame_plan(aoi, "native", aspect)
    n = len(years)
    W, H = gif_dims(plan["width"] / plan["height"], n)
    col = ee.ImageCollection([D.image(y).visualize(bands=D.BANDS, min=0, max=255) for y in years])
    url = call(col.getVideoThumbURL, {"region": _rect(plan["region"]), "dimensions": f"{W}x{H}", "crs": "EPSG:3857",
                                      "framesPerSecond": max(1, min(int(fps), 30))})
    return {"url": url, "width": W, "height": H, "frames": n,
            "ground_m": (plan["region"][2] - plan["region"][0]) / W * math.cos(math.radians(plan["lat"]))}


def layer_thumb(aoi, spec, preset="1440p", aspect="auto"):
    """A still of an analysis layer over a grey version of the matching year, with the AOI outlined in white."""
    from . import layers
    plan = frame_plan(aoi, preset, aspect)
    img, vis, legend = layers.build(spec, aoi)
    base_year = int(spec.get("b") or spec.get("year") or spec.get("end") or 2022)
    grey = D.image(base_year).reduce(ee.Reducer.mean()).visualize(min=-20, max=300)
    edge = ee.Image().byte().paint(ee.FeatureCollection([ee.Feature(aoi.ee())]), 1, 2).visualize(palette=["ffffff"])
    comp = grey.blend(img.visualize(**vis)).blend(edge)
    url = call(comp.getThumbURL, {"region": _rect(plan["region"]), "dimensions": f"{plan['width']}x{plan['height']}",
                                  "crs": "EPSG:3857", "format": "png"})
    return {**plan, "url": url, "legend": legend, "title": (legend or {}).get("title", ""), "base_year": base_year}


# ---------- GeoTIFF downloads ----------
def _download_image(spec, aoi):
    t = spec.get("type")
    if t == "year":
        y = int(spec["year"])
        img = D.image(y).toUint8()
        alpha = ee.Image(255).toUint8().clip(aoi.ee()).unmask(0).rename("alpha")
        return img.addBands(alpha), D.grid(y), 4, f"timelapse_{y}"
    if t == "change":
        a, b, w = int(spec["a"]), int(spec["b"]), int(spec.get("window", 3))
        g = D.common_grid(D.window_years(a, w) + D.window_years(b, w))
        img = D.change(a, b, g, w).select("cls").updateMask(D.valid()).clip(aoi.ee()).unmask(0).toUint8()
        return img, g, 1, f"change_classes_{a}_{b}" + ("_3yr" if w == 3 else "")
    if t == "yoc":
        s, e = int(spec.get("start", 1988)), int(spec.get("end", 2022))
        g = D.common_grid(range(s, e + 1))
        img = D.yoc(s, e, spec.get("metric", "gli"), g).select("year").updateMask(D.valid()).clip(aoi.ee()).unmask(0).toInt16()
        return img, g, 1, f"year_of_change_{spec.get('metric', 'gli')}_{s}_{e}"
    if t == "trend":
        s, e = int(spec.get("start", 1988)), int(spec.get("end", 2022))
        g = D.common_grid(range(s, e + 1))
        tr = D.trend(s, e, g)
        img = tr.select("slope").multiply(10).rename("gli_slope_per_decade").addBands(tr.select("p-value"))
        return img.updateMask(D.valid()).clip(aoi.ee()).toFloat(), g, 2, f"greenness_trend_{s}_{e}"
    if t == "qa":
        y = int(spec["year"])
        img = D.in_linear_segment(y).updateMask(D.valid()).clip(aoi.ee()).unmask(0).toUint8()
        return img, D.grid(y), 1, f"gapfill_qa_{y}"
    raise ValueError(f"Unknown layer type {t!r}.")


def chunk_grid(bbox, transform, bytes_per_px):
    """Cover the lon/lat bbox with whole native pixels, split into tiles under the request budget."""
    s, ox, oy = transform[0], transform[2], transform[5]
    x0, y0 = merc(bbox[0], bbox[1])
    x1, y1 = merc(bbox[2], bbox[3])
    c0, c1 = math.floor((x0 - ox) / s), math.ceil((x1 - ox) / s)
    r0, r1 = math.floor((oy - y1) / s), math.ceil((oy - y0) / s)
    tile = int(math.sqrt((EE_REQUEST_BYTES * 0.95) / bytes_per_px)) // 256 * 256
    chunks = []
    for rr in range(r0, r1, tile):
        for cc in range(c0, c1, tile):
            w, h = min(tile, c1 - cc), min(tile, r1 - rr)
            chunks.append({"col": cc - c0, "row": rr - r0, "width": w, "height": h,
                           "transform": [s, 0, ox + cc * s, 0, -s, oy - rr * s]})
    return chunks, c1 - c0, r1 - r0, ox + c0 * s, oy - r0 * s


def download_plan(aoi, spec):
    img, grid_, nb, base = _download_image(spec, aoi)
    crs, tr = grid_
    s = tr[0]
    bpp = 8 * nb if spec.get("type") == "trend" else 2 * nb      # measured: 3-band uint8 is budgeted at 6 bytes/px
    chunks, cols, rows, gx0, gy0 = chunk_grid(aoi.bbox, tr, bpp)
    if len(chunks) > 400:
        raise ValueError(f"{len(chunks)} files would be needed at native resolution; pick a smaller area.")
    name_of = lambda i, c: f"{base}_{i + 1:03d}" if len(chunks) > 1 else base

    def one(ic):
        i, c = ic
        url = call(img.getDownloadURL, {"name": name_of(i, c), "crs": crs, "crs_transform": c["transform"],
                                        "dimensions": f"{c['width']}x{c['height']}", "format": "GEO_TIFF"})
        return {**c, "url": url, "file": name_of(i, c) + ".tif"}

    with ThreadPoolExecutor(max_workers=8) as ex:
        out = list(ex.map(one, enumerate(chunks)))
    return {"name": base, "crs": crs, "scale": s, "bands": nb, "cols": cols, "rows": rows, "chunks": out,
            "vrt": vrt(base, out, cols, rows, s, gx0, gy0, nb, spec.get("type")) if len(out) > 1 else None}


def vrt(base, chunks, cols, rows, s, x0, y0, nb, kind):
    dtype = {"trend": "Float32", "yoc": "Int16"}.get(kind, "Byte")
    srs = 'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Mercator_1SP"],PARAMETER["central_meridian",0],PARAMETER["scale_factor",1],PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1],EXTENSION["PROJ4","+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +nadgrids=@null +wktext +no_defs"],AUTHORITY["EPSG","3857"]]'
    out = [f'<VRTDataset rasterXSize="{cols}" rasterYSize="{rows}">', f"  <SRS>{escape(srs)}</SRS>",
           f"  <GeoTransform>{x0!r}, {s!r}, 0, {y0!r}, 0, {-s!r}</GeoTransform>"]
    for b in range(1, nb + 1):
        out.append(f'  <VRTRasterBand dataType="{dtype}" band="{b}">')
        if nb == 4 and b == 4:
            out.append("    <ColorInterp>Alpha</ColorInterp>")
        for c in chunks:
            out.append(f'    <SimpleSource><SourceFilename relativeToVRT="1">{escape(c["file"])}</SourceFilename>'
                       f"<SourceBand>{b}</SourceBand>"
                       f'<SrcRect xOff="0" yOff="0" xSize="{c["width"]}" ySize="{c["height"]}"/>'
                       f'<DstRect xOff="{c["col"]}" yOff="{c["row"]}" xSize="{c["width"]}" ySize="{c["height"]}"/></SimpleSource>')
        out.append("  </VRTRasterBand>")
    out.append("</VRTDataset>")
    return "\n".join(out)
