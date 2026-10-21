"""Settings, dataset facts and Earth Engine limits (measured 2026-10-21 against the live API)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
MIMU = ROOT / "data/mimu"
ON_VERCEL = bool(os.environ.get("VERCEL"))
# Vercel's filesystem is read-only except /tmp (per instance, so the stats cache only lives while it is warm).
CACHE = Path(os.environ.get("MMTL_CACHE_DIR") or ("/tmp/mmtl-cache" if ON_VERCEL else ROOT / "cache"))
# The page is served by run.py locally; when hosted, it lives on GitHub Pages and this app is the API only.
SERVE_WEB = WEB.is_dir() and not ON_VERCEL
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "MMTL_CORS_ORIGINS", "https://geonet-myanmar.github.io,http://127.0.0.1:8765,http://localhost:8765").split(",") if o.strip()]

EE_PROJECT = os.environ.get("EE_PROJECT", "gee-python-419405")
COLLECTION = "projects/ee-earth-timelapse/assets/annual"
YEARS = list(range(1984, 2023))
HANSEN = "UMD/hansen/global_forest_change_2025_v1_13"   # datamask only (land / water / no data)

# Bump whenever a computation changes, so cached statistics are not reused across versions.
ALGO_VERSION = "2026.10.21-1"

# Native grids (EPSG:3857). 1984-2014 are 30 m; 2015-2022 are 19.109 m (Web Mercator zoom 13).
SCALE_FINE = 19.109257071294063
SCALE_COARSE = 30.0
WEBMERC_HALF = 20037508.342789244

# Request limits, measured: every thumbnail / download request is budgeted at 6 bytes per pixel.
EE_REQUEST_BYTES = 50_331_648
BYTES_PER_PX = 6
MAX_REQUEST_PX = (EE_REQUEST_BYTES - 64) // BYTES_PER_PX       # 8,388,597 px  (3840x2160 fits)
MAX_VIDEO_PX = 26_214_400                                        # getVideoThumbURL, all frames together

# AOI limits (quota protection; everything bills to EE_PROJECT).
AOI_WARN_KM2 = 50_000
AOI_MAX_KM2 = 250_000
AOI_MAX_VERTICES = 200_000

ATTRIBUTION = "Google Earth Timelapse (Google, Landsat, Copernicus)"
SENTINEL_NOTICE = "Contains modified Copernicus Sentinel data [2015–2022]"
MIMU_CREDIT = "Boundaries: MIMU PCode v9.4"

# Sensor eras, from https://developers.google.com/earth-engine/timelapse/about
ERAS = [
    {"from": 1984, "to": 1998, "label": "Landsat 4/5 TM", "note": "gaps before 1999 filled by per-pixel linear interpolation"},
    {"from": 1999, "to": 2012, "label": "Landsat 5 TM + Landsat 7 ETM+", "note": "Landsat 7 scan-line gaps after May 2003"},
    {"from": 2013, "to": 2014, "label": "Landsat 8 OLI", "note": ""},
    {"from": 2015, "to": 2022, "label": "Sentinel-2 + Landsat 8/9", "note": "19.1 m grid instead of 30 m"},
]
