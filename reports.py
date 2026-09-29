"""Batch downloads + PDF reports for arbitrary coordinates.

Fetches each point's series (for whatever exact dates the caller resolved
client-side), assembles one combined CSV, and optionally renders a PDF per
point (the shared reports/template.qmd -- the RProject3 Tikhoye.qmd-style
analysis) via Quarto. Runs as a background job so the UI can poll progress
instead of blocking on N x ~30-60s renders.

No dependency on any dataset's own anomaly field (only some sources have
one, and they use different climatology baselines) -- the anomaly is always
computed locally (SST minus the mean SST for that calendar day across
whatever dates were fetched), so the same template/logic runs for every
dataset.
"""
import io
import math
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import date
from pathlib import Path

import pandas as pd

import datasets as D

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "reports" / "template.qmd"
REPORTS_DIR = D.LIBRARY / "reports"
DOWNLOADS_DIR = D.LIBRARY / "downloads"
SERIES_DIR = D.LIBRARY / "series"   # per-point raw series, reused across runs
REPORTS_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)
SERIES_DIR.mkdir(exist_ok=True)

_QUARTO_CANDIDATES = (
    r"C:\Program Files\RStudio\resources\app\bin\quarto\bin\quarto.exe",
    "quarto",
)
_SAFE = re.compile(r"[^\w\-]+")
_REMOTE_PACING_S = 0.3  # be gentle on ERDDAP across many sequential points


def _quarto_exe():
    for c in _QUARTO_CANDIDATES:
        if c == "quarto" or Path(c).exists():
            if c == "quarto" and shutil.which("quarto") is None:
                continue
            return c
    raise RuntimeError("quarto executable not found (checked RStudio bundle + PATH)")


def _fmt_coords(lat, lon):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f}\u00b0{ns} {abs(lon):.4f}\u00b0{ew}"


_MAX_GAP_DAYS = 31  # dates further apart than this get their own request


def _date_runs(dates, max_gap=_MAX_GAP_DAYS):
    """Group sorted ISO dates into runs, splitting wherever the gap between
    consecutive dates exceeds max_gap days.

    ERDDAP can only be asked for a *contiguous* time span, so fetching
    min(dates)..max(dates) in one shot is catastrophic for the common "same
    few days every year" request: 5 days x 24 years spans 8420 daily
    timesteps on the wire to return 120 values, which is slow enough to trip
    the socket timeout on its own. Splitting on the yearly gaps turns that
    into 24 requests of ~20 timesteps. A genuinely contiguous range still
    comes back as a single run, i.e. one request, exactly as before."""
    runs = [[dates[0]]]
    for d in dates[1:]:
        prev = date.fromisoformat(runs[-1][-1])
        if (date.fromisoformat(d) - prev).days > max_gap:
            runs.append([])
        runs[-1].append(d)
    return runs


def _fetch_raw_series(ds, lat, lon, var, wanted):
    """Network step only: raw (date, value) rows for `wanted`, nothing derived."""
    series = []
    for run in _date_runs(sorted(wanted)):
        series.extend(ds.point_series(lat, lon, var, run[0], run[-1]))
    df = pd.DataFrame(series)
    if df.empty:
        return pd.DataFrame(columns=["date", "value"])
    # runs never overlap, but point_series snaps each endpoint to the nearest
    # available date, which can pull one row into two adjacent runs
    return df.drop_duplicates(subset="date")[["date", "value"]]


def _derive_frame(raw, wanted):
    """Pure step: keep `wanted`, add md/year/local anomaly. No network, no I/O.

    The anomaly is relative to the dates in THIS request, so it is always
    derived here rather than cached alongside the raw values."""
    df = raw[raw["date"].isin(set(wanted))].dropna(subset=["value"]).copy()
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    df["sst_celsius"] = df["value"]
    df["md"] = df["date"].dt.strftime("%m-%d")
    df["sst_anomaly"] = df["sst_celsius"] - df.groupby("md")["sst_celsius"].transform("mean")
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def fetch_point_frame(ds, lat, lon, var, wanted_dates):
    """Uncached fetch + derive for one point (kept for direct/scripted use)."""
    wanted = sorted(set(wanted_dates))
    if not wanted:
        raise ValueError("no dates requested")
    return _derive_frame(_fetch_raw_series(ds, lat, lon, var, wanted), wanted)


