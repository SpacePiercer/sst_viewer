"""MUR tile geometry, offline. No network, no fixtures -- run it directly:

    conda run -n mfa_env python test_tiles.py

Covers the three things that silently corrupt a mosaic if they drift: the
95..295 longitude frame, the outward tile snap across the antimeridian, and
the seam where two tiles meet (an off-by-one there shifts a whole region by
5 degrees and still *looks* like a map).
"""
import tempfile
from pathlib import Path

import numpy as np

import datasets as D

mur = D.DATASETS["mur_okhotsk"]

# --- the 95..295 frame -----------------------------------------------------
# 175E and 175W are 10 degrees apart, not 350: the box straddles 180.
assert mur._nlon(175.0) == 175.0
assert mur._nlon(-175.0) == 185.0
assert mur.tile_of(52.3, -175.0) == (50.0, 185.0)
assert mur.tile_of(52.3, 175.0) == (50.0, 175.0)
assert mur.tile_of(52.3, 60.0) is None          # west of the Pacific box
assert mur.tile_of(80.0, 150.0) is None         # north of it

# a lon round-trips into the frame the index grid actually uses
i, j = mur.latlon_to_idx(52.3, -175.0)
assert j == round((185.0 - mur.lon0) / mur.dlon), j
assert i == round((52.3 - mur.lat0) / mur.dlat), i

# --- tiles_for across the dateline ----------------------------------------
assert mur.tiles_for(175.0, 50.0, -172.0, 52.0) == [
    (50.0, 175.0), (50.0, 180.0), (50.0, 185.0)]

# snaps OUTWARD: a box inside one tile still returns that whole tile
assert mur.tiles_for(141.2, 51.1, 142.0, 51.9) == [(50.0, 140.0)]

# clipped to PACIFIC, never past it
assert mur.tiles_for(140.0, -40.0, 145.0, -18.0) == [(-20.0, 140.0)]
assert mur.tiles_for(140.0, 68.0, 145.0, 80.0) == [(65.0, 140.0)]
assert mur.tiles_for(140.0, 80.0, 145.0, 85.0) == []   # wholly outside

# --- mosaic_idx seam -------------------------------------------------------
_REAL_FIELDS = D.FIELDS
with tempfile.TemporaryDirectory() as tmp:
    D.FIELDS = Path(tmp)                      # _tile_path reads this at call time
    (D.FIELDS / mur.id).mkdir(parents=True)
    for tile, fill in (((50.0, 140.0), 1.0), ((50.0, 145.0), 2.0)):
        np.save(mur._tile_path("2020-01-01", "analysed_sst", tile),
                np.full((500, 500), fill, np.float32))

    # lon 145.0 is column 5000; the window straddles it by 10 cells each side
    j0, j1 = 4990, 5009
    i0 = round((50.0 - mur.lat0) / mur.dlat)
    out = mur.mosaic_idx("2020-01-01", "analysed_sst", i0, i0 + 2, j0, j1)
    assert out.shape == (3, 20), out.shape
    assert (out[:, :10] == 1.0).all(), "west tile did not land left of the seam"
    assert (out[:, 10:] == 2.0).all(), "seam is not at lon 145.0"

    # a window over a tile that was never fetched is NaN, not an error
    gap = mur.mosaic_idx("2020-01-01", "analysed_sst", i0, i0, 6000, 6009)
    assert np.isnan(gap).all()

D.FIELDS = _REAL_FIELDS   # pytest imports this module; do not leave the
                          # global cache dir pointing at a deleted temp dir


# --- Mercator overlay lattice ---------------------------------------------
# The old resampler sampled output rows evenly in Mercator y and rounded to the
# nearest data row, so rows fell off the bottom of the bincount (7 of 500 on a
# 5 deg box, 900 of 2500 on a 25 deg one) and a cell's size and offset moved
# with whatever box happened to be rendered. Both are assertable properties.

def window(w, s, e, n):
    """The (i0, ni, j0, nj) index window _render_box would use for a bbox."""
    t = mur.tiles_for(w, s, e, n)
    s2, n2 = min(x[0] for x in t), max(x[0] for x in t) + mur.TILE
    w2, e2 = min(x[1] for x in t), max(x[1] for x in t) + mur.TILE
    i0 = int(round((s2 - mur.lat0) / mur.dlat))
    j0 = int(round((w2 - mur.lon0) / mur.dlon))
    return (i0, min(int(round((n2 - s2) / mur.dlat)), mur.nlat - i0),
            j0, min(int(round((e2 - w2) / mur.dlon)), mur.nlon - j0))


BOXES = [(140, 50, 145, 55),        # one tile
         (140, 50, 155, 55),        # wide
         (135, 45, 165, 60),        # 3000 cells wide; the full study region
                                    # exceeds 4096 rows at d=1 and is merged
         (175, 50, -172, 52),       # straddles the antimeridian
         (140, -3, 145, 3)]         # straddles the equator (shortest cells)

