# Myanmar Earth Timelapse Explorer

A local web app for Google's **Earth Timelapse v0** annual mosaics (1984–2022, Earth Engine asset
`projects/ee-earth-timelapse/assets/annual`, CC BY 4.0). Pick an area anywhere in Myanmar, then:

- **Explore**: scrub or play through 39 years, swipe or flicker between two years, adjust the display.
- **Analyze**:
  - a 39-year profile of the area: greenness, green and bright/bare cover, visible change, gap-fill share, mean colour
  - map layers for change A→B, year of change, greenness trend and gap-fill QA, each with area statistics at native resolution
  - a pixel inspector
- **Timelapse**: MP4, WebM or GIF videos at native pixels up to 4K, with year, title, sensor era, gap-fill badge,
  timeline, scale bar, north arrow and attribution burned in. Also Earth Engine's own quick GIF, before/after and
  filmstrip PNGs, and native-grid GeoTIFFs.

The area can be drawn, uploaded (GeoJSON, KML, KMZ, zipped Shapefile, a loose `.shp/.dbf/.prj` set, GPX),
or chosen from MIMU States/Regions, Districts and Townships (PCode v9.4, searchable in English or Myanmar).

## Run it

```
pip install -r requirements.txt          # requirements-dev.txt adds the data scripts and tests
python run.py              # opens http://127.0.0.1:8765
python run.py --lan        # also reachable from other computers on the network
```

The app uses this machine's Earth Engine login with project `gee-python-419405`. Override it with
`EE_PROJECT=...`. The stored credentials carry no project, so the app always passes one explicitly.
Everything an area costs counts against that project's noncommercial quota (150 EECU-hours a month).

## What is checked, and what that means for results

- **Visual product.** The bands are 8-bit display colours: TOA reflectance stretched 0.02–0.50 with gamma 1.7,
  ocean replaced by ETOPO bathymetry. Indices (GLI greenness, brightness, CIELAB ΔE) are **indicative**.
- **1984–1986 are mostly reconstructed in Myanmar.** In three test boxes, 1985 lies on a straight line with
  1984 and 1986 for 100% of pixels, and 1986 for 61–70%. From 1988 the share is 0–1%. The gap-fill QA layer
  and the tinted chart years show it per area.
- **Sensor drift.** Stable-forest greenness dips in 2013–2016. The greenness chart draws that national series as a
  dashed reference line, and the trend map only counts slopes outside the stable-forest range.
- **Native resolution.**
  - Every statistic is reduced on the asset's own grid: 30 m to 2014, 19.109 m from 2015.
  - Cross-year comparisons use the finest grid all the years share.
  - Map tiles render at screen zoom; the numbers never do.
- **Thresholds** were calibrated on Myanmar pixels by `scripts/04_calibrate.py`. Change thresholds are what nearby
  years differ by on only 5% of all land. Year-of-change thresholds bound each pixel's maximum over about 30
  windows. The provenance is in comments in `app/dataset.py` and in the About tab.

Earth Engine limits measured for this app:
- Thumbnails and downloads: 50,331,648 bytes per request at 6 bytes/px (≤ 8.39 Mpx).
- `getVideoThumbURL`: ≤ 26,214,400 px across all frames.
- Thumbnail URLs are CORS-enabled and last 2 hours.

## Rebuild the data

```
python scripts/01_fetch_mimu.py      # MIMU WFS -> data/raw/mimu (falls back to Downloads/tmp copies)
python scripts/02_build_admin.py     # data/mimu/adm0-3.geojson (full res) + web/data/admin.topo.json (display)
python scripts/03_vendor.py          # pinned JS libraries -> web/vendor (+ SHA-256 in VERSIONS.txt)
python scripts/04_calibrate.py       # threshold evidence; --reference rewrites data/calibration.json
python scripts/05_make_fixtures.py   # upload test files + reference areas
```

## Tests

```
python -m pytest -m "not live and not e2e"   # unit: maths, AOI rules, frame/GIF/download geometry
python -m pytest -m live                     # Earth Engine: tiles, native-grid stats and GeoTIFFs, QA signature
python -m pytest -m e2e                      # the app in Chrome: every upload format, analysis, MP4 render
```

The e2e suite uses the running app on port 8765, or starts one on 8766 for the duration of the tests.

## Layout

```
app/        FastAPI backend: ee_client, dataset (maths), aoi, layers, stats, media, main
web/        page, CSS, ES modules (no build step), data/admin.topo.json, vendor/
data/mimu/  MIMU boundaries at full resolution (used for analysis)
scripts/    data preparation and calibration
tests/      unit, live and e2e tests; fixtures/
```

## Published version

- **Page:** https://geonet-myanmar.github.io/myanmar-earth-timelapse-explorer/ (GitHub Pages). It is built from
  `web/` by `.github/workflows/pages.yml` on every push to `main` that touches `web/`.
- **API:** https://myanmar-earth-timelapse-explorer.vercel.app (Vercel project `myanmar-earth-timelapse-explorer`,
  team GeoNet Myanmar). The same FastAPI app; on Vercel it serves only `/api` (no static files), caches in `/tmp`,
  and allows the Pages origin through CORS (`MMTL_CORS_ORIGINS`).
- `web/js/config.js` sends API calls to Vercel when the page is on `github.io`, and to the same origin under `run.py`.

Redeploy the API after changing `app/` or `data/`:

```
vercel deploy --prod --scope geo-net-myanmar
```

`.vercelignore` keeps the upload to the API's needs. Production environment variables on Vercel:
- `EE_SERVICE_ACCOUNT_KEY` (sensitive): the key JSON
- `EE_PROJECT`

The Earth Engine identity is the service account `mm-timelapse-web@gee-python-419405.iam.gserviceaccount.com`.
Its roles:
- Earth Engine Resource Viewer
- Service Usage Consumer
- the custom role `eeRenderOnly`: create maps, thumbnails, video and filmstrip thumbnails, and nothing else

It cannot write or delete assets, or start exports. Its key lives outside the repository
(`~/.config/earthengine/mm-timelapse-web-key.json`). To revoke it, delete the key in Cloud Console under IAM →
Service accounts.

The public API spends the project's Earth Engine quota. It allows 300 requests per minute per address on each
instance, and areas up to 250,000 km². For a hard ceiling, set the "EECU-time per day" quota in Cloud Console.

## Credits

Google Earth Timelapse (Google, Landsat, Copernicus), CC BY 4.0; contains modified Copernicus Sentinel data
[2015–2022]. Boundaries: MIMU PCode v9.4. Hansen/UMD/Google/USGS/NASA Global Forest Change (land mask,
calibration). ESA WorldCover 2021 (calibration). Basemaps and labels: Esri.
