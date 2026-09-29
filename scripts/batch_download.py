"""Batch CSV + PDF download for a set of named coordinates.

Drives the running app's own batch endpoint, so the data path, the series
cache and the report template are exactly the ones the Data tab uses -- this
is a front door, not a second implementation.

Input: JSON on stdin (or -f FILE):

    {
      "dataset": "mur_okhotsk",        # optional, this is the default
      "generate_pdf": true,            # optional, default true
      "refresh": false,                # optional, ignore the series cache
      "points": [
        {"name": "Tikhoye 1.5 km", "lat": 48.74997, "lon": 140.21045,
         "md": ["06-05"], "years": [2023, 2026]}
      ]
    }

`md`    : list of "MM-DD" calendar days for that point.
`years` : [from, to] inclusive, or an explicit list like [2023, 2025, 2026].
          A "MM-DD" that does not exist in a year (02-29) is skipped for it.

    conda run -n mfa_env python scripts/batch_download.py -f spec.json
    conda run -n mfa_env python scripts/batch_download.py --dry-run < spec.json

--dry-run resolves and prints the dates without starting anything: always
worth doing first, because a full run can take minutes per point.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date

BASE = "http://127.0.0.1:8000"


def expand(md_list, years):
    """['06-05'], [2023, 2026] -> ['2023-06-05', ... , '2026-06-05']."""
    if len(years) == 2 and years[1] > years[0] + 1:
        years = list(range(years[0], years[1] + 1))
    out = []
    for y in years:
        for md in md_list:
            m, d = (int(x) for x in md.split("-"))
            try:
                out.append(date(y, m, d).isoformat())
            except ValueError:
                print(f"  ! {y}-{md} does not exist, skipped", file=sys.stderr)
    return sorted(set(out))


def api(path, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-f", "--file", help="spec JSON (default: stdin)")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve dates and exit without starting the job")
    a = ap.parse_args()

    spec = json.load(open(a.file, encoding="utf-8") if a.file else sys.stdin)
    dataset = spec.get("dataset", "mur_okhotsk")
    want_pdf = spec.get("generate_pdf", True)

    points = []
    for p in spec["points"]:
        dates = expand(p["md"], p["years"])
        if not dates:
            sys.exit(f"point {p['name']!r} resolved to no dates")
        points.append({"lat": float(p["lat"]), "lon": float(p["lon"]),
                       "label": p["name"], "dates": dates})
        print(f"  {p['name']:<32} {len(dates):>3} date(s)  "
              f"{dates[0]} .. {dates[-1]}")
    total = sum(len(p["dates"]) for p in points)
    # one comparison PDF over all points: on by default with PDFs, 2+ points
    want_cmp = spec.get("compare", want_pdf) and len(points) >= 2
    print(f"\n  {len(points)} point(s), {total} dates, dataset={dataset}, "
          f"pdf={want_pdf}, compare={want_cmp}")
    if a.dry_run:
        return

    try:
        job = api("/api/batch_job", {"dataset": dataset, "points": points,
                                     "generate_pdf": want_pdf,
                                     "generate_compare": want_cmp,
                                     "refresh_data": spec.get("refresh", False)})
    except urllib.error.URLError as e:
        sys.exit(f"cannot reach the app at {BASE} ({e}); start it with "
                 f"scripts\\launch.ps1 first")
    jid = job["id"]
    print(f"\n  job {jid} started\n")

    last, t0 = None, time.time()
    while True:
        st = api(f"/api/batch_job_status?id={jid}", timeout=15)
        cur = tuple((p["label"], p["stage"]) for p in st["points"])
        if cur != last:
            done = sum(1 for p in st["points"] if p["status"] == "done")
            print(f"  t+{time.time()-t0:5.0f}s  {done}/{len(points)}  " +
                  " | ".join(f"{p['label'].split()[0]}:{p['stage']}"
                             for p in st["points"]))
            last = cur
        if st["state"] == "done":
            break
        time.sleep(3)

    print()
    failed = 0
    for p in st["points"]:
        if p["status"] == "done":
            print(f"  OK   {p['label']:<32} {p.get('pdf_url') or '(csv only)'}")
        else:
            failed += 1
            print(f"  FAIL {p['label']:<32} {p.get('error')}")
    print(f"  CSV  {st.get('csv_url')}")
    if want_cmp:
        print(f"  CMP  {st.get('compare_url') or 'FAILED: ' + str(st.get('compare_error'))}")
    if failed:
        sys.exit(f"{failed} point(s) failed")


if __name__ == "__main__":
    main()
