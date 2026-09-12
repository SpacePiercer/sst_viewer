"""Smoke test: fails loudly if the data paths moved or parsing broke.
Remote (ERDDAP) checks run only if the network is reachable.
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
    assert set(D.DATASETS) == {"oisst_local", "oisst_remote", "mur_okhotsk"}
    for ds in D.DATASETS.values():
        meta = D.dataset_meta(ds)
        assert meta["variables"] and meta["overlay_bounds"], meta

    # ---- oisst_local: v1 behavior preserved --------------------------------
    loc = D.get_dataset("oisst_local")
    dates = loc.dates()
    assert len(dates) > 1000, f"expected ~1118 OISST dates, got {len(dates)}"
    assert dates[0] < "2001" and dates[-1] > "2024", (dates[0], dates[-1])

    png, vmin, vmax, snapped = D.render_overlay("oisst_local", dates[0], "sst")
    assert png.exists() and png.stat().st_size > 10_000, png
    assert vmin < vmax and snapped == dates[0]

    pv = loc.point_values(46.0, 147.0, "2010-06-15")
    assert pv["values"]["sst"] is not None and -2 <= pv["values"]["sst"] <= 20, pv
    assert not pv["land"]

    s = loc.point_series(46.0, 147.0, "sst", "2010-05-20", "2010-07-01")
    assert len(s) > 30 and s[0]["value"] is not None, len(s)

    pb = D.playback_dates("oisst_local", "2000-05-20", "2005-07-01", gap_days=10)
    assert 10 < len(pb) < 60, len(pb)
    pb2 = D.playback_dates("oisst_local", "2000-06-01", "2010-07-01",
                           same_day_each_year=True)
    assert all(d[5:] == "06-01" for d in pb2) and len(pb2) == 11, pb2

    # ---- fields cache round-trip (offline) ----------------------------------
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)
    arr[0, 0] = np.nan
    D.save_field("oisst_local", "1900-01-01", "smoketest", arr, (0, 0, 1, 1))
    back = D.load_field("oisst_local", "1900-01-01", "smoketest")
    assert back.dtype == np.float32 and back.shape == (3, 4)
    assert np.isnan(back[0, 0]) and back[2, 3] == 11.0
    for p in D._field_paths("oisst_local", "1900-01-01", "smoketest"):
        p.unlink(missing_ok=True)

    # ---- areas CRUD + polygon mean series -----------------------------------
    poly = {"type": "polygon", "latlngs": [[45.5, 146.5], [46.5, 146.5],
                                           [46.5, 148.0], [45.5, 148.0]]}
    area = A.api_area_create(payload={"name": "smoke-poly", "geom": poly,
                                      "dataset": "oisst_local", "var": "sst",
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
        ms = D.area_mean_series("oisst_local", poly, "sst",
                                "2010-05-20", "2010-06-05")
        assert len(ms) > 10 and ms[0]["value"] is not None, ms[:3]
        circ = {"type": "circle", "lat": 46.0, "lon": 147.0, "radius_m": 50_000}
        mc = D.area_mean_series("oisst_local", circ, "sst",
                                "2010-06-01", "2010-06-05")
        assert mc and mc[0]["value"] is not None, mc
    finally:
        A.api_area_delete(area["id"])
    assert all(a["id"] != area["id"] for a in A.api_areas())

    # ---- PDF report for an arbitrary point (quarto render, offline) ---------
    loc_ds = D.get_dataset("oisst_local")
    wanted = [p["date"] for p in loc_ds.point_series(48.75, 140.20, "sst",
                                                      "2020-05-20", "2021-05-25")]
    frame = R.fetch_point_frame(loc_ds, 48.75, 140.20, "sst", wanted)
    assert frame is not None and len(frame) > 5, frame
    pdf = R.render_pdf(frame, 48.75, 140.20, "Tikhoye Lake (smoketest)",
                       loc_ds.name, "oisst_local", "smoketest range")
    assert pdf.exists() and pdf.stat().st_size > 20_000, pdf
    pdf.unlink()

    # ---- batch job (CSV only, no quarto -- fast) -----------------------------
    import time as _time
    points = [{"lat": 48.75, "lon": 140.20, "label": "P1", "dates": wanted[:10]},
              {"lat": 43.91, "lon": 145.81, "label": "P2", "dates": wanted[:10]}]
    job_id = R.start_batch_job("oisst_local", points, generate_pdf=False)
    for _ in range(600):  # first oisst_local fetch per point scans ~1100 files, up to ~30s
        job = R.JOBS[job_id]
        if job["state"] == "done":
            break
        _time.sleep(0.5)
    assert job["state"] == "done" and job["done"] == 2, job
    assert job["csv_url"] and (D.LIBRARY / "downloads" /
                               job["csv_url"].split("/")[-1]).exists(), job
    assert all(p["status"] == "done" for p in job["points"]), job["points"]
    (D.LIBRARY / "downloads" / job["csv_url"].split("/")[-1]).unlink()

    # ---- remote datasets (skip cleanly offline) ------------------------------
    remote_msg = "skipped (offline)"
    if network_ok():
        rem = D.get_dataset("oisst_remote")
        rdates = rem.dates()
        assert rdates[0] <= "1981-09-01" and rdates[-1] > "2025", \
            (rdates[0], rdates[-1])
        d = "1990-01-15"  # outside the local window: forces the remote path
        rem.ensure_field(d)
        g = rem.grid(d, "sst")
        assert g.shape == (720, 1440) and np.nanmin(g) > -3, g.shape
        png, *_ = D.render_overlay("oisst_remote", d, "sst", -2, 25)
        assert png.exists(), png

        mur = D.get_dataset("mur_okhotsk")
        mdates = mur.dates()
        assert mdates[0] <= "2002-06-02" and mdates[-1] > "2025", mdates[0]
        pv = mur.point_values(46.0, 147.0, "2020-06-01")  # tiny point request
        assert pv["values"]["analysed_sst"] is not None, pv
        remote_msg = f"oisst_remote {len(rdates)} dates; mur {len(mdates)} dates"

    print("smoke test OK:", len(dates), "local dates;",
          f"overlay {png.name};", "areas CRUD ok;",
          f"poly mean {len(ms)} pts; remote: {remote_msg}")


if __name__ == "__main__":
    main()
