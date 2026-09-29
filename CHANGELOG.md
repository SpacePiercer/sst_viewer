# Changelog

## 2026-09-29 — Overlay squares sat off the grid lines

**Overlay PNGs are now at most 4096 px a side** (`datasets.py`
`_merc_plan`, `MAX_OVERLAY_SIDE`; lattice version `m3` -> `m4`, so old PNGs
are no longer served). Chrome resamples any image taller than 4096 px before
drawing it: a 5° MUR tile at 52N was 500x6579 and whole-grid OISST
1440x11520, so their row edges landed on multiples of height/4096 instead of
where the grid overlay (correctly) draws them -- blocks up to ~6 screen px
off at z13, in both directions. The plan now drops row oversampling (8 -> 4
for one MUR tile, 8 -> 2 for OISST) and, only if still too tall, merges
cells, until both sides fit; the grid's lattice snapping follows it via
`X-Lattice`. The full 135-165E 40-65N study region now renders at 2 cells
per pixel (it is sub-pixel on screen at that extent anyway). Check:
`test_tiles.py` asserts no overlay side exceeds 4096.

## 2026-09-27 — Comparison PDF for multi-point batches; overlay PNG button gone

**One comparison PDF per batch** (`reports.py`, `reports/compare.qmd`,
`app.js?v=52`). Per-point PDFs made several capes hard to read side by side.
A new "Also generate one comparison PDF" checkbox (greyed out until 2+ rows
are checked) renders, after the per-point work, one document: a satellite
locator map (Esri World Imagery tiles stitched with PIL, numbered
colour-coded dots, north first), a colour-shaded point × year mean table,
then per year a map strip beside the daily line chart with lines labelled at
their ends, and a north-at-top heatmap of each point's difference from its
own window mean with leader lines from the dots. The strip reaches R as raw
RGB bytes (base R has no PNG reader, and nothing new was installed). A
single-calendar-day batch gets one year-on-x chart instead of empty panels.

**Comparison map: legend instead of on-map names** (`reports.py`
`locator_map`, `_spread`). Names drawn beside the dots collided as soon as two
points were closer than a label is long (a 2 km / 3 km pair off the same cape
is ~1 km apart). Names now sit in a "Points, north to south" legend panel to
the right of the map; markers that would overlap are pushed apart just enough
to read, with a leader line and a small dot at each true position. The same
spreading applies to the per-year map strip. Check in `test_smoke.py`.

**Table of contents in both templates** — clickable, subsections indented
3em under their section (`\DeclareTOCStyleEntry` in the header).

Quarto's streaming/timeout code moved out of `render_pdf` into
`_quarto_render` so both reports share it. `batch_download.py` takes
`"compare"` (defaults to on with PDFs, 2+ points) and prints a `CMP` line.

**"Download overlay PNG" removed** (`static/index.html`, `static/app.js`) —
not used; its handler and EN/RU strings went with it.

## 2026-09-10 — Control island, preloaded timelapse with a scrubber

**The status bar became the control island** (`static/index.html`,
`static/app.js`, `app.js?v=21`). Dataset, variable and the dd/mm/yyyy date
picker with ◀ ▶ now live in the pill above the map — the same elements, moved,
not copies, so nothing has to be kept in sync. The Map tab keeps overlay
opacity and the "snapped to nearest date" notice; `updateStatus()` no longer
renders text, it pushes state into those controls.

**`upwell.pfeg.noaa.gov` is not a fallback after all** (`datasets.py`, comment
only). It answers `.das` from its own metadata cache, which is what makes it
look alive, but it 302-redirects every *data* request to
`coastwatch.pfeg.noaa.gov` — so when the canonical host resets the TLS
handshake, as it is doing today and did for three weeks in Aug-Sep 2026, both
hostnames are down. The comment promising a drop-in swap was wrong and now
says so.

