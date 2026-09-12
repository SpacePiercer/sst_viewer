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

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import auth as AU
import config as cfg
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


app.state.allowed_hosts = cfg.ALLOWED_HOSTS


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Host check, then the headers a public deployment needs.

    index.html must never be served from cache without checking: it carries the
    `app.js?v=N` cache-buster, so a stale copy pins the browser to an old
    app.js forever. "no-cache" = revalidate, not "don't store" -- unchanged
    HTML still comes back as a cheap 304.

    The CSP is what forces Leaflet and Chart.js to be vendored under
    static/vendor instead of pulled from a CDN: `script-src 'self'` and a
    third-party <script> cannot both be true. Esri tiles are the map itself, so
    img-src names that host explicitly. HSTS is only meaningful over TLS, and
    over plain HTTP it would strand a local dev server on a protocol it does
    not speak."""
    allowed = request.app.state.allowed_hosts
    if allowed != ["*"]:
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in allowed:
            return JSONResponse({"detail": "unknown host"}, status_code=400)
    resp = await call_next(request)
    if resp.headers.get("content-type", "").startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: blob: https://server.arcgisonline.com; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
    if cfg.SECURE_COOKIES:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp


# Anything reachable without a session. Deliberately tiny: the login page and
# the call that creates a session, nothing else. /api/ping stays open so a
# monitor can see the process is alive without holding a credential.
_OPEN_PATHS = {"/login", "/login.html", "/api/login", "/api/ping", "/favicon.ico"}


@app.middleware("http")
async def _require_session(request: Request, call_next):
    """One gate for every route, instead of a dependency on each of 20-odd
    handlers -- a route added later is then private by default rather than
    private only if someone remembered. An API call gets 401 (the frontend can
    react); a browser asking for a page gets bounced to the login screen."""
    user = AU.read_cookie(request.cookies.get(AU.COOKIE))
    request.state.user = user
    path = request.url.path
    if user or path in _OPEN_PATHS:
        return await call_next(request)
    if path.startswith("/api/") or path.startswith("/library/"):
        return JSONResponse({"detail": "not signed in"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


def _user(request: Request):
    """The signed-in name. The middleware has already refused anonymous
    callers, so reaching here without one would be a bug, not a request."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "not signed in")
    return user


@app.post("/api/login")
def api_login(request: Request, response: Response, payload: dict = Body(...)):
    name = (payload.get("username") or "").strip().lower()
    keys = (f"ip:{request.client.host if request.client else '?'}", f"user:{name}")
    if AU.login_blocked(keys):
        # deliberately refuses the RIGHT password too: a lockout that lets a
        # guesser through the moment they land on it is decorative
        raise HTTPException(429, "too many attempts, try again later")
    if not AU.verify(name, payload.get("password") or ""):
        AU.login_failed(keys)
        # one message for both "no such user" and "wrong password": which of
        # the two it was is not the caller's business
        raise HTTPException(401, "wrong user name or password")
    AU.login_ok(keys)
    response.set_cookie(AU.COOKIE, AU.make_cookie(name), httponly=True,
                        secure=cfg.SECURE_COOKIES, samesite="lax",
                        max_age=AU.TTL_DAYS * 86400, path="/")
    return {"user": name}


@app.get("/api/capabilities")
def api_capabilities():
    """What this deployment can actually do. The public image ships no R,
    Quarto or TeX, so the frontend hides the PDF option rather than letting
    every point in a batch fail with "quarto executable not found"."""
    return {"pdf": cfg.ENABLE_PDF}


