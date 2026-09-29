"""sst_viewer web app.
Run: conda run -n mfa_env uvicorn app:app --port 8000
Then open http://localhost:8000
"""
import contextlib
import json
import re
import threading
import uuid
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import datasets as D
import health as H
import reports as R

HERE = Path(__file__).resolve().parent
AREAS_FILE = HERE / "areas.json"


@contextlib.asynccontextmanager
async def _lifespan(_app):
    H.start()  # daemon thread; nothing to tear down
    yield


app = FastAPI(title="sst_viewer", lifespan=_lifespan)


@app.middleware("http")
async def _revalidate_html(request, call_next):
    """index.html must never be served from cache without checking: it carries
    the `app.js?v=N` cache-buster, so a stale copy pins the browser to an old
    app.js forever. "no-cache" = revalidate, not "don't store" -- unchanged
    HTML still comes back as a cheap 304."""
    resp = await call_next(request)
    if resp.headers.get("content-type", "").startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/api/ping")
def api_ping():
    """Plain liveness probe. The server runs until it is stopped -- closing the
    browser does NOT shut it down."""
    return {"ok": True}


@app.get("/api/health")
def api_health():
    """Current state of every source. Served from memory -- polling this is
    free and never touches the network."""
    return H.snapshot()


def _ds(dsid):
    try:
        return D.get_dataset(dsid)
    except KeyError as e:
        raise HTTPException(404, str(e))


def _remote_guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except D.RemoteError as e:
        raise HTTPException(502, str(e))
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/datasets")
def api_datasets():
    # oisst_remote gets its dates inline -- the boot path needs a date axis
    # immediately and that list is disk-cached with a 24 h TTL, so it is cheap.
    # MUR's date list still loads lazily via /api/dataset_dates.
    return {
        "gridded": [D.dataset_meta(ds, with_dates=(ds.id == "oisst_remote"))
                    for ds in D.DATASETS.values()],
    }


@app.get("/api/dataset_dates")
def api_dataset_dates(dataset: str):
    ds = _ds(dataset)
    return {"id": ds.id, "dates": _remote_guard(ds.dates)}


def _bbox(bbox):
    """'w,s,e,n' -> (w, s, e, n) floats. 400 on anything else."""
    if bbox is None:
        return None
    try:
        w, s, e, n = (float(x) for x in bbox.split(","))
    except ValueError:
        raise HTTPException(400, "bbox must be 'west,south,east,north'")
    return (w, s, e, n)


def _bounds_hdr(b):
    """render_overlay's 5th value -> the X-Bounds header. It is ALREADY
    (s, w, n, e) -- Leaflet order, the same order app.js parses it back in --
    so this only joins it. Reordering here is how the overlay ends up drawn
    with latitude and longitude swapped."""
    if b is None:
        return None
    s, w, n, e = b
    return f"{s},{w},{n},{e}"


def _lattice_hdr(dataset, bb):
    """'scale,over,div' for the X-Lattice header; empty if it cannot be built."""
    try:
        q = D.lattice_for(dataset, bb)
    except Exception:
        return ""
    return f"{q['scale']!r},{q['over']},{q['div']}"


@app.get("/api/overlay")
def api_overlay(date: str, var: str = "sst", dataset: str = "oisst_remote",
                vmin: float | None = None, vmax: float | None = None,
                bbox: str | None = Query(None, description="west,south,east,north")):
    png, lo, hi, snapped, bounds = _remote_guard(D.render_overlay, dataset, date, var,
                                                 vmin, vmax, _bbox(bbox))
    return FileResponse(png, media_type="image/png",
                        headers={"X-Vmin": str(lo), "X-Vmax": str(hi),
                                 "X-Date": snapped,
                                 "X-Bounds": _bounds_hdr(bounds) or "",
                                 # the exact raster lattice, so the map can
                                 # draw grid lines where the IMAGERY's cell
                                 # boundaries are rather than where they
                                 # mathematically belong -- see lattice_for()
                                 "X-Lattice": _lattice_hdr(dataset, _bbox(bbox)),
                                 "Access-Control-Expose-Headers":
                                     "X-Vmin, X-Vmax, X-Date, X-Bounds, X-Lattice",
                                 # no-cache, not no-store: the browser keeps
                                 # the body and revalidates, and the server
                                 # answers from its own disk cache, so a hit
                                 # costs a 304. max-age would be wrong on BOTH
                                 # paths -- a tiled box renders empty before
                                 # its tiles arrive and correct afterwards at
                                 # the same URL, and a whole-grid overlay's URL
                                 # does not change when the server-side
                                 # resampling does (see LATTICE_V), so a stale
                                 # body would outlive the fix for an hour.
                                 "Cache-Control": "no-cache"})


