import time
import datasets as D

print("ERDDAP base:", D.ERDDAP)

def timed(label, fn):
    t = time.time()
    try:
        r = fn()
        print(f"OK   {label:38s} {time.time()-t:6.1f}s  {str(r)[:70]}")
        return True
    except Exception as e:
        print(f"FAIL {label:38s} {time.time()-t:6.1f}s  {type(e).__name__}: {str(e)[:110]}")
        return False

timed("ERDDAP index.html", lambda: len(D._http_get(D.ERDDAP + "/griddap/index.html", timeout=20)))

mur = D.get_dataset("mur_okhotsk")
timed("mur.dates() (time axis)", lambda: f"{len(mur.dates())} dates")

# the actual failing call: a one-point subset
timed("mur.point_series 1 day",
      lambda: mur.point_series(48.44, 140.191, "analysed_sst", "2020-05-01", "2020-05-01"))
timed("mur.point_series 20 days",
      lambda: f"{len(mur.point_series(48.44, 140.191, 'analysed_sst', '2020-05-01', '2020-05-20'))} pts")
