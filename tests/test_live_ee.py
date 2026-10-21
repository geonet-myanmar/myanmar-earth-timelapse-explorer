"""Live Earth Engine checks (python -m pytest -m live). Uses the same credentials as the app."""
import io, math, urllib.request
import pytest
from PIL import Image
from app import aoi as A, layers as L, media as M, stats as S
from app.config import SCALE_FINE, MAX_VIDEO_PX

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True, scope="module")
def _ee():
    from app.ee_client import init
    init()                       # the server does this at startup; ee objects can't be built before it


def box(w, s, e, n, name="test"):
    return A.resolve({"kind": "geojson", "name": name,
                      "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}})


def fetch(url):
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read()


def tile_xy(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def test_year_tile_renders_over_yangon():
    url = L.map_url({"type": "year", "year": 2022})["url"]
    x, y = tile_xy(96.16, 16.80, 10)
    st, ct, body = fetch(url.replace("{z}", "10").replace("{x}", str(x)).replace("{y}", str(y)))
    assert st == 200 and ct in ("image/jpeg", "image/png")     # opaque RGB tiles come back as JPEG
    assert Image.open(io.BytesIO(body)).size == (256, 256)


def test_analysis_layer_needs_and_uses_an_aoi():
    with pytest.raises(ValueError):
        L.build({"type": "trend"}, None)
    r = L.map_url({"type": "change", "a": 2000, "b": 2012, "metric": "classes"}, box(96.02, 19.66, 96.24, 19.88))
    assert r["url"].startswith("https://earthengine.googleapis.com/") and r["legend"]["kind"] == "categorical"


def test_hpakant_stats_on_native_grids():
    a = A.resolve({"kind": "admin", "pcode": "MMR001009"})
    r22, r10 = S.year_stats(a, 2022), S.year_stats(a, 2010)
    assert r22["grid_m"] == pytest.approx(SCALE_FINE, abs=1e-3) and r10["grid_m"] == 30
    assert r22["valid_km2"] == pytest.approx(5756.5, rel=0.005)
    assert 0 < r22["gli"] < 0.4 and r22["bare_pct"] > r10["bare_pct"]    # the mines grew


def test_gapfill_signature_in_the_sagaing_test_box():
    a = box(94.6, 22.0, 95.2, 22.6)
    assert S.year_stats(a, 1985)["qa_pct"] > 95
    assert S.year_stats(a, 2005)["qa_pct"] < 5


def test_near_null_change_is_mostly_unchanged():
    r = S.change_stats(box(96.02, 19.66, 96.24, 19.88), 2016, 2020, 3)
    assert r["classes"][0]["pct"] > 80


def test_change_window_across_the_2015_grid_switch():
    # 2014-2016 mixes 30 m ints with 19 m pixels averaged to float; the collection must still be homogeneous
    r = S.change_stats(box(96.40, 21.62, 96.50, 21.72), 2005, 2015, 3)
    assert r["grid_m"] == 30 and abs(sum(c["pct"] for c in r["classes"]) - 100) < 0.01


def test_frames_come_back_at_the_planned_size():
    r = M.frame_urls(box(96.02, 19.66, 96.24, 19.88), [1990, 2022], "720p")
    for f in r["frames"]:
        st, ct, body = fetch(f["url"])
        assert st == 200 and "jpeg" in ct
        assert Image.open(io.BytesIO(body)).size == (r["width"], r["height"])


def test_ee_gif_stays_within_the_video_limit():
    r = M.gif_url(box(96.02, 19.66, 96.24, 19.88), list(range(1984, 2023)), fps=4)
    assert r["width"] * r["height"] * 39 <= MAX_VIDEO_PX
    st, ct, body = fetch(r["url"])
    assert st == 200 and ct == "image/gif" and body[:3] == b"GIF"


@pytest.mark.parametrize("year,scale", [(2022, SCALE_FINE), (2010, 30.0)])
def test_geotiff_is_on_the_native_grid(tmp_path, year, scale):
    import rasterio
    plan = M.download_plan(box(96.10, 19.74, 96.12, 19.76), {"type": "year", "year": year})
    assert len(plan["chunks"]) == 1 and plan["scale"] == pytest.approx(scale)
    st, ct, body = fetch(plan["chunks"][0]["url"])
    f = tmp_path / "t.tif"
    f.write_bytes(body)
    with rasterio.open(f) as ds:
        assert ds.crs.to_epsg() == 3857 and ds.count == 4
        assert ds.transform.a == pytest.approx(scale, rel=1e-6)
        assert (ds.width, ds.height) == (plan["cols"], plan["rows"])


def test_pixel_profile_flags_reconstructed_years():
    r = S.point_profile(96.25, 25.62)
    ys = r["years"]
    assert [d["year"] for d in ys] == list(range(1984, 2023))
    assert ys[0]["linear"] and ys[1]["linear"] and not ys[20]["linear"]