@app.get("/api/colorbar")
def api_colorbar(var: str = "sst", dataset: str = "oisst_remote"):
    try:
        png = D.render_colorbar(dataset, var)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "max-age=86400"})


@app.get("/api/point")
def api_point(lat: float, lon: float, date: str, dataset: str = "oisst_remote"):
    ds = _ds(dataset)
    return _remote_guard(ds.point_values, lat, lon, date)


@app.get("/api/series")
def api_series(lat: float, lon: float, var: str = "sst",
               dataset: str = "oisst_remote",
               start: str | None = None, end: str | None = None):
    ds = _ds(dataset)
    if var not in ds.variables and var != ds.ice_var:
        raise HTTPException(400, f"unknown variable {var!r}")
    pts = _remote_guard(ds.point_series, lat, lon, var, start, end)
    return {"lat": lat, "lon": lon, "var": var, "dataset": dataset, "points": pts}


@app.post("/api/batch_series")
def api_batch_series(payload: dict = Body(...)):
    """One date, many points: sample all coordinates from a single gridded box
    (one ERDDAP request) instead of one request per point. Returns values
    aligned with the input `points`. Used by the coordinate tool to fetch a
    whole set of dots per date rather than dot by dot."""
    ds = _ds(payload.get("dataset", "mur_okhotsk"))
    if not D.supports_batch(ds):
        raise HTTPException(400, f"{ds.id} does not support batch fetch")
    points = [(float(la), float(lo)) for la, lo in payload["points"]]
    if not points:
        raise HTTPException(400, "no points")
    var = payload.get("var") or next(iter(ds.variables))
    date, values = _remote_guard(D.batch_sample, ds, points, var, payload["date"])
    return {"date": date, "var": var, "dataset": ds.id, "values": values}


@app.post("/api/batch_job")
def api_batch_job(payload: dict = Body(...)):
    """Start a background job: fetch each point's series for its own exact
    date list, assemble one combined CSV, and optionally render a PDF per
    point. Poll progress via /api/batch_job_status."""
    dsid = payload.get("dataset", "oisst_remote")
    _ds(dsid)
    points = payload.get("points") or []
    if not points:
        raise HTTPException(400, "no points")
    for p in points:
        if not p.get("dates"):
            raise HTTPException(400, f"point {p.get('label')!r} has no dates")
    job_id = R.start_batch_job(dsid, points,
                               bool(payload.get("generate_pdf", False)),
                               bool(payload.get("refresh_data", False)),
                               bool(payload.get("generate_compare", False)))
    return {"id": job_id}


