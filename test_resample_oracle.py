"""Independent correctness oracle for the Mercator overlay resampler.

    conda run -n mfa_env python test_resample_oracle.py

Nothing here is borrowed from datasets.py's formula. The whole oracle is built
from two facts that hold no matter how the resampler is written:

  (A) Leaflet places the PNG between the returned SW and NE corners, and the
      screen is Web Mercator, so output row r (r = 0 at the NORTH edge) covers
      the Mercator interval
          m_r0 = m(n) - r     * (m(n) - m(s)) / H
          m_r1 = m(n) - (r+1) * (m(n) - m(s)) / H
      and samples the latitude at its centre, lat_r = m^-1((m_r0 + m_r1)/2).

  (B) Data row k is a CELL: it owns every latitude in
          [lat0 + (k - 0.5)*dlat,  lat0 + (k + 0.5)*dlat]
      (lat0 is a cell CENTRE), so the data row an output row must show is
          k(r) = floor((lat_r - lat0)/dlat + 0.5).

Given (A) and (B) the whole mapping is determined, and rasterisation can only
disagree with it by the unavoidable half-pixel of the pixel grid. Everything
below is a consequence:

  P1 forward/inverse agreement - every output row shows the data row that
     contains the latitude that row actually samples (tolerance: 1 output px).
  P2 surjectivity - no data row and no data column in the window is skipped.
  P3 stability - one fixed cell keeps the same latitude span in three
     different overlapping windows (tolerance: 1 output px).
  P4 cell edges - the output row where the sampled data row changes sits on
     the real cell edge lat0 + (k + 0.5)*dlat (tolerance: 1 output px), which
     is what makes the map's grid lines land on block boundaries.

m(phi) = ln(tan(pi/4 + phi/2)), m^-1(y) = 2*atan(exp(y)) - pi/2.
"""
import math

import numpy as np

import datasets as D

MUR = D.DATASETS["mur_okhotsk"]
OISST = D.DATASETS["oisst_remote"]

REPORT = []


def merc(lat):
    """Forward Web Mercator y. Array in, array out. No clipping."""
    return np.log(np.tan(np.pi / 4 + np.radians(np.asarray(lat, dtype="f8")) / 2))


def imerc(y):
    """Inverse Web Mercator."""
    return np.degrees(2 * np.arctan(np.exp(np.asarray(y, dtype="f8"))) - np.pi / 2)


def mur_window(w, s, e, n):
    """The (i0, ni, j0, nj) index window _render_box builds for a bbox: the
    requested box snapped OUTWARD to whole 5-degree tiles."""
    t = MUR.tiles_for(w, s, e, n)
    assert t, (w, s, e, n)
    s2, n2 = min(x[0] for x in t), max(x[0] for x in t) + MUR.TILE
    w2, e2 = min(x[1] for x in t), max(x[1] for x in t) + MUR.TILE
    i0 = int(round((s2 - MUR.lat0) / MUR.dlat))
    j0 = int(round((w2 - MUR.lon0) / MUR.dlon))
    ni = min(int(round((n2 - s2) / MUR.dlat)), MUR.nlat - i0)
    nj = min(int(round((e2 - w2) / MUR.dlon)), MUR.nlon - j0)
    return i0, ni, j0, nj


# name, (w, s, e, n)
BOXES = [
    ("small 5deg      140-145E 50-55N", (140.0, 50.0, 145.0, 55.0)),
    ("wide            140-155E 50-55N", (140.0, 50.0, 155.0, 55.0)),
    ("tall            140-145E 40-65N", (140.0, 40.0, 145.0, 65.0)),
    ("study region    135-165E 40-65N", (135.0, 40.0, 165.0, 65.0)),
    ("equatorial      140-145E  3S-3N", (140.0, -3.0, 145.0, 3.0)),
    ("high latitude   140-145E 62-69N", (140.0, 62.0, 145.0, 69.0)),
    ("antimeridian    175E-172W 50-52N", (175.0, 50.0, -172.0, 52.0)),
    ("whole Pacific (over the px cap)", D.PACIFIC),
]


