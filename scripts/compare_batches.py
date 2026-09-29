r"""Compare two batch CSVs cell by cell -- the app run against the script run.

    conda run -n mfa_env python scripts/compare_batches.py APP.csv SCRIPT.csv

What this catches is the UI layer, not the data: both runs POST to the same
/api/batch_job, so a disagreement means the browser sent something different
from the spec -- the wrong dataset in the picker, a row left unchecked, a name
that did not become the label, the PDF flag off. Those are real and invisible
in a script-only run.

What it does NOT catch is a wrong VALUE: identical inputs through one code path
give identical outputs. verify_batch.py is the check for that, and neither
replaces the other.

It is also only meaningful if the second run actually refetched. Both runs
reading the same library/series/ cache agree by construction -- run the script
side with "refresh": true, or this prints a pass it did not earn.
"""

import csv
import sys
from pathlib import Path

KEY = ("label", "date")


def load(p):
    rows = {}
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[tuple(r[k] for k in KEY)] = r
    return rows


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    a_path, b_path = (Path(x) for x in argv)
    a, b = load(a_path), load(b_path)

    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    shared = sorted(set(a) & set(b))

    bad = []
    for k in shared:
        va, vb = a[k]["value"], b[k]["value"]
        if va == vb:
            continue
        try:
            if abs(float(va) - float(vb)) < 1e-9:
                continue
        except ValueError:
            pass
        bad.append((k, va, vb))
        # coordinates too: a mis-mapped label would still line up on value
    coord = [(k, a[k]["lat"], b[k]["lat"], a[k]["lon"], b[k]["lon"])
             for k in shared
             if a[k]["lat"] != b[k]["lat"] or a[k]["lon"] != b[k]["lon"]]

    print(f"app   : {a_path.name}  {len(a)} rows")
    print(f"script: {b_path.name}  {len(b)} rows")
    for k in only_a:
        print(f"  ONLY IN APP     {k[0]} {k[1]}")
    for k in only_b:
        print(f"  ONLY IN SCRIPT  {k[0]} {k[1]}")
    for k, va, vb in bad:
        print(f"  VALUE DIFFERS   {k[0]} {k[1]}: app={va} script={vb}")
    for k, la, lb, oa, ob in coord:
        print(f"  COORD DIFFERS   {k[0]} {k[1]}: app={la},{oa} script={lb},{ob}")

    if only_a or only_b or bad or coord:
        print(f"\nMISMATCH: {len(only_a)} app-only, {len(only_b)} script-only, "
              f"{len(bad)} value, {len(coord)} coord")
        return 1
    print(f"\n{len(shared)}/{len(shared)} rows identical across both paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