@app.post("/api/logout")
def api_logout(response: Response):
    response.delete_cookie(AU.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request):
    return {"user": _user(request)}


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
def api_batch_job(request: Request, payload: dict = Body(...)):
    """Start a background job: fetch each point's series for its own exact
    date list, assemble one combined CSV, and optionally render a PDF per
    point. Poll progress via /api/batch_job_status."""
    dsid = payload.get("dataset", "oisst_local")
    _ds(dsid)
    points = payload.get("points") or []
    if not points:
        raise HTTPException(400, "no points")
    if payload.get("generate_pdf") and not cfg.ENABLE_PDF:
        raise HTTPException(400, "PDF rendering is not available on this server")
    for p in points:
        if not p.get("dates"):
            raise HTTPException(400, f"point {p.get('label')!r} has no dates")
    job_id = R.start_batch_job(dsid, points,
                               bool(payload.get("generate_pdf", False)),
                               _user(request),
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
                         dataset: str = "oisst_local",
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


def _visible(a, user):
    return a.get("owner") == user or a.get("shared")


def _owned(a, user):
    """Shared means readable, never writable -- only the owner edits or deletes.
    403, not 404: the caller can see it in their list, so pretending it is gone
    would just be confusing."""
    if a.get("owner") != user:
        raise HTTPException(403, "not yours")
    return a


@app.get("/api/areas")
def api_areas(request: Request):
    user = _user(request)
    with _AREAS_LOCK:
        return [a for a in _load_areas() if _visible(a, user)]


@app.post("/api/areas")
def api_area_create(request: Request, payload: dict = Body(...)):
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
        "owner": _user(request), "shared": bool(payload.get("shared")),
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
def api_area_update(request: Request, area_id: str, payload: dict = Body(...)):
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
    shared = payload.get("shared")
    if name is None and geom is None and shared is None:
        raise HTTPException(400, "nothing to update")
    user = _user(request)
    with _AREAS_LOCK:
        areas = _load_areas()
        a = _owned(_find_area([x for x in areas if _visible(x, user)], area_id), user)
        if name is not None:
            a["name"] = name
        if geom is not None:
            a["geom"] = geom
        if shared is not None:
            a["shared"] = bool(shared)
        _save_areas(areas)
    return a


@app.delete("/api/areas/{area_id}")
def api_area_delete(request: Request, area_id: str):
    user = _user(request)
    with _AREAS_LOCK:
        areas = _load_areas()
        a = _owned(_find_area([x for x in areas if _visible(x, user)], area_id), user)
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
                         dataset: str = "oisst_local",
                         start: str | None = None, end: str | None = None):
    with _AREAS_LOCK:
        a = _find_area(_load_areas(), area_id)
    ds = _ds(dataset)
    if var not in ds.variables and var != ds.ice_var:
        raise HTTPException(400, f"unknown variable {var!r}")
    pts = _remote_guard(D.area_mean_series, dataset, a["geom"], var, start, end)
    return {"area": area_id, "var": var, "dataset": dataset, "points": pts}


@app.get("/login")
def login_page():
    return FileResponse(HERE / "static" / "login.html")


@app.get("/library/{path:path}")
def api_library(request: Request, path: str):
    """Was a plain StaticFiles mount, i.e. every PDF and CSV readable by anyone
    who guessed a filename. Now: signed in, and for anything under users/, it
    has to be your own. library/series is shared on purpose -- the raw series
    for a coordinate is the same data for everyone and expensive to refetch."""
    user = _user(request)
    root = D.LIBRARY.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "not found")          # also kills ../ escapes
    rel = target.relative_to(root).parts
    if rel and rel[0] == "users" and (len(rel) < 2 or rel[1] != user):
        raise HTTPException(403, "not yours")
    if rel and rel[0] not in ("users", "series"):
        # snapshots and area GIFs sit in library/<area_id>/, so they inherit
        # the area's visibility. Default-deny: a directory that is neither a
        # user's, the shared series cache, nor a visible area is nobody's
        # business -- that is what keeps an archive dropped into library/ from
        # being readable by everyone.
        with _AREAS_LOCK:
            area = next((a for a in _load_areas() if a["id"] == rel[0]), None)
        if not area or not _visible(area, user):
            raise HTTPException(403, "not yours")
    return FileResponse(target)
app.mount("/", StaticFiles(directory=HERE / "static", html=True), name="static")
