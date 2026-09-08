"""Generate groups of SST sample points along a coastline.

Approach (uses the global-land-mask library, ~1 km resolution):
  1. Extract the land/ocean boundary as one contour polyline.
  2. Resample it to uniform 1 km arc-length spacing.
  3. Walk the shore between the region's start and stop, skipping bay
     interiors, dropping a group every ~28 km.
  4. In each group, place 3 points 1/3/5 km offshore along the coast normal
     (perpendicular to the local shoreline, pointing into the ocean).
  5. Overwrite that region's .csv and .txt.

Usage:  python make_coast_points.py [kamchatka|primorsky]   (default kamchatka)
"""
import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from global_land_mask import globe

# --- parameters shared by all regions ------------------------------------
ALONG_KM = 28.0                   # spacing between groups, measured along the shore
OFFSETS_KM = (1.0, 3.0, 5.0)      # perpendicular distances offshore

# --- bay skipping --------------------------------------------------------
# A bay is a basin joined to the sea through a mouth much narrower than the
# basin. Two shore points that are close in a straight line (the two mouth
# headlands) but far apart along the shore, WITH open water on the straight
# line between them, bracket a bay -> the shore between them is skipped.
# (If that straight line crossed land it would be a peninsula/isthmus -> kept.)
MOUTH_KM = 6.0                    # max width of a mouth we treat as skippable
MIN_BAY_KM = 12.0                 # min along-shore excursion to count as a bay
MAX_BAY_KM = 400.0                # don't look for a mouth farther along than this

RES = 1 / 120.0
KM_PER_DEG = 111.32
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "..", "data")

# --- regions -------------------------------------------------------------
# start/stop are (lon, lat) seeds snapped to the nearest shore vertex.
# stop kinds:  ("lat_max", value) walk until latitude passes value;
#              ("point", (lon, lat)) walk until nearest to that cape.
REGIONS = {
    "kamchatka": dict(
        box=dict(lat0=51.0, lat1=62.9, lon0=156.0, lon1=179.5),
        start=(158.28, 52.0),               # south end of the east coast
        stop=("lat_max", 62.0),
        lat_min=52.0,
        out="kamchatka_east_coast_points",
    ),
    # Primorsky / S. Khabarovsk coast, split at Cape Zolotoy (each its own dates).
    "primorsky_south": dict(
        box=dict(lat0=44.5, lat1=48.75, lon0=135.5, lon1=141.0),
        start=(136.65, 45.00),              # 45.00 N on the open coast
        stop=("point", (138.986, 47.319)),  # Cape Zolotoy
        lat_min=None,
        # The land mask is wrong around Samarga/Yedinka (a phantom cape+bay from
        # a cloud/ice artifact), so drop the auto groups north of 47.0 N and pin
        # two manual groups whose 1/3/5 km points run due east from the real
        # village shore coordinates.
        drop_above_lat=47.0,
        manual_east=[
            (47.14588973140175, 138.71192685597427),  # Yedinka
            (47.24742578393870, 138.80889379244508),  # Samarga
        ],
        out="primorsky_south_coast_points",
    ),
    "primorsky_north": dict(
        box=dict(lat0=44.5, lat1=48.75, lon0=135.5, lon1=141.0),
        start=(138.986, 47.319),            # Cape Zolotoy
        stop=("point", (140.173, 48.452)),  # Cape Peschany (Sov. Gavan lighthouse)
        lat_min=None,
        out="primorsky_north_coast_points",
    ),
}


def enu_scale(lat):
    """meters-per-degree (east, north) at a latitude, in km."""
    return KM_PER_DEG * np.cos(np.radians(lat)), KM_PER_DEG


def extract_coast(box):
    lons = np.arange(box["lon0"], box["lon1"], RES)
    lats = np.arange(box["lat0"], box["lat1"], RES)
    LON, LAT = np.meshgrid(lons, lats)
    land = globe.is_land(LAT, LON).astype(float)
    cs = plt.contour(LON, LAT, land, levels=[0.5])
    segs = cs.allsegs[0]
    # the mainland coast is by far the longest contour in this box
    seg = max(segs, key=len)  # Nx2 (lon, lat)
    return seg


