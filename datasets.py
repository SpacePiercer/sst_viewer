"""Data access layer for sst_viewer v2.

Registry of gridded datasets (DATASETS), each a small object with the same
interface:
    id, name, resolution_label, variables, bounds (None = global),
    dates(), grid(date, var), point_values(...), point_series(...),
    field_available(date, var), ensure_field(date)

  - oisst_remote: NOAA OISST 0.25 deg, global, one whole field per date via
    NOAA ERDDAP griddap, Sept 1981 - present.
  - mur_okhotsk : GHRSST MUR 0.01 deg via ERDDAP, covering PACIFIC as 5 deg
    tiles (a whole-box 1 km field would be GBs/date, so there is no whole-grid
    path at all -- see MurPacific). Point values and series are tiny
    single-pixel requests and work anywhere on the globe.

Plus: overlay/colorbar/GIF rendering and saved-area geometry reductions.
All remote fields fetch lazily on first access (ensure_field) -- there is
no separate manual "load" step.

ERDDAP grammar verified live 2026-07-04 against the PFEG ERDDAP:
ncdcOisst21Agg_LonPM180 (sst/anom/err/ice, dims time,zlev,lat,lon, degC,
lat -89.875..89.875 asc, lon -179.875..179.875 asc, times at 12:00Z) and
jplMURSST41 (analysed_sst/sea_ice_fraction, dims time,lat,lon, degC,
times at 09:00Z). Okhotsk box request = 2501x3001 cells, ~60 MB/var/date.
"""
import bisect
import functools
import http.client
import io
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.cm
import matplotlib.colors
from matplotlib.path import Path as MplPath
import netCDF4
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OISST_DIR = HERE / "data" / "oisst_may20_july1"  # self-contained, no cross-folder deps
CACHE = Path(os.environ.get("SST_CACHE", Path(__file__).resolve().parent / "cache"))  # gitignored, regenerable
FIELDS = CACHE / "fields"
LIBRARY = HERE / "library"          # user content: NOT under cache/
CACHE.mkdir(exist_ok=True)
FIELDS.mkdir(exist_ok=True)
LIBRARY.mkdir(exist_ok=True)

# Every map view lives inside this box: Chukchi Sea down to south of New
# Guinea, Indochina across to the Chilean coast. Sized so the whole Pacific
# fits a wide screen at full zoom-out, and so every region already researched
# (Okhotsk, East Kamchatka, Primorsky) sits well inside it. Longitudes run
# 95..295 instead of wrapping at 180 -- the box straddles the antimeridian and
# a wrapped frame would cut it in half.
PACIFIC = (95.0, -20.0, 295.0, 70.0)   # w, s, e, n

ICE_THRESHOLD = 0.15          # standard 15% sea-ice concentration cutoff
MERC_LAT = 85.05112878        # Web Mercator latitude limit
ICE_RGBA = (232, 244, 248, 255)      # pale ice blue-white  #e8f4f8
NODATA_RGBA = (153, 153, 153, 255)   # mid gray             #999999
LAND_RGBA = (0, 0, 0, 0)             # transparent, basemap shows through

# upwell.pfeg.noaa.gov (161.55.160.6) is NOT a usable fallback, tempting as it
# looks: it answers .das from its own metadata cache, but 302-redirects every
# DATA request to coastwatch.pfeg.noaa.gov, so a dead canonical host takes both
# down. Measured 2026-09-11, while coastwatch was resetting the TLS handshake
# on every request (as it did for three weeks in Aug-Sep 2026). Nothing to
# switch to -- when this host is dark, the remote datasets are dark.
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap"
HTTP_TIMEOUT = 30             # per-socket-op seconds

OISST_VARS = {
    "sst":  {"label": "SST (°C)", "cmap": "viridis", "diverging": False},
    "anom": {"label": "SST anomaly (°C)", "cmap": "RdBu_r", "diverging": True},
    "err":  {"label": "Analysis error (°C)", "cmap": "magma", "diverging": False},
}
MUR_VARS = {
    "analysed_sst":     {"label": "SST (°C)", "cmap": "viridis", "diverging": False},
    "sea_ice_fraction": {"label": "Sea-ice fraction", "cmap": "Blues", "diverging": False},
}


class RemoteError(RuntimeError):
    """Network / ERDDAP failure that should surface as a clear UI error."""


# ------------------------------------------------------------------ HTTP

_RETRY_WAITS = (4, 12)  # ERDDAP 5xx and connection timeouts are usually transient


def _retry_transient(fn):
    """Run fn, retrying twice on gateway 5xx or network errors (timeouts,
    resets) before giving up. Real HTTP errors (404 etc.) raise immediately."""
    for wait in _RETRY_WAITS:
        try:
            return fn()
        except RemoteError as e:
            if not re.search(r"HTTP 50[234]|network error", str(e)):
                raise
            time.sleep(wait)
    return fn()


def _http_get(url, timeout=HTTP_TIMEOUT):
    return _retry_transient(lambda: _http_get_raw(url, timeout))


def _http_download(url, dest, timeout=HTTP_TIMEOUT):
    return _retry_transient(lambda: _http_download_raw(url, dest, timeout))


# Health monitoring taps every real request instead of making its own, so a
# busy app barely needs to probe. health.py appends to this; empty otherwise.
OBSERVERS = []


def _notify(url, reachable, t0, err=None):
    ms = int((time.time() - t0) * 1000)
    for fn in OBSERVERS:
        try:
            fn(url, reachable, ms, err)
        except Exception:
            pass  # monitoring must never break a real fetch


def _http_get_raw(url, timeout=HTTP_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": "sst_viewer/2"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
        _notify(url, True, t0)
        return body
    except urllib.error.HTTPError as e:
        # the server answered: reachable, even though this request failed
        _notify(url, True, t0)
        body = e.read()[:400].decode("utf-8", "replace")
        raise RemoteError(f"ERDDAP HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, http.client.HTTPException,
            TimeoutError, OSError) as e:
        _notify(url, False, t0, str(e)[:200])
        raise RemoteError(f"network error: {e}") from e


def _http_download_raw(url, dest, timeout=HTTP_TIMEOUT):
    """Stream a (possibly huge) response to dest atomically."""
    req = urllib.request.Request(url, headers={"User-Agent": "sst_viewer/2"})
    tmp = dest.parent / (dest.name + ".part")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        tmp.replace(dest)
        _notify(url, True, t0)
    except urllib.error.HTTPError as e:
        _notify(url, True, t0)
        tmp.unlink(missing_ok=True)
        body = e.read()[:400].decode("utf-8", "replace")
        raise RemoteError(f"ERDDAP HTTP {e.code}: {body}") from e
    except (urllib.error.URLError, http.client.HTTPException,
            TimeoutError, OSError) as e:
        # IncompleteRead (truncated stream on a big box) is an HTTPException;
        # wrap as a network error so _retry_transient retries it.
        _notify(url, False, t0, str(e)[:200])
        tmp.unlink(missing_ok=True)
        raise RemoteError(f"network error: {e}") from e


def _read_nc_bytes(data):
    """Parse NetCDF bytes via a temp file (netCDF4 needs a real path)."""
    with tempfile.NamedTemporaryFile(suffix=".nc", dir=CACHE, delete=False) as f:
        f.write(data)
        p = Path(f.name)
    try:
        return netCDF4.Dataset(p), p
    except OSError:
        p.unlink(missing_ok=True)
        raise RemoteError("ERDDAP returned an unreadable file")


# ------------------------------------------------------------ fields cache

def _field_paths(dsid, date, var):
    d = FIELDS / dsid
    return d / f"{date}_{var}.npy", d / f"{date}_{var}.json"


def save_field(dsid, date, var, arr, bounds):
    npy, meta = _field_paths(dsid, date, var)
    npy.parent.mkdir(parents=True, exist_ok=True)
    np.save(npy, np.asarray(arr, dtype=np.float32))
    meta.write_text(json.dumps({"bounds": list(bounds), "shape": list(arr.shape)}))


def load_field(dsid, date, var, mmap=False):
    npy, _ = _field_paths(dsid, date, var)
    if not npy.exists():
        return None
    return np.load(npy, mmap_mode="r" if mmap else None)


# ------------------------------------------------------------- ERDDAP axis

def _time_axis(dsid_erddap, cache_name):
    """date 'YYYY-MM-DD' -> full ISO time string, from griddap .json?time.
    Disk-cached with a 24 h TTL; stale cache is used if the network fails."""
    f = FIELDS / cache_name / "time_axis.json"
    cached = None
    if f.exists():
        cached = json.loads(f.read_text())
        if time.time() - cached.get("fetched", 0) < 86400:
            return cached["times"]
    try:
        raw = _http_get(f"{ERDDAP}/griddap/{dsid_erddap}.json?time", timeout=60)
        rows = json.loads(raw)["table"]["rows"]
        times = {}
        for (v,) in rows:
            iso = v if isinstance(v, str) else \
                datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            times[iso[:10]] = iso
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"fetched": time.time(), "times": times}))
        return times
    except RemoteError:
        if cached:
            return cached["times"]
        raise


