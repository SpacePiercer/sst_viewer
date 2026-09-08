"""Data access layer for sst_viewer v2.

Registry of gridded datasets (DATASETS), each a small object with the same
interface:
    id, name, resolution_label, variables, bounds (None = global),
    dates(), grid(date, var), point_values(...), point_series(...),
    field_available(date, var), ensure_field(date)

  - oisst_local : NOAA OISST 0.25 deg from the local .nc files (offline).
  - oisst_remote: same grid via NOAA ERDDAP griddap, Sept 1981 - present.
  - mur_okhotsk : GHRSST MUR 0.01 deg via ERDDAP. Map fields use the fixed
    Okhotsk box (a global 1 km field would be GBs/date); point values and
    series are tiny single-pixel requests and work anywhere on the globe.

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
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OISST_DIR = HERE / "data" / "oisst_may20_july1"  # self-contained, no cross-folder deps
CACHE = HERE / "cache"
FIELDS = CACHE / "fields"
LIBRARY = HERE / "library"          # user content: NOT under cache/
CACHE.mkdir(exist_ok=True)
FIELDS.mkdir(exist_ok=True)
LIBRARY.mkdir(exist_ok=True)

ICE_THRESHOLD = 0.15          # standard 15% sea-ice concentration cutoff
MERC_LAT = 85.05112878        # Web Mercator latitude limit
ICE_RGBA = (232, 244, 248, 255)      # pale ice blue-white  #e8f4f8
NODATA_RGBA = (153, 153, 153, 255)   # mid gray             #999999
LAND_RGBA = (0, 0, 0, 0)             # transparent, basemap shows through

# upwell.pfeg.noaa.gov (161.55.160.6) is the same PFEG ERDDAP on a second
# machine and serves byte-identical data -- a drop-in fallback if this host
# goes down again, as it did for three weeks in Aug-Sep 2026.
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
    mask = np.isnan(_read_field(oisst_index()[sorted(oisst_index())[0]], "sst"))
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
        """(west, east, south, north, w_px, h_px) of the rendered overlay."""
        if self.bounds is None:
            return -180.0, 180.0, -MERC_LAT, MERC_LAT, self.nlon, 1200
        w, s, e, n = self.bounds
        my = _m(n) - _m(s)
        mx = math.radians(e - w)
        if my >= mx:
            h = 1500
            wpx = max(1, round(1500 * mx / my))
        else:
            wpx = 1500
            h = max(1, round(1500 * my / mx))
        return w, e, s, n, wpx, h

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


class OisstLocal(OisstBase):
    id = "oisst_local"
    name = "NOAA OISST v2.1 (local)"
    resolution_label = "0.25°"

    def dates(self):
        return sorted(oisst_index())

    def grid(self, date, var):
        path = oisst_index().get(date)
        if path is None:
            raise KeyError(f"no OISST file for {date}")
        return _read_field(path, var)

    def field_available(self, date, var):
        return date in oisst_index()

    def subgrid(self, date, var, i0, i1, j0, j1):
        return _oisst_nc_subgrid(oisst_index()[date], var, i0, i1, j0, j1)

    @functools.lru_cache(maxsize=256)
    def _full_series(self, var, i, j):
        """Value of one grid cell across every indexed OISST date.
        ponytail: opens all ~1100 files sequentially (~10-30 s first call per
        point); lru-cached in memory. Precompute to parquet if it ever hurts."""
        jj = (j + 720) % 1440  # back to native 0..360 lon order
        vals = []
        for d in self.dates():
            with netCDF4.Dataset(oisst_index()[d]) as ds:
                v = ds.variables[var][0, 0, i, jj]
            v = float(v) if v is not np.ma.masked else None
            vals.append((d, v))
        return tuple(vals)

    def point_series(self, lat, lon, var="sst", start=None, end=None):
        i, j = self.nearest_ocean_idx(*self.latlon_to_idx(lat, lon))
        return [{"date": d, "value": v} for d, v in self._full_series(var, i, j)
                if (start is None or d >= start) and (end is None or d <= end)]


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


class MurOkhotsk(ErddapMixin, GriddedDataset):
    id = "mur_okhotsk"
    name = "GHRSST MUR 1 km"
    resolution_label = "0.01°"
    ERDDAP_ID = "jplMURSST41"
    bounds = (135.0, 40.0, 165.0, 65.0)   # map-field box only; points are global
    variables = MUR_VARS
    ice_var = "sea_ice_fraction"
    ALL_VARS = ("analysed_sst", "sea_ice_fraction")
    mb_per_field = 120  # 2 vars x ~60 MB (float64 on the wire)

    lat0, dlat, nlat = 40.0, 0.01, 2501
    lon0, dlon, nlon = 135.0, 0.01, 3001

    def field_available(self, date, var):
        return _field_paths(self.id, date, var)[0].exists()

    def ensure_field(self, date):
        if all(self.field_available(date, v) for v in self.ALL_VARS):
            return "cached"
        date, t = self._iso_time(date)
        sub = f"%5B({t})%5D%5B(40.0):(65.0)%5D%5B(135.0):(165.0)%5D"
        url = f"{ERDDAP}/griddap/{self.ERDDAP_ID}.nc?" + \
              ",".join(v + sub for v in self.ALL_VARS)
        dest = CACHE / f"mur_dl_{uuid.uuid4().hex[:6]}.nc"
        try:
            _http_download(url, dest, timeout=60)  # ~120 MB, streamed
            with netCDF4.Dataset(dest) as ds:
                for v in self.ALL_VARS:
                    a = ds.variables[v][0, :, :].filled(np.nan)
                    save_field(self.id, date, v, a, self.bounds)
        finally:
            dest.unlink(missing_ok=True)
        return "downloaded"

    def grid(self, date, var):
        a = load_field(self.id, date, var)
        if a is None:
            self.ensure_field(date)
            a = load_field(self.id, date, var)
        return a

    def subgrid(self, date, var, i0, i1, j0, j1):
        a = load_field(self.id, date, var, mmap=True)
        if a is None:
            raise KeyError(f"field {date}/{var} not cached")
        return np.asarray(a[i0:i1 + 1, j0:j1 + 1])

    MAX_BOX_CELLS = 8_000_000  # one batch box request cap (~a 9x9 deg region at 0.01)

    def box_field(self, date, var, w, s, e, n, timeout=300):
        """Download an arbitrary (w,s,e,n) box of `var` for one date straight
        from ERDDAP and return (lats, lons, arr). This is the batch primitive:
        one request covers a whole region of points instead of one per point.
        Not limited to the fixed map box (points can be anywhere, e.g. Kamchatka
        east of 165E)."""
        cells = (abs(n - s) / self.dlat + 1) * (abs(e - w) / self.dlon + 1)
        if cells > self.MAX_BOX_CELLS:
            raise RemoteError(
                f"region too large for one batch request ({cells / 1e6:.0f}M cells) "
                "— narrow the coordinates or fetch in sub-regions")
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
        w, s, e, n = self.bounds
        inside = s <= lat <= n and w <= lon <= e
        if inside and all(self.field_available(date, v) for v in self.ALL_VARS):
            i, j = self.latlon_to_idx(lat, lon)
            vals = {}
            for v in self.ALL_VARS:
                x = float(self.grid(date, v)[i, j])
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
        # global single-pixel request — NOT limited to the map box
        lat = max(-89.99, min(89.99, lat))    # MUR grid edges
        lon = max(-179.99, min(180.0, lon))
        ax = self.dates()
        s0 = _nearest(ax, start) if start else ax[0]
        e0 = _nearest(ax, end) if end else ax[-1]
        axm = self.time_axis()
        rows = self._remote_series(var, round(lat, 3), round(lon, 3),
                                   axm[s0], axm[e0])
        return [{"date": d, "value": v} for d, v in rows]


DATASETS = {d.id: d for d in (OisstLocal(), OisstRemote(), MurOkhotsk())}


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
    }
    if with_dates:
        meta["dates"] = ds.dates()
    return meta


# ------------------------------------------------------------------ rendering

def _m(lat):
    lat = max(-MERC_LAT, min(MERC_LAT, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _merc_indices(ds):
    """(row_idx, col_idx) fancy indices mapping the data grid to the overlay
    image (row 0 = top/north). lru-cached per dataset via dict below."""
    w, e, s, n, wpx, h = ds.image_geom()
    ys = np.linspace(_m(n), _m(s), h, endpoint=False) + (_m(s) - _m(n)) / (2 * h)
    lats = np.degrees(np.arctan(np.sinh(ys)))
    rows = np.clip(np.round((lats - ds.lat0) / ds.dlat).astype(int), 0, ds.nlat - 1)
    lons = np.linspace(w, e, wpx, endpoint=False) + (e - w) / (2 * wpx)
    cols = np.clip(np.round((lons - ds.lon0) / ds.dlon).astype(int), 0, ds.nlon - 1)
    return rows, cols


_MERC_IDX_CACHE = {}


def _merc_indices_cached(ds):
    if ds.id not in _MERC_IDX_CACHE:
        _MERC_IDX_CACHE[ds.id] = _merc_indices(ds)
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


def render_overlay(dsid, date, var, vmin=None, vmax=None):
    """Return (png_path, vmin, vmax, date). Cached on disk. Snaps the date to
    the dataset's available dates."""
    ds = get_dataset(dsid)
    if var not in ds.variables and var != ds.ice_var:
        raise ValueError(f"unknown variable {var!r} for {dsid}")
    date = ds.nearest_date(date)
    if vmin is not None and vmax is not None:
        out = CACHE / f"{dsid}_{date}_{var}_{vmin:g}_{vmax:g}.png"
        if out.exists():
            return out, vmin, vmax, date

    spec = ds.variables.get(var) or MUR_VARS["sea_ice_fraction"]
    data = ds.grid(date, var)
    if vmin is None or vmax is None:
        vmin, vmax = _auto_scale(data, spec["diverging"])
    out = CACHE / f"{dsid}_{date}_{var}_{vmin:g}_{vmax:g}.png"
    if out.exists():
        return out, vmin, vmax, date

    land = ds.land()
    nodata = np.isnan(data) & ~land if land is not None else np.zeros(data.shape, bool)
    norm = matplotlib.colors.Normalize(vmin=vmin, vmax=vmax)
    cmap = matplotlib.cm.get_cmap(spec["cmap"])
    rgba = (cmap(norm(np.nan_to_num(data, nan=vmin))) * 255).astype(np.uint8)
    rgba[nodata] = NODATA_RGBA
    if ds.ice_var and var != ds.ice_var:
        ice = ds.grid(date, ds.ice_var)
        icy = (~np.isnan(ice)) & (ice >= ICE_THRESHOLD)
        if land is not None:
            icy &= ~land
        rgba[icy] = ICE_RGBA
    if land is not None:
        rgba[land] = LAND_RGBA
    else:
        rgba[np.isnan(data)] = LAND_RGBA  # MUR: masked = land/lake, basemap shows
    rows, cols = _merc_indices_cached(ds)
    rgba = rgba[np.ix_(rows, cols)]
    Image.fromarray(rgba, "RGBA").save(out)
    return out, vmin, vmax, date


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


