# SST Viewer

Interactive web map and report generator for **sea surface temperature (SST)**
around the Russian Far East (Sea of Okhotsk, Kamchatka, Primorye). It is built
for day-to-day coastal research work: browse satellite SST fields, pull time
series for exact coastal points, and turn them into PDF trend reports.

## The idea

Satellite SST products (NOAA OISST, GHRSST MUR) are free but awkward to use:
each lives on its own ERDDAP server, answers slowly, and returns raw NetCDF.
Answering a simple question such as *"how has early-summer water temperature
off these five capes changed since 2000?"* usually means scripts, manual
downloads and a separate R analysis. SST Viewer puts the whole loop in one
browser tab: **look at the map → pick points → download → get a report.**

## Current state

A working single-user app that runs locally (FastAPI + Leaflet, R/Quarto for reports).

- Three datasets: a local OISST archive (fully offline), OISST v2.1 global and
  MUR 0.01° from NOAA ERDDAP, fetched on demand and cached forever.
- Map with timelapse, GIF export, A/B swipe compare, measuring, saved areas and
  point/area charts; EN/RU interface.
- Batch download for any list of coordinates with flexible date/year builders,
  producing one CSV plus per-point PDF trend reports and a multi-point comparison PDF.
- Live source-health indicators, nightly cache warming, and batch verification scripts.
- Smoke, cache, health and tile-alignment tests.
- A hardened public-hosting setup (accounts, Docker, deploy runbook) was built and
  then rolled back. For now the app runs locally only.

## Ideal state

- Hosted online for a small research group, with accounts, per-user saved areas
  and a shared report library.
- More datasets (chlorophyll, sea ice, wind) on the same map and in the same reports.
- Scheduled reports: pick points once, get an updated comparison PDF every season.
- Automatic detection and flagging of upwelling events and marine heatwaves along the coast.


## Run

Easiest: `powershell -File scripts\launch.ps1` — starts the server in the background if
it isn't already running, and opens the browser.

Manual:

```
conda run -n mfa_env python -m uvicorn app:app --port 8000
```

from this directory, then open **http://localhost:8000** (needs internet for
basemap tiles + Leaflet/Chart.js CDN; remote datasets need internet on first
use, everything cached works offline).

Smoke test: `conda run -n mfa_env python test_smoke.py` (remote checks are
skipped automatically when offline).

## Datasets (selector in the Layer section)

| id | source | coverage |
|---|---|---|
| `oisst_local` | local .nc files in `data/oisst_may20_july1/` | 2000–2025, May 20 – Jul 1 only; default, fully offline |
| `oisst_remote` | NOAA ERDDAP, OISST v2.1 0.25° (`ncdcOisst21Agg_LonPM180`) | Sept 1981 – present, all days, global |
| `mur_okhotsk` | NOAA ERDDAP, GHRSST MUR 0.01° (`jplMURSST41`) | mid-2002 – present, fixed box 135–165°E 40–65°N |

`data/oisst_may20_july1/` is self-contained inside `sst_viewer/` — no
cross-folder dependency on the rest of the project. Remote fields download on
demand (a MUR date is ~120 MB / ~1 min) and are cached forever in
`cache/fields/<dataset>/` as float32 .npy — a cached field is never
re-downloaded, and `oisst_remote` reads the local file instead of downloading
when one exists for that date; browsing/timelapse/GIF export all fetch
whatever's missing on the fly (no separate manual "load" step). ERDDAP errors
(down server, out-of-range dates) surface in the UI; everything already
cached keeps working.

## What it does

- **UI:** named control sections with (?) hover help, a status bar (dataset ·
  variable · date) at the top of the map, and an EN/RU language switch
  (top-right of the sidebar, persisted in localStorage).
- **Gridded layer:** dataset selector (above), variables per dataset
  (OISST: SST / anomaly / analysis error; MUR: SST / sea-ice fraction).
- **Cell classes:** color ramp = valid values; pale blue-white = ice
  (concentration/fraction ≥ 15%); gray = ocean cell with no data; land
  transparent (basemap shows through; for MUR, masked cells = land).
- **Base map:** Esri satellite only (no picker). Carto "Light" now needs a
  paid API key and Esri's ocean bathymetry has no real tiles over the NW
  Pacific past ~z11, so both were dropped.
- **Control island:** the pill above the map holds the live dataset, variable
  and date pickers, plus the status line (loading, snapped-date and error
  messages) so they are visible from every tab.
- **Color scale:** auto (2–98 percentile per frame) or fixed min/max.
  Timelapse and A/B compare force fixed scale so frames are comparable.
