// About tab: dataset, method, calibration, caveats and sources. Numbers come from /api/meta where they can.
import {$, esc} from "./util.js";
import {S} from "./state.js";

export function renderAbout() {
  const m = S.meta, T = m.thresholds;
  $("#about").innerHTML = `<div class="about">
  <div class="group" style="border-top:0;padding-top:0">
    <h3>The imagery</h3>
    <p><a href="https://developers.google.com/earth-engine/datasets/catalog/projects_ee-earth-timelapse_assets_annual" target="_blank" rel="noopener">Earth Timelapse v0</a>:
      39 annual, gap-filled, water-masked RGB mosaics (1984–2022) from Landsat 4, 5, 7, 8, 9 and Copernicus Sentinel-2, published by Google Earth Outreach
      under CC BY 4.0 (<a href="https://developers.google.com/earth-engine/timelapse/about" target="_blank" rel="noopener">methodology</a>).
      Pixels are 30 m to 2014 and 19.1 m from 2015 (Web Mercator).</p>
    <table><thead><tr><th>Years</th><th>Sensors</th><th>Note</th></tr></thead><tbody>
      ${m.eras.map(e => `<tr><td>${e.from}–${e.to}</td><td>${esc(e.label)}</td><td>${esc(e.note)}</td></tr>`).join("")}
    </tbody></table>
    <p>It is a <b>visual</b> product: TOA reflectance stretched from 0.02 to 0.50 with gamma 1.7, matched to MODIS BRDF, open ocean replaced by styled
      ETOPO1 bathymetry. Google does not recommend it for radiometric analysis, so every index here is <b>indicative</b>.</p>
  </div>
  <div class="group">
    <h3>What was checked for Myanmar</h3>
    <ul>
      <li><b>1984–1986 are mostly reconstructed.</b> In three 0.6° test boxes (Sagaing, Shan, Ayeyarwady delta) every pixel's 1985 value lies on a straight line
        with 1984 and 1986 (within 2 DN in all bands), and 61–70% of 1986; from 1988 on only 0–1% do. In Hpakant township 1984 and 1985 are identical.
        The Gap-fill QA layer and the tinted chart years show this for your own area.</li>
      <li><b>The colours drift between sensors.</b> The median greenness of 558 stable-forest pixels dips from about 0.165 to 0.142–0.148 in
        2013–2016 (Landsat 8 and early Sentinel-2 years) and steps down after 1990. The greenness chart draws that national series as a dashed line, so
        the same wiggle in your area is not mistaken for local change. A Mann–Kendall test alone flags 41% of stable forest as trending, so the trend map
        also requires the slope to leave the stable-forest range (±${T.trend_slope} GLI per decade).</li>
      <li><b>2015 changes the pixel grid</b> from 30 m to 19.1 m. Year-to-year change at 2015 includes that switch.</li>
    </ul>
  </div>
  <div class="group">
    <h3>How the numbers are made</h3>
    <ul>
      <li><b>Native resolution.</b> Each year is reduced on its own grid (crs and transform read from the asset). Comparisons across years use the finest grid
        they share: 19.1 m when every year is 2015 or later, otherwise 30 m with the 19.1 m years averaged onto it. Map layers are drawn at the screen's
        zoom; the numbers never are.</li>
      <li><b>Pseudo-reflectance</b> ρ = 0.02 + 0.48·(DN/255)^1.7 inverts the documented stretch. <b>Greenness</b> GLI = (2G − R − B)/(2G + R + B);
        <b>brightness</b> = mean ρ; <b>colour change</b> = CIELAB ΔE76 of the displayed colours.</li>
      <li><b>Synthetic ocean</b> (bit-identical in 1990, 2005 and 2020 and not Hansen GFC land) is left out of every statistic and reported separately.</li>
      <li><b>Thresholds</b> were calibrated on Myanmar pixels in 14 boxes across the country. Green cover (GLI &gt; ${T.green_gli}) and bright/bare
        surface (brightness &gt; ${T.bare_bright}, GLI &lt; ${T.bare_gli}) separate ESA WorldCover 2021 classes. Change thresholds are what
        <i>nearby</i> years differ by on only 5% of all land, in both the Landsat and Sentinel-2 eras: single years ΔE ≥ ${T.de_visible},
        |ΔGLI| ≥ ${T.dgli}, |Δbrightness| ≥ ${T.dbright}; 3-year means ΔE ≥ ${T.de_visible_w3}, |ΔGLI| ≥ ${T.dgli_w3}, |Δbrightness| ≥ ${T.dbright_w3}.
        (Forest-only noise was too low: farmland made a quarter of Naypyitaw "change" between 2016 and 2020.)</li>
      <li><b>Change A→B</b> compares 3-year means around each year by default, which damps one-off mosaic quirks.</li>
      <li><b>Year of change</b> compares 3-year means before and after each year and keeps each pixel's largest drop. Because every pixel gets about 30 tries,
        the threshold bounds the <i>maximum</i>: ${T.yoc_gli} GLI (stable-forest p95, all-land p90) or ΔE ${T.yoc_de} (all-land p90).</li>
      <li><b>Areas</b> are true areas (Earth Engine pixelArea); large areas are reduced as parallel cells and summed.</li>
    </ul>
  </div>
  <div class="group">
    <h3>Sources and licences</h3>
    <ul>
      <li>${esc(m.attribution)}, CC BY 4.0. ${esc(m.sentinel_notice)} (<a href="https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice" target="_blank" rel="noopener">legal notice</a>).</li>
      <li>Administrative boundaries: <a href="https://geonode.themimu.info/" target="_blank" rel="noopener">MIMU</a> PCode v9.4 (States/Regions, Districts, Townships).
        Names follow MIMU; boundaries are not authoritative.</li>
      <li>Hansen/UMD/Google/USGS/NASA Global Forest Change (land mask and stable forest); ESA WorldCover 2021 (calibration only).</li>
      <li>Basemaps: Esri World Imagery; CARTO and OpenStreetMap contributors.</li>
    </ul>
    <p class="note">Uploaded files are read in your browser; only the area's polygon is sent to the analysis server, which runs
      Earth Engine under the project <code>${esc(m.project)}</code> (algorithm version ${esc(m.algo_version)}). Source:
      <a href="https://github.com/geonet-myanmar/myanmar-earth-timelapse-explorer" target="_blank" rel="noopener">github.com/geonet-myanmar/myanmar-earth-timelapse-explorer</a>.</p>
  </div></div>`;
}