def _nearest(sorted_dates, iso):
    if not sorted_dates:
        raise KeyError("dataset has no available dates")
    i = bisect.bisect_left(sorted_dates, iso)
    cands = sorted_dates[max(0, i - 1):i + 1]
    return min(cands, key=lambda d: abs(Date.fromisoformat(d).toordinal()
                                        - Date.fromisoformat(iso).toordinal()))


# ------------------------------------------------------------ OISST local IO

_FNAME_RE = re.compile(r"oisst-avhrr-v02r01\.(\d{8})\.nc$")

# One outbound tile request at a time, process-wide. Two tile jobs over
# overlapping boxes (a second browser tab, a reload mid-download, a pan that
# starts a fresh job while the old thread runs on) would otherwise fetch the
# same tile twice and race each other's writes. Serialising also keeps MUR
# traffic to a single stream, which is the same politeness rule health.py
# spells out for the probes.
_TILE_FETCH_LOCK = threading.Lock()


@functools.lru_cache(maxsize=1)
def oisst_index():
    """date-string 'YYYY-MM-DD' -> Path, built from filenames only."""
    idx = {}
    for p in OISST_DIR.glob("*.nc"):
        m = _FNAME_RE.search(p.name)
        if m:
            s = m.group(1)
            idx[f"{s[:4]}-{s[4:6]}-{s[6:]}"] = p
    if not idx:
        raise FileNotFoundError(f"No OISST files found in {OISST_DIR}")
    return idx