- **Timelapse:** every frame is fetched before playback starts (progress bar
  while it loads), then a scrubber tracks it and can be dragged to any frame,
  playing or stopped. fps, step-days snapping to available dates, and a "same
  day each year" mode that uses the Data tab's dates+years editor.
- **GIF export:** cropped to its own box (N/S/W/E in degrees), not to whatever
  the map happens to show — seed it from the view, draw it with the mouse, or
  recall any saved area, so a series of GIFs lines up. The box can be saved as
  a new area, updated in place, or deleted from the same tab. Rendered
  server-side with PIL; land is gray (no basemap) and each frame is stamped
  with its date.
- **A/B swipe compare:** two dates side by side with a draggable divider.
- **Measure:** click to add vertices, great-circle km; double-click/Esc ends.
- **Click any ocean pixel:** values popup (per-dataset variables) + "chart
  this point" (remote datasets fetch the whole series in one ERDDAP request).
- **Coordinates (Data tab):** paste arbitrary `lat, lon` coordinates (one per
  line) and Add — each coordinate shows as a labelled dot on the map (name,
  or `lat, lon` until named), the map reframes to fit them all, and each row
  gets its own date builder:
  add specific dates and/or date ranges (with a day step), optionally
  "repeat across years" (a year range with a step, or explicit
  non-consecutive years as chips) instead of retyping the same dates per
  year. Check the rows you want (select-all/deselect-all, or "copy these
  dates to checked rows" to broadcast one row's date config to the others),
  then **Download**: builds one combined CSV of every checked coordinate's
  resolved dates, and — if **Also generate PDF(s)** is checked — also renders
  one PDF report per checked coordinate as a background job (progress bar,
  per-point status, links appear as each finishes). Each report computes its
  anomaly locally (SST minus the mean SST for that calendar day across the
  fetched dates — the same method for every dataset, since none of them
  expose a directly comparable native anomaly field) and renders
  `reports/template.qmd` (the RProject3 `Tikhoye.qmd`-style trend analysis:
  raw SST/anomaly, year-overlaid daily SST, mean-yearly-SST trend + lm
  diagnostics, representative-day trends, daily trend-strength heatmap) via
  Quarto (~30–60 s/report; needs Quarto + R with
  ggplot2/dplyr/lubridate/broom, already installed). Output lands in
  `library/reports/` (PDFs) and `library/downloads/` (CSVs).
  **Also generate one comparison PDF** (greyed out until 2+ rows are
  checked) adds a single document for reading every point at once: a
  satellite locator map with numbered, colour-coded points (north to south),
  a colour-shaded point × year mean table, then per year a map strip beside
  the daily line chart (lines labelled by number at their ends) and a
  north-at-top heatmap of each point's difference from its own window mean,
  its rows joined to the dots by leader lines (`reports/compare.qmd`; the map
  is stitched from Esri World Imagery tiles at render time, so it needs
  internet). Both report templates open with a clickable table of contents.
- **Saved areas:** draw a point / rectangle / circle / polygon on the map
  (hand-rolled on Leaflet events, no plugin), name it, and the current
  dataset/variable/date/scale are stored with it in `areas.json`. Per area:
  Go to (restores the saved view), Snapshot PNG and GIF cropped to the area
  (saved under `library/<area_id>/`, listed with open/delete), Chart
  (spatial-mean series over the area's cells — polygon masking via
  matplotlib.path), Rename, Delete. `areas.json` + `library/` live outside
  `cache/`, so clearing the cache never touches user content.
- **Charts:** multiple series, x = date or day-of-year (one line per year),
  PNG and CSV export.

## Loading screen

A splash (viridis field, wordmark, progress bar, rotating tips) covers the
app while it boots, driven by the real startup steps: first health sweep →
datasets → first map render → saved areas. It removes itself from the DOM
when done, so it can never trap a click.

The splash waits for the first health sweep to finish, so the status dots are
already green/red when the app appears — never grey. That works because the
**cold sweep is a different shape from every later one** (`health.py`):

- it probes *every* never-checked source in the first tick, instead of one
  remote per 30 s tick;
- it uses `FIRST_PROBE_TIMEOUT_S` (3 s) instead of `PROBE_TIMEOUT_S` (15 s).

Together those turn a ~30 s wait for the first verdict into ~6 s worst case
(3 s × the host's two DNS addresses; measured 6.05 s against the dead host).
It still costs only one request, because sources sharing a host are answered
by the first probe's passive observation. A false "down" from the short
timeout is re-checked at full timeout on the next tick rather than sitting on
the 60 s failure backoff.

`SPLASH_HEALTH_CAP_MS` (12 s, `static/app.js`) is only a safety net against a
pathological hang — reaching it means dots are still grey when the app opens,
which is the thing this design avoids.

Two other bits of work ride along with it:

- **PDF toolchain check.** Quarto's absence used to surface only at the *end*
  of a long batch fetch. It is now probed at startup and shown as its own
  chip, so a missing toolchain is visible before you queue an hour of work.
- **Remote date-axis prefetch.** After the splash lifts, the date axes for
  any source the probe just reported healthy are warmed in the background
  (fire-and-forget), so the first switch to MUR/ERDDAP is instant instead of
  a multi-second stall. Skipped entirely for sources that are down, so a dead
  host costs nothing.

## Source health

Three dots under the sidebar title, answering two different questions: the
**ERDDAP server** ("does it answer at all?", probed with `/erddap/version`)
and each **dataset** on it ("does its data actually come through?", probed
with its own time axis). A server can serve metadata in 0.1 s while every real
read hangs, and one dataset can be unloaded on a healthy server — one dot
could not say both. They lean on each other so the set still costs about one
request per tick: a dead server condemns its datasets with no further request,
and a dataset that returns data vouches for the server with none.

Green = reachable, amber = answering but slow (≥4 s), red = unreachable, grey
= not checked yet. Hover for latency, age, the last error, and which question
that dot answers; click to open the ERDDAP server's own status page. The local
file store and the PDF toolchain are not shown — they are installed or not.
`GET /api/health` still returns every source as JSON.

The dataset picker refuses a source the prober already calls down, instead of
parking the UI on a host that will not answer.

State comes from two places (`health.py`):

- **passively**, from every real request the app already makes — free, and
  it means a busy app barely probes at all;
- **actively**, from one daemon thread that probes **at most one remote
  source per 30 s tick**, and only if that source hasn't been seen in the
  last 60 s.

The rate budget is per **host**, not per dataset: both ERDDAP datasets live
on `upwell.pfeg.noaa.gov`, so probing them separately would double the
load on one server for no extra information. Worst case is therefore
**2 requests/minute to NOAA, never concurrent**, dropping to 4/hour once a
source starts failing (60 s → 2 → 5 → 10 → 15 min backoff, reset on
success). Adding more datasets on the same host does not raise that ceiling.
The probe reads **one value off the dataset's time axis**
(`.csv?time[0:1:0]`, a few dozen bytes). A `.das` would be cheaper, but ERDDAP
answers it from a metadata cache: in Sep 2026 PFEG returned `.das` in 0.1 s
while every real read timed out, so a `.das` probe would have shown all-green
against a dataset that could not serve a single value. The dots have to track
whether data flows, not whether the server process is alive.

## Notes / known limits

- Health status is *reachability*, and passive observations are host-level:
  an HTTP 404/500 for one dataset means the server answered, so it does not
  mark its neighbours down. Dataset-level truth comes from the active probe,
  i.e. within ~60 s.
- First "chart this point" on `oisst_local` takes ~10–30 s (reads one cell
  from all ~1100 NetCDF files); cached in memory afterwards. On the remote
  datasets it's one ERDDAP request (~seconds).
- Rendered overlay PNGs and downloaded fields cache in `cache/` (safe to
  delete anytime — saved areas/media are NOT in there).
- Overlay PNGs are resampled to Web Mercator rows server-side so they align
  with the basemap, onto a per-dataset lattice that gives every data row at
  least one pixel (so nothing is dropped and blocks keep the same size and
  place at every zoom). PNGs are capped at 24 Mpx total and 4096 px a side
  (Chrome silently resamples anything taller, which slides the blocks off
  the grid lines); past a cap the row oversampling is given back first, then
  the grid degrades by a whole number of cells per pixel, never a fractional
  resample.
  Full 0.01° resolution is kept in the cached fields for point queries.
- Full map-with-basemap PNG export isn't implemented; use a screenshot for a
  composed map image.
- Area subsets don't cross the antimeridian (the study region doesn't).

## Folder layout

`app.py`/`datasets.py`/`reports.py`/`health.py` + `static/` are the running app.
`data/` holds the local OISST archive (`oisst_may20_july1/`, moved in from
`RProject/` so the app has no cross-folder dependency) plus generated
coastal-points CSVs/TXTs (per-region offshore sample points, made by
`scripts/make_coast_points.py`). `scripts/` holds one-off tools: `make_coast_points.py`
(generates offshore sample points along a coastline) and `launch.ps1` (starts the server + opens the
browser). `reports/template.qmd` is the shared PDF report template. `cache/`
and `library/` (including `library/reports/` and `library/downloads/`) are
generated/user content (gitignored) — see above.
