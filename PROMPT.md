# Implementation Prompt: Interactive SST Map Viewer ("sst_viewer")

You are implementing a local, interactive web app for visualizing sea surface
temperature (SST) on a world map, built on the data already present in
`C:\Users\Georgii\OneDrive\Desktop\sst_data_analysis\`. Read
`RESEARCH_OVERVIEW.md` in the project root first — it describes every dataset
and sub-project. Build the app inside `sst_data_analysis/sst_viewer/`.

## Ground truth about the available data (verified — do not re-derive)

| Dataset | Local form | Usable as map layer? |
|---|---|---|
| NOAA OISST v2.1 (0.25°, daily) | `RProject/oisst_may20_july1/*.nc` — 1,118 **global** daily files, years 2000–2025, dates May 20 – July 1 only (~1.6 MB each) | **Yes — primary gridded layer** |
| NASA MUR (0.01°, daily) | `python_script/full_analysis/mur_raw_data/*.nc` — 1,107 small point-box extracts (~57 KB) around coastal stations | No — point/station data only |
| ESA SST_cci v2.1 (0.05°, daily) | `python_script/full_analysis/sstcci_data/netcdf/*.nc` — 71 point extracts, 1982–2016 | No — point/station data only |
| Processed station CSVs | `python_script/full_analysis/data/mur_csv_data/P*_all_data.csv`, `processed_sst_data.csv` (from `scripts/prepare_data.py`) | Station time series for charts |

OISST files contain variables `sst`, `anom`, `err`, and `ice` (sea-ice
concentration) on a global 0.25° grid with a `zlev` dimension of size 1.
MUR data carries `analysed_sst`, `analysis_error`, `mask`, `sea_ice_fraction`.
All SST is in Kelvin in MUR/CCI raw files; OISST `sst` is already °C. Verify
units on first read rather than trusting this note.

The user's study region is the Okhotsk Sea (135–165°E, 40–65°N) with named
coastal stations listed in `RESEARCH_OVERVIEW.md` (Sakhalin, Kurils,
Hokkaido, Kodiak). Default the map view there, but keep the map global —
OISST files are global.

## Architecture (keep it this simple)

- **Backend:** Python + FastAPI + xarray/netCDF4, run with uvicorn from the
  existing `mfa_env` conda env if its packages suffice; otherwise create
  `environment.yml` for a new env. One process, no database.
- **Frontend:** a single `index.html` + one JS file + one CSS file using
  **Leaflet** (via CDN). No build step, no npm, no framework.
- The backend renders SST fields to transparent PNGs with
  matplotlib (`imshow`, no axes) and serves them as Leaflet `ImageOverlay`s
  with known lat/lon bounds. Do NOT build a tile server — at 0.25° a single
  global PNG per date is at most 1440×720 px and renders instantly.
- Cache rendered PNGs on disk keyed by (dataset, date, variable, colormap)
  so timelapse playback is fast after first pass.
- A small JSON API:
  - `GET /api/datasets` → list of datasets, their date ranges, variables
  - `GET /api/overlay?dataset=oisst&date=2010-06-15&var=sst` → PNG
  - `GET /api/point?lat=..&lon=..&dataset=..&date=..` → value at pixel (for
    click-to-inspect)
  - `GET /api/series?lat=..&lon=..&dataset=..&start=..&end=..` → time series
    JSON (for charts)
  - `GET /api/stations` → the named coastal stations + which datasets cover
    them (parse coordinates from `RESEARCH_OVERVIEW.md` / `coords.txt` once
    into a static `stations.json`; do not re-parse at runtime)

Scan the OISST directory once at startup to build a date→file index; dates
are in the filenames (`oisst-avhrr-v02r01.YYYYMMDD.nc`), so no file needs to
be opened for indexing.

## Required features

### 1. Map layers and base maps
- Base-map switcher with at least: **satellite imagery** (Esri World Imagery
  tile service), **ocean/bathymetry** (Esri Ocean Basemap or GEBCO tiles),
  and a plain light gray reference layer. These are free public tile
  services usable directly in Leaflet.
- SST overlay on top with an opacity slider.
- Layer/variable switcher: SST (°C), SST anomaly (`anom`), analysis error
  (`err`) — all present in the OISST files.

### 2. Ice and no-data rendering (explicitly requested — do not skip)
When rendering the SST PNG, classify each cell:
- **Valid SST** → colormap (perceptually uniform, e.g. `cmocean.thermal` or
  `viridis`-family; diverging `RdBu_r` for anomaly, centered at 0).
- **Ice-covered** (OISST `ice` ≥ 0.15, the standard 15% concentration
  threshold; make the threshold a constant) → a distinct flat color
  (white/pale cyan hatching or solid #e8f4f8) clearly labeled "ice" in the
  legend.
- **No data** (masked/NaN over ocean) → a third distinct color
  (e.g. mid-gray diagonal pattern or solid #999) labeled "no data".
- **Land** → fully transparent so the base map shows through.
The legend/colorbar must show all three states plus the color ramp with its
current min/max. Let the user toggle between fixed color scale (set min/max
in a small settings box — essential for comparable timelapse frames) and
per-frame auto-scale.

### 3. Date control and timelapse
- Date picker (native `<input type="date">`) constrained to available dates;
  gray out or snap to nearest available date since local coverage is only
  May 20 – July 1 of each year.
- Prev/next-day buttons and keyboard ←/→.
- **Timelapse:** play/pause button, speed control (frames per second), and a
  `GAP_DAYS` integer input. Playback iterates the sorted list of *available*
  dates: gap=1 steps consecutive available dates; gap=N skips N days forward
  each frame (snapping to the nearest available date). This naturally
  supports the user's two modes: consecutive days within a season, and
  same-date-across-years style lapses (e.g. gap=365 from May 20 walks
  May 20 of every year). Also add an explicit "same day each year" toggle
  since gap=365 drifts on leap years.
- Prefetch the next 2–3 frames' PNGs during playback so it doesn't stutter.

### 4. Measurement tool
- Distance measurement: click to add vertices, shows cumulative great-circle
  (haversine) distance in km; double-click or Esc to finish; delete button.
  Implement with plain Leaflet events and a polyline — do not add a plugin
  dependency for this (~40 lines).

### 5. Click-to-inspect and station markers
- Clicking any ocean pixel shows a popup: lat/lon, SST, anomaly, ice
  fraction, and a "chart this point" button.
- The named coastal stations render as markers (toggleable layer). Station
  popups show which datasets cover them and offer the same chart button,
  backed by the MUR/CCI CSVs where available (longer/higher-resolution
  series than OISST).

### 6. Charts and export
- A collapsible chart panel (use **Chart.js** via CDN — no build step)
  supporting at least:
  - Time series of SST at a point/station across the selected date range
    (multi-year: x = date, or overlay mode: x = day-of-year, one line per
    year — mirror the "SST colored by year" plots from RProject3).
  - Anomaly time series.
  - Comparison: 2+ points/stations on one chart.
- Export: PNG download of the current chart (Chart.js `toBase64Image`), CSV
  download of the charted data, and PNG download of the current map view
  (`leaflet-image` approach or a backend composite; if map export is
  fragile, exporting the SST overlay PNG + a screenshot hint is acceptable
  for v1 — say so in the README).
- Timelapse export to animated GIF or MP4 via a backend endpoint
  (matplotlib frames + ffmpeg, which lives at
  `mfa_env\Library\bin\ffmpeg.exe` — `conda run -n mfa_env ffmpeg`).

### 7. A/B swipe comparison (Worldview-style)
- A "Compare" toggle that splits the map with a draggable vertical divider:
  side A shows the overlay for date A, side B for date B (same variable and
  color scale — force fixed scale while comparing, otherwise the comparison
  lies). Each side gets its own date picker; a "same day, other year" shortcut
  sets B to A ± N years.
- Implement with two Leaflet `ImageOverlay`s and a CSS `clip-path` (or
  `clip`) rect updated as the divider drags — do not add a plugin dependency;
  the side-by-side plugin ecosystem is stale and this is ~50 lines.
- The inspect popup, while comparing, shows both values and their difference.

### 8. Extensibility for future datasets
Wrap dataset access in one small `datasets.py` module with a function-level
registry: each dataset provides `dates()`, `grid(date, var)` → 2D array +
bounds, and `point_series(lat, lon, ...)`. OISST is the only gridded entry
now; MUR/CCI register as station-series-only entries. When the user later
downloads gridded MUR/CCI subsets, adding them is one registry entry. Do not
build plugin architecture beyond this.

## Constraints and environment notes
- Windows 11, PowerShell 5.1 (no `&&`); prefer `conda run -n mfa_env python`.
  Bare `python` may hit the Windows Store alias.
- Data lives on OneDrive — open NetCDF files read-only, never write into the
  data directories; put the PNG cache under `sst_viewer/cache/` (gitignored).
- Never read whole large files into chat/context; operate via scripts.
- Do not download any new data in this task; work with local files only.
- No new global installs (`winget`, etc.) without asking.

## Deliverables
1. `sst_viewer/` — `app.py` (FastAPI), `datasets.py`, `static/index.html`,
   `static/app.js`, `static/style.css`, `stations.json`, `README.md` with a
   one-line run command.
2. A smoke test (`test_smoke.py` or an `assert`-based `__main__` check) that:
   indexes the OISST directory, renders one overlay PNG, reads one point
   value, and returns one station series — fails loudly if data paths moved.
3. Verify end-to-end before finishing: start the server, fetch an overlay
   PNG and a series JSON with curl/Invoke-WebRequest, and confirm the map
   loads (report what you checked).

## Suggested implementation order
1. `datasets.py` + OISST date index + PNG rendering (ice/no-data classes) —
   verify one PNG looks right before any frontend work.
2. FastAPI endpoints + static Leaflet page with base-map switcher, overlay,
   opacity, legend.
3. Date picker + prev/next + timelapse with GAP_DAYS.
4. Click-to-inspect + stations + measurement tool.
5. Charts + CSV/PNG export.
6. A/B swipe comparison.
7. GIF/MP4 timelapse export.
8. README + smoke test + end-to-end verification.

Stop and report (rather than improvising) if the OISST files turn out not to
be global grids, or if `mfa_env` lacks xarray/netCDF4/fastapi — list what's
missing and ask before creating a new environment.