def _series_path(dataset_id, lat, lon, var):
    stem = _SAFE.sub("_", f"{dataset_id}_{lat:.4f}_{lon:.4f}_{var}").strip("_")
    return SERIES_DIR / f"{stem}.csv"


def point_frame_cached(ds, dataset_id, lat, lon, var, wanted_dates, refresh=False):
    """(frame, from_cache) for one point, reusing a per-point on-disk series.

    Splits the pipeline in two: the raw series for a coordinate is downloaded
    once and kept under library/series/, so re-running a report -- or asking
    for a subset of dates already held -- renders the PDF with no network I/O.
    Only dates genuinely absent from the cache are requested.

    Dates that come back with nothing are stored as blank rows on purpose: a
    land pixel or a gap in the source would otherwise be re-requested on
    every future run, which is the slow path this cache exists to avoid."""
    wanted = sorted(set(wanted_dates))
    if not wanted:
        raise ValueError("no dates requested")
    path = _series_path(dataset_id, lat, lon, var)
    have = pd.DataFrame(columns=["date", "value"])
    if path.exists() and not refresh:
        try:
            have = pd.read_csv(path, dtype={"date": str})
        except Exception:
            have = pd.DataFrame(columns=["date", "value"])  # unreadable -> refetch

    known = set(have["date"]) if not have.empty else set()
    missing = [d for d in wanted if d not in known]
    if missing:
        fresh = _fetch_raw_series(ds, lat, lon, var, missing)
        got = set(fresh["date"]) if not fresh.empty else set()
        blanks = pd.DataFrame({"date": [d for d in missing if d not in got],
                               "value": [None] * len(set(missing) - got)})
        have = (pd.concat([f for f in (have, fresh, blanks) if not f.empty],
                          ignore_index=True)
                  .drop_duplicates(subset="date").sort_values("date"))
        SERIES_DIR.mkdir(exist_ok=True)
        have.to_csv(path, index=False)
    return _derive_frame(have, wanted), not missing


def _describe_dates(dates):
    """Human-readable date-range summary for the PDF subtitle -- distinguishes
    a plain range within one year from a day-range repeated across years, so
    the header reflects what was actually asked for."""
    ds = sorted(dates)
    n = len(ds)
    years = sorted({d[:4] for d in ds})
    if len(years) == 1:
        return f"{ds[0]} to {ds[-1]} ({n} date{'s' if n != 1 else ''}, {years[0]})"
    mds = sorted({d[5:] for d in ds})
    if len(mds) <= 15:
        return f"{mds[0]} to {mds[-1]} (month-day) · {years[0]}–{years[-1]} ({n} dates)"
    return f"{ds[0]} to {ds[-1]} ({n} dates, {years[0]}–{years[-1]})"


_CHUNK_PROGRESS_RE = re.compile(r"^(\d+)/(\d+)\b")
_RENDER_TIMEOUT_S = 180