**Switching dataset or variable no longer looks broken.** Three separate
faults, all of them "nothing happens": the status line lived in the Map tab's
sidebar, so a slow or failed switch reported itself where nobody could see it;
a failed switch left `state.dataset` and the picker pointing at a dataset with
no dates, which then made every later variable switch fail silently too; and
asking a dark host for its date axis parked the UI for minutes while the
server retried. Now `#dateInfo` sits in the island (visible from every tab,
red on error, full text on hover), the picker is disabled while a date axis
loads and rolls back to the previous dataset if it fails, a dataset the health
prober already calls `down` is refused instantly with "that dataset's server
is not answering right now", and the fetch is capped at 120 s. The variable
list follows the dataset as it always should have -- MUR offers
`analysed_sst` / `sea_ice_fraction`, OISST `sst` / `anom` / `err`.

**Map furniture follows the open tab** (`syncMapLayers`): the GIF crop box is
drawn only on Timelapse, the saved-area outlines only on Areas (still gated by
that tab's "show on map" checkbox). Neither is left cluttering the data from
the other tabs.

**Island messages clear themselves.** Re-picking the dataset that is already
selected fires no `change` event, so the "server is not answering" warning had
nothing to clear it and sat there for good. Every writer now goes through
`islandMsg`, which also expires an error after 8 s.

**The date stamp on GIF frames is legible.** It was PIL's default bitmap font
in plain white -- ~11 px on a 500 px frame and invisible over pale water. Now
it scales with the frame (`width / 22`, min 14 px) in a bold system face with
a 2 px black outline.

**The GIF has its own crop box** (`static/index.html`, `static/app.js`).
It used to be cropped to whatever the map happened to show, so the same
animation came out a different shape every time and a stray pan put the wrong
piece of ocean in the file. The Timelapse tab now has four editable degree
fields (N/S/W/E), seeded from the current view, drawn on the map as a dashed
magenta rectangle, with "from map" and "zoom to box" to move between the two.
Any saved area can be recalled into the box from a dropdown -- its bounding
box is what the server crops to anyway (`D.area_bbox`), so circles and
polygons work as well as rectangles. "Draw on map" rubber-bands a rectangle
straight into the box (`startDraw("rect", "box")` -- the existing draw tool,
routed to the fields instead of to a new area), and the box can be saved as a
new area, updated in place, or deleted without leaving the tab. Updating in
place needed a real edit on the server: `PUT /api/areas/{id}` took only a
name, so it now takes `name` and/or `geom` (`api_area_rename` ->
`api_area_update`, covered in `test_smoke.py`). That makes a run of GIFs line
up frame for frame. Verified end to end: two different boxes render two
differently sized GIFs, and draw -> save -> reshape -> rename -> delete all
round-trip through `areas.json`.

**Three dots: the server, and each dataset separately** (`health.py`,
`static/app.js`). "Is ERDDAP answering at all" and "does this dataset's data
come through" are different questions and one dot could not say both — a
server can serve metadata in 0.1 s while every real read hangs (PFEG,
Sep 2026), and a single dataset can be unloaded on a healthy server. The new
`host` source probes `/erddap/version` (20 bytes); each dataset keeps probing
its own time axis. They lean on each other so the pair still costs ~1 request
per tick: a dead server condemns every dataset with no further request, and a
dataset that returns data vouches for the server with none. `/version` fires
only when the datasets stop vouching — exactly when the distinction matters.
A dataset marked down only by the server drops its failure backoff the moment
the server answers again, instead of staying red for up to 15 minutes. Hover
text now names which question each dot answers. Two new tests cover both
directions (`test_server_down_condemns_datasets_for_free`,
`test_dataset_down_on_a_live_server`).

**The health chips link to the server's own status page.** Each remote source
now carries a `notices` URL (`/erddap/status.html` on its host — load, uptime,
recent failures) and the chip renders as a link to it; the hover text says so.
It is the only outage feed that is about the machine this app actually talks
to. (NASA's `status.earthdata.nasa.gov/api/v1/notifications` is machine-
readable but covers the PO.DAAC side, not PFEG.)

**Coordinate dots are opaque, magenta, and actually on top.** They are now
`#ff10c8` with a 3 px white ring (`fillOpacity: 1`) — the one hue in neither
the SST ramp (viridis) nor the anomaly ramp (blue-white-red). The real reason
they looked washed out was the stacking order: the SST image overlay panes sat
at z-index 401/402, *above* Leaflet's own `overlayPane` (400), so an
85%-opaque raster was painted over every vector. The overlay panes moved to
250/260, between the basemap tiles and the vectors — which also un-buries the
saved-area outlines.

**Timelapse loads every frame before it plays.** `preloadFrames` fetches the
whole run three at a time behind `#tlProg` ("loading frames n/N"); playback
starts only when the bar fills, so it never stutters on the network. The frame
cache cap is raised to the run length for the duration (`frameCacheCap`), so
frame 1 is still cached when a long run wraps.

**A frame scrubber** (`#tlScrub`) tracks playback and is draggable at any time
— stopped or playing — to jump to a frame; playback continues from there.

**Play/Stop no longer races.** Clicking Play twice used to start a second
interval (the button only flipped to Pause *after* the date list arrived), and
stopping mid-fetch let the run start anyway. `tlGen` is now a cancel token:
`stopPlay()` bumps it, and any list fetch or preload still in flight sees the
mismatch and bails.

**"Same day each year" uses the Data tab's date/year editor.** The checkbox
swaps the from/to/step rows for the same structured dates + years form
(`dateYearFormHtml`, shared by both tabs through `rowAt`, one pseudo-row with
`ridx -1`), resolved by the same `parseDateSpec` and filtered to the dates the
dataset has. Both GIF endpoints take an explicit `dates=` list in that mode
(`/api/export/timelapse`, `/api/areas/{id}/gif`).

## 2026-09-10 — Basemap trimmed, health strip shows online sources, map fits added points

**Basemap is now Esri satellite only** (`static/app.js`, `app.js?v=20`), no
layer picker. Carto "Light" serves an *API KEY REQUIRED* watermark tile
without a paid key; Esri "Ocean depth" has no real bathymetry over the NW
Pacific past ~z11 (every cell comes back *Map data not yet available*), and
`maxNativeZoom` did not help because the tiles Esri does serve there are
already those placeholders. Both removed; `L.control.layers` went with them.

**The source-health dots show online datasets only.** The strip under the
title dropped *NOAA OISST v2.1 (local)* and *PDF reports* — a local file store
and a render toolchain are installed or not, and "reachable" says nothing
useful about them. Filtered to `kind === "remote"` client-side; `health.py`
still probes every source for the splash.

**Coordinate rows are dots on the map.** Each row draws a blue dot with a
permanent label above it — the row's name, or `lat, lon` until named
(`renderCoordLayer`, redrawn on every list change). Adding coordinates also
reframes the map: `addCoordsFromText` calls `fitCoords`, which `fitBounds`
over every row (25% margin, `maxZoom 12`) so a new point is always in view.

## 2026-09-08 — PDF links download; batch download as a skill

**PDF/CSV links now download instead of opening** (`static/app.js`,
`app.js?v=18`). Both used `target="_blank"`; the CSV only appeared to download
because Chrome cannot render CSV inline, while PDFs opened in the built-in
viewer. Both links now carry `download` (same-origin, so it is honoured) and
the PDF label changed from "PDF ready — open" to "⬇ PDF report", EN + RU.

**New `sst-download` skill** (`.claude/skills/sst-download/`) plus
`scripts/batch_download.py`: given coordinates, names and per-point calendar
days + years, it drives the app's own `/api/batch_job`, so the fetch path,
series cache and report template stay the single implementation. Defaults to
`mur_okhotsk` with PDFs on. `--dry-run` resolves and prints the dates without
starting the job; `MM-DD` values that do not exist in a year (02-29) are
skipped for that year with a warning.

The skill records the hazard found while doing this by hand: the Data tab
calls `prompt()` for unnamed points when PDFs are on and `alert()` on a bad
date row, and a browser dialog freezes the Chrome extension for the rest of
the session — so batch runs go through the API, not the UI.

## 2026-09-08 — Repointed to upwell + the health probe now reads real data

**Host.** `coastwatch.pfeg.noaa.gov` has been unreachable since 17 Aug (TCP
connect times out, TLS reset). `upwell.pfeg.noaa.gov` is the same PFEG ERDDAP
under a different hostname and is healthy — catalog 3.3 MB in 1.3 s, `.das` in
0.1 s. `datasets.ERDDAP` now points there.

**Probe.** Switching hosts alone would have made things *worse*: the health
probe was a `.das`, which ERDDAP answers from an in-memory metadata cache, so
all four dots would have gone green while every real fetch still failed. The
probe now reads one value off the dataset's time axis
(`.csv?time[0:1:0]`, a few dozen bytes, no grid touched). Measured on upwell at
the same moment: `.das` → **green in 0.2 s**, `time[0]` → **red**.

**Current state:** the two datasets we use (`jplMURSST41`,
`ncdcOisst21Agg_LonPM180`) still cannot serve data anywhere — even `time[0]`
fails — while *other* datasets on upwell return in 0.1 s. Both declare their
source as `(local files)`, so the file store backing them at PFEG is
unavailable. Nothing to fix on our side; the dots now report that honestly and
will go green by themselves when NOAA restores it.

**Also:** `index.html` is now served with `Cache-Control: no-cache`. It carries
the `app.js?v=N` cache-buster, so a cached copy pinned the browser to an old
`app.js` indefinitely — the day/month date fix was not reaching the page at all.
Versioned `app.js` still caches normally.

## 2026-09-07 — Dates keep what you type; server no longer exits with the browser

**Date items are day/month only** (`static/app.js`, `app.js?v=16`). Years now
always come from their own section, and the "repeat across years" checkbox is
gone — there is no longer a mode in which a date can be lost.

*The bug:* `dmyToIso()` returned `""` unless **all three** fields were filled,
so a dd/mm typed under a year-bearing triplet was never committed to state.
Ticking "repeat across years" re-rendered the row from that state and the
typed date vanished. Half-typed input is now committed as a partial ISO under
a fixed leap year (`2000-05-` etc., so 02-29 stays representable), and typing
in a date field refreshes only the row summary instead of re-rendering the
row — re-rendering mid-typing was the mechanism that erased it.

`rowSpecText()` always emits `md@years` now and requires both a complete
day/month on every item and at least one year. `row.repeatYears` is gone from
the model; `fmtYMD` became dead and was removed.

**Auto-shutdown reverted.** The server runs until stopped. Removed the
`pagehide`/`/api/closing` grace period, the idle watchdog and the 5 s client
heartbeat; `/api/ping` stays as a plain liveness probe. `os` and `time`
imports in `app.py` are no longer needed and were dropped.

Verified with no browser tab open: still up at t+20 s, t+60 s and t+170 s,
past both the old 15 s close-grace and the 150 s idle backstop.

**Not a bug:** the "first map click is swallowed" I reported was my own
automation — the browser window was resizing between screenshot and click, so
coordinates landed scaled by ~0.857. With stable geometry the first click
after a load opens the popup correctly.

`test_health.py` and `test_smoke.py` pass. `test_shutdown.py` covered only the
removed behaviour and was deleted.

## 2026-08-17 — Fast cold health sweep (dots are coloured before the app opens)

**Why:** the app appeared while the source dots were still grey. The splash
was hitting its 8 s cap because the first probe took 19–30 s.

**Root cause, not the cap:** the first sweep inherited the steady-state
policy — one remote probe per 30 s tick at `PROBE_TIMEOUT_S` = 15 s, doubled
to ~30 s because the host publishes both an A and an AAAA record. Raising the
cap would only have traded a grey strip for a 30 s splash.

**Fixed (`health.py`):** the cold sweep is now its own shape.

- Probes *every* never-checked source in tick 1 rather than one per tick.
  Still one request in practice — sources sharing a host are answered by the
  first probe's passive observation and skipped.
- Uses `FIRST_PROBE_TIMEOUT_S` = 3 s. Startup needs a fast verdict; steady
  state needs an accurate one, so later ticks keep the full 15 s.
- A cold-sweep failure schedules a full-timeout re-check on the next tick
  instead of sitting on the 60 s backoff, so a short-timeout false negative
  self-corrects in 30 s.
- Probe callables now take a timeout (`_run_probe(st, timeout)`).

`SPLASH_HEALTH_CAP_MS` 8 s → 12 s: now a safety net rather than the thing
that ends the wait.

**Measured against the still-down NOAA host:** first verdict 19–30 s → 6.05 s
(3 s × 2 DNS addresses). Polling from cold: both remotes grey at the instant
the port opens, all four resolved 0.46 s later. Three Chrome loads recorded
the chip classes at the exact moment the splash was removed — `["ok", "down",
"down", "ok"]`, **0 grey**, every time. No console errors.

Sweep semantics changed, so `test_probe_budget` was rewritten around steady
state and two new checks added: `test_cold_sweep` (tick 1 resolves every
source, at the short timeout) and `test_cold_sweep_shares_host` (a shared
host still costs one request at startup).

## 2026-08-17 — Loading screen (+ two jobs folded into it)

**Added — splash (`static/`, `app.js?v=14`):** pure-CSS viridis field (same
palette as the overlays, so it paints on the first frame with zero requests),
`SST Viewer` wordmark, progress bar and one of six rotating app tips, EN+RU.
Driven by the actual boot steps — health sweep → datasets → first map render
→ saved areas — and removed from the DOM on completion so it cannot trap a
click. A failing step is logged and skipped rather than stranding the user
behind the splash.

**Deliberate limit:** the splash waits for the first health sweep only up to
`SPLASH_HEALTH_CAP_MS` = 8 s. A probe against a dead host takes ~30 s and the
local dataset does not need NOAA at all, so gating on it fully would hold the
app hostage for nothing. Healthy sources resolve in ~1 s, so in the good case
the status strip is already complete when the splash lifts.

**Folded into the same startup window:**

- **PDF toolchain is now a health chip** (`health.py`, kind `tool`). Quarto's
  absence previously surfaced only at the *end* of a long batch fetch. It is
  probed at startup, costs one `Path.exists()`, and does not consume the
  remote request budget (`_tick` now splits on `kind != "remote"`).
- **Remote date-axis prefetch** after the splash lifts — fire-and-forget, and
  only for sources the probe just reported healthy, so the first switch to
  MUR/ERDDAP is instant instead of a multi-second stall and a dead host costs
  nothing.

**Verified live in Chrome:** cold start holds the splash with the bar
advancing (17% at 5 s) and tips rotating; warm start passes through in under
a second; splash gone from the DOM; four chips reading local `reachable`,
both ERDDAP `unreachable`, PDF reports `available`; no console errors.

## 2026-08-17 — Live source health + two batch-fetch fixes

**Why:** a batch run showed "⚠ network error" on the first point and left the
other three at "pending…" indefinitely, with no way to tell whether the fault
was the app, the network, or NOAA.

Measured from this machine: `coastwatch.pfeg.noaa.gov` resolves, but TCP
connect takes the full timeout and the TLS handshake is then reset
(WinError 10054) — on *every* request, including a single-pixel one-day
query. Other NOAA ERDDAP servers (`coastwatch.noaa.gov`, `polarwatch`,
`aoml`) answer in ~1.4 s. So the PFEG site is down; the app was correct to
report a network error, just unable to say so usefully.

**Added — `health.py` + `/api/health` + sidebar status dots:**

- Per-source state (ok / slow / down / unknown) with latency, age, error and
  next-check countdown; UI dots under the sidebar title, EN+RU tooltips,
  polled every 10 s from server memory (never triggers outbound traffic).
- Two signals: passive observation of every real request (via the new
  `datasets.OBSERVERS` hook in the HTTP layer) plus one daemon thread
  probing **at most one remote source per 30 s tick**.
- Rate budget is per-host, not per-dataset — both ERDDAP datasets share one
  server, so the ceiling is 2 req/min to NOAA, never concurrent, backing off
  60 s → 15 min while a source is failing. Probe is `.das`, not a data
  subset. Adding datasets on the same host does not raise the ceiling.
- A probe's own request also reaches the passive observer; the prober now
  claims the source first (`_PROBING`) so the failure isn't counted twice
  and a backoff step isn't skipped — while the *sibling* dataset on the same
  host still picks the signal up for free.

**Fixed — `reports.py`:**

- `fetch_point_frame` asked ERDDAP for `min(dates)..max(dates)` contiguously.
  For the common "same few days every year" request that is catastrophic:
  5 days × 24 years = 120 wanted values spanning **8420 daily timesteps** on
  the wire, slow enough to trip the socket timeout by itself. Now clusters
  the dates into runs (split on gaps > 31 days) and issues one request per
  run — 24 requests of ~20 timesteps. A genuinely contiguous range is still
  a single request.
- Batch worker now fails fast: a transport-level failure on one point marks
  the rest "skipped: source unreachable" instead of re-proving a dead host at
  3 retries × up to 120 s *per point*. Point-specific errors ("no data for
  these dates") still only fail that point.

**Also:** startup moved from the deprecated `@app.on_event` to a lifespan
handler.

**Verified:** `test_health.py` (new — date-run clustering, backoff, passive
observation, one-probe-per-tick budget, no double-count) passes; existing
`test_smoke.py` passes (remote leg skipped, NOAA offline); live server
confirmed local green at 3 ms and both remotes red with the real reset error,
backoff climbing 60 s → 293 s.

## 2026-08-16 — Data tab date fields: dd/mm/yyyy + mutually exclusive item types

**Why:** native `<input type="date">` fields displayed `mm/dd/yyyy` (Chromium
ties date-input display order to the browser/OS language, not to any
per-page or `lang`-attribute control — confirmed dead end after testing).
Requested a `dd/mm/yyyy` display everywhere, with a guarantee that day/month
are never transposed in the resulting API calls.

**Changed (`static/app.js`, `static/index.html`, `static/style.css` only —
no backend changes):**

- Replaced every native date input with a custom 3-field `dd/mm/yyyy` widget
  (`dmyTripletHtml()` / `dmyToIso()`):
  - The 4 static single-purpose fields (Map tab date picker, Timelapse
    from/to, A/B's Date B) keep a hidden `<input>` with a phantom `.value`
    property (`wireDMY()`), so all existing `.value` get/set and `.onchange`
    code kept working unchanged.
  - The Data tab's per-coordinate date-item rows (`+ date` / `+ date range`)
    got their own triplet rendering wired through the existing delegated
    change handler via `data-part="d"|"m"|"y"`.
- Fixed a bug found while testing: the delegated change handler used to
  rebuild the whole row on every keystroke, which wiped a partially-typed
  day/month before the other two sub-fields were filled in. Now it only
  commits and rerenders once a triplet is complete.
- When "repeat across years" is enabled for a coordinate row, the year
  sub-field is now hidden from the `+ date` / `+ date range` items entirely
  (day/month only) — years are set exclusively in the `+ year` /
  `+ year range` section below, instead of being present-but-ignored in two
  places at once.
- `+ date` and `+ date range` are now mutually exclusive per row (same for
  `+ year` / `+ year range`): once a row has an item of one kind, the button
  for the other kind is hidden until the list is emptied again.

**Verified live (browser):**
- Map tab: typed day=20/month=07 on a date outside the local dataset's
  range → composed to ISO `2025-07-20`, correctly triggered the existing
  "snapped to nearest available date" behavior (proves day/month order, not
  a new bug).
- Typed day=15/month=06/year=2020 → status bar and overlay updated to
  `2020-06-15`.
- A/B's Date B and Timelapse from/to fields matched their underlying state
  correctly (`15/06/2020`, `20/05/2025` → `01/07/2025`).
- Data tab: built a `20/05/2020 .. 25/06/2020` range → resolved to "37
  date(s): 2020-05-20 ... 2020-06-25"; ran a real Download and confirmed the
  downloaded CSV's rows actually run `2020-05-20` → `2020-06-25`.
- Enabled "repeat across years" on the same row → year fields disappeared
  from the date-range row (kept `20/05 .. 25/06`), added a `2003–2025` year
  range → resolved to "851 date(s): 2003-05-20 ... 2025-06-25" (37 days ×
  23 years).
- Confirmed `+ date`/`+ date range` and `+ year`/`+ year range` toggle
  visibility correctly as items are added/removed.

Bumped `app.js?v=10`. Smoke test (`test_smoke.py`) still passes — this was
a frontend-only change.