for box in BOXES:
    i0, ni, j0, nj = window(*box)
    rows, cols, (s, w, n, e) = D._merc_map(mur, i0, ni, j0, nj)
    assert np.bincount(rows, minlength=ni).min() >= 1, f"{box}: data rows dropped"
    assert np.bincount(cols, minlength=nj).min() >= 1, f"{box}: data cols dropped"
    # the image covers the cells' real edges, not their centres
    assert abs(s - (mur.lat0 + (i0 - 0.5) * mur.dlat)) < 1e-9, (box, s)
    assert abs(w - (mur.lon0 + (j0 - 0.5) * mur.dlon)) < 1e-9, (box, w)
    assert len(rows) * len(cols) <= D.MAX_OVERLAY_PX

# stability: the SAME data cell must land the same way in two different,
# overlapping boxes -- same height in px, same offset from another cell.
def place(box, k, kref):
    i0, ni, j0, nj = window(*box)
    rows, _, _ = D._merc_map(mur, i0, ni, j0, nj)
    at = np.flatnonzero(rows == k - i0)
    ref = np.flatnonzero(rows == kref - i0)
    assert at.size and ref.size, (box, k, kref)
    return at.size, int(at[0] - ref[0])

K = int(round((52.5 - mur.lat0) / mur.dlat))     # a cell at 52.5N
KREF = int(round((51.0 - mur.lat0) / mur.dlat))  # and one at 51.0N
# Two windows that render with the SAME (oversample, divisor) must place a cell
# identically -- same height in px, same offset from another cell.
SMALL = (140, 50, 145, 55)
for other in [(141, 51, 144, 54), (140.5, 50.5, 144.5, 54.5)]:
    assert D._merc_plan(mur, *window(*SMALL)) == D._merc_plan(mur, *window(*other)), other
    assert place(SMALL, K, KREF) == place(other, K, KREF), other

# The property that actually governs what the user sees: a cell edge must land
# within half an output row of where it belongs, so the imagery agrees with the
# grid overlay drawn at lat0+(k+0.5)*dlat. A bigger window gives the oversample
# back and so quantises more coarsely -- but a window is only that big when the
# map is zoomed far enough out that the cell is correspondingly small on screen,
# so the error in SCREEN pixels stays bounded either way. Assert the invariant
# directly: every cell is within one output row of its exact Mercator height,
# and the worst edge error is at most half a row, i.e. cos(phi)/(2*oversample)
# of a cell.
for box in [(140, 50, 145, 55), (135, 45, 155, 60), (135, 40, 165, 65),
            (150, 0, 155, 5), (140, 60, 145, 69)]:
    i0, ni, j0, nj = window(*box)
    over, div = D._merc_plan(mur, i0, ni, j0, nj)
    rows, _, (bs, bw, bn, be) = D._merc_map(mur, i0, ni, j0, nj)
    # exact height each block should have, in output rows
    k = np.arange(i0 // div, -(-(i0 + ni) // div) + 1) * div
    # every d-cell BLOCK shows up (d = 1: every data row)
    counts = np.bincount((rows + i0) // div - i0 // div, minlength=len(k) - 1)
    assert counts.min() >= 1, (box, "dropped")
    exact = np.diff(D._row_edge_m(mur, k)) * (D._merc_scale(mur) * over / div)
    got = np.diff(np.rint(D._row_edge_m(mur, k) * (D._merc_scale(mur) * over / div)))
    assert np.abs(got - exact).max() <= 1.0, (box, float(np.abs(got - exact).max()))
    # worst edge error as a fraction of one cell
    frac = 0.5 / exact.min()
    assert frac <= 0.5 / over * 1.01 + 1e-9 or over == 1, (box, over, frac)

# whole-grid path (OISST): same lattice, cached, and 1 px per column exactly
oisst = D.DATASETS["oisst_remote"]
rows, cols, (s, w, n, e) = D._merc_indices_cached(oisst)
assert D._merc_indices_cached(oisst)[0] is rows, "whole-grid indices lost their cache"
assert (w, e) == (-180.0, 180.0), (w, e)
assert len(cols) == oisst.nlon and np.bincount(cols).min() == 1
inside = np.bincount(rows, minlength=oisst.nlat)[
    int((-D.MERC_LAT - oisst.lat0) / oisst.dlat) + 1:
    int((D.MERC_LAT - oisst.lat0) / oisst.dlat)]
assert inside.min() >= 1, "data rows dropped inside the Mercator band"

# Chrome resamples any image with a side > 4096 px before drawing it, which
# slides every block off the grid lines (a 5-deg MUR tile at 52N was 6579 rows,
# whole-grid OISST 11520). No overlay may exceed that on either side.
assert len(rows) <= 4096, ("oisst whole grid", len(rows))
for box in BOXES + [(135, 40, 165, 65), (140, 60, 145, 69), D.PACIFIC]:
    r_, c_, _ = D._merc_map(mur, *window(*box))
    assert max(len(r_), len(c_)) <= 4096, (box, len(r_), len(c_))

print("ok")