def _quarto_render(template, params, tmpdir, on_progress=None):
    """Copy `template` into tmpdir, render it with -P params, return the PDF.

    Quarto prints its own chunk-execution progress to the console as it
    knits ("6/26", "7/26 [group1]", ...) -- stream that live instead of
    capture_output+wait, and forward each fraction to on_progress(0..1) so
    callers get a genuine, non-guessed render progress signal."""
    qmd = tmpdir / template.name
    shutil.copy(template, qmd)
    args = [_quarto_exe(), "render", str(qmd)]
    for k, v in params.items():
        args += ["-P", f"{k}:{v}"]
    proc = subprocess.Popen(
        args, cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    timed_out = threading.Event()
    watchdog = threading.Timer(_RENDER_TIMEOUT_S, lambda: (timed_out.set(), proc.kill()))
    watchdog.start()
    output = []
    try:
        for line in proc.stdout:
            output.append(line)
            m = _CHUNK_PROGRESS_RE.match(line.strip())
            if m and on_progress:
                done, total = int(m.group(1)), int(m.group(2))
                if total:
                    on_progress(min(1.0, done / total))
        proc.wait()
    finally:
        watchdog.cancel()

    if timed_out.is_set():
        raise RuntimeError(f"quarto render timed out after {_RENDER_TIMEOUT_S}s")
    rendered = qmd.with_suffix(".pdf")
    if proc.returncode != 0 or not rendered.exists():
        raise RuntimeError(f"quarto render failed:\n{''.join(output)[-4000:]}")
    if on_progress:
        on_progress(1.0)
    return rendered


def render_pdf(df, lat, lon, label, ds_name, dataset_id, date_summary, on_progress=None):
    """Render the shared template for one point's already-fetched frame.
    Returns the final Path under library/reports/."""
    tmpdir = Path(tempfile.mkdtemp(prefix="sst_report_"))
    try:
        csv_path = tmpdir / "data.csv"
        df[["date", "sst_celsius", "sst_anomaly"]].to_csv(csv_path, index=False)
        rendered = _quarto_render(TEMPLATE, {
            "title": f"SST Analysis For {label}",
            "subtitle": f"{ds_name} \u00b7 {date_summary}",
            "coords": _fmt_coords(lat, lon), "source": csv_path,
        }, tmpdir, on_progress)

        safe_name = _SAFE.sub("_", label).strip("_") or "point"
        dest = REPORTS_DIR / f"{safe_name}_{dataset_id}_{uuid.uuid4().hex[:6]}.pdf"
        shutil.move(str(rendered), str(dest))
        return dest
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------- comparison report
# One PDF for the whole batch: a satellite locator map with numbered,
# colour-coded points, a colour-shaded point x year mean table, and per-year
# line charts drawn in the same colours -- so the map is the charts' legend.

COMPARE_TEMPLATE = HERE / "reports" / "compare.qmd"
_TILE_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
             "World_Imagery/MapServer/tile/{z}/{y}/{x}")
# Okabe-Ito, reordered so the first few stay distinct on satellite imagery
# ponytail: 8 colours, then they repeat -- add shapes if batches outgrow it
PALETTE = ["#D55E00", "#56B4E9", "#E69F00", "#009E73", "#CC79A7",
           "#0072B2", "#F0E442", "#000000"]
_MAP_MAX_PX = 1000


def _merc_px(lat, lon, z):
    """Web Mercator world pixel coordinates at zoom z (256 px tiles)."""
    n = 256 * 2 ** z
    y = math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat)))
    return (lon + 180) / 360 * n, (1 - y / math.pi) / 2 * n


