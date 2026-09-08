# Implementation Prompt: sst_viewer v2 — remote datasets, bulk loading, saved areas

You are extending the working app in
`C:\Users\Georgii\OneDrive\Desktop\sst_data_analysis\sst_viewer\`
(FastAPI + `datasets.py` backend, plain Leaflet + Chart.js frontend, EN/RU
i18n, overlay PNGs Mercator-resampled server-side, disk cache in `cache/`).
Read `README.md` and `datasets.py` first; PROMPT.md describes v1. Preserve
all v1 behavior: variables, ice/no-data classes, fixed/auto color scale,
timelapse with GAP_DAYS, A/B swipe, measure tool, stations, charts, exports,
EN/RU switch (all new UI must be added to the I18N dict in `app.js`).

## Decisions already made (do not re-ask)

- Remote access goes through **NOAA ERDDAP griddap** (token-free). ESA CCI
  stays exactly as-is (local Mombetsu point series); the "long record" maps
  come from OISST, which ERDDAP serves back to Sept 1981.
- Bulk download is **explicit only**: a "Load range" action with a progress
  bar. No auto-download at startup; app startup stays instant.
- MUR 1 km gridded maps are limited to the **fixed Okhotsk study box
  135–165°E, 40–65°N**.
- Saving an area stores **geometry + current view settings**; snapshots/GIFs
  are generated **on demand** from the saved-areas panel, not at save time.

## Part 1 — Dataset registry with remote sources

Refactor `datasets.py` so every dataset implements one small interface
(plain dict or class, no plugin framework):
`id, name, resolution_label, date_range(), variables, bounds (None=global),
grid(date, var) -> 2D array + geo bounds, point_series(lat, lon, var, start, end)`.

Datasets to expose in a **dataset selector** (new UI in the Layer section,
shown in the status bar and legend):

| id | source | coverage | notes |
|---|---|---|---|
| `oisst_local` | existing local .nc files | 2000–2025, May 20 – Jul 1 | current behavior, works offline, keep as default |
| `oisst_remote` | ERDDAP, NOAA OISST v2.1 0.25° | Sept 1981 – present, **all calendar days**, global | vars sst/anom/err/ice as now |
| `mur_okhotsk` | ERDDAP, GHRSST MUR 0.01° | mid-2002 – present, Okhotsk box only | vars analysed_sst + sea-ice fraction; ice class from `sea_ice_fraction >= 0.15`; no-data where masked |

ERDDAP specifics (verify at implementation time with WebFetch — dataset ids
and URL grammar must be confirmed against the live server, not assumed):

- Servers: `https://coastwatch.pfeg.noaa.gov/erddap/` and/or
  `https://www.ncei.noaa.gov/erddap/` (OISST aggregation, e.g.
  `ncdcOisst21Agg_LonPM180`; MUR: `jplMURSST41`).
- One date's field: `griddap/<id>.nc?<var>[(TIME)][(lat0):(lat1)][(lon0):(lon1)]`.
- One point's full time series in ONE request:
  `<var>[(t0):(t1)][(lat)][(lat)]...` — use this for charts; never loop
  per-date requests for a series.
- Respect ERDDAP failure modes: 404 for out-of-range time (snap to the
  dataset's actual time axis, which you can read once from
  `griddap/<id>.json?time`), HTTP 5xx/timeouts → clear error to the UI, and
  the app must keep working with whatever is cached.

Caching: fetched fields go to `cache/fields/<dataset>/<date>_<var>.npy`
(float32, plus a tiny .json sidecar with bounds/shape) — rendered PNGs stay
in the existing PNG cache keyed by dataset. A cached field is never
re-downloaded. `oisst_local` remains the fast path; `oisst_remote` should
check whether the local file for that date exists and read it instead of
downloading (same grid).

MUR rendering: the Okhotsk box at 0.01° is ~2500×3000 cells. Downsample to
max ~1500 px on the long side for the overlay PNG (keep full resolution in
the cached field for point queries). The overlay bounds are the box, not the
world — the frontend must use per-dataset bounds for the ImageOverlay
(worldcopies still apply). Outside the box the basemap simply shows.

Point series when both datasets cover a point: the series API takes the
dataset id explicitly; the click-popup charts use the currently selected
dataset. Station "high-res series" buttons keep using the local CSVs.

