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
import re
import shutil
import subprocess
import tempfile
import threading
import time
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


def render_pdf(df, lat, lon, label, ds_name, dataset_id, date_summary, on_progress=None):
    """Render the shared template for one point's already-fetched frame.
    Returns the final Path under library/reports/.

    Quarto prints its own chunk-execution progress to the console as it
    knits ("6/26", "7/26 [group1]", ...) -- stream that live instead of
    capture_output+wait, and forward each fraction to on_progress(0..1) so
    callers get a genuine, non-guessed render progress signal."""
    tmpdir = Path(tempfile.mkdtemp(prefix="sst_report_"))
    try:
        csv_path = tmpdir / "data.csv"
        df[["date", "sst_celsius", "sst_anomaly"]].to_csv(csv_path, index=False)

        qmd = tmpdir / "template.qmd"
        shutil.copy(TEMPLATE, qmd)

        title = f"SST Analysis For {label}"
        subtitle = f"{ds_name} \u00b7 {date_summary}"

        proc = subprocess.Popen(
            [_quarto_exe(), "render", str(qmd),
             "-P", f"title:{title}", "-P", f"subtitle:{subtitle}",
             "-P", f"coords:{_fmt_coords(lat, lon)}", "-P", f"source:{csv_path}"],
            cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
        rendered = tmpdir / "template.pdf"
        if proc.returncode != 0 or not rendered.exists():
            raise RuntimeError(f"quarto render failed:\n{''.join(output)[-4000:]}")
        if on_progress:
            on_progress(1.0)

        safe_name = _SAFE.sub("_", label).strip("_") or "point"
        dest = REPORTS_DIR / f"{safe_name}_{dataset_id}_{uuid.uuid4().hex[:6]}.pdf"
        shutil.move(str(rendered), str(dest))
        return dest
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ------------------------------------------------------------ batch jobs

JOBS = {}  # id -> status dict; single-user app, plain dict + daemon thread


def start_batch_job(dataset_id, points, generate_pdf, refresh_data=False):
    """points: [{"lat":, "lon":, "label":, "dates": [iso, ...]}, ...].
    Returns a job id; progress/results poll via JOBS[job_id].

    Data fetch and PDF render are separate steps: each point's raw series is
    cached on disk, so a second run over the same coordinates and dates skips
    straight to rendering. Pass refresh_data=True to force a re-download."""
    ds = D.get_dataset(dataset_id)
    var = next(iter(ds.variables))
    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "state": "running", "total": len(points), "done": 0,
        "csv_url": None,
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
            # no need to be polite to a server we never contacted
            if (dataset_id != "oisst_local" and i < len(points) - 1
                    and not entry["from_cache"]):
                time.sleep(_REMOTE_PACING_S)

        if rows:
            csv_path = DOWNLOADS_DIR / f"sst_batch_{job_id}.csv"
            pd.DataFrame(rows, columns=["lat", "lon", "label", "date", "value"]
                        ).to_csv(csv_path, index=False)
            job["csv_url"] = f"/library/downloads/{csv_path.name}"
        job["state"] = "done"

    threading.Thread(target=worker, daemon=True).start()
    return job_id