@app.get("/api/batch_job_status")
def api_batch_job_status(id: str):
    job = R.JOBS.get(id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


@app.post("/api/tile_job")
def api_tile_job(payload: dict = Body(...)):
    """Start a background download of every MUR tile the given box needs but
    does not have cached yet. Poll progress via /api/tile_job_status.
    total == 0 means everything is already on disk -- nothing to wait for."""
    dsid = payload.get("dataset", "mur_okhotsk")
    if dsid not in D.DATASETS:
        raise HTTPException(400, f"unknown dataset {dsid!r}")
    ds = D.DATASETS[dsid]
    if not hasattr(ds, "mosaic_idx"):
        raise HTTPException(400, f"{dsid} is not tiled; no tiles to fetch")
    try:
        w, s, e, n = (float(x) for x in payload["bbox"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "bbox must be [west, south, east, north]")
    date = payload.get("date")
    if not date:
        raise HTTPException(400, "date is required")
    varz = payload.get("vars") or None
    job = _remote_guard(D.start_tile_job, dsid, date, (w, s, e, n), varz)
    # start_tile_job may hand back just the id or (id, total)
    jid, total = job if isinstance(job, tuple) else (
        job, D.TILE_JOBS.get(job, {}).get("total", 0))
    return {"id": jid, "total": total}


@app.get("/api/tile_job_status")
def api_tile_job_status(id: str):
    job = D.TILE_JOBS.get(id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return {"state": job.get("state", "running"), "done": job.get("done", 0),
            "total": job.get("total", 0), "error": job.get("error")}


@app.get("/api/playback_dates")
def api_playback_dates(start: str, end: str, gap: int = 1,
                       same_day_each_year: bool = False,
                       dataset: str = "oisst_remote"):
    _ds(dataset)
    return _remote_guard(D.playback_dates, dataset, start, end, gap, same_day_each_year)


def _gif_params(dataset, start, end, gap, same_day_each_year, bbox, dates=None):
    if dates:
        # explicit frame list (the timelapse date/year editor); keep only dates
        # the dataset actually has, in order
        want = set(dates.split(","))
        dates = [d for d in D.get_dataset(dataset).dates() if d in want]
    else:
        dates = D.playback_dates(dataset, start, end, gap, same_day_each_year)
    if not dates:
        raise HTTPException(404, "no available dates in range")
    if len(dates) > 400:
        raise HTTPException(400, f"{len(dates)} frames is too many; increase gap")
    bb = tuple(float(x) for x in bbox.split(",")) if bbox else None
    return dates, bb


@app.get("/api/export/timelapse")
def api_export_timelapse(start: str, end: str, var: str = "sst",
                         dataset: str = "oisst_remote",
                         gap: int = 1, same_day_each_year: bool = False,
                         vmin: float = -2, vmax: float = 25, fps: float = 4,
                         dates: str | None = Query(None, description="explicit ISO frame list"),
                         bbox: str | None = Query(None, description="west,south,east,north")):
    _ds(dataset)
    dates, bb = _remote_guard(_gif_params, dataset, start, end, gap,
                              same_day_each_year, bbox, dates)
    gif = _remote_guard(D.export_gif, dataset, dates, var, vmin, vmax, bb, fps)
    return FileResponse(gif, media_type="image/gif", filename=gif.name)


# -------------------------------------------------------------- saved areas

_AREAS_LOCK = threading.Lock()


def _load_areas():
    if AREAS_FILE.exists():
        return json.loads(AREAS_FILE.read_text(encoding="utf-8"))
    return []


def _save_areas(areas):
    tmp = AREAS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(areas, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(AREAS_FILE)


def _find_area(areas, area_id):
    for a in areas:
        if a["id"] == area_id:
            return a
    raise HTTPException(404, f"unknown area {area_id!r}")


@app.get("/api/areas")
def api_areas():
    with _AREAS_LOCK:
        return _load_areas()


@app.post("/api/areas")
def api_area_create(payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    geom = payload.get("geom") or {}
    if geom.get("type") not in ("point", "rect", "circle", "polygon"):
        raise HTTPException(400, "bad geometry")
    try:
        D.area_bbox(geom)  # validates required fields
    except (KeyError, ValueError, TypeError):
        raise HTTPException(400, "bad geometry")
    area = {
        "id": uuid.uuid4().hex[:8], "name": name, "geom": geom,
        "dataset": payload.get("dataset", "oisst_remote"),
        "var": payload.get("var", "sst"),
        "date": payload.get("date"),
        "vmin": payload.get("vmin"), "vmax": payload.get("vmax"),
    }
    with _AREAS_LOCK:
        areas = _load_areas()
        areas.append(area)
        _save_areas(areas)
    return area


@app.put("/api/areas/{area_id}")
def api_area_update(area_id: str, payload: dict = Body(...)):
    """Rename and/or reshape a saved area. Either field alone is a valid edit
    -- the GIF crop box edits the geometry and leaves the name untouched."""
    name = payload.get("name")
    geom = payload.get("geom")
    if name is not None:
        name = name.strip()
        if not name:
            raise HTTPException(400, "name must not be empty")
    if geom is not None:
        if geom.get("type") not in ("point", "rect", "circle", "polygon"):
            raise HTTPException(400, "bad geometry")
        try:
            D.area_bbox(geom)  # validates required fields
        except (KeyError, ValueError, TypeError):
            raise HTTPException(400, "bad geometry")
    if name is None and geom is None:
        raise HTTPException(400, "nothing to update")
    with _AREAS_LOCK:
        areas = _load_areas()
        a = _find_area(areas, area_id)
        if name is not None:
            a["name"] = name
        if geom is not None:
            a["geom"] = geom
        _save_areas(areas)
    return a


@app.delete("/api/areas/{area_id}")
def api_area_delete(area_id: str):
    with _AREAS_LOCK:
        areas = _load_areas()
        a = _find_area(areas, area_id)
        areas.remove(a)
        _save_areas(areas)
    d = D.LIBRARY / area_id
    if d.exists():
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
    return {"ok": True}


_SAFE_NAME = re.compile(r"^[\w.\-]+$")


@app.get("/api/areas/{area_id}/media")
def api_area_media(area_id: str):
    with _AREAS_LOCK:
        _find_area(_load_areas(), area_id)
    d = D.LIBRARY / area_id
    if not d.exists():
        return []
    return [{"name": f.name, "size": f.stat().st_size}
            for f in sorted(d.iterdir()) if f.is_file()]


@app.delete("/api/areas/{area_id}/media/{name}")
def api_area_media_delete(area_id: str, name: str):
    if not _SAFE_NAME.match(name):
        raise HTTPException(400, "bad file name")
    f = D.LIBRARY / area_id / name
    if not f.exists():
        raise HTTPException(404, "no such file")
    f.unlink()
    return {"ok": True}


@app.post("/api/areas/{area_id}/snapshot")
def api_area_snapshot(area_id: str, date: str, var: str = "sst",
                      dataset: str = "oisst_remote",
                      vmin: float = -2, vmax: float = 25):
    with _AREAS_LOCK:
        a = _find_area(_load_areas(), area_id)
    _ds(dataset)
    d = D.LIBRARY / area_id
    d.mkdir(exist_ok=True)
    out = d / f"snap_{dataset}_{date}_{var}.png"
    _, snapped = _remote_guard(D.snapshot_png, dataset, date, var, vmin, vmax,
                               D.area_bbox(a["geom"]), out)
    return {"name": out.name, "date": snapped}


@app.post("/api/areas/{area_id}/gif")
def api_area_gif(area_id: str, start: str, end: str, var: str = "sst",
                 dataset: str = "oisst_remote", gap: int = 1,
                 same_day_each_year: bool = False,
                 vmin: float = -2, vmax: float = 25, fps: float = 4,
                 dates: str | None = Query(None, description="explicit ISO frame list")):
    with _AREAS_LOCK:
        a = _find_area(_load_areas(), area_id)
    _ds(dataset)
    dates, _ = _remote_guard(_gif_params, dataset, start, end, gap,
                             same_day_each_year, None, dates)
    d = D.LIBRARY / area_id
    d.mkdir(exist_ok=True)
    out = d / f"gif_{dataset}_{start}_{end}_{var}.gif"
    _remote_guard(D.export_gif, dataset, dates, var, vmin, vmax,
                  D.area_bbox(a["geom"]), fps, out)
    return {"name": out.name, "frames": len(dates)}


@app.get("/api/areas/{area_id}/mean_series")
def api_area_mean_series(area_id: str, var: str = "sst",
                         dataset: str = "oisst_remote",
                         start: str | None = None, end: str | None = None):
    with _AREAS_LOCK:
        a = _find_area(_load_areas(), area_id)
    ds = _ds(dataset)
    if var not in ds.variables and var != ds.ice_var:
        raise HTTPException(400, f"unknown variable {var!r}")
    pts = _remote_guard(D.area_mean_series, dataset, a["geom"], var, start, end)
    return {"area": area_id, "var": var, "dataset": dataset, "points": pts}


app.mount("/library", StaticFiles(directory=D.LIBRARY), name="library")
app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")