def geom(ds, i0, ni, j0, nj):
    """Run the implementation and unpack what the oracle needs."""
    rows, cols, (s, w, n, e) = D._merc_map(ds, i0, ni, j0, nj)
    H, W = len(rows), len(cols)
    div = int(round(nj / W))                 # integer cells-per-pixel it chose
    ms, mn = float(merc(s)), float(merc(n))
    dm = (mn - ms) / H                       # Mercator units per output row
    return rows, cols, (s, w, n, e), H, W, div, ms, mn, dm


# ---------------------------------------------------------------- P1 + P2 + P4
p1_worst = 0.0        # worst |sampled lat - its block|, in output pixels
p1_worst_at = ""
p1_mismatch = 0       # output rows whose data row differs from the inverse
p2_fail = []
p4_worst = 0.0
p4_worst_at = ""
lines = []

for label, box in BOXES:
    i0, ni, j0, nj = mur_window(*box)
    rows, cols, bnd, H, W, div, ms, mn, dm = geom(MUR, i0, ni, j0, nj)
    s, w, n, e = bnd

    # --- P2: surjectivity ------------------------------------------------
    rmin = int(np.bincount(rows, minlength=ni).min())
    cmin = int(np.bincount(cols, minlength=nj).min())
    # with div>1 the lattice is coarsened on purpose: only the SAMPLED rows
    # (block centres) can appear, so surjectivity is asserted over blocks.
    if div == 1:
        if rmin < 1:
            p2_fail.append(f"{label}: {int((np.bincount(rows, minlength=ni) == 0).sum())} data rows dropped")
        if cmin < 1:
            p2_fail.append(f"{label}: {int((np.bincount(cols, minlength=nj) == 0).sum())} data cols dropped")
    else:
        nb = -(-ni // div)
        blocks = np.unique(rows)
        if len(blocks) != nb:
            p2_fail.append(f"{label}: div={div}, {nb - len(blocks)} blocks dropped")
        if len(np.unique(cols)) != -(-nj // div):
            p2_fail.append(f"{label}: div={div}, column blocks dropped")
    assert H * W <= D.MAX_OVERLAY_PX, (label, H * W)

    # --- P1: every output row shows the data row it actually samples ------
    # Independent inverse: centre of output row r -> Mercator -> latitude ->
    # the cell (or, when degraded, the block) that owns that latitude.
    r = np.arange(H)
    m_r = mn - (r + 0.5) * dm
    lat_r = imerc(m_r)
    kf = np.floor((lat_r - MUR.lat0) / MUR.dlat + 0.5)      # data row owning lat_r
    kimpl = rows.astype("f8") + i0                           # what the code shows
    if div == 1:
        p1_mismatch += int((kf != kimpl).sum())
        lo = MUR.lat0 + (kimpl - 0.5) * MUR.dlat
        hi = MUR.lat0 + (kimpl + 0.5) * MUR.dlat
    else:
        b = np.floor((kimpl - div // 2) / div)               # block index
        p1_mismatch += int((np.floor(kf / div) != b).sum())
        lo = MUR.lat0 + (b * div - 0.5) * MUR.dlat
        hi = MUR.lat0 + ((b + 1) * div - 0.5) * MUR.dlat
    # how far outside its own cell/block the sampled latitude falls, in px
    over = np.maximum(np.maximum(merc(lo) - m_r, m_r - merc(hi)), 0.0) / dm
    if float(over.max()) > p1_worst:
        p1_worst, p1_worst_at = float(over.max()), label

    # --- P4: cell edges --------------------------------------------------
    if div == 1:
        st = np.r_[0, np.flatnonzero(np.diff(rows)) + 1]     # run starts, N->S
        kk = rows[st] + i0                                   # data row of each run
        # the run for row k starts at k's NORTH edge: lat0 + (k + 0.5)*dlat
        want = (mn - merc(MUR.lat0 + (kk[1:] + 0.5) * MUR.dlat)) / dm
        err = np.abs(want - st[1:])
        if err.size and float(err.max()) > p4_worst:
            p4_worst, p4_worst_at = float(err.max()), label
    # bounds must be the true CELL-EDGE box of what was drawn, else every
    # block sits half a cell off the grid lines the map draws at
    # lat0 + (k + 0.5)*dlat.
    if div == 1:
        assert abs(s - (MUR.lat0 + (i0 - 0.5) * MUR.dlat)) < 1e-9, (label, s)
        assert abs(n - (MUR.lat0 + (i0 + ni - 0.5) * MUR.dlat)) < 1e-9, (label, n)
        assert abs(w - (MUR.lon0 + (j0 - 0.5) * MUR.dlon)) < 1e-9, (label, w)
        assert abs(e - (MUR.lon0 + (j0 + nj - 0.5) * MUR.dlon)) < 1e-9, (label, e)
    cov = (f"rows/cell min={rmin} cols/cell min={cmin}" if div == 1 else
           f"blocks covered {len(np.unique(rows))}/{-(-ni // div)} rows, "
           f"{len(np.unique(cols))}/{-(-nj // div)} cols")
    lines.append(f"  {label:34s} cells {ni:5d}x{nj:-6d} -> png {H:5d}x{W:-6d} "
                 f"div={div} {cov}")

REPORT.append("P1/P2/P4 windows:")
REPORT += lines

assert not p2_fail, "SURJECTIVITY FAILED:\n" + "\n".join(p2_fail)
assert p1_mismatch == 0 or p1_worst <= 1.0, (
    f"P1: {p1_mismatch} output rows show the wrong data row, worst "
    f"{p1_worst:.3f} px outside it ({p1_worst_at})")
assert p1_worst <= 1.0, f"P1: sampled latitude {p1_worst:.3f} px outside its own cell ({p1_worst_at})"
assert p4_worst <= 1.0, f"P4: cell edge off by {p4_worst:.3f} px ({p4_worst_at})"

# Why 1 px and not 0: the image is stretched between the returned bounds, so a
# pixel edge is displayed at m_s + q*(m_n - m_s)/H while the lattice intends
# (p0 + q)/S. With e0 = p0 - S*m_s and e1 = p1 - S*m_n (both in [-0.5, 0.5]),
# the displayed-minus-intended offset is q*(e0 - e1)/H - e0 in pixels: linear
# in q, so bounded by max(|e0|, |e1|) <= 0.5 px, independent of box height.
# Add each edge's own rint() of <= 0.5 px and 1.0 px is the exact ceiling.
REPORT.append(f"P1 inverse agreement : mismatched output rows = {p1_mismatch}, "
              f"worst excursion outside own cell = {p1_worst:.4f} px  [<= 1.0]")
REPORT.append(f"P2 surjectivity      : no data row/column dropped in any window")
REPORT.append(f"P4 cell edges        : worst edge error = {p4_worst:.4f} px  [<= 1.0]  ({p4_worst_at})")


# ------------------------------------------------------------------- P3
# One fixed cell, three different overlapping windows that all contain it.
PLAT, PLON = 52.345, 146.789
K = int(math.floor((PLAT - MUR.lat0) / MUR.dlat + 0.5))
J = int(math.floor((PLON - MUR.lon0) / MUR.dlon + 0.5))
KREF = int(math.floor((51.0 - MUR.lat0) / MUR.dlat + 0.5))

P3_BOXES = [("A 145-150E 50-55N", (146.0, 52.0, 148.0, 53.0)),
            ("B 140-155E 45-60N", (143.0, 48.0, 152.0, 58.0)),
            ("C 135-165E 45-60N", (135.0, 45.0, 165.0, 60.0))]   # widest box still at d=1

spans = []
plans = []
for label, box in P3_BOXES:
    i0, ni, j0, nj = mur_window(*box)
    rows, cols, bnd, H, W, div, ms, mn, dm = geom(MUR, i0, ni, j0, nj)
    assert div == 1, (label, div)
    at = np.flatnonzero(rows == K - i0)
    ref = np.flatnonzero(rows == KREF - i0)
    cat = np.flatnonzero(cols == J - j0)
    assert at.size and ref.size and cat.size, (label, "cell not in window")
    top = float(imerc(mn - at[0] * dm))            # north edge of the cell, deg
    bot = float(imerc(mn - (at[-1] + 1) * dm))     # south edge, deg
    spans.append((label, at.size, top, bot, int(at[0] - ref[0]), cat.size, dm))
    plans.append(D._merc_plan(MUR, i0, ni, j0, nj))

REPORT.append("P3 stability of cell k=%d (%.3fN) / j=%d (%.3fE):" % (K, PLAT, J, PLON))
for label, h, top, bot, off, cw, _ in spans:
    REPORT.append(f"  {label}: height {h} px, lat span {bot:.7f}..{top:.7f} "
                  f"({(top - bot) * 111320:.1f} m), offset from 51.0N cell {off} px, width {cw} px")

# A window big enough to blow the pixel budget gives the row oversample back,
# so its lattice is coarser and a cell CANNOT occupy the same pixel count as in
# a small window. Pixel-for-pixel equality is therefore asserted only between
# windows that render with the same plan. What must hold everywhere is the
# physical invariant: the cell covers the same piece of the Earth, to within one
# output pixel of whichever window is coarser.
base = spans[0]
base_plan = plans[0]
for (label, h, top, bot, off, cw, dm), plan in zip(spans[1:], plans[1:]):
    tol = math.degrees(dm)   # >= one output pixel expressed in degrees of lat
    if plan == base_plan:
        assert h == base[1], f"P3: cell height {h} px in {label} vs {base[1]} px in {base[0]}"
        assert cw == base[5], f"P3: cell width {cw} px in {label} vs {base[5]} px in {base[0]}"
        assert off == base[4], f"P3: offset from the 51.0N cell is {off} px in {label} vs {base[4]}"
    assert abs(top - base[2]) <= tol, f"P3: north edge moves {abs(top - base[2]) / tol:.2f} px in {label}"
    assert abs(bot - base[3]) <= tol, f"P3: south edge moves {abs(bot - base[3]) / tol:.2f} px in {label}"
drift = max(abs(s[2] - base[2]) for s in spans[1:]) * 111320
REPORT.append(f"  worst north-edge drift across the three windows: {drift:.4f} m "
              f"(one output px = {math.degrees(base[6]) * 111320:.1f} m)")


# ------------------------------------------------------------------- OISST
# Whole-grid path. Same two facts, plus: rows outside the Mercator band have
# nowhere to land, so surjectivity is asserted strictly inside it.
rows, cols, (s, w, n, e) = D._merc_indices_cached(OISST)
H, W = len(rows), len(cols)
ms, mn = float(merc(s)), float(merc(n))
dm = (mn - ms) / H
r = np.arange(H)
lat_r = imerc(mn - (r + 0.5) * dm)
kf = np.floor((lat_r - OISST.lat0) / OISST.dlat + 0.5)
mism = int((kf != rows).sum())
lo = OISST.lat0 + (rows - 0.5) * OISST.dlat
hi = OISST.lat0 + (rows + 0.5) * OISST.dlat
over = float((np.maximum(np.maximum(merc(lo) - (mn - (r + 0.5) * dm),
                                    (mn - (r + 0.5) * dm) - merc(hi)), 0.0) / dm).max())
k_lo = int(math.ceil((-D.MERC_LAT - OISST.lat0) / OISST.dlat + 0.5))
k_hi = int(math.floor((D.MERC_LAT - OISST.lat0) / OISST.dlat - 0.5))
bc = np.bincount(rows, minlength=OISST.nlat)
inside_min = int(bc[k_lo:k_hi + 1].min())
outside_band = int((bc == 0).sum())
assert W == OISST.nlon and int(np.bincount(cols).min()) == 1, "OISST columns not 1:1"
assert mism == 0 or over <= 1.0, f"OISST: {mism} rows wrong, worst {over:.3f} px"
assert over <= 1.0, f"OISST: sampled latitude {over:.3f} px outside its own cell"
assert inside_min >= 1, "OISST: data rows dropped inside the Mercator band"
assert abs(s + D.MERC_LAT) < 1e-9 and abs(n - D.MERC_LAT) < 1e-9, (s, n)
REPORT.append("OISST whole grid:")
REPORT.append(f"  png {H}x{W} for {OISST.nlat}x{OISST.nlon} cells, bounds "
              f"{s:.5f}..{n:.5f}N {w:g}..{e:g}E")
REPORT.append(f"  P1 mismatched rows = {mism}, worst excursion = {over:.4f} px  [<= 1.0]")
REPORT.append(f"  P2 rows inside +-{D.MERC_LAT:.2f} deg: min px/row = {inside_min}; "
              f"{outside_band} rows lie beyond the Mercator limit (unrenderable by definition)")
REPORT.append(f"  cols: exactly 1 px per data column")

print("\n".join(REPORT))
print("ok")