def locator_map(points, out_dir):
    """points: [(n, label, lat, lon, colour)]. Stitches Esri World Imagery
    tiles around the points and writes, into out_dir:
      map.png    -- numbered dots + names, the report's opening map
      strip.rgb  -- the same view with numbers only, as raw RGB bytes (base R
                    has no PNG reader), for the per-year map/chart figures
    Returns (strip_w, strip_h, {n: (x, y)}) -- dot pixel positions in the
    strip, which the heatmap uses to line its rows up with the dots."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        num_font = ImageFont.truetype("arialbd.ttf", 18)
        lbl_font = ImageFont.truetype("arialbd.ttf", 17)
        small = ImageFont.truetype("arial.ttf", 12)
        num_small = ImageFont.truetype("arialbd.ttf", 12)
    except OSError:
        num_font = lbl_font = small = num_small = ImageFont.load_default()
    r = 13

    lats = [p[2] for p in points]
    lons = [p[3] for p in points]
    pad_lat = max((max(lats) - min(lats)) * 0.15, 0.1)
    pad_lon = max((max(lons) - min(lons)) * 0.15, 0.1)
    s, n = min(lats) - pad_lat, max(lats) + pad_lat
    w, e = min(lons) - pad_lon, max(lons) + pad_lon

    # deepest zoom whose crop still fits the size budget
    for z in range(13, 2, -1):
        x0, y0 = _merc_px(n, w, z)
        x1, y1 = _merc_px(s, e, z)
        if max(x1 - x0, y1 - y0) <= _MAP_MAX_PX:
            break
    # a north-south chain of capes is a thin strip: widen it so the reader
    # gets enough coast on either side to recognise where it is
    min_w = (y1 - y0) * 0.6
    if x1 - x0 < min_w:
        cx = (x0 + x1) / 2
        x0, x1 = cx - min_w / 2, cx + min_w / 2

    tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), "#20303a")
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            req = urllib.request.Request(_TILE_URL.format(z=z, y=ty, x=tx),
                                         headers={"User-Agent": "sst_viewer/2"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                tile = Image.open(io.BytesIO(resp.read())).convert("RGB")
            mosaic.paste(tile, ((tx - tx0) * 256, (ty - ty0) * 256))
    ox, oy = tx0 * 256, ty0 * 256
    base = mosaic.crop((int(x0 - ox), int(y0 - oy), int(x1 - ox), int(y1 - oy)))
    dots = {num: (_merc_px(lat, lon, z)[0] - x0, _merc_px(lat, lon, z)[1] - y0)
            for num, _, lat, lon, _ in points}

    text_col = lambda c: "black" if c in ("#F0E442", "#E69F00", "#56B4E9") else "white"

    def draw(img, scale=1.0):
        """Numbered markers; returns where each marker was drawn."""
        d = ImageDraw.Draw(img)
        # the strip is downscaled, but its dots must stay big enough to read
        rr, nf = (r, num_font) if scale == 1.0 else (9, num_small)
        true = {k: (x * scale, y * scale) for k, (x, y) in dots.items()}
        marks = _spread(true, 2 * rr + 3)
        for num, _, _, _, colour in points:
            (tx, ty), (mx, my) = true[num], marks[num]
            if math.hypot(mx - tx, my - ty) > 1.5:
                # marker pushed off its point: a leader back to the true spot
                d.line((tx, ty, mx, my), fill="white", width=2)
                d.ellipse((tx - 3, ty - 3, tx + 3, ty + 3), fill=colour, outline="white")
        for num, _, _, _, colour in points:
            mx, my = marks[num]
            d.ellipse((mx - rr, my - rr, mx + rr, my + rr), fill=colour,
                      outline="white", width=2)
            d.text((mx, my), str(num), font=nf, fill=text_col(colour), anchor="mm")
        d.text((img.width - 6, img.height - 4), "Imagery: Esri World Imagery",
               font=small, fill="white", anchor="rs", stroke_width=2, stroke_fill="black")
        return marks

    # the report's opening map: numbered markers, names in a legend panel on
    # the right -- names drawn on the imagery collide as soon as points are
    # closer together than a label is long
    named = base.copy()
    draw(named)
    row_h, pad = 30, 16
    legend_w = int(max(lbl_font.getlength(p[1]) for p in points)) + 3 * pad + 2 * r
    canvas = Image.new("RGB", (named.width + legend_w, max(named.height, 60 + row_h * len(points))), "white")
    canvas.paste(named, (0, 0))
    d = ImageDraw.Draw(canvas)
    lx = named.width + pad
    d.text((lx, pad), "Points, north to south", font=lbl_font, fill="#333333", anchor="lt")
    for i, (num, label, _, _, colour) in enumerate(points):
        cy = pad + 40 + i * row_h
        d.ellipse((lx, cy - r, lx + 2 * r, cy + r), fill=colour, outline="#555555", width=1)
        d.text((lx + r, cy), str(num), font=num_font, fill=text_col(colour), anchor="mm")
        d.text((lx + 2 * r + pad // 2, cy), label, font=lbl_font, fill="#222222", anchor="lm")
    canvas.save(out_dir / "map.png")

    # the strip: numbers only (the charts label lines by number), and small --
    # it is read by R byte by byte
    scale = min(1.0, 420 / base.height)
    strip = base.resize((max(1, round(base.width * scale)), max(1, round(base.height * scale))))
    marks = draw(strip, scale=scale)
    (out_dir / "strip.rgb").write_bytes(strip.tobytes())
    return strip.width, strip.height, marks


def _spread(pos, min_d, iters=60):
    """Push marker centres apart until no two are closer than min_d, so points
    a kilometre apart still show as separate, readable numbers. Returns
    {key: (x, y)}; markers that need no room stay exactly where they are."""
    pos = {k: [x, y] for k, (x, y) in pos.items()}
    keys = list(pos)
    for _ in range(iters):
        moved = False
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
                dist = math.hypot(dx, dy)
                if dist < min_d:
                    if dist < 1e-6:          # same spot: split them vertically
                        dx, dy, dist = 0.0, 1.0, 1.0
                    push = (min_d - dist) / 2 + 0.01
                    ux, uy = dx / dist, dy / dist
                    pos[a][0] -= ux * push; pos[a][1] -= uy * push
                    pos[b][0] += ux * push; pos[b][1] += uy * push
                    moved = True
        if not moved:
            break
    return {k: (x, y) for k, (x, y) in pos.items()}


def render_compare_pdf(rows, ds_name, dataset_id, date_summary, on_progress=None):
    """rows: DataFrame with lat, lon, label, date, value (the batch CSV).
    Needs >= 2 labels. Returns the final Path under library/reports/."""
    pts = (rows.groupby("label", sort=False)[["lat", "lon"]].first()
               .sort_values("lat", ascending=False).reset_index())  # north first
    if len(pts) < 2:
        raise ValueError("a comparison report needs at least 2 points")
    pts["n"] = range(1, len(pts) + 1)
    pts["colour"] = [PALETTE[i % len(PALETTE)] for i in range(len(pts))]

    tmpdir = Path(tempfile.mkdtemp(prefix="sst_compare_"))
    try:
        sw, sh, dots = locator_map(
            list(pts[["n", "label", "lat", "lon", "colour"]].itertuples(index=False)),
            tmpdir)
        pts["px"] = [dots[k][0] for k in pts["n"]]
        pts["py"] = [dots[k][1] for k in pts["n"]]
        pts[["n", "label", "colour", "px", "py"]].to_csv(tmpdir / "points.csv", index=False)
        csv_path = tmpdir / "data.csv"
        rows.merge(pts[["label", "n", "colour"]], on="label")[
            ["n", "label", "colour", "date", "value"]].to_csv(csv_path, index=False)
        rendered = _quarto_render(COMPARE_TEMPLATE, {
            "title": f"SST Comparison, {len(pts)} Points",
            "subtitle": f"{ds_name} \u00b7 {date_summary}",
            "source": csv_path, "map": tmpdir / "map.png",
            "points": tmpdir / "points.csv", "strip": tmpdir / "strip.rgb",
            "strip_w": sw, "strip_h": sh,
        }, tmpdir, on_progress)
        dest = REPORTS_DIR / f"comparison_{len(pts)}pts_{dataset_id}_{uuid.uuid4().hex[:6]}.pdf"
        shutil.move(str(rendered), str(dest))
        return dest
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------------ batch jobs

JOBS = {}  # id -> status dict; single-user app, plain dict + daemon thread


def start_batch_job(dataset_id, points, generate_pdf, refresh_data=False,
                    generate_compare=False):
    """points: [{"lat":, "lon":, "label":, "dates": [iso, ...]}, ...].
    Returns a job id; progress/results poll via JOBS[job_id].

    generate_compare adds one comparison PDF over every point that returned
    data (needs >= 2 of them; otherwise it is silently not attempted).

    Data fetch and PDF render are separate steps: each point's raw series is
    cached on disk, so a second run over the same coordinates and dates skips
    straight to rendering. Pass refresh_data=True to force a re-download."""
    ds = D.get_dataset(dataset_id)
    var = next(iter(ds.variables))
    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "state": "running", "total": len(points), "done": 0,
        "csv_url": None,
        "compare_state": None, "compare_url": None, "compare_error": None,
        "points": [{"lat": p["lat"], "lon": p["lon"], "label": p["label"],
                    "status": "pending", "stage": "queued", "render_frac": 0.0,
                    "from_cache": False, "pdf_url": None, "error": None}
                   for p in points],
    }
    JOBS[job_id] = job

    def worker():
        rows = []
        unreachable = None  # first transport-level failure aborts the rest
        for i, p in enumerate(points):
            entry = job["points"][i]
            if unreachable:
                # re-proving a dead host costs 3 retries x up to 120 s PER
                # POINT, which is what makes a batch look hung rather than
                # failed. One point is enough evidence.
                entry["status"] = "error"
                entry["stage"] = "error"
                entry["error"] = f"skipped: source unreachable ({unreachable})"
                job["done"] += 1
                continue
            try:
                entry["stage"] = "fetching"
                df, from_cache = point_frame_cached(
                    ds, dataset_id, p["lat"], p["lon"], var, p["dates"],
                    refresh=refresh_data)
                entry["from_cache"] = from_cache
                if df is None:
                    raise ValueError("no data for these dates")
                for _, r in df.iterrows():
                    rows.append([p["lat"], p["lon"], p["label"], r["date"], r["sst_celsius"]])
                if generate_pdf:
                    entry["stage"] = "rendering"
                    pdf = render_pdf(df, p["lat"], p["lon"], p["label"], ds.name,
                                     dataset_id, _describe_dates(p["dates"]),
                                     on_progress=lambda f: entry.__setitem__("render_frac", f))
                    entry["pdf_url"] = f"/library/reports/{pdf.name}"
                entry["status"] = "done"
                entry["stage"] = "done"
            except Exception as e:
                # only transport failures condemn the whole batch -- "no data
                # for these dates" is specific to this point
                if isinstance(e, D.RemoteError) and "network error" in str(e):
                    unreachable = str(e)[:120]
                entry["status"] = "error"
                entry["stage"] = "error"
                entry["error"] = str(e)[:300]
            job["done"] += 1
            # every dataset is remote now (oisst_local is gone), so the pacing
            # delay always applies -- only a cache hit skips it, since that
            # point never touched the network
            if i < len(points) - 1 and not entry["from_cache"]:
                time.sleep(_REMOTE_PACING_S)

        if rows:
            csv_path = DOWNLOADS_DIR / f"sst_batch_{job_id}.csv"
            frame = pd.DataFrame(rows, columns=["lat", "lon", "label", "date", "value"])
            frame.to_csv(csv_path, index=False)
            job["csv_url"] = f"/library/downloads/{csv_path.name}"
            if generate_compare and frame["label"].nunique() >= 2:
                job["compare_state"] = "rendering"
                try:
                    pdf = render_compare_pdf(
                        frame, ds.name, dataset_id,
                        _describe_dates(sorted({d for p in points for d in p["dates"]})))
                    job["compare_url"] = f"/library/reports/{pdf.name}"
                    job["compare_state"] = "done"
                except Exception as e:
                    job["compare_state"] = "error"
                    job["compare_error"] = str(e)[:300]
        job["state"] = "done"

    threading.Thread(target=worker, daemon=True).start()
    return job_id
