"""FastAPI app: JSON API under /api, plus the static page from web/ when run locally.

Hosted, the page is on GitHub Pages and this app is the API only (CORS allows the Pages origin).
"""
import json, logging, time
from collections import deque
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import aoi as A, dataset as D, layers as Lr, media as Md, stats as S
from .config import (ROOT, WEB, SERVE_WEB, CORS_ORIGINS, YEARS, ERAS, ATTRIBUTION, SENTINEL_NOTICE, MIMU_CREDIT, ALGO_VERSION, EE_PROJECT,
                     AOI_WARN_KM2, AOI_MAX_KM2, MAX_REQUEST_PX, MAX_VIDEO_PX, SCALE_FINE, SCALE_COARSE)
from .ee_client import EEError, init

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="Myanmar Earth Timelapse Explorer", docs_url="/api/docs", openapi_url="/api/openapi.json")
RATE_PER_MIN = 300          # per client IP; a full 39-year profile is ~45 requests
_hits: dict = {}


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    """Every request spends the project's Earth Engine quota, so damp runaway clients (per instance)."""
    if request.method == "POST" and request.url.path.startswith("/api/"):
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
        now = time.time()
        if len(_hits) > 5000:
            _hits.clear()
        q = _hits.setdefault(ip, deque())
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= RATE_PER_MIN:
            return JSONResponse({"detail": "Too many requests from this address; wait a minute and try again."}, status_code=429)
        q.append(now)
    return await call_next(request)


app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["content-type"], max_age=86400)    # outermost, so 4xx answers carry CORS too


@app.exception_handler(ValueError)
async def _bad_request(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(EEError)
async def _ee_failed(_: Request, e: EEError):
    return JSONResponse({"detail": f"Earth Engine: {e}"}, status_code=502)


class AoiBody(BaseModel):
    aoi: dict


class LayerBody(BaseModel):
    layer: dict
    aoi: Optional[dict] = None


class YearBody(AoiBody):
    year: int


class ChangeBody(AoiBody):
    a: int
    b: int
    window: int = 3


class SpanBody(AoiBody):
    start: int = 1988
    end: int = 2022
    metric: str = "gli"
    alpha: float = 0.05


class PointBody(BaseModel):
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-85, le=85)


class FramesBody(AoiBody):
    years: list[int] = Field(default_factory=lambda: list(YEARS))
    preset: str = "native"
    aspect: str = "auto"
    format: str = "jpg"


class GifBody(AoiBody):
    years: list[int] = Field(default_factory=lambda: list(YEARS))
    fps: int = 4
    aspect: str = "auto"


class DownloadBody(AoiBody):
    layer: dict


def _aoi(spec):
    return A.resolve(spec)


@app.on_event("startup")
def _startup():
    init()
    D.grids()


def _reference():
    f = ROOT / "data/calibration.json"
    if not f.exists():
        return None
    ref = json.loads(f.read_text(encoding="utf-8"))
    sf = ref["stable_forest_gli_median"]
    return {"stable_forest_gli": [sf.get(str(y)) for y in YEARS], "n_pixels": ref["n_pixels"], "source": ref["source"]}


@app.get("/api/meta")
def meta():
    return {"years": YEARS, "eras": ERAS, "attribution": ATTRIBUTION, "sentinel_notice": SENTINEL_NOTICE,
            "mimu": MIMU_CREDIT, "algo_version": ALGO_VERSION, "project": EE_PROJECT, "thresholds": D.T,
            "classes": D.CLASS_NAMES, "class_colors": Lr.CLASS_COLORS,
            "grids": {"coarse_m": SCALE_COARSE, "fine_m": SCALE_FINE, "fine_from": 2015},
            "limits": {"aoi_warn_km2": AOI_WARN_KM2, "aoi_max_km2": AOI_MAX_KM2, "frame_px": MAX_REQUEST_PX,
                       "video_px": MAX_VIDEO_PX},
            "presets": list(Md.PRESETS), "aspects": ["auto", *Md.ASPECTS], "reference": _reference()}


@app.post("/api/aoi")
def aoi_check(body: AoiBody):
    a = _aoi(body.aoi)
    return a.public(with_geometry=a.kind != "admin")


@app.get("/api/admin/{pcode}")
def admin_geometry(pcode: str):
    f = A.admin_feature(pcode)
    if not f:
        raise HTTPException(404, f"Unknown PCode {pcode}")
    return f


@app.post("/api/layer")
def layer(body: LayerBody):
    aoi = _aoi(body.aoi) if body.aoi else None
    return Lr.map_url(body.layer, aoi)


@app.post("/api/stats/year")
def stats_year(body: YearBody):
    return S.year_stats(_aoi(body.aoi), body.year)


@app.post("/api/stats/change")
def stats_change(body: ChangeBody):
    if body.window not in (1, 3):
        raise ValueError("window must be 1 or 3")
    return S.change_stats(_aoi(body.aoi), body.a, body.b, body.window)


@app.post("/api/stats/yoc")
def stats_yoc(body: SpanBody):
    if body.metric not in ("gli", "de"):
        raise ValueError("metric must be gli or de")
    return S.yoc_stats(_aoi(body.aoi), body.start, body.end, body.metric)


@app.post("/api/stats/trend")
def stats_trend(body: SpanBody):
    return S.trend_stats(_aoi(body.aoi), body.start, body.end, body.alpha)


@app.post("/api/point")
def point(body: PointBody):
    return S.point_profile(body.lon, body.lat)


@app.post("/api/frames")
def frames(body: FramesBody):
    if body.preset not in Md.PRESETS:
        raise ValueError(f"Unknown preset {body.preset!r}")
    return Md.frame_urls(_aoi(body.aoi), body.years, body.preset, body.aspect, body.format)


@app.post("/api/frames/plan")
def frames_plan(body: FramesBody):
    return Md.frame_plan(_aoi(body.aoi), body.preset, body.aspect)


@app.post("/api/gif")
def gif(body: GifBody):
    return Md.gif_url(_aoi(body.aoi), body.years, body.fps, body.aspect)


class ThumbBody(AoiBody):
    layer: dict
    preset: str = "1440p"
    aspect: str = "auto"


@app.post("/api/thumb")
def thumb(body: ThumbBody):
    if body.preset not in Md.PRESETS:
        raise ValueError(f"Unknown preset {body.preset!r}")
    return Md.layer_thumb(_aoi(body.aoi), body.layer, body.preset, body.aspect)


@app.post("/api/download")
def download(body: DownloadBody):
    return Md.download_plan(_aoi(body.aoi), body.layer)


if SERVE_WEB:
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {"service": "Myanmar Earth Timelapse Explorer API", "app": "https://geonet-myanmar.github.io/myanmar-earth-timelapse-explorer/",
                "docs": "/api/docs"}