def resample_1km(coast):
    """Return coast resampled to ~1 km uniform arc length, ordered south->north."""
    lon, lat = coast[:, 0], coast[:, 1]
    # per-segment length in km (equirectangular)
    dx = np.diff(lon) * np.cos(np.radians(lat[:-1])) * KM_PER_DEG
    dy = np.diff(lat) * KM_PER_DEG
    s = np.concatenate([[0], np.cumsum(np.hypot(dx, dy))])
    n = int(s[-1])
    ss = np.linspace(0, s[-1], n)
    return np.column_stack([np.interp(ss, s, lon), np.interp(ss, s, lat)])


def outward_normal(lon, lat, tx, ty):
    """Pick the unit normal (east,north) that points into the ocean.

    Score each candidate by how much ocean lies along it vs. the far side,
    sampled across the full 0..5 km reach so a single noisy pixel can't flip it.
    """
    cands = [(ty, -tx), (-ty, tx)]
    ex, ey = enu_scale(lat)
    probes = np.arange(0.5, 5.1, 0.5)
    best, best_score = cands[0], -1e9
    for nx, ny in cands:
        near = sum(int(globe.is_ocean(lat + ny * d / ey, lon + nx * d / ex)) for d in probes)
        far = sum(int(globe.is_ocean(lat - ny * d / ey, lon - nx * d / ex)) for d in probes)
        score = near - far
        if score > best_score:
            best_score, best = score, (nx, ny)
    return best


def seaward_clear(plat, plon, nx, ny, d):
    """True if the ocean is open out to d km on the seaward side of the point.

    The origin coast sits ~d km directly behind the point, so we only inspect
    the seaward hemisphere (the half plane the outward normal points into).
    Any land there within d km means another shoreline -- an island, an
    opposite bay wall, a heavy wiggle -- is too close, so the point is dropped.
    """
    if globe.is_land(plat, plon):            # the point itself must be in the water
        return False
    ex, ey = enu_scale(plat)
    kk = np.arange(-d, d + 1e-9, RES * KM_PER_DEG)  # ~0.93 km spaced offsets, km
    DX, DY = np.meshgrid(kk, kk)                     # east, north
    sel = (np.hypot(DX, DY) <= d) & (DX * nx + DY * ny > 0)
    lats = plat + DY / ey
    lons = plon + DX / ex
    return not globe.is_land(lats[sel], lons[sel]).any()


def geo_km(a, b):
    """Straight-line distance in km between (lon,lat) points a and b."""
    return np.hypot((b[0] - a[0]) * np.cos(np.radians(a[1])) * KM_PER_DEG,
                    (b[1] - a[1]) * KM_PER_DEG)


def mouth_is_water(sub, i, j):
    """True if the straight line across a candidate mouth runs over open water."""
    t = np.linspace(0.1, 0.9, 9)
    lons = sub[i, 0] + t * (sub[j, 0] - sub[i, 0])
    lats = sub[i, 1] + t * (sub[j, 1] - sub[i, 1])
    return globe.is_ocean(lats, lons).mean() >= 0.85


def detect_bays(sub):
    """Mask over the 1 km shore path: False where the shore is bay interior.

    Walk the shore; at each point look ahead for the farthest point that is
    still within MOUTH_KM straight-line but >= MIN_BAY_KM along the shore and
    reachable across open water. That pair is a bay mouth -> drop everything
    between them and jump across.
    """
    n = len(sub)
    keep = np.ones(n, bool)
    lo, la = sub[:, 0], sub[:, 1]
    lo_min, lo_max = int(MIN_BAY_KM), int(MAX_BAY_KM)  # ~1 km per step
    i = 0
    while i < n:
        jhi = min(i + lo_max, n - 1)
        cos_i = np.cos(np.radians(la[i]))
        found = -1
        for j in range(jhi, i + lo_min - 1, -1):
            dx = (lo[j] - lo[i]) * cos_i * KM_PER_DEG
            dy = (la[j] - la[i]) * KM_PER_DEG
            if dx * dx + dy * dy <= MOUTH_KM * MOUTH_KM and mouth_is_water(sub, i, j):
                found = j
                break
        if found > 0:
            keep[i + 1:found] = False
            i = found
        else:
            i += 1
    return keep


def nearest(path, pt):
    d = np.hypot((path[:, 0] - pt[0]) * np.cos(np.radians(pt[1])) * KM_PER_DEG,
                 (path[:, 1] - pt[1]) * KM_PER_DEG)
    return int(np.argmin(d))


