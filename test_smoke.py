"""Smoke test: fails loudly if the data paths moved or parsing broke.

The registry is ONLINE-ONLY now -- oisst_local is gone and nothing reads the
local .nc archive any more -- so every check that needs actual values lives in
the network branch. What stays offline is the shape of things: the registry,
the tiled metadata the frontend keys off, the 5-value render_overlay contract,
and the areas CRUD (which stores geometry, not data).

Run: conda run -n mfa_env python test_smoke.py
"""
import numpy as np

import datasets as D
import app as A
import reports as R


def network_ok():
    """One real value off a dataset's time axis -- NOT index.html. The PFEG
    catalog pages answer in ~1 s while the datasets we use cannot return a
    single value (Sep 2026), so an index.html check sends the remote leg into
    multi-minute timeouts. Same reasoning as the probe in health.py.
    _http_get_raw, not _http_get: no retries wanted in a liveness check."""
    try:
        D._http_get_raw(
            f"{D.ERDDAP}/griddap/ncdcOisst21Agg_LonPM180.csv?time%5B0:1:0%5D",
            timeout=10)
        return True
    except D.RemoteError:
        return False


def main():
    # ---- registry builds, every entry answers meta -------------------------
    assert set(D.DATASETS) == {"oisst_remote", "mur_okhotsk"}, set(D.DATASETS)
    for ds in D.DATASETS.values():
        meta = D.dataset_meta(ds)
        assert meta["variables"] and meta["overlay_bounds"], meta
        # the frontend pins its maxBounds to this; a transpose here walks the
        # map out of the Pacific box on the first pan
        assert meta["max_bounds"] == [[-20.0, 95.0], [70.0, 295.0]], meta
        assert meta["remote"], meta   # nothing local survives

    mur_meta = D.dataset_meta(D.DATASETS["mur_okhotsk"])
    assert mur_meta["tiled"] is True and mur_meta["tile_deg"] == 5.0, mur_meta
    oi_meta = D.dataset_meta(D.DATASETS["oisst_remote"])
    assert oi_meta["tiled"] is False and oi_meta["tile_deg"] is None, oi_meta

    # ---- the dataset id "oisst_local" no longer exists anywhere -------------
    try:
        D.get_dataset("oisst_local")
        raise AssertionError("oisst_local is back in the registry")
    except KeyError:
        pass

    # ---- MUR is tiled: no whole-grid array, no bbox-less export -------------
    mur = D.get_dataset("mur_okhotsk")
    try:
        mur.grid("2020-06-01", "analysed_sst")
        raise AssertionError("MUR built a 180M-cell whole grid")
    except RuntimeError:
        pass
    try:  # raises before any network call
        D._export_overlay("mur_okhotsk", "2020-06-01", "analysed_sst", -2, 25, None)
        raise AssertionError("tiled export without a bbox should fail")
    except ValueError:
        pass

    # ---- fields cache round-trip (offline) ----------------------------------
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    arr[0, 0] = np.nan
    D.save_field("oisst_remote", "1900-01-01", "smoketest", arr, (0, 0, 1, 1))
    back = D.load_field("oisst_remote", "1900-01-01", "smoketest")
    assert back.dtype == np.float32 and back.shape == (3, 4)
    assert np.isnan(back[0, 0]) and back[2, 3] == 11.0
    for p in D._field_paths("oisst_remote", "1900-01-01", "smoketest"):
        p.unlink(missing_ok=True)

    # ---- areas CRUD (geometry only, no data fetched) ------------------------
    poly = {"type": "polygon", "latlngs": [[45.5, 146.5], [46.5, 146.5],
                                           [46.5, 148.0], [45.5, 148.0]]}
    area = A.api_area_create(payload={"name": "smoke-poly", "geom": poly,
                                      "dataset": "oisst_remote", "var": "sst",
                                      "date": "2010-06-15"})
    try:
        assert any(a["id"] == area["id"] for a in A.api_areas())
        A.api_area_update(area["id"], payload={"name": "smoke-poly-2"})
        assert any(a["name"] == "smoke-poly-2" for a in A.api_areas())
        # reshaping without renaming is what the GIF crop box does
        box = {"type": "rect", "w": 140.0, "s": 45.0, "e": 150.0, "n": 52.0}
        A.api_area_update(area["id"], payload={"geom": box})
        got = next(a for a in A.api_areas() if a["id"] == area["id"])
        assert got["geom"] == box and got["name"] == "smoke-poly-2", got
    finally:
        A.api_area_delete(area["id"])
    assert all(a["id"] != area["id"] for a in A.api_areas())

    # ---- map markers: close points get pushed apart, far ones stay put -----
    import math
    m = R._spread({1: (100.0, 100.0), 2: (105.0, 100.0), 3: (100.0, 100.0),
                   4: (400.0, 400.0)}, 29)
    close = [m[1], m[2], m[3]]
    assert all(math.dist(p, q) >= 29 - 1e-6 for i, p in enumerate(close)
               for q in close[i + 1:]), m
    assert m[4] == (400.0, 400.0), m

    # ---- everything past here needs the network -----------------------------
    if not network_ok():
        print("smoke test OK (offline): registry, tiled meta, field cache, "
              "areas CRUD. Remote checks skipped.")
        return

    rem = D.get_dataset("oisst_remote")
    rdates = rem.dates()
    assert rdates[0] <= "1981-09-01" and rdates[-1] > "2025", (rdates[0], rdates[-1])

    d = "1990-01-15"
    rem.ensure_field(d)
    g = rem.grid(d, "sst")
    assert g.shape == (720, 1440) and np.nanmin(g) > -3, g.shape

    # render_overlay returns FIVE values now; bounds is (s, w, n, e)
    png, vmin, vmax, snapped, bounds = D.render_overlay("oisst_remote", d, "sst", -2, 25)
    assert png.exists() and png.stat().st_size > 10_000, png
    assert vmin < vmax and snapped == d
    s, w, n, e = bounds
    assert s < n and w < e, bounds
    assert A._bounds_hdr(bounds) == f"{s},{w},{n},{e}"

    pb = D.playback_dates("oisst_remote", "2000-05-20", "2005-07-01", gap_days=10)
    assert 10 < len(pb) < 250, len(pb)
    pb2 = D.playback_dates("oisst_remote", "2000-06-01", "2010-07-01",
                           same_day_each_year=True)
    assert all(x[5:] == "06-01" for x in pb2) and len(pb2) == 11, pb2

    pv = rem.point_values(46.0, 147.0, "2010-06-15")
    assert pv["values"]["sst"] is not None and -2 <= pv["values"]["sst"] <= 25, pv

    ms = D.area_mean_series("oisst_remote", poly, "sst", "2010-05-20", "2010-06-05")
    assert len(ms) > 10 and ms[0]["value"] is not None, ms[:3]
    circ = {"type": "circle", "lat": 46.0, "lon": 147.0, "radius_m": 50_000}
    mc = D.area_mean_series("oisst_remote", circ, "sst", "2010-06-01", "2010-06-05")
    assert mc and mc[0]["value"] is not None, mc

    # ---- tile job contract --------------------------------------------------
    # a box outside PACIFIC needs no tiles at all: total 0, done immediately,
    # and no thread started -- the "nothing to wait for" case the UI relies on
    jid, total = D.start_tile_job("mur_okhotsk", "2020-06-01", (10.0, 0.0, 20.0, 10.0))
    assert total == 0 and D.TILE_JOBS[jid]["state"] == "done", D.TILE_JOBS[jid]
    # and a continent-sized box is refused rather than queued for hours
    jid2, total2 = D.start_tile_job("mur_okhotsk", "2020-06-01",
                                    (100.0, -15.0, 290.0, 65.0))
    assert total2 > D.MAX_JOB_TILES and D.TILE_JOBS[jid2]["state"] == "error"

    # ---- bbox render of the tiled dataset (one tile, snapped outward) -------
    bpng, _, _, bdate, bbounds = D.render_overlay(
        "mur_okhotsk", "2020-06-01", "analysed_sst", -2, 25,
        bbox=(146.0, 46.0, 147.0, 47.0))
    assert bpng.exists(), bpng
    bs, bw, bn, be = bbounds
    # CELL-EDGE box of the drawn pixels: half a cell (0.005 deg) outside the
    # 45/145/50/150 tile box, which is where the grid lines actually are.
    assert max(abs(a - b) for a, b in
               zip((bs, bw, bn, be), (44.995, 144.995, 49.995, 149.995))) < 1e-6, bbounds

    # ---- PDF report for an arbitrary point (quarto render) ------------------
    wanted = [p["date"] for p in rem.point_series(48.75, 140.20, "sst",
                                                  "2020-05-20", "2020-06-10")]
    frame = R.fetch_point_frame(rem, 48.75, 140.20, "sst", wanted)
    assert frame is not None and len(frame) > 5, frame
    pdf = R.render_pdf(frame, 48.75, 140.20, "Tikhoye Lake (smoketest)",
                       rem.name, "oisst_remote", "smoketest range")
    assert pdf.exists() and pdf.stat().st_size > 20_000, pdf
    pdf.unlink()

    # ---- comparison PDF: 2 points -> map (Esri tiles) + table + line charts --
    import pandas as pd
    rows = pd.concat([
        pd.DataFrame({"lat": lat, "lon": lon, "label": lbl,
                      "date": frame["date"], "value": frame["sst_celsius"] + off})
        for lat, lon, lbl, off in [(48.75, 140.20, "South", 0.0),
                                   (49.30, 140.45, "North", -1.0)]])
    cpdf = R.render_compare_pdf(rows, rem.name, "oisst_remote", "smoketest range")
    # the satellite map alone is a few hundred KB; a text-only PDF is ~20 KB
    assert cpdf.exists() and cpdf.stat().st_size > 100_000, cpdf
    cpdf.unlink()

    # ---- batch job (CSV only, no quarto -- fast) -----------------------------
    import time as _time
    points = [{"lat": 48.75, "lon": 140.20, "label": "P1", "dates": wanted[:10]},
              {"lat": 43.91, "lon": 145.81, "label": "P2", "dates": wanted[:10]}]
    job_id = R.start_batch_job("oisst_remote", points, generate_pdf=False)
    for _ in range(600):
        job = R.JOBS[job_id]
        if job["state"] == "done":
            break
        _time.sleep(0.5)
    assert job["state"] == "done" and job["done"] == 2, job
    assert job["csv_url"] and (D.LIBRARY / "downloads" /
                               job["csv_url"].split("/")[-1]).exists(), job
    assert all(p["status"] == "done" for p in job["points"]), job["points"]
    (D.LIBRARY / "downloads" / job["csv_url"].split("/")[-1]).unlink()

    print("smoke test OK:", f"{len(rdates)} oisst_remote dates;",
          f"overlay {png.name}; box overlay {bpng.name};",
          f"areas CRUD ok; poly mean {len(ms)} pts")


if __name__ == "__main__":
    main()
