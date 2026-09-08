# Changelog

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
