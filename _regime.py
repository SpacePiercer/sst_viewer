"""At each zoom: the box the client would request, the plan, and whether the
grid overlay is even drawn (app.js hides it below MIN_CELL_PX = 1.5 screen px)."""
import math
import datasets as D

mur = D.DATASETS["mur_okhotsk"]
MIN_CELL_PX = 1.5
LAT, LON, MAPW, MAPH = 53.5, 146.0, 1400, 760

for z in range(6, 15):
    px_per_deg = 256 * 2 ** z / 360
    dw = MAPW / px_per_deg
    dh = MAPH / px_per_deg * math.cos(math.radians(LAT))
    w, e = LON - dw / 2, LON + dw / 2
    s, n = LAT - dh / 2, LAT + dh / 2
    t = mur.tiles_for(w, s, e, n)
    s2, n2 = min(x[0] for x in t), max(x[0] for x in t) + mur.TILE
    w2, e2 = min(x[1] for x in t), max(x[1] for x in t) + mur.TILE
    i0, i1, j0, j1 = mur.bbox_to_idx(w2, s2, e2 - mur.dlon, n2 - mur.dlat)
    ni, nj = i1 - i0 + 1, j1 - j0 + 1
    over, div = D._merc_plan(mur, i0, ni, j0, nj)
    rows, cols, _ = D._merc_map(mur, i0, ni, j0, nj)
    cell_px = 0.01 * px_per_deg
    # worst edge error, in screen px, from quantising to whole output rows
    err_px = (0.5 / (over / math.cos(math.radians(LAT)))) * cell_px / math.cos(math.radians(LAT))
    print(f"z={z:2d} box {e2-w2:5.1f}x{n2-s2:4.1f} deg  cells {ni}x{nj}  "
          f"plan over={over} div={div}  png {len(rows)}x{len(cols)} "
          f"({len(rows)*len(cols)/1e6:5.1f} Mpx)  cell={cell_px:6.2f}px  "
          f"grid={'ON ' if cell_px >= MIN_CELL_PX else 'off'}  "
          f"max edge err={err_px:5.2f}px")
