"""Verify the fetch/render split: the raw series is cached per point, so a
second run does ZERO network calls, and a subset of cached dates does too.
Uses a fake dataset that counts point_series calls -- no real network.
Run: conda run -n mfa_env python test_cache.py
"""
import reports as R

CALLS = []


class FakeDS:
    """Minimal stand-in: records every fetch and returns one value per date."""
    variables = {"sst": {}}
    name = "FakeDS"

    def point_series(self, lat, lon, var, start, end):
        CALLS.append((start, end))
        from datetime import date, timedelta
        out, cur = [], date.fromisoformat(start)
        stop = date.fromisoformat(end)
        while cur <= stop:
            out.append({"date": cur.isoformat(), "value": 10.0 + cur.year - 2005})
            cur += timedelta(days=1)
        return out


DSID = "unittest_ds"
LAT, LON, VAR = 48.1234, 140.5678, "sst"
dates_2y = [f"{y}-05-{d:02d}" for y in (2005, 2006) for d in range(25, 32)]

# start clean
p = R._series_path(DSID, LAT, LON, VAR)
p.unlink(missing_ok=True)
ds = FakeDS()

# --- run 1: cold cache -> must hit the network
CALLS.clear()
df1, cached1 = R.point_frame_cached(ds, DSID, LAT, LON, VAR, dates_2y)
n1 = len(CALLS)
assert df1 is not None and len(df1) == 14, df1
assert cached1 is False, "cold run must not report cached"
assert n1 > 0, "cold run must fetch"
print(f"run1 (cold):      rows={len(df1):3d} network_calls={n1} from_cache={cached1}")

# --- run 2: same request -> must be served entirely from disk
CALLS.clear()
df2, cached2 = R.point_frame_cached(ds, DSID, LAT, LON, VAR, dates_2y)
assert cached2 is True, "second identical run must be cached"
assert len(CALLS) == 0, f"second run made {len(CALLS)} network calls, expected 0"
assert len(df2) == len(df1), (len(df2), len(df1))
print(f"run2 (same):      rows={len(df2):3d} network_calls={len(CALLS)} from_cache={cached2}")

# --- run 3: a SUBSET of cached dates -> still zero network
CALLS.clear()
subset = dates_2y[:5]
df3, cached3 = R.point_frame_cached(ds, DSID, LAT, LON, VAR, subset)
assert cached3 is True and len(CALLS) == 0, (cached3, CALLS)
assert len(df3) == 5, len(df3)
print(f"run3 (subset):    rows={len(df3):3d} network_calls={len(CALLS)} from_cache={cached3}")

# --- run 4: new dates -> fetches ONLY the missing ones
CALLS.clear()
extra = dates_2y + [f"2007-05-{d:02d}" for d in range(25, 32)]
df4, cached4 = R.point_frame_cached(ds, DSID, LAT, LON, VAR, extra)
assert cached4 is False and len(CALLS) > 0
fetched_years = {c[0][:4] for c in CALLS}
assert fetched_years == {"2007"}, f"should only refetch 2007, got {fetched_years}"
assert len(df4) == 21, len(df4)
print(f"run4 (new year):  rows={len(df4):3d} network_calls={len(CALLS)} fetched_years={fetched_years}")

# --- run 5: refresh=True -> forces a re-download
CALLS.clear()
df5, cached5 = R.point_frame_cached(ds, DSID, LAT, LON, VAR, dates_2y, refresh=True)
assert cached5 is False and len(CALLS) > 0, "refresh must re-download"
print(f"run5 (refresh):   rows={len(df5):3d} network_calls={len(CALLS)} from_cache={cached5}")

# --- anomaly is derived per-request, not cached
a_full = df1["sst_anomaly"].tolist()
a_sub = df3["sst_anomaly"].tolist()
assert set(a_sub) == {0.0}, "single-year subset must have zero anomaly"
assert set(a_full) != {0.0}, "two-year request must have non-zero anomaly"
print("anomaly derived per request (subset all-zero, full non-zero): OK")

p.unlink(missing_ok=True)
print("\nCACHE TESTS PASSED")