def _crop_to_bbox(img, ds, bbox):
    """Crop a rendered overlay image to bbox intersected with the dataset's
    image extent."""
    w0, e0, s0, n0, wpx, h = ds.image_geom()
    w, s, e, n = bbox
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


def export_gif(dsid, dates, var, vmin, vmax, bbox=None, fps=4, out=None):
    """Animated GIF of overlay frames (land gray: no basemap in the export)."""
    ds = get_dataset(dsid)
    frames = []
    for d in dates:
        png, _, _, _ = render_overlay(dsid, d, var, vmin, vmax)
        img = _gray_land(Image.open(png).convert("RGBA"))
        if bbox:
            img = _crop_to_bbox(img, ds, bbox)
        if img.width < 500:
            k = max(1, round(500 / img.width))
            img = img.resize((img.width * k, img.height * k), Image.NEAREST)
        ImageDraw.Draw(img).text((8, 6), d, fill=(255, 255, 255, 255))
        frames.append(img.convert("P", palette=Image.ADAPTIVE))
    if out is None:
        out = CACHE / f"timelapse_{dsid}_{dates[0]}_{dates[-1]}_{var}_{len(dates)}f.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=max(40, int(1000 / fps)), loop=0)
    return out


def snapshot_png(dsid, date, var, vmin, vmax, bbox, out):
    """Overlay cropped to bbox, saved as PNG (keeps transparency for land)."""
    png, lo, hi, date = render_overlay(dsid, date, var, vmin, vmax)
    img = _crop_to_bbox(Image.open(png).convert("RGBA"), get_dataset(dsid), bbox)
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