def _read_field(path, var):
    """Read a 2D global field, lon rolled to -180..180, lat ascending."""
    with netCDF4.Dataset(path) as ds:
        a = ds.variables[var][0, 0, :, :].filled(np.nan)
    return np.roll(a, a.shape[1] // 2, axis=1)  # lon 0..360 -> -180..180


@functools.lru_cache(maxsize=1)
def land_mask():
    """True where land. OISST's sst is gap-filled over all ocean, so NaN in a
    reference file is land; NaN elsewhere in another file is genuine no-data."""
    f = CACHE / "landmask.npy"
    if f.exists():
        return np.load(f)
    try:
        src = _read_field(oisst_index()[sorted(oisst_index())[0]], "sst")
    except FileNotFoundError:
        # the nightly cleanup removes the local .nc files; derive the mask from
        # a fetched OISST field instead -- same grid, same gap-filling.
        rds = DATASETS["oisst_remote"]
        src = rds.grid(rds.dates()[-1], "sst")
    mask = np.isnan(src)
    np.save(f, mask)
    return mask


# ------------------------------------------------------------ dataset classes

class GriddedDataset:
    """Shared geometry helpers. Data arrays are float32, lat-ascending,
    row 0 = southernmost, matching (lat0 + i*dlat, lon0 + j*dlon) centers."""
    id = name = resolution_label = ""
    bounds = None            # (w, s, e, n) or None = global
    ice_var = None
    mb_per_field = 0         # rough download MB per date (all needed vars)
    variables = {}

    lat0 = dlat = lon0 = dlon = 0.0
    nlat = nlon = 0

    def dates(self):
        raise NotImplementedError

    def nearest_date(self, iso):
        return _nearest(self.dates(), iso)

    def grid(self, date, var):
        raise NotImplementedError

    def field_available(self, date, var):
        raise NotImplementedError

    def ensure_field(self, date):
        """Make grid(date, *) work offline afterwards. Returns 'cached' or
        'downloaded'."""
        return "cached"

    def latlon_to_idx(self, lat, lon):
        i = int(round((lat - self.lat0) / self.dlat))
        j = int(round((lon - self.lon0) / self.dlon))
        i = max(0, min(self.nlat - 1, i))
        if self.bounds is None:
            j %= self.nlon
        else:
            j = max(0, min(self.nlon - 1, j))
        return i, j

    def cell_latlons(self, i0, i1, j0, j1):
        lats = self.lat0 + np.arange(i0, i1 + 1) * self.dlat
        lons = self.lon0 + np.arange(j0, j1 + 1) * self.dlon
        return lats, lons

    def bbox_to_idx(self, w, s, e, n):
        i0 = max(0, int(math.floor((s - self.lat0) / self.dlat)))
        i1 = min(self.nlat - 1, int(math.ceil((n - self.lat0) / self.dlat)))
        j0 = max(0, int(math.floor((w - self.lon0) / self.dlon)))
        j1 = min(self.nlon - 1, int(math.ceil((e - self.lon0) / self.dlon)))
        return i0, i1, j0, j1

    def subgrid(self, date, var, i0, i1, j0, j1):
        return np.asarray(self.grid(date, var)[i0:i1 + 1, j0:j1 + 1])

    def image_geom(self):
        """(west, east, south, north, w_px, h_px) of the whole-grid overlay.
        The extent is the true CELL-EDGE box of the pixels actually drawn
        (lat0/lon0 are cell CENTRES, so it is half a cell outside them),
        clipped to the Web Mercator latitude limit; the size comes from the
        dataset's Mercator lattice -- see _merc_map."""
        rows, cols, (s, w, n, e) = _merc_indices_cached(self)
        return w, e, s, n, len(cols), len(rows)

    def land(self):
        """Bool land mask on the data grid, or None -> NaN cells are drawn
        transparent (land) instead of gray (no-data)."""
        return None


class OisstBase(GriddedDataset):
    lat0, dlat, nlat = -89.875, 0.25, 720
    lon0, dlon, nlon = -179.875, 0.25, 1440
    variables = OISST_VARS
    ice_var = "ice"
    ALL_VARS = ("sst", "anom", "err", "ice")

    def land(self):
        try:
            return land_mask()
        except FileNotFoundError:
            return None  # no local files at all: NaN renders as land

    def nearest_ocean_idx(self, i, j):
        """Coastal stations can land on a land cell at 0.25 deg; snap to the
        nearest ocean cell within a 5x5 neighborhood."""
        lm = self.land()
        if lm is None or not lm[i, j]:
            return i, j
        best = None
        for di in range(-2, 3):
            for dj in range(-2, 3):
                ii, jj = i + di, (j + dj) % 1440
                if 0 <= ii < 720 and not lm[ii, jj]:
                    d = di * di + dj * dj
                    if best is None or d < best[0]:
                        best = (d, ii, jj)
        return (best[1], best[2]) if best else (i, j)

    def point_values(self, lat, lon, date):
        i, j = self.latlon_to_idx(lat, lon)
        out = {"lat": lat, "lon": lon, "date": date, "values": {}}
        for var in self.ALL_VARS:
            g = self.grid(date, var)
            v = float(g[i, j])
            out["values"][var] = None if math.isnan(v) else round(v, 3)
        lm = self.land()
        out["land"] = bool(lm[i, j]) if lm is not None else out["values"]["sst"] is None
        ice = out["values"].pop("ice")
        out["ice_fraction"] = ice
        out["is_ice"] = ice is not None and ice >= ICE_THRESHOLD
        return out


def _oisst_nc_subgrid(path, var, i0, i1, j0, j1):
    """Partial read of a local OISST file in the rolled (-180..180) frame.
    ponytail: no antimeridian wrap for area subsets (the study region is
    135-165E); add a two-slice read if areas ever straddle 180."""
    jj0, jj1 = (j0 + 720) % 1440, (j1 + 720) % 1440
    with netCDF4.Dataset(path) as ds:
        if jj0 <= jj1:
            a = ds.variables[var][0, 0, i0:i1 + 1, jj0:jj1 + 1].filled(np.nan)
        else:
            left = ds.variables[var][0, 0, i0:i1 + 1, jj0:].filled(np.nan)
            right = ds.variables[var][0, 0, i0:i1 + 1, :jj1 + 1].filled(np.nan)
            a = np.concatenate([left, right], axis=1)
    return a


class ErddapMixin:
    """Remote fetch helpers; classes define ERDDAP_ID, TIME_SUFFIX handling
    via the time axis, and _subset_url()."""
    ERDDAP_ID = ""

    def time_axis(self):
        return _time_axis(self.ERDDAP_ID, self.id)

    def dates(self):
        return sorted(self.time_axis())

    def _iso_time(self, date):
        ax = self.time_axis()
        if date not in ax:
            date = _nearest(sorted(ax), date)
        return date, ax[date]


class OisstRemote(ErddapMixin, OisstBase):
    id = "oisst_remote"
    name = "NOAA OISST v2.1 (ERDDAP)"
    resolution_label = "0.25°"
    ERDDAP_ID = "ncdcOisst21Agg_LonPM180"
    mb_per_field = 17  # 4 vars x ~4.2 MB

    _GRID_BOUNDS = (-180.0, -90.0, 180.0, 90.0)

    def _local_path(self, date):
        try:
            return oisst_index().get(date)
        except FileNotFoundError:
            return None

    def field_available(self, date, var):
        if self._local_path(date) is not None:
            return True
        return _field_paths(self.id, date, var)[0].exists()

    def ensure_field(self, date):
        if all(self.field_available(date, v) for v in self.ALL_VARS):
            return "cached"
        date, t = self._iso_time(date)
        sub = f"%5B({t})%5D%5B(0.0)%5D%5B(-89.875):(89.875)%5D%5B(-179.875):(179.875)%5D"
        url = f"{ERDDAP}/griddap/{self.ERDDAP_ID}.nc?" + \
              ",".join(v + sub for v in self.ALL_VARS)
        ds, p = _read_nc_bytes(_http_get(url, timeout=120))
        try:
            for v in self.ALL_VARS:
                a = ds.variables[v][0, 0, :, :].filled(np.nan)
                save_field(self.id, date, v, a, self._GRID_BOUNDS)
        finally:
            ds.close()
            p.unlink(missing_ok=True)
        return "downloaded"

    def grid(self, date, var):
        lp = self._local_path(date)
        if lp is not None:
            return _read_field(lp, var)   # same grid, fast offline path
        a = load_field(self.id, date, var)
        if a is None:
            self.ensure_field(date)
            a = load_field(self.id, date, var)
        return a

    def subgrid(self, date, var, i0, i1, j0, j1):
        lp = self._local_path(date)
        if lp is not None:
            return _oisst_nc_subgrid(lp, var, i0, i1, j0, j1)
        a = load_field(self.id, date, var, mmap=True)
        if a is None:
            raise KeyError(f"field {date}/{var} not cached")
        return np.asarray(a[i0:i1 + 1, j0:j1 + 1])

    def point_values(self, lat, lon, date):
        if all(self.field_available(date, v) for v in self.ALL_VARS):
            return super().point_values(lat, lon, date)
        # single-cell remote read: tiny request, no 17 MB field download
        date, t = self._iso_time(date)
        sub = f"%5B({t})%5D%5B(0.0)%5D%5B({lat})%5D%5B({lon})%5D"
        url = f"{ERDDAP}/griddap/{self.ERDDAP_ID}.nc?" + \
              ",".join(v + sub for v in self.ALL_VARS)
        ds, p = _read_nc_bytes(_http_get(url))
        try:
            vals = {}
            for v in self.ALL_VARS:
                x = float(np.ma.filled(ds.variables[v][:].squeeze(), np.nan))
                vals[v] = None if math.isnan(x) else round(x, 3)
        finally:
            ds.close()
            p.unlink(missing_ok=True)
        ice = vals.pop("ice")
        return {"lat": lat, "lon": lon, "date": date, "values": vals,
                "land": vals["sst"] is None, "ice_fraction": ice,
                "is_ice": ice is not None and ice >= ICE_THRESHOLD}

    @functools.lru_cache(maxsize=64)
    def _remote_series(self, var, lat, lon, t0, t1):
        url = (f"{ERDDAP}/griddap/{self.ERDDAP_ID}.nc?"
               f"{var}%5B({t0}):({t1})%5D%5B(0.0)%5D%5B({lat})%5D%5B({lon})%5D")
        ds, p = _read_nc_bytes(_http_get(url, timeout=120))
        try:
            tvar = ds.variables["time"]
            dts = netCDF4.num2date(tvar[:], tvar.units)
            vals = ds.variables[var][:].squeeze(axis=(1, 2, 3)).filled(np.nan)
        finally:
            ds.close()
            p.unlink(missing_ok=True)
        return tuple((d.strftime("%Y-%m-%d"),
                      None if math.isnan(float(v)) else round(float(v), 3))
                     for d, v in zip(dts, vals))

    def point_series(self, lat, lon, var="sst", start=None, end=None):
        ax = self.dates()
        s = _nearest(ax, start) if start else ax[0]
        e = _nearest(ax, end) if end else ax[-1]
        axm = self.time_axis()
        # snap to the nearest ocean cell using the (shared-grid) land mask
        i, j = self.nearest_ocean_idx(*self.latlon_to_idx(lat, lon))
        clat = self.lat0 + i * self.dlat
        clon = self.lon0 + j * self.dlon
        rows = self._remote_series(var, clat, clon, axm[s], axm[e])
        return [{"date": d, "value": v} for d, v in rows]


class MurPacific(ErddapMixin, GriddedDataset):
    """MUR 1 km over the whole Pacific box, fetched as 5-degree tiles.

    One 1 km field for the whole box would be 180M cells -- ~700 MB on disk
    per variable and ~1.4 GB on the wire, per date. Tiles make the same
    coverage practical: each is 500x500 (1 MB float32), only the tiles the
    viewport actually shows are fetched, panning reuses what is already on
    disk, and a partly-fetched region still renders (missing tiles are NaN).
    This is the chunk-and-merge that a whole-box download cannot be.

    Tile edges are multiples of 5 deg and so is 180, so no tile ever straddles
    the antimeridian -- each is requested in ERDDAP's -180..180 frame and
    stored in this dataset's 95..295 frame.
    """
    id = "mur_okhotsk"        # kept: saved areas and the on-disk cache use it
    name = "GHRSST MUR 1 km"
    resolution_label = "0.01°"
    ERDDAP_ID = "jplMURSST41"
    bounds = PACIFIC
    variables = MUR_VARS
    ice_var = "sea_ice_fraction"
    ALL_VARS = ("analysed_sst", "sea_ice_fraction")
    mb_per_field = 2          # per tile per variable -- the unit actually fetched

    TILE = 5.0                                  # degrees
    lat0, dlat, nlat = PACIFIC[1], 0.01, 9000   # -20.00 .. 69.99
    lon0, dlon, nlon = PACIFIC[0], 0.01, 20000  #  95.00 .. 294.99

    # ------------------------------------------------------------ geometry
    def _nlon(self, lon):
        """Longitudes reach us in -180..180; this grid runs 95..295."""
        return lon + 360.0 if lon < self.lon0 else lon

    def latlon_to_idx(self, lat, lon):
        return super().latlon_to_idx(lat, self._nlon(lon))

    def bbox_to_idx(self, w, s, e, n):
        w, e = self._nlon(w), self._nlon(e)
        if e < w:
            e += 360.0
        return super().bbox_to_idx(w, s, e, n)

    def tiles_for(self, w, s, e, n):
        """Tile origins (south, west) covering the box, clipped to the box."""
        bw, bs, be, bn = self.bounds
        w, e = self._nlon(w), self._nlon(e)
        if e < w:
            e += 360.0
        w, s, e, n = max(w, bw), max(s, bs), min(e, be), min(n, bn)
        if w >= e or s >= n:
            return []
        T = self.TILE
        return [(round(float(la), 2), round(float(lo), 2))
                for la in np.arange(math.floor(s / T) * T, n, T)
                for lo in np.arange(math.floor(w / T) * T, e, T)]

    def tile_of(self, lat, lon):
        lon = self._nlon(lon)
        bw, bs, be, bn = self.bounds
        if not (bs <= lat < bn and bw <= lon < be):
            return None
        T = self.TILE
        return (math.floor(lat / T) * T, math.floor(lon / T) * T)

    def _tile_path(self, date, var, tile):
        la, lo = tile
        return FIELDS / self.id / f"{date}_{var}_t{la:g}_{lo:g}.npy"

    # ------------------------------------------------------------- fetching
    def tile_cached(self, date, var, tile):
        return self._tile_path(date, var, tile).exists()

    # MUR's axes stop at +-179.99 / +-89.99: there is no cell at exactly 180 or
    # at a pole. The tile whose frame origin is 180.0 therefore has no data in
    # its first column, and asking ERDDAP for a box starting at -180.0 is an
    # outright error -- which used to abort the whole job, so the dateline
    # strip could never load at all.
    AX_LON, AX_LAT = 179.99, 89.99

    def fetch_tile(self, date, var, tile):
        """Download one 5-degree tile and cache it. No-op if already there."""
        p = self._tile_path(date, var, tile)
        if p.exists():
            return
        la, lo = tile
        npt = int(round(self.TILE / self.dlat))       # 500 cells a side
        rw = ((lo + 180.0) % 360.0) - 180.0           # back to ERDDAP's frame
        qw = max(rw, -self.AX_LON)
        qe = min(rw + self.TILE - self.dlon, self.AX_LON)
        qs = max(la, -self.AX_LAT)
        qn = min(la + self.TILE - self.dlat, self.AX_LAT)
        if qw > qe or qs > qn:
            return                                    # tile lies off the axis
        with _TILE_FETCH_LOCK:
            if p.exists():                            # won by another thread
                return
            lats, lons, arr = self.box_field(date, var, qw, qs, qe, qn)
            # Place what came back by ITS OWN coordinates. ERDDAP is inclusive
            # on both ends and snaps to cell centres, so a tile clipped by the
            # axis (the 180.0 one) or by rounding comes back short -- and
            # left-aligning a short block is what would slide that tile a
            # kilometre west while leaving its far column empty.
            out = np.full((npt, npt), np.nan, np.float32)
            if lats.size and lons.size:
                i = int(round((float(lats[0]) - la) / self.dlat))
                j = int(round((self._nlon(float(lons[0])) - lo) / self.dlon))
                si, sj = max(0, -i), max(0, -j)
                di, dj = max(0, i), max(0, j)
                h = min(arr.shape[0] - si, npt - di)
                w2 = min(arr.shape[1] - sj, npt - dj)
                if h > 0 and w2 > 0:
                    out[di:di + h, dj:dj + w2] = arr[si:si + h, sj:sj + w2]
            # Write through a temp name: np.save straight to the final path
            # leaves a truncated .npy if the process dies mid-write, and
            # tile_cached() would then call that corpse "present" forever --
            # every later render of the box 500s on np.load, permanently.
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.parent / (p.stem + f".{uuid.uuid4().hex[:6]}.part.npy")
            np.save(tmp, out)
            tmp.replace(p)

    def missing_tiles(self, date, w, s, e, n, varz=None):
        return [(v, t) for t in self.tiles_for(w, s, e, n)
                for v in (varz or self.ALL_VARS)
                if not self.tile_cached(date, v, t)]

    # -------------------------------------------------------------- reading
    def mosaic_idx(self, date, var, i0, i1, j0, j1):
        """Assemble cached tiles into one array over the index window.
        Tiles that were never fetched come back NaN."""
        out = np.full((i1 - i0 + 1, j1 - j0 + 1), np.nan, np.float32)
        npt = int(round(self.TILE / self.dlat))
        T = self.TILE
        la_lo = math.floor((self.lat0 + i0 * self.dlat) / T) * T
        lo_lo = math.floor((self.lon0 + j0 * self.dlon) / T) * T
        la_hi = self.lat0 + i1 * self.dlat
        lo_hi = self.lon0 + j1 * self.dlon
        for la in np.arange(la_lo, la_hi + 1e-9, T):
            for lo in np.arange(lo_lo, lo_hi + 1e-9, T):
                p = self._tile_path(date, var,
                                    (round(float(la), 2), round(float(lo), 2)))
                if not p.exists():
                    continue
                ti = int(round((la - self.lat0) / self.dlat))
                tj = int(round((lo - self.lon0) / self.dlon))
                a0, a1 = max(i0, ti), min(i1 + 1, ti + npt)
                b0, b1 = max(j0, tj), min(j1 + 1, tj + npt)
                if a0 >= a1 or b0 >= b1:
                    continue
                t = np.load(p, mmap_mode="r")
                out[a0 - i0:a1 - i0, b0 - j0:b1 - j0] = \
                    t[a0 - ti:a1 - ti, b0 - tj:b1 - tj]
        return out

    def mosaic(self, date, var, w, s, e, n):
        return self.mosaic_idx(date, var, *self.bbox_to_idx(w, s, e, n))

    subgrid = mosaic_idx

    def grid(self, date, var):
        # 180M cells; nothing should ever want the whole box at 1 km at once.
        raise RuntimeError("MUR is tiled - use mosaic()/subgrid() with a bbox")

    def field_available(self, date, var):
        return any((FIELDS / self.id).glob(f"{date}_{var}_t*.npy"))

    MAX_BOX_CELLS = 8_000_000  # one box request cap (~a 9x9 deg region at 0.01)

    def box_field(self, date, var, w, s, e, n, timeout=300):
        """Download an arbitrary (w,s,e,n) box of `var` for one date straight
        from ERDDAP and return (lats, lons, arr). This is the primitive both
        tiles and batch point extraction ride on: one request covers a whole
        region instead of one per point. Not limited to the map box (points
        can be anywhere, e.g. Kamchatka east of 165E)."""
        cells = (abs(n - s) / self.dlat + 1) * (abs(e - w) / self.dlon + 1)
        if cells > self.MAX_BOX_CELLS:
            raise RemoteError(
                f"region too large for one batch request ({cells / 1e6:.0f}M cells) "
                "- narrow the coordinates or fetch in sub-regions")
        date, t = self._iso_time(date)
        sub = f"%5B({t})%5D%5B({s}):({n})%5D%5B({w}):({e})%5D"
        url = f"{ERDDAP}/griddap/{self.ERDDAP_ID}.nc?{var}{sub}"
        dest = CACHE / f"mur_box_{uuid.uuid4().hex[:6]}.nc"
        try:
            _http_download(url, dest, timeout=timeout)
            with netCDF4.Dataset(dest) as nc:
                latn = "latitude" if "latitude" in nc.variables else "lat"
                lonn = "longitude" if "longitude" in nc.variables else "lon"
                lats = np.asarray(nc.variables[latn][:])
                lons = np.asarray(nc.variables[lonn][:])
                arr = np.ma.filled(nc.variables[var][0, :, :].astype("f8"), np.nan)
        finally:
            dest.unlink(missing_ok=True)
        return lats, lons, arr

    def point_values(self, lat, lon, date):
        tile = self.tile_of(lat, lon)
        if tile and all(self.tile_cached(date, v, tile) for v in self.ALL_VARS):
            i, j = self.latlon_to_idx(lat, lon)
            vals = {}
            for v in self.ALL_VARS:
                x = float(self.mosaic_idx(date, v, i, i, j, j)[0, 0])
                vals[v] = None if math.isnan(x) else round(x, 3)
        else:
            date, t = self._iso_time(date)
            sub = f"%5B({t})%5D%5B({lat})%5D%5B({lon})%5D"
            url = f"{ERDDAP}/griddap/{self.ERDDAP_ID}.nc?" + \
                  ",".join(v + sub for v in self.ALL_VARS)
            ds, p = _read_nc_bytes(_http_get(url))
            try:
                vals = {}
                for v in self.ALL_VARS:
                    x = float(np.ma.filled(ds.variables[v][:].squeeze(), np.nan))
                    vals[v] = None if math.isnan(x) else round(x, 3)
            finally:
                ds.close()
                p.unlink(missing_ok=True)
        ice = vals.get("sea_ice_fraction")
        return {"lat": lat, "lon": lon, "date": date, "values": vals,
                "land": vals["analysed_sst"] is None, "ice_fraction": ice,
                "is_ice": ice is not None and ice >= ICE_THRESHOLD}

    @functools.lru_cache(maxsize=64)
    def _remote_series(self, var, lat, lon, t0, t1):
        url = (f"{ERDDAP}/griddap/{self.ERDDAP_ID}.nc?"
               f"{var}%5B({t0}):({t1})%5D%5B({lat})%5D%5B({lon})%5D")
        ds, p = _read_nc_bytes(_http_get(url, timeout=120))
        try:
            tvar = ds.variables["time"]
            dts = netCDF4.num2date(tvar[:], tvar.units)
            vals = ds.variables[var][:].squeeze(axis=(1, 2)).filled(np.nan)
        finally:
            ds.close()
            p.unlink(missing_ok=True)
        return tuple((d.strftime("%Y-%m-%d"),
                      None if math.isnan(float(v)) else round(float(v), 3))
                     for d, v in zip(dts, vals))

    def point_series(self, lat, lon, var="analysed_sst", start=None, end=None):
        # global single-pixel request - NOT limited to the map box
        lat = max(-89.99, min(89.99, lat))    # MUR grid edges
        lon = max(-179.99, min(180.0, lon))
        ax = self.dates()
        s0 = _nearest(ax, start) if start else ax[0]
        e0 = _nearest(ax, end) if end else ax[-1]
        axm = self.time_axis()
        rows = self._remote_series(var, round(lat, 3), round(lon, 3),
                                   axm[s0], axm[e0])
        return [{"date": d, "value": v} for d, v in rows]


DATASETS = {d.id: d for d in (OisstRemote(), MurPacific())}


def get_dataset(dsid):
    if dsid not in DATASETS:
        raise KeyError(f"unknown dataset {dsid!r}")
    return DATASETS[dsid]


def supports_batch(ds):
    """True if ds can nearest-cell sample many points from one box request."""
    return hasattr(ds, "box_field")


def batch_sample(ds, points, var, date, margin=0.1):
    """Sample `var` at many (lat, lon) points for one date with a SINGLE gridded
    box request covering all of them (nearest cell each), instead of one request
    per point. Returns (snapped_date, [value|None ...]) aligned with `points`.
    Same source + nearest-cell method as ds.point_series — just amortised."""
    la = np.array([p[0] for p in points], dtype="f8")
    lo = np.array([p[1] for p in points], dtype="f8")
    lats, lons, arr = ds.box_field(
        date, var, float(lo.min() - margin), float(la.min() - margin),
        float(lo.max() + margin), float(la.max() + margin))
    ii = np.abs(lats[:, None] - la[None, :]).argmin(axis=0)
    jj = np.abs(lons[:, None] - lo[None, :]).argmin(axis=0)
    vals = arr[ii, jj]
    return ds.nearest_date(date), [
        None if math.isnan(float(v)) else round(float(v), 3) for v in vals]


def dataset_meta(ds, with_dates=False):
    w, e, s, n, _, _ = ds.image_geom()
    meta = {
        "id": ds.id, "name": ds.name, "resolution_label": ds.resolution_label,
        "variables": {k: v["label"] for k, v in ds.variables.items()},
        "bounds": list(ds.bounds) if ds.bounds else None,
        "overlay_bounds": [[s, w], [n, e]],
        "remote": isinstance(ds, ErddapMixin),
        "batch": supports_batch(ds),
        "mb_per_field": ds.mb_per_field,
        "ice_threshold": ICE_THRESHOLD,
        # tiled datasets have no whole-grid image: the client must send a bbox
        # and watch a tile job, so it needs to know before asking.
        "tiled": hasattr(ds, "mosaic_idx"),
        "tile_deg": getattr(ds, "TILE", None),
        "max_bounds": [[PACIFIC[1], PACIFIC[0]], [PACIFIC[3], PACIFIC[2]]],
        # The real grid, so the map can draw cell EDGES rather than guess the
        # spacing from resolution_label. lat0/lon0 are cell CENTRES, so an edge
        # sits at lat0 + (k + 0.5)*dlat -- half a cell off from the round
        # numbers. Drawing on the round numbers puts every line through the
        # middle of a cell, which looks plausible and is wrong by 500 m.
        "grid": {"lat0": ds.lat0, "lon0": ds.lon0,
                 "dlat": ds.dlat, "dlon": ds.dlon},
    }
    if with_dates:
        meta["dates"] = ds.dates()
    return meta


# ------------------------------------------------------------------ rendering

def _m(lat):
    lat = max(-MERC_LAT, min(MERC_LAT, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


# ------------------------------------------------ Mercator overlay lattice
#
# Web Mercator stretches latitude: a data row of dlat degrees occupies
# dlat_rad/cos(phi) Mercator units, SHORTEST at the latitude nearest the
# equator. Sampling output rows evenly in Mercator y and rounding each to the
# nearest data row (what this file did until now) therefore skips rows, and
# makes one cell 1 px and its neighbour 2 px depending on where the samples
# happen to fall -- which is why blocks changed size and jumped when the
# rendered box changed.
#
# The output grid is instead a lattice fixed PER DATASET:
#
#     S    = cos(phi_eq) / dlat_rad                 pixels per Mercator unit
#     P(k) = round(S * m(lat0 + (k - 0.5) * dlat))  pixel edge of data row k
#
# phi_eq is the dataset latitude nearest the equator, so S is the smallest
# scale at which every row spans >= 1 px. P's argument then rises by >= 1 per
# row and round() is monotone, so P(k+1) - P(k) >= 1: NO row is ever dropped.
# Longitude is linear in Mercator, so a column is exactly 1 px.
#
# Pixel edges ARE cell edges, so the map's grid lines (lat0 + (k+0.5)*dlat)
# land on block boundaries -- provided the image is placed at the cell-edge
# bounds returned here, not at the cell-CENTRE box that was asked for.
# And because S and the rounding origin are dataset constants, a given cell
# gets the same height and the same pixel offset from every other cell in
# EVERY window that contains it: panning or zooming cannot move or resize it.
#
# Cost: vertical oversampling is 1/cos(phi) against the data. The binding
# limit is MAX_OVERLAY_SIDE (4096 px a side, the most the browser draws
# unresampled), not the pixel total: the whole study region (135..165E,
# 40..65N, 2500x3000 cells) would be 4260 rows at d = 1, so it comes out at
# d = 2. Past a cap the lattice is divided by an integer power of two
# (d data cells per pixel, blocks anchored on the GLOBAL lattice so they still
# do not slide), never a fractional resample: cells stay uniform, they just
# get coarser -- and only at zooms where they are sub-pixel on screen anyway.
# The extreme is the whole Pacific box at once, 9000x20000 cells -> d = 8.
MAX_OVERLAY_PX = 24_000_000
# ...and no side longer than this. Chrome silently resamples any image taller
# (or wider) than 4096 px to 4096 before drawing it -- measured: a 500x6579
# MUR tile came out with its row edges on multiples of 47908/4096 screen px,
# not 47908/6579 -- so every block slid up to half a cell off the grid lines,
# which are computed from the ORIGINAL row count. Keeping each side <= 4096
# means the browser draws the pixels this file actually placed.
MAX_OVERLAY_SIDE = 4096

# Bumped whenever the lattice above changes shape. It is part of every
# rendered filename because nothing else in those names describes the
# geometry: without it a PNG rasterised by the previous resampler is served
# forever under the name the new one asks for -- with the new bounds, which
# is the old bug plus a half-cell shift. Old files simply go unreferenced.
# PNG rows per data row at the equator. One row per cell is NOT enough: a cell
# at 53.5N is 1/cos(53.5) = 1.68 rows tall, and rounding that to a whole 2 rows
# makes it 19% too tall -- ~7 px of slip against the grid at zoom 12, with cells
# alternating 1 and 2 rows to average out. That ragged alternation is what shows
# as the imagery drifting off the grid lines. Oversampling by 8 cuts the
# quantisation error to at most 1/16 of a cell (well under a screen pixel at any
# zoom where cells are visible at all). It costs 8x the PNG rows, which is only
# spent on the small boxes you get when zoomed in -- wide boxes hit the pixel
# cap and step the oversample back down, and at those zooms cells are sub-pixel
# and the grid is hidden anyway.
ROW_OVERSAMPLE = 8

LATTICE_V = "m4"


def _merc_scale(ds):
    """Output pixels per Mercator unit for this dataset (the S above)."""
    s, n = (ds.bounds[1], ds.bounds[3]) if ds.bounds else (-90.0, 90.0)
    phi = 0.0 if s <= 0.0 <= n else min(abs(s), abs(n))
    return math.cos(math.radians(phi)) / math.radians(ds.dlat)


def _row_edge_m(ds, k):
    """Mercator y of the SOUTH edge of data row k (array in, array out),
    clipped to the Mercator limit -- rows past it have nowhere to go."""
    lat = np.clip(ds.lat0 + (np.asarray(k, dtype="f8") - 0.5) * ds.dlat,
                  -MERC_LAT, MERC_LAT)
    return np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def _merc_plan(ds, i0, ni, j0, nj, max_px=MAX_OVERLAY_PX):
    """(row oversample, cell divisor) this window will be rendered with.

    Both are powers of two on the dataset's own lattice, so two windows that
    come back with the SAME pair place every cell identically -- that is the
    property that stops cells moving when the map zooms. Split out from
    _merc_map so tests can assert on the choice instead of reverse-engineering
    it from pixel counts."""
    scale = _merc_scale(ds)
    over, div = ROW_OVERSAMPLE, 1
    while True:
        b0, b1 = i0 // div, -(-(i0 + ni) // div)
        c0, c1 = j0 // div, -(-(j0 + nj) // div)
        k = np.arange(b0, b1 + 1) * div
        px = np.rint(_row_edge_m(ds, k) * (scale * over / div)).astype(np.int64)
        h, w = int(np.diff(px).sum()), int(c1 - c0)
        if h * w <= max_px and max(h, w) <= MAX_OVERLAY_SIDE:
            return over, div
        # Spend the oversample first: it is pure rendering accuracy and costs
        # nothing to give back. Only once it is gone do we start merging real
        # data cells, which is the step that actually loses information.
        if over > 1:
            over //= 2
        elif div < 64:
            div *= 2
        else:
            return over, div


def _merc_map(ds, i0, ni, j0, nj, max_px=MAX_OVERLAY_PX):
    """Resample data rows i0..i0+ni-1, cols j0..j0+nj-1 onto the overlay.

    Returns (rows, cols, (s, w, n, e)): fancy indices RELATIVE to (i0, j0),
    rows top-down (row 0 = north), and the true cell-edge bounds the PNG has
    to be stretched between for its blocks to sit on the real cells."""
    over, div = _merc_plan(ds, i0, ni, j0, nj, max_px)
    scale = _merc_scale(ds)
    b0, b1 = i0 // div, -(-(i0 + ni) // div)   # block range on the GLOBAL
    c0, c1 = j0 // div, -(-(j0 + nj) // div)   # lattice, not this window's
    k = np.arange(b0, b1 + 1) * div            # data row at each block edge
    px = np.rint(_row_edge_m(ds, k) * (scale * over / div)).astype(np.int64)
    counts = np.diff(px)
    src = np.clip(k[:-1] + div // 2 - i0, 0, ni - 1)   # row a block samples
    rows = np.repeat(src, counts)[::-1]                # image row 0 = north
    cols = np.clip(np.arange(c0, c1) * div + div // 2 - j0, 0, nj - 1)
    return rows, cols, (
        max(-MERC_LAT, ds.lat0 + (b0 * div - 0.5) * ds.dlat),
        ds.lon0 + (c0 * div - 0.5) * ds.dlon,
        min(MERC_LAT, ds.lat0 + (b1 * div - 0.5) * ds.dlat),
        ds.lon0 + (c1 * div - 0.5) * ds.dlon)


_MERC_IDX_CACHE = {}


def _merc_indices_cached(ds):
    """Whole-grid (rows, cols, bounds). Cached per dataset: it never changes
    and it is the hot path for OISST."""
    if ds.id not in _MERC_IDX_CACHE:
        _MERC_IDX_CACHE[ds.id] = _merc_map(ds, 0, ds.nlat, 0, ds.nlon)
    return _MERC_IDX_CACHE[ds.id]


def _auto_scale(data, diverging):
    valid = data[~np.isnan(data)]
    if valid.size == 0:
        return (0.0, 1.0)
    lo, hi = np.percentile(valid, [2, 98])
    if diverging:
        m = max(abs(lo), abs(hi), 0.1)
        return (-round(m * 2) / 2, round(m * 2) / 2)
    return (float(np.floor(lo * 2) / 2), float(np.ceil(hi * 2) / 2))


def _colorize(ds, data, var, vmin, vmax, land=None, ice=None):
    """data -> RGBA uint8, same shape. `land` and `ice` are arrays over the SAME
    window as data (None = not applicable).

    A dataset with no land mask (MUR) cannot tell "land" from "no data", so its
    NaNs go transparent and the basemap shows through -- guessing gray there
    would paint every coastline and lake as a data outage."""
    spec = ds.variables.get(var) or MUR_VARS["sea_ice_fraction"]
    norm = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax)
    cmap = matplotlib.cm.get_cmap(spec["cmap"])
    rgba = (cmap(norm(np.nan_to_num(data, nan=vmin))) * 255).astype(np.uint8)
    nan = np.isnan(data)
    if land is not None:
        rgba[nan & ~land] = NODATA_RGBA
    if ice is not None:
        icy = (~np.isnan(ice)) & (ice >= ICE_THRESHOLD)
        if land is not None:
            icy &= ~land
        rgba[icy] = ICE_RGBA
    if land is not None:
        rgba[land] = LAND_RGBA
    else:
        rgba[nan] = LAND_RGBA
    return rgba


def lattice_for(dsid, bbox=None):
    """The exact raster lattice the overlay for `bbox` is drawn on.

    The map's grid overlay has to draw the boundaries the IMAGERY actually
    has, not the mathematically true ones. Those differ: a cell edge is
    rasterised to a whole output row, so it lands up to half a row from truth
    -- about 40 m for MUR, invisible on the ground but several screen pixels
    once you are zoomed in past z12, which reads as the grid sliding off the
    squares. Giving the client `scale` lets it snap each line to the same
    rint() the renderer used, so the two agree exactly at every zoom.

    Returns {scale, over, div, lat0, dlat, lon0, dlon}: a latitude L is drawn
    at Minv(rint(scale*L_mercator)/scale), and columns step by `div` cells."""
    ds = get_dataset(dsid)
    if not hasattr(ds, "mosaic_idx") or bbox is None:
        i0, ni, j0, nj = 0, ds.nlat, 0, ds.nlon
    else:
        tiles = ds.tiles_for(*bbox)
        if not tiles:
            raise ValueError("bbox does not intersect dataset bounds")
        T = ds.TILE
        s_, n_ = min(t[0] for t in tiles), max(t[0] for t in tiles) + T
        w_, e_ = min(t[1] for t in tiles), max(t[1] for t in tiles) + T
        i0 = int(round((s_ - ds.lat0) / ds.dlat))
        j0 = int(round((w_ - ds.lon0) / ds.dlon))
        ni = min(int(round((n_ - s_) / ds.dlat)), ds.nlat - i0)
        nj = min(int(round((e_ - w_) / ds.dlon)), ds.nlon - j0)
    over, div = _merc_plan(ds, i0, ni, j0, nj)
    return {"scale": _merc_scale(ds) * over / div, "over": over, "div": div,
            "lat0": ds.lat0, "dlat": ds.dlat, "lon0": ds.lon0, "dlon": ds.dlon}


def _render_box(ds, date, var, vmin, vmax, bbox):
    """Overlay for one bbox of a tiled dataset, snapped OUTWARD to whole tiles.
    Snapping is what makes panning cheap: every viewport inside the same tiles
    hits the same PNG on disk."""
    tiles = ds.tiles_for(*bbox)
    if not tiles:
        raise ValueError("bbox does not intersect dataset bounds")
    T = ds.TILE
    s, n = min(t[0] for t in tiles), max(t[0] for t in tiles) + T
    w, e = min(t[1] for t in tiles), max(t[1] for t in tiles) + T
    i0 = int(round((s - ds.lat0) / ds.dlat))
    j0 = int(round((w - ds.lon0) / ds.dlon))
    ni = min(int(round((n - s) / ds.dlat)), ds.nlat - i0)
    nj = min(int(round((e - w) / ds.dlon)), ds.nlon - j0)
    i1, j1 = i0 + ni - 1, j0 + nj - 1
    # Built up front because `bounds` is part of what a cache hit returns.
    # Cheap: a few thousand logs, no per-pixel arctan.
    rows, cols, bounds = _merc_map(ds, i0, ni, j0, nj)
    # The tile count belongs in the cache key. The client renders the box once
    # BEFORE its tile job runs (selectDataset -> setDate -> refreshOverlay), so
    # without this the first, empty render would be cached under the name the
    # finished render wants -- and the area would stay blank forever.
    have = sum(ds.tile_cached(date, var, t) for t in tiles)
    tag = f"b{s:g}_{w:g}_{n:g}_{e:g}_k{have}"

    if vmin is not None and vmax is not None:
        out = CACHE / f"{ds.id}_{date}_{var}_{vmin:g}_{vmax:g}_{tag}_{LATTICE_V}.png"
        if out.exists():
            return out, vmin, vmax, date, bounds
    data = ds.mosaic_idx(date, var, i0, i1, j0, j1)
    if vmin is None or vmax is None:
        spec = ds.variables.get(var) or MUR_VARS["sea_ice_fraction"]
        vmin, vmax = _auto_scale(data, spec["diverging"])
    out = CACHE / f"{ds.id}_{date}_{var}_{vmin:g}_{vmax:g}_{tag}_{LATTICE_V}.png"
    if out.exists():
        return out, vmin, vmax, date, bounds

    land = ds.land()
    if land is not None:
        land = land[i0:i1 + 1, j0:j1 + 1]
    ice = None
    if ds.ice_var and var != ds.ice_var:
        ice = ds.mosaic_idx(date, ds.ice_var, i0, i1, j0, j1)
    rgba = _colorize(ds, data, var, vmin, vmax, land, ice)
    Image.fromarray(rgba[np.ix_(rows, cols)], "RGBA").save(out)
    return out, vmin, vmax, date, bounds


def render_overlay(dsid, date, var, vmin=None, vmax=None, bbox=None):
    """Return (png_path, vmin, vmax, date, bounds). Cached on disk. Snaps the
    date to the dataset's available dates.

    CALLERS BEWARE: this tuple grew from 4 to 5 elements. `bounds` is
    (s, w, n, e) -- Leaflet order -- of what was ACTUALLY rendered, and is what
    feeds the X-Bounds response header; app.py and reports.py must unpack it.
    It is the CELL-EDGE box of the drawn pixels, so it sits half a cell outside
    the tile/grid box that was asked for; placing the PNG anywhere else puts
    every block half a cell off the grid lines the map draws.

    bbox=(w, s, e, n) is honoured only for tiled datasets (those with
    mosaic_idx): the box is snapped outward to the tile grid and only those
    tiles are drawn. Tiles not yet fetched come out NaN, so a partly downloaded
    region still renders. For everything else bbox is ignored and the whole
    grid is drawn, exactly as before."""
    ds = get_dataset(dsid)
    if var not in ds.variables and var != ds.ice_var:
        raise ValueError(f"unknown variable {var!r} for {dsid}")
    date = ds.nearest_date(date)
    if bbox and hasattr(ds, "mosaic_idx"):
        return _render_box(ds, date, var, vmin, vmax, bbox)

    rows, cols, bounds = _merc_indices_cached(ds)
    if vmin is not None and vmax is not None:
        out = CACHE / f"{dsid}_{date}_{var}_{vmin:g}_{vmax:g}_{LATTICE_V}.png"
        if out.exists():
            return out, vmin, vmax, date, bounds

    spec = ds.variables.get(var) or MUR_VARS["sea_ice_fraction"]
    data = ds.grid(date, var)
    if vmin is None or vmax is None:
        vmin, vmax = _auto_scale(data, spec["diverging"])
    out = CACHE / f"{dsid}_{date}_{var}_{vmin:g}_{vmax:g}_{LATTICE_V}.png"
    if out.exists():
        return out, vmin, vmax, date, bounds

    ice = ds.grid(date, ds.ice_var) if ds.ice_var and var != ds.ice_var else None
    rgba = _colorize(ds, data, var, vmin, vmax, ds.land(), ice)
    Image.fromarray(rgba[np.ix_(rows, cols)], "RGBA").save(out)
    return out, vmin, vmax, date, bounds


# ---------------------------------------------------------------- tile jobs

TILE_JOBS = {}            # job id -> {"state", "done", "total", "error"}
MAX_JOB_TILES = 200       # ~200 MB and ~10 min at one tile at a time: enough
                          # for a continent-sized view, short of a multi-GB run


def _run_tile_job(ds, date, missing, job):
    # Strictly one tile at a time. ERDDAP is a shared public service and a
    # parallel fan-out from a single client is exactly what health.py goes out
    # of its way to avoid -- the progress bar is what buys us the patience.
    for var, tile in missing:
        try:
            ds.fetch_tile(date, var, tile)
        except RemoteError as e:
            job["error"] = str(e)[:300]
            job["state"] = "error"
            return
        job["done"] += 1
    job["state"] = "done"


def start_tile_job(dsid, date, bbox, varz=None):
    """Fetch every tile the bbox needs, in a daemon thread.
    Returns (job_id, total). total == 0 means the job is already done."""
    ds = get_dataset(dsid)
    date = ds.nearest_date(date)
    missing = ds.missing_tiles(date, *bbox, varz=varz)
    jid = uuid.uuid4().hex[:8]
    job = {"state": "done", "done": 0, "total": len(missing), "error": None}
    if len(TILE_JOBS) > 200:   # ponytail: finished jobs pile up; drop them all
        TILE_JOBS.clear()      # once the dict gets silly, no LRU needed
    TILE_JOBS[jid] = job
    if not missing:
        return jid, 0
    if len(missing) > MAX_JOB_TILES:
        job["state"] = "error"
        job["error"] = (f"{len(missing)} tiles is too much to download at once "
                        f"(limit {MAX_JOB_TILES}) - zoom in further")
        return jid, len(missing)
    job["state"] = "running"
    threading.Thread(target=_run_tile_job, args=(ds, date, missing, job),
                     daemon=True).start()
    return jid, len(missing)


def render_colorbar(dsid, var):
    """Horizontal 256x14 color strip PNG bytes for the legend."""
    ds = get_dataset(dsid)
    if var not in ds.variables:
        raise ValueError(f"unknown variable {var!r}")
    cmap = matplotlib.cm.get_cmap(ds.variables[var]["cmap"])
    strip = (cmap(np.linspace(0, 1, 256))[None, :, :] * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(strip, "RGBA").resize((256, 14), Image.NEAREST).save(buf, "PNG")
    return buf.getvalue()


def _crop_to_bbox(img, ds, bbox, extent=None):
    """Crop a rendered overlay image to bbox intersected with the image extent.
    `extent` is (w, e, s, n) of what the image actually covers -- a tiled
    dataset renders one snapped box, not the whole grid, so it must say so."""
    w0, e0, s0, n0 = extent or ds.image_geom()[:4]
    wpx, h = img.size
    w, s, e, n = bbox
    if hasattr(ds, "_nlon"):          # tiled grids live in the 95..295 frame
        w, e = ds._nlon(w), ds._nlon(e)
        if e < w:
            e += 360.0
    w, e = max(w, w0), min(e, e0)
    s, n = max(s, s0), min(n, n0)
    if w >= e or s >= n:
        raise ValueError("bbox does not intersect dataset bounds")
    x0 = int((w - w0) / (e0 - w0) * wpx)
    x1 = int(math.ceil((e - w0) / (e0 - w0) * wpx))
    y0 = int((_m(n0) - _m(n)) / (_m(n0) - _m(s0)) * h)
    y1 = int(math.ceil((_m(n0) - _m(s)) / (_m(n0) - _m(s0)) * h))
    return img.crop((max(0, x0), max(0, y0), min(wpx, x1), min(h, y1)))


def _gray_land(img):
    gray = Image.new("RGBA", img.size, (70, 70, 70, 255))
    gray.paste(img, (0, 0), img)  # transparent (land) -> gray
    return gray


# The frame date used to be PIL's default bitmap font in plain white -- about
# 11 px on a 500+ px frame, and invisible over pale water. Scale it to the
# frame and give it a black outline so it reads on ice, cloud or open sea.
_FONT_CANDIDATES = ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _stamp_font(width):
    size = max(14, round(width / 22))
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _export_overlay(dsid, date, var, vmin, vmax, bbox):
    """(RGBA image cropped to bbox, snapped date) for GIF/PNG export. A tiled
    dataset has no whole-grid image, so it always goes through the bbox path --
    and therefore cannot export without one."""
    ds = get_dataset(dsid)
    tiled = hasattr(ds, "mosaic_idx")
    if tiled and not bbox:
        raise ValueError(f"{dsid} is tiled - an export needs a bbox")
    png, _, _, date, (s, w, n, e) = render_overlay(
        dsid, date, var, vmin, vmax, bbox=bbox if tiled else None)
    img = Image.open(png).convert("RGBA")
    return img, date, (w, e, s, n)


# An export is not a render: the GIF/PNG paths reach for dates the user has
# never had on screen, so their tiles are not on disk and every frame would
# come out blank. Fetch what they need first -- but bound it, because 132
# frames x 30 tiles x 2 variables is 8 GB, not an export.
MAX_EXPORT_TILES = 400            # ~400 MB


def ensure_export_tiles(ds, dates, bbox):
    """Pull every tile the given dates need over bbox. Tiled datasets only."""
    if not hasattr(ds, "fetch_tile"):
        return
    want = [(d, v, t) for d in dates
            for v, t in ds.missing_tiles(ds.nearest_date(d), *bbox)]
    if len(want) > MAX_EXPORT_TILES:
        raise RemoteError(
            f"this export needs {len(want)} MUR tiles (~{len(want)} MB) — "
            "zoom in further or export fewer frames")
    for d, v, t in want:
        ds.fetch_tile(ds.nearest_date(d), v, t)


def export_gif(dsid, dates, var, vmin, vmax, bbox=None, fps=4, out=None):
    """Animated GIF of overlay frames (land gray: no basemap in the export)."""
    ds = get_dataset(dsid)
    if bbox:
        ensure_export_tiles(ds, dates, bbox)
    frames = []
    for d in dates:
        img, _, extent = _export_overlay(dsid, d, var, vmin, vmax, bbox)
        img = _gray_land(img)
        if bbox:
            img = _crop_to_bbox(img, ds, bbox, extent)
        if img.width < 500:
            k = max(1, round(500 / img.width))
            img = img.resize((img.width * k, img.height * k), Image.NEAREST)
        pad = max(6, img.width // 60)
        ImageDraw.Draw(img).text((pad, pad), d, font=_stamp_font(img.width),
                                 fill=(255, 255, 255, 255), stroke_width=2,
                                 stroke_fill=(0, 0, 0, 255))
        frames.append(img.convert("P", palette=Image.ADAPTIVE))
    if out is None:
        out = CACHE / f"timelapse_{dsid}_{dates[0]}_{dates[-1]}_{var}_{len(dates)}f_{LATTICE_V}.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=max(40, int(1000 / fps)), loop=0)
    return out


def snapshot_png(dsid, date, var, vmin, vmax, bbox, out):
    """Overlay cropped to bbox, saved as PNG (keeps transparency for land)."""
    if bbox:
        ensure_export_tiles(get_dataset(dsid), [date], bbox)
    img, date, extent = _export_overlay(dsid, date, var, vmin, vmax, bbox)
    img = _crop_to_bbox(img, get_dataset(dsid), bbox, extent)
    if img.width < 500:
        k = max(1, round(500 / img.width))
        img = img.resize((img.width * k, img.height * k), Image.NEAREST)
    img.save(out)
    return out, date


# ---------------------------------------------------------------- timelapse

def playback_dates(dsid, start, end, gap_days=1, same_day_each_year=False):
    """List of available dates for playback. gap_days steps N calendar days,
    snapping to the nearest available date; same_day_each_year walks the same
    month/day across years (leap-safe, unlike gap=365)."""
    avail = [d for d in get_dataset(dsid).dates() if start <= d <= end]
    if not avail:
        return []
    if same_day_each_year:
        md = start[5:]
        return [d for d in avail if d[5:] == md]
    if gap_days <= 1:
        return avail
    out, cur = [], Date.fromisoformat(avail[0])
    last = Date.fromisoformat(avail[-1])
    avail_d = [Date.fromisoformat(d) for d in avail]
    while cur <= last:
        nearest = min(avail_d, key=lambda d: abs((d - cur).days))
        iso = nearest.isoformat()
        if not out or out[-1] != iso:
            out.append(iso)
        cur += timedelta(days=gap_days)
    return out


# ------------------------------------------------------------- area geometry

def area_bbox(geom):
    """(w, s, e, n) of a saved geometry; points get a ~1 deg pad for media."""
    t = geom["type"]
    if t == "point":
        return (geom["lon"] - 1, geom["lat"] - 0.7, geom["lon"] + 1, geom["lat"] + 0.7)
    if t == "rect":
        return (geom["w"], geom["s"], geom["e"], geom["n"])
    if t == "circle":
        dlat = geom["radius_m"] / 111_000
        dlon = geom["radius_m"] / (111_000 * max(0.1, math.cos(math.radians(geom["lat"]))))
        return (geom["lon"] - dlon, geom["lat"] - dlat,
                geom["lon"] + dlon, geom["lat"] + dlat)
    if t == "polygon":
        lats = [p[0] for p in geom["latlngs"]]
        lons = [p[1] for p in geom["latlngs"]]
        return (min(lons), min(lats), max(lons), max(lats))
    raise ValueError(f"unknown geometry type {t!r}")


def _haversine_km(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    dlat, dlon = (lat2 - lat1) * r, (lon2 - lon1) * r
    h = np.sin(dlat / 2) ** 2 + \
        math.cos(lat1 * r) * np.cos(lat2 * r) * np.sin(dlon / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(h))


def _geom_mask(geom, lats, lons):
    """Bool mask over the (lats x lons) cell-center grid."""
    LO, LA = np.meshgrid(lons, lats)
    t = geom["type"]
    if t == "rect":
        return np.ones(LA.shape, bool)  # bbox slice already is the rect
    if t == "circle":
        d = _haversine_km(geom["lat"], geom["lon"], LA, LO)
        return d <= geom["radius_m"] / 1000
    if t == "polygon":
        path = MplPath([(p[1], p[0]) for p in geom["latlngs"]])
        pts = np.column_stack([LO.ravel(), LA.ravel()])
        return path.contains_points(pts).reshape(LA.shape)
    raise ValueError(f"unknown geometry type {t!r}")


def area_mean_series(dsid, geom, var, start=None, end=None):
    """Spatial-mean series of var over the geometry's cells. For remote
    datasets only cached fields contribute (no implicit bulk downloads)."""
    ds = get_dataset(dsid)
    if geom["type"] == "point":
        return ds.point_series(geom["lat"], geom["lon"], var, start, end)
    w, s, e, n = area_bbox(geom)
    if ds.bounds:
        bw, bs, be, bn = ds.bounds
        w, s, e, n = max(w, bw), max(s, bs), min(e, be), min(n, bn)
    i0, i1, j0, j1 = ds.bbox_to_idx(w, s, e, n)
    lats, lons = ds.cell_latlons(i0, i1, j0, j1)
    mask = _geom_mask(geom, lats, lons)
    if not mask.any():
        return []
    rows = []
    for d in ds.dates():
        if (start and d < start) or (end and d > end):
            continue
        if not ds.field_available(d, var):
            continue
        sub = ds.subgrid(d, var, i0, i1, j0, j1)
        vals = sub[mask]
        vals = vals[~np.isnan(vals)]
        rows.append({"date": d,
                     "value": round(float(vals.mean()), 3) if vals.size else None})
    return rows