def build_sub(path, region):
    """Return (sub, lat_min, lat_max): the shore path from start to stop."""
    kind, val = region["stop"]
    if kind == "lat_max":
        if path[0, 1] > path[-1, 1]:      # orient south->north, walk north
            path = path[::-1]
        i0 = nearest(path, region["start"])
        return path[i0:], region["lat_min"], val
    # "point": walk from the start seed to the stop cape along the polyline
    i0, i1 = nearest(path, region["start"]), nearest(path, val)
    sub = path[i0:i1 + 1] if i1 >= i0 else path[i1:i0 + 1][::-1]
    return sub, region["lat_min"], None


def main():
    name = (sys.argv[1] if len(sys.argv) > 1 else "kamchatka").lower()
    region = REGIONS[name]
    coast = extract_coast(region["box"])
    path = resample_1km(coast)  # ~1 km spacing

    sub, lat_min, lat_max = build_sub(path, region)
    keep = detect_bays(sub)
    K = sub[keep]                       # ordered open-coast shore vertices
    skipped_km = int((~keep).sum())     # ~1 km per removed vertex

    rows = []          # (group, dist_km, lat, lon)
    dropped = 0
    partial = 0
    group = 0
    acc = 0.0          # along-shore distance travelled
    next_at = 0.0      # next along-shore station to drop a group at
    for k in range(len(K)):
        lon, lat = K[k]
        if lat_max is not None and lat > lat_max:
            break
        if acc + 1e-6 >= next_at and (lat_min is None or lat >= lat_min):
            next_at += ALONG_KM
            # local tangent over a ~+/-4 km baseline so 1 km wiggles don't twist the normal
            w = 4
            a, b = K[max(k - w, 0)], K[min(k + w, len(K) - 1)]
            ex, ey = enu_scale(lat)
            tx = (b[0] - a[0]) * ex
            ty = (b[1] - a[1]) * ey
            norm = np.hypot(tx, ty)
            tx, ty = tx / norm, ty / norm
            nx, ny = outward_normal(lon, lat, tx, ty)
            kept = []
            for dkm in OFFSETS_KM:
                plat = lat + (ny * dkm) / ey
                plon = lon + (nx * dkm) / ex
                if seaward_clear(plat, plon, nx, ny, dkm):
                    kept.append((dkm, round(plat, 5), round(plon, 5)))
                else:
                    dropped += 1
            if kept:
                group += 1
                if len(kept) < len(OFFSETS_KM):
                    partial += 1
                for dkm, plat, plon in kept:
                    rows.append((group, dkm, plat, plon))
        if k < len(K) - 1:
            acc += geo_km(K[k], K[k + 1])

    # --- manual overrides where the land mask is unreliable --------------
    thr = region.get("drop_above_lat")
    if thr is not None:
        grp_lat = {gg: max(la for g2, _, la, _ in rows if g2 == gg)
                   for gg in {r[0] for r in rows}}
        keep = sorted(gg for gg, la in grp_lat.items() if la <= thr)
        remap = {gg: i + 1 for i, gg in enumerate(keep)}
        rows = [(remap[gg], d, la, lo) for gg, d, la, lo in rows if gg in remap]
        group = len(keep)
    for mlat, mlon in region.get("manual_east", []):
        group += 1
        ex, _ = enu_scale(mlat)
        for dkm in OFFSETS_KM:
            rows.append((group, dkm, round(mlat, 5), round(mlon + dkm / ex, 5)))

    # --- write outputs ---------------------------------------------------
    csv_path = os.path.join(DATA_DIR, region["out"] + ".csv")
    txt_path = os.path.join(DATA_DIR, region["out"] + ".txt")
    with open(csv_path, "w", newline="") as f:
        f.write("group,distance_km,latitude,longitude\n")
        for g, d, la, lo in rows:
            f.write(f"{g},{d:g},{la},{lo}\n")
    with open(txt_path, "w") as f:
        for g, d, la, lo in rows:
            f.write(f"{la}, {lo}\n")

    print(f"[{name}] groups: {group}  points: {len(rows)}  dropped(too near another shore): {dropped}  partial groups: {partial}")
    print(f"bay shoreline skipped: ~{skipped_km} km")
    print(f"start ({sub[0,1]:.3f},{sub[0,0]:.3f})  end group ({rows[-1][2]:.3f},{rows[-1][3]:.3f})")
    print(f"wrote {csv_path}")
    print(f"wrote {txt_path}")


if __name__ == "__main__":
    main()
