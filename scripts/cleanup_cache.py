r"""Nightly wipe of the sst_viewer derived caches and the local OISST sources.

Removes:
  cache/fields/**            every .npy tile/field, its .json sidecar, the
                             per-dataset subdirectories themselves
  cache/*_*.png              rendered overlay PNGs at the top level of cache/
  cache/*.part               abandoned partial downloads
  data/oisst_may20_july1/*.nc  the local OISST source files

Never touches:
  cache/landmask.npy   datasets.py land_mask() reads exactly this path and can
                       only regenerate it with a network request -- keeping it
                       leaves the app usable offline right after a wipe.
  library/             user content (reports, downloads, series)
  areas.json, cache/uvicorn*.log, cache/timelapse_*.gif, anything else.

Dry run is the default, so a mis-fired invocation cannot destroy anything:
    conda run -n mfa_env python scripts/cleanup_cache.py            # dry run
    conda run -n mfa_env python scripts/cleanup_cache.py --yes      # deletes

--- scheduling ----------------------------------------------------------
This script only DELETES. The nightly job also re-downloads the day's data
afterwards, so it runs through scripts/nightly.py, registered by
scripts/register_nightly.ps1 as \AgenticOS\sst_viewer_nightly (daily 03:30,
log in cache/nightly.log). Do not schedule this file directly -- that would
wipe the cache and leave it empty.
------------------------------------------------------------------------------
"""

import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from datasets import CACHE, FIELDS  # noqa: E402  single source of truth for the cache path
OISST_DIR = HERE / "data" / "oisst_may20_july1"

KEEP = {CACHE / "landmask.npy"}  # load-bearing: see module docstring


def _show(p):
    """Display path: relative to the repo when it lives there, else absolute.
    CACHE is outside the repo now, so relative_to(HERE) would raise."""
    try:
        return p.relative_to(HERE)
    except ValueError:
        return p


def victims():
    """(files, dirs) that a real run would delete. Files first, dirs after."""
    files = [p for p in FIELDS.rglob("*") if p.is_file()]
    files += [p for p in CACHE.glob("*_*.png") if p.is_file()]
    files += [p for p in OISST_DIR.glob("*.nc") if p.is_file()]
    # Interrupted downloads leave <name>.part behind -- one was 95 MB. They are
    # never resumed (_http_download_raw always starts a fresh temp), so they are
    # pure garbage the moment the process that owned them is gone.
    files += [p for p in CACHE.glob("*.part") if p.is_file()]
    files = [p for p in files if p not in KEEP]
    dirs = [p for p in FIELDS.iterdir() if p.is_dir()] if FIELDS.is_dir() else []
    return files, dirs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--yes", action="store_true", help="actually delete")
    ap.add_argument("--dry-run", action="store_true", help="default; list only")
    ap.add_argument("--verbose", "-v", action="store_true", help="list every file")
    a = ap.parse_args(argv)

    files, dirs = victims()
    total = sum(p.stat().st_size for p in files)

    if not a.yes:
        for p in (files if a.verbose else files[:20]):
            print(f"  would delete  {_show(p)}")
        if not a.verbose and len(files) > 20:
            print(f"  ... and {len(files) - 20} more (-v to list all)")
        for d in dirs:
            print(f"  would rmdir   {_show(d)}")
        print(f"DRY RUN: {len(files)} files, {total / 1e6:.1f} MB would be freed "
              f"(pass --yes to delete)")
        return 0

    n = 0
    for p in files:
        try:
            p.unlink()
            n += 1
        except OSError as e:
            print(f"skip {p}: {e}", file=sys.stderr)
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    print(f"cleanup: {n} files, {total / 1e6:.1f} MB freed")
    return 0


def _selftest():
    """One runnable check: the keep-list actually holds. `python cleanup_cache.py --selftest`"""
    files, dirs = victims()
    assert (CACHE / "landmask.npy") not in files, "landmask.npy must survive"
    assert not any("library" in p.parts for p in files), "library/ must survive"
    assert not any(p.name == "areas.json" for p in files), "areas.json must survive"
    assert all(str(p).startswith((str(FIELDS), str(CACHE), str(OISST_DIR))) for p in files)
    assert all(p.suffix in (".npy", ".json", ".png", ".nc", ".part") for p in files), \
        "only derived/source data, no logs or gifs"
    assert all(d.parent == FIELDS for d in dirs)
    print(f"selftest OK ({len(files)} files, {len(dirs)} dirs selected)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit(main())
