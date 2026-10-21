"""End-to-end checks in the installed Chrome (python -m pytest -m e2e). Needs network for Earth Engine and tiles."""
import json, os, re, subprocess
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
from conftest import FIXTURES

pytestmark = pytest.mark.e2e
# Your own files to try (os.pathsep-separated), e.g. MMTL_REAL_FILES="C:/data/a.kml;C:/data/b.geojson"
REAL = [Path(p) for p in os.environ.get("MMTL_REAL_FILES", "").split(os.pathsep) if p.strip()] or [Path("unset")]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(base_url + "/#tab=area", wait_until="networkidle")
    pg.evaluate("localStorage.clear()")
    yield pg
    ctx.close()


def card_area(pg):
    m = re.search(r"Area\s+([\d,.]+)\s*(km²|ha)", pg.inner_text("#aoicard"))
    v = float(m.group(1).replace(",", ""))
    return v / 100 if m.group(2) == "ha" else v


def test_loads_without_errors(page):
    page.wait_for_timeout(2500)
    assert page.inner_text("#yearbadge").startswith("2022")
    assert page.locator(".leaflet-tile-loaded").count() > 0
    assert page.errors == []


def test_admin_search_by_myanmar_name(page):
    page.fill("#adminsearch", "ဖားကန့်")
    page.click("#adminresults li[data-p='MMR001009']")
    page.wait_for_selector("#aoicard:not([hidden])")
    assert "Hpakant" in page.inner_text("#aoichip") and abs(card_area(page) - 5757) < 1
    assert page.input_value("#sel-ts") == "MMR001009"


CASES = [("hpakant_4326.geojson", None), ("hpakant_32647.geojson", None), ("hpakant_utm_nocrs.geojson", "EPSG:32647"),
         ("nyaungshwe.kml", None), ("nyaungshwe.kmz", None), ("taunggyi_pair_shp.zip", None)]


@pytest.mark.parametrize("name,crs", CASES)
def test_upload_formats(page, expected_areas, name, crs):
    page.click("#aoimode button[data-mode=upload]")
    page.set_input_files("#fileinput", str(FIXTURES / name))
    if crs:
        page.wait_for_selector("#crsgo")
        page.select_option("#crspick", crs)
        page.click("#crsgo")
    page.click("#useupload")
    page.wait_for_selector("#aoicard:not([hidden])")
    assert card_area(page) == pytest.approx(expected_areas[name], rel=0.005)


def test_upload_loose_shapefile_set(page, expected_areas):
    page.click("#aoimode button[data-mode=upload]")
    page.set_input_files("#fileinput", [str(FIXTURES / f"loose/taunggyi_pair.{e}") for e in ("shp", "shx", "dbf", "prj", "cpg")])
    page.click("#useupload")
    page.wait_for_selector("#aoicard:not([hidden])")
    assert card_area(page) == pytest.approx(expected_areas["loose"], rel=0.005)


def test_points_are_buffered_and_outside_is_rejected(page):
    page.click("#aoimode button[data-mode=upload]")
    page.set_input_files("#fileinput", str(FIXTURES / "points.kml"))
    page.click("#bufgo")
    page.wait_for_selector("#aoicard:not([hidden])")
    assert card_area(page) == pytest.approx(3 * 3.1416, rel=0.03)          # three 1 km circles
    page.set_input_files("#fileinput", str(FIXTURES / "outside.geojson"))
    page.click("#useupload")
    page.wait_for_selector("#maptoast:not([hidden])")
    assert "does not overlap Myanmar" in page.inner_text("#maptoast")


@pytest.mark.parametrize("path", REAL, ids=lambda p: p.name[:24])
def test_real_files(page, path):
    if not path.exists():
        pytest.skip("set MMTL_REAL_FILES to run this")
    page.click("#aoimode button[data-mode=upload]")
    page.set_input_files("#fileinput", str(path))
    page.wait_for_selector("#useupload, #bufgo, #crsgo")
    page.click("#useupload" if page.locator("#useupload").count() else "#bufgo")
    page.wait_for_selector("#aoicard:not([hidden])", timeout=60000)
    assert card_area(page) > 0 and page.errors == []


