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
    # local gets its dates inline; remote date lists load lazily via
    # /api/dataset_dates so startup never touches the network
    return {
        "gridded": [D.dataset_meta(ds, with_dates=(ds.id == "oisst_local"))
                    for ds in D.DATASETS.values()],
    }


@app.get("/api/dataset_dates")
def api_dataset_dates(dataset: str):
    ds = _ds(dataset)
    return {"id": ds.id, "dates": _remote_guard(ds.dates)}


@app.get("/api/overlay")
def api_overlay(date: str, var: str = "sst", dataset: str = "oisst_local",
                vmin: float | None = None, vmax: float | None = None):
    png, lo, hi, snapped = _remote_guard(D.render_overlay, dataset, date, var, vmin, vmax)
    return FileResponse(png, media_type="image/png",
                        headers={"X-Vmin": str(lo), "X-Vmax": str(hi),
                                 "X-Date": snapped,
                                 "Access-Control-Expose-Headers": "X-Vmin, X-Vmax, X-Date",
                                 "Cache-Control": "max-age=3600"})


@app.get("/api/colorbar")
def api_colorbar(var: str = "sst", dataset: str = "oisst_local"):
    try:
        png = D.render_colorbar(dataset, var)
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "max-age=86400"})


@app.get("/api/point")
def api_point(lat: float, lon: float, date: str, dataset: str = "oisst_local"):
    ds = _ds(dataset)
    return _remote_guard(ds.point_values, lat, lon, date)


@app.get("/api/series")
def api_series(lat: float, lon: float, var: str = "sst",
               dataset: str = "oisst_local",
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
    dsid = payload.get("dataset", "oisst_local")
    _ds(dsid)
    points = payload.get("points") or []
    if not points:
        raise HTTPException(400, "no points")
    for p in points:
        if not p.get("dates"):
            raise HTTPException(400, f"point {p.get('label')!r} has no dates")
    job_id = R.start_batch_job(dsid, points,
                               bool(payload.get("generate_pdf", False)),
                               bool(payload.get("refresh_data", False)))
    return {"id": job_id}


@app.get("/api/batch_job_status")
def api_batch_job_status(id: str):
    job = R.JOBS.get(id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return job


@app.get("/api/playback_dates")
def api_playback_dates(start: str, end: str, gap: int = 1,
                       same_day_each_year: bool = False,
                       dataset: str = "oisst_local"):
    _ds(dataset)
    return _remote_guard(D.playback_dates, dataset, start, end, gap, same_day_each_year)


def _gif_params(dataset, start, end, gap, same_day_each_year, bbox):
    dates = D.playback_dates(dataset, start, end, gap, same_day_each_year)
    if not dates:
        raise HTTPException(404, "no available dates in range")
    if len(dates) > 400:
        raise HTTPException(400, f"{len(dates)} frames is too many; increase gap")
    bb = tuple(float(x) for x in bbox.split(",")) if bbox else None
    return dates, bb


@app.get("/api/export/timelapse")
def api_export_timelapse(start: str, end: str, var: str = "sst",
                         dataset: str = "oisst_local",
                         gap: int = 1, same_day_each_year: bool = False,
                         vmin: float = -2, vmax: float = 25, fps: float = 4,
                         bbox: str | None = Query(None, description="west,south,east,north")):
    _ds(dataset)
    dates, bb = _remote_guard(_gif_params, dataset, start, end, gap,
                              same_day_each_year, bbox)
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
        "dataset": payload.get("dataset", "oisst_local"),
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
def api_area_rename(area_id: str, payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    with _AREAS_LOCK:
        areas = _load_areas()
        a = _find_area(areas, area_id)
        a["name"] = name
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
                      dataset: str = "oisst_local",
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
                 dataset: str = "oisst_local", gap: int = 1,
                 same_day_each_year: bool = False,
                 vmin: float = -2, vmax: float = 25, fps: float = 4):
    with _AREAS_LOCK:
        a = _find_area(_load_areas(), area_id)
    _ds(dataset)
    dates, _ = _remote_guard(_gif_params, dataset, start, end, gap,
                             same_day_each_year, None)
    d = D.LIBRARY / area_id
    d.mkdir(exist_ok=True)
    out = d / f"gif_{dataset}_{start}_{end}_{var}.gif"
    _remote_guard(D.export_gif, dataset, dates, var, vmin, vmax,
                  D.area_bbox(a["geom"]), fps, out)
    return {"name": out.name, "frames": len(dates)}


@app.get("/api/areas/{area_id}/mean_series")
def api_area_mean_series(area_id: str, var: str = "sst",
                         dataset: str = "oisst_local",
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
