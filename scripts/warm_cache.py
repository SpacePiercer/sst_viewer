r"""Re-download the two things the app always wants, after the nightly wipe.

  * MUR 1 km over the Okhotsk study box, for MUR's newest available date
  * OISST 0.25 deg globally, for OISST's newest available date

The wipe leaves the cache empty, so without this the first launch of the day
pays a multi-minute download before it can draw anything. Running it overnight
means the morning opens on data that is already local.

coastwatch.pfeg.noaa.gov is unreliable for days at a time (see the comment on
ERDDAP in datasets.py), so a single failed attempt says nothing about whether
the data is gettable. This keeps retrying on a fixed interval until everything
is in or the deadline passes -- bounded, because an unbounded retry loop would
still be hammering a dead host when the next night's run starts.

    conda run -n mfa_env python scripts/warm_cache.py
    conda run -n mfa_env python scripts/warm_cache.py --hours 6 --every 15
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datasets as D  # noqa: E402

# The study region, not the whole PACIFIC box: PACIFIC at 1 km is ~180M cells,
# and this is the area actually worked in.
OKHOTSK = (135.0, 40.0, 165.0, 65.0)


def warm_once(log=print):
    """One attempt. Returns True when everything is on disk."""
    ok = True

    # --- OISST: one global field for its newest date ----------------------
    try:
        ds = D.DATASETS["oisst_remote"]
        date = ds.dates()[-1]
        if all(ds.field_available(date, v) for v in ds.ALL_VARS):
            log(f"oisst_remote {date}: already cached")
        else:
            log(f"oisst_remote {date}: downloading global field ...")
            ds.ensure_field(date)
            log(f"oisst_remote {date}: done")
    except Exception as e:                      # RemoteError and friends
        log(f"oisst_remote FAILED: {str(e)[:160]}")
        ok = False

    # --- MUR: the Okhotsk tiles for its newest date -----------------------
    try:
        mur = D.DATASETS["mur_okhotsk"]
        date = mur.dates()[-1]
        missing = mur.missing_tiles(date, *OKHOTSK)
        if not missing:
            log(f"mur_okhotsk {date}: all {len(mur.tiles_for(*OKHOTSK))} tiles cached")
        else:
            log(f"mur_okhotsk {date}: {len(missing)} tiles to fetch ...")
            for i, (var, tile) in enumerate(missing, 1):
                mur.fetch_tile(date, var, tile)
                if i % 10 == 0 or i == len(missing):
                    log(f"  {i}/{len(missing)}")
            log(f"mur_okhotsk {date}: done")
    except Exception as e:
        log(f"mur_okhotsk FAILED: {str(e)[:160]}")
        ok = False

    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--hours", type=float, default=6.0,
                    help="give up after this long (default 6)")
    ap.add_argument("--every", type=float, default=15.0,
                    help="minutes between retries (default 15)")
    ap.add_argument("--once", action="store_true", help="one attempt, no retry")
    a = ap.parse_args(argv)

    def log(m):
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

    deadline = time.time() + a.hours * 3600
    attempt = 0
    while True:
        attempt += 1
        log(f"--- warm attempt {attempt} ---")
        if warm_once(log):
            log("warm complete")
            return 0
        if a.once:
            log("warm incomplete (--once)")
            return 1
        if time.time() + a.every * 60 >= deadline:
            log(f"warm incomplete, giving up after {a.hours} h")
            return 1
        log(f"retrying in {a.every:g} min")
        time.sleep(a.every * 60)


if __name__ == "__main__":
    sys.exit(main())