def test_draw_rectangle(page):
    page.click("#aoimode button[data-mode=draw]")
    page.click("[data-draw=Rectangle]")
    b = page.locator("#map").bounding_box()
    x, y = b["x"] + b["width"] * 0.45, b["y"] + b["height"] * 0.45
    page.mouse.click(x, y)
    page.mouse.move(x + 60, y + 50, steps=5)
    page.mouse.click(x + 60, y + 50)
    page.wait_for_selector("#aoicard:not([hidden])")
    assert "Drawn rectangle" in page.inner_text("#aoicard") and card_area(page) > 1


def test_preset_opens_swipe(page):
    page.click("#aoimode button[data-mode=presets]")
    page.click(".preset[data-id=naypyitaw]")
    # the divider is a zero-width element (the line is its ::before), so check the attribute, not visibility
    page.wait_for_function("!document.querySelector('#swipe').hidden && document.querySelector('#swipeR').textContent === '2012'")
    assert page.inner_text("#swipeL") == "2000"


def test_analysis_flow(page):
    page.click("#aoimode button[data-mode=presets]")
    page.click(".preset[data-id=naypyitaw]")
    page.wait_for_selector("#aoicard:not([hidden])")
    page.click("#tabs button[data-tab=analyze]")
    page.wait_for_function("document.querySelector('#ts-progress').hidden && document.querySelector('#ch-strip svg')", timeout=600000)
    assert page.locator("#ch-strip svg rect[fill^='rgb']").count() == 39
    with page.expect_download() as dl:
        page.click("#ts-csv")
    lines = Path(dl.value.path()).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 41 and lines[1].startswith("year,")
    page.click("#anmode button[data-an=change]")
    page.wait_for_selector("#ch-stats table", timeout=600000)
    assert "vegetation loss" in page.inner_text("#ch-stats") and not page.locator("#legend").is_hidden()
    page.click("#anmode button[data-an=yoc]")
    page.wait_for_selector("#ch-yoc svg", timeout=600000)
    assert page.errors == []


def test_mp4_render(page, tmp_path):
    import imageio_ffmpeg
    page.click("#aoimode button[data-mode=presets]")
    page.click(".preset[data-id=naypyitaw]")
    page.wait_for_selector("#aoicard:not([hidden])")
    page.click("#tabs button[data-tab=timelapse]")
    page.select_option("#v-from", "2016"); page.select_option("#v-to", "2022")
    page.select_option("#v-preset", "480p"); page.select_option("#v-fade", "4"); page.select_option("#v-format", "mp4")
    page.click("#v-render")
    page.wait_for_selector("#v-dl", timeout=600000)
    with page.expect_download() as dl:
        page.click("#v-dl")
    f = tmp_path / "t.mp4"
    dl.value.save_as(f)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    info = subprocess.run([ff, "-hide_banner", "-i", str(f)], capture_output=True, text=True).stderr
    assert "h264" in info
    w, h = map(int, re.search(r"(\d{3,4})x(\d{3,4})", info).groups())
    assert max(w, h) <= 854 and w % 2 == 0 and h % 2 == 0
    count = subprocess.run([ff, "-hide_banner", "-i", str(f), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    assert int(re.findall(r"frame=\s*(\d+)", count)[-1]) == 7 + 6 * 4    # 7 years + 4 crossfade frames between each


def test_phone_width_has_no_horizontal_scroll(browser, base_url):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    pg.goto(base_url + "/#tab=analyze", wait_until="networkidle")
    for tab in ("area", "explore", "analyze", "timelapse", "about"):
        pg.click(f"#tabs button[data-tab={tab}]")
        assert pg.evaluate("document.scrollingElement.scrollWidth") <= 390, tab
    ctx.close()


def test_dark_theme(page):
    page.click("#themebtn")      # auto -> light
    page.click("#themebtn")      # light -> dark
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert sum(map(int, re.findall(r"\d+", bg)[:3])) < 120