## Part 2 — "Load range" bulk download

- New section in the sidebar: date range (+ the current GAP_DAYS /
  same-day-each-year settings), an estimate line ("N fields, ~X MB"), a
  Load button, a progress bar with cancel.
- Backend: a job endpoint (`POST /api/load_range`, `GET /api/load_status?id=`,
  simple polling — no websockets) that downloads the needed fields
  sequentially into the cache and pre-renders overlay PNGs at the current
  scale. Sequential is fine; add a short per-request timeout and continue past
  individual failures, reporting them in the final status.
- After a completed load, browsing/timelapse in that range must be instant
  and work offline.
- Loading a range you mostly have already should skip cached fields (report
  "42 cached / 8 downloaded").

## Part 3 — Saved areas library

Drawing tools (hand-rolled on Leaflet events like the v1 measure tool — do
NOT add Leaflet.draw, it is unmaintained):

- **Point**, **rectangle** (drag), **circle** (click center, drag radius),
  **polygon** (click vertices, double-click to close).
- After drawing, a small save dialog: name (required), the current
  dataset/variable/date/scale are recorded automatically.

Storage: `areas.json` next to `stations.json`, managed by the backend
(`GET/POST/DELETE /api/areas`). Media files go to `library/<area_id>/` and
are listed by the API. Both are gitignored, survive restarts, and live
outside `cache/` (deleting cache must never delete user content).

Panel (new collapsible panel or sidebar section, i18n'd):

- List of saved areas: name, shape icon, dataset/var/date it was saved with.
- Actions per area: **Go to** (fly to the area AND restore the saved
  dataset/variable/date/scale), **Snapshot PNG** (server composes the overlay
  cropped to the area's bbox for the current date), **GIF** (uses the current
  timelapse settings, cropped to the area's bbox), **Chart** (spatial-mean
  series of the variable over the area's cells — implement a mean-over-
  geometry reduction in the backend; for a point this is just the point
  series), **Rename**, **Delete** (confirm).
- Media list per area: generated snapshots/GIFs with open + delete.
- The area's outline is drawn on the map (toggleable, like stations).

Geometry → cell mask: rectangle/circle are trivial; for polygons use
matplotlib.path.Path.contains_points (already a dependency) — no shapely.

## Part 4 — plumbing and polish

- Status bar and legend show the active dataset's name + resolution.
- Timelapse/compare/GIF export must work with the selected dataset,
  including `mur_okhotsk` (GIF crop uses the dataset bounds intersected with
  the requested bbox).
- Add the new strings to BOTH `en` and `ru` in the I18N dict.
- Update README (run command unchanged) and the smoke test: add a check that
  builds each registry entry, reads one remote field **only if the network is
  reachable** (skip cleanly offline), verifies the fields cache round-trip,
  and exercises areas.json CRUD + a polygon mean series.
- requests/httpx: prefer stdlib `urllib` or existing deps; do not add a
  dependency for simple GETs unless retry/timeout handling genuinely needs it.

## Constraints (unchanged from v1)

- Windows 11, PowerShell 5.1; run everything with `conda run -n mfa_env`.
  Multi-line `python -c` doesn't work — write temp .py files.
- OneDrive data directories are read-only for the app; all writes go under
  `sst_viewer/` (cache/, library/, areas.json).
- Do not `winget install` or create new conda envs without asking.
- Verify end-to-end before finishing: start the server, switch to each
  dataset, load a small remote range (2–3 dates) with the progress endpoint,
  draw and save one of each shape, generate one snapshot and one GIF from
  the panel, chart one area mean. Report what you checked.

## Suggested order

1. Registry refactor with `oisst_local` only — v1 must still fully work.
2. `oisst_remote` (field fetch, time-axis read, cache, series-in-one-request).
3. `mur_okhotsk` (bbox fetch, downsampled overlay, per-dataset bounds in JS).
4. Dataset selector UI + status bar/legend + i18n.
5. Load-range job + progress UI.
6. Drawing tools + areas API + panel + media generation.
7. Smoke test, README, end-to-end verification.

Stop and ask (rather than improvising) if the ERDDAP dataset ids/time axes
don't match expectations, or if MUR request sizes make the Okhotsk box
impractical (then propose a smaller default box with the measured numbers).
