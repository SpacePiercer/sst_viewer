"""Independently verify a batch CSV against NOAA, bypassing the app entirely.

The point of this script is that it shares NO code with the app: it reads the
CSV the batch produced, then asks ERDDAP for the same pixel on the same date
over plain HTTP and compares. If the app's fetch path, its per-coordinate cache
or its date handling were wrong, the numbers would disagree here.

    conda run -n mfa_env python scripts/verify_batch.py library/downloads/sst_batch_XXXX.csv

Exit code 0 = every value matched. 1 = at least one mismatch or unverifiable
point, so the batch should not be trusted until someone looks.

ERDDAP returns 503 when busy (common right after an outage), so each point is
retried with a backoff before being called a failure.
"""
import csv
import sys
import time
import urllib.request
from pathlib import Path

# dataset id -> (erddap dataset, variable, time-of-day on its axis)
DATASETS = {
    "mur_okhotsk": ("jplMURSST41", "analysed_sst", "09:00:00Z"),
    "oisst_remote": ("ncdcOisst21Agg_LonPM180", "sst", "12:00:00Z"),
}
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap"
TOL = 0.001          # the app rounds to 3 dp; anything above this is a real disagreement
RETRIES, BACKOFF_S = 4, 20


def fetch(ds, var, tod, lat, lon, date):
    url = (f"{ERDDAP}/{ds}.csv?{var}%5B({date}T{tod})%5D"
           f"%5B({lat})%5D%5B({lon})%5D")
    for attempt in range(RETRIES):
        try:
            raw = urllib.request.urlopen(url, timeout=90).read().decode()
            last = [l for l in raw.strip().split("\n") if l][-1].split(",")
            return float(last[3]), float(last[1]), float(last[2])
        except Exception as e:
            if attempt == RETRIES - 1:
                raise
            time.sleep(BACKOFF_S)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = Path(sys.argv[1])
    dsid = sys.argv[2] if len(sys.argv) > 2 else "mur_okhotsk"
    if dsid not in DATASETS:
        sys.exit(f"no verification route for dataset {dsid!r} "
                 f"(known: {', '.join(DATASETS)})")
    ds, var, tod = DATASETS[dsid]

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    print(f"{'point':28} {'date':11} {'app':>8} {'erddap':>8} {'diff':>7}  cell used")
    bad = 0
    for r in rows:
        lat, lon, date, app = (float(r["lat"]), float(r["lon"]), r["date"],
                               float(r["value"]))
        try:
            val, glat, glon = fetch(ds, var, tod, lat, lon, date)
        except Exception as e:
            print(f"{r['label'][:28]:28} {date:11} {app:8.3f} {'--':>8} {'--':>7}  "
                  f"UNVERIFIED: {str(e)[:40]}")
            bad += 1
            continue
        diff = app - val
        flag = "" if abs(diff) <= TOL else "   <-- MISMATCH"
        if flag:
            bad += 1
        print(f"{r['label'][:28]:28} {date:11} {app:8.3f} {val:8.3f} {diff:+7.3f}  "
              f"{glat:.4f},{glon:.4f}{flag}")

    print(f"\n{len(rows) - bad}/{len(rows)} verified against {ds} on ERDDAP")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
