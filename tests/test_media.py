"""Frame, GIF and download geometry against the measured Earth Engine limits. No Earth Engine calls."""
import math
import pytest
from app import aoi as A, media as M
from app.config import MAX_REQUEST_PX, MAX_VIDEO_PX, SCALE_FINE, WEBMERC_HALF, EE_REQUEST_BYTES


def aoi_box(w, s, e, n):
    return A.resolve({"kind": "geojson", "geometry": {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}})


def test_native_frames_sit_on_the_19m_grid():
    p = M.frame_plan(aoi_box(96.02, 19.66, 96.24, 19.88), "native")
    assert p["native"] and p["scale"] == SCALE_FINE
    assert p["width"] % 2 == 0 and p["height"] % 2 == 0
    k = (p["region"][0] + WEBMERC_HALF) / SCALE_FINE
    assert abs(k - round(k)) < 1e-6
    assert p["width"] * p["height"] <= MAX_REQUEST_PX


def test_large_area_is_capped_at_4k_and_the_request_limit():
    p = M.frame_plan(A.resolve({"kind": "admin", "pcode": "MMR001"}), "native")   # Kachin State
    assert max(p["width"], p["height"]) <= 3840
    assert p["width"] * p["height"] * 6 <= EE_REQUEST_BYTES
    assert not p["native"] and p["ground_m"] > 19


@pytest.mark.parametrize("preset,long_side", [("1080p", 1920), ("720p", 1280), ("4k", 3840)])
def test_fixed_presets(preset, long_side):
    p = M.frame_plan(aoi_box(95.9, 16.7, 96.3, 17.0), preset, "16:9")
    assert abs(max(p["width"], p["height"]) - long_side) <= 2
    assert p["width"] / p["height"] == pytest.approx(16 / 9, rel=0.01)


@pytest.mark.parametrize("aspect,n", [(1.0, 39), (16 / 9, 39), (0.5625, 39), (1.0, 2)])
def test_gif_dims_respect_the_video_limit(aspect, n):
    w, h = M.gif_dims(aspect, n)
    assert w * h * n <= MAX_VIDEO_PX and w <= 1000 and h <= 1000


def test_download_chunks_cover_the_area_within_budget():
    tr = [SCALE_FINE, 0, -WEBMERC_HALF, 0, -SCALE_FINE, 18483639.10403697]
    chunks, cols, rows, x0, y0 = M.chunk_grid([96.0, 16.0, 97.5, 17.5], tr, 8)
    assert sum(c["width"] * c["height"] for c in chunks) == cols * rows
    assert all(c["width"] * c["height"] * 8 <= EE_REQUEST_BYTES for c in chunks)
    k = (x0 + WEBMERC_HALF) / SCALE_FINE
    assert abs(k - round(k)) < 1e-6          # tiles start on native pixel edges


def test_vrt_lists_every_tile():
    tr = [30.0, 0, -20037510, 0, -30.0, 18483630]
    chunks, cols, rows, x0, y0 = M.chunk_grid([96.0, 16.0, 97.0, 17.0], tr, 8)
    for i, c in enumerate(chunks):
        c["file"] = f"t_{i}.tif"
    x = M.vrt("t", chunks, cols, rows, 30.0, x0, y0, 4, "year")
    assert x.count("<SimpleSource>") == 4 * len(chunks) and "Alpha" in x
