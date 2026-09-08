"""Live per-source health, refreshed by one polite background prober.

Two signals feed the same state, so freshness costs as few requests as
possible:

  * passive -- every real fetch the app already makes reports its outcome
    through `datasets.OBSERVERS`. Free, and it means a busy app barely probes
    at all.
  * active  -- a single daemon thread that probes AT MOST ONE remote source
    per tick, and only if that source has not been seen recently.

Rate limiting is deliberately budgeted against the HOST, not the dataset:
both ERDDAP datasets live on the same PFEG box, so
probing them independently would double the load on one server for no extra
information. One probe per tick across all remote sources caps total outbound
health traffic at 1 request / TICK_S no matter how many datasets are added
later.

With the defaults below that is 2 requests/minute to NOAA, single-threaded
(never concurrent), dropping to 4/hour once a source starts failing. ERDDAP's
published guidance is to avoid parallel and rapid-fire requests rather than a
numeric rate; this sits far under any plausible threshold and backs off hard
exactly when a struggling server would most want us to.

The probe reads ONE value off the dataset's time axis. A `.das` would be
cheaper still, but it is served from ERDDAP's metadata cache and stays green
while the dataset's files are unreadable -- so it answers "is the server
running", when the question is "does data flow".
"""
import random
import threading
import time
import urllib.parse

import datasets as D

TICK_S = 30           # thread wake interval; at most ONE remote probe per tick
FRESH_S = 60          # a source seen this recently (probe or real traffic) is skipped
PROBE_TIMEOUT_S = 15  # per address tried, not per probe -- see _tick()
# The FIRST sweep has a different job from every later one: the loading screen
# is waiting on it, so it needs a verdict fast, not a verdict that is right
# about a merely-slow server. 15 s x 2 DNS addresses = ~30 s of grey dots,
# which is what this exists to avoid. A false "down" here self-corrects on the
# next tick, which re-probes with the full timeout.
FIRST_PROBE_TIMEOUT_S = 3
SLOW_MS = 4000        # answered, but slow enough that the user should know
# consecutive-failure backoff: don't hammer a source that is already down
BACKOFF_S = (60, 120, 300, 600, 900)

_LOCK = threading.RLock()
_STATE = {}           # source id -> mutable status dict
_HOSTS = {}           # netloc -> [source id, ...]  (for passive observation)
_PROBING = set()      # source ids with an in-flight probe
_thread = None


def _host_of(url):
    return urllib.parse.urlparse(url).netloc


# ------------------------------------------------------------------ probes

def _erddap_probe(ds):
    # Read ONE value off the dataset's time axis, not the .das metadata.
    # A .das is answered from ERDDAP's in-memory metadata cache, so it keeps
    # returning 200 even when the dataset's files are unreadable and every
    # real fetch hangs -- exactly the PFEG state in Sep 2026, where .das came
    # back in 0.1 s while a single-pixel read timed out at 42 s. The dots have
    # to track whether DATA flows, not whether the server process is alive.
    # Cost is unchanged: the response is a few dozen bytes and touches no grid.
    url = f"{D.ERDDAP}/griddap/{ds.ERDDAP_ID}.csv?time%5B0:1:0%5D"

    def probe(timeout):
        # _http_get_raw, NOT _http_get: retrying a health check would triple
        # the load and delay the very signal we are trying to report.
        D._http_get_raw(url, timeout=timeout)
    return probe


def _local_probe(ds):
    def probe(_timeout):
        if not any(D.OISST_DIR.glob("*.nc")):
            raise FileNotFoundError(f"no .nc files in {D.OISST_DIR}")
    return probe


def _quarto_probe():
    """PDF rendering is not a data source, but it fails the same way from the
    user's point of view -- and it used to fail only at the END of a long
    batch fetch. Checking it up front costs one Path.exists()."""
    def probe(_timeout):
        import reports as R
        R._quarto_exe()  # raises RuntimeError if neither candidate path exists
    return probe


def _build():
    for ds in D.DATASETS.values():
        remote = bool(getattr(ds, "ERDDAP_ID", ""))
        host = _host_of(D.ERDDAP) if remote else None
        _STATE[ds.id] = {
            "id": ds.id, "name": ds.name,
            "kind": "remote" if remote else "local",
            "host": host, "status": "unknown", "latency_ms": None,
            "checked": 0.0, "error": None, "fails": 0,
            "since": time.time(), "via": None,
            "_probe": _erddap_probe(ds) if remote else _local_probe(ds),
            "_next": 0.0,
        }
        if host:
            _HOSTS.setdefault(host, []).append(ds.id)
    _STATE["reports"] = {
        "id": "reports", "name": "PDF reports", "kind": "tool", "host": None,
        "status": "unknown", "latency_ms": None, "checked": 0.0, "error": None,
        "fails": 0, "since": time.time(), "via": None,
        "_probe": _quarto_probe(), "_next": 0.0,
    }


# ------------------------------------------------------------- state update

def _record(sid, ok, latency_ms, err, via):
    """Caller must hold _LOCK."""
    st = _STATE[sid]
    if not ok:
        status = "down"
    elif latency_ms is not None and latency_ms >= SLOW_MS:
        status = "slow"
    else:
        status = "ok"
    if status != st["status"]:
        st["since"] = time.time()
    st["fails"] = 0 if ok else st["fails"] + 1
    st.update(status=status, latency_ms=latency_ms, checked=time.time(),
              error=None if ok else err, via=via)
    wait = FRESH_S if ok else BACKOFF_S[min(st["fails"] - 1, len(BACKOFF_S) - 1)]
    st["_next"] = time.time() + wait


def observe(url, reachable, latency_ms, err=None):
    """Passive signal from real app traffic. `reachable` means the server
    answered at all -- an HTTP 404/500 for one dataset says nothing about the
    others on that host, so only transport-level failures mark a host down.
    Dataset-level truth comes from the active probe."""
    with _LOCK:
        for sid in _HOSTS.get(_host_of(url), ()):
            # A probe's own request lands here too. Let the prober record that
            # one -- it knows whether the DATASET answered, not just the host,
            # and counting it twice would double the failure count and so
            # skip a backoff step. Other sources on the host still benefit.
            if sid in _PROBING:
                continue
            _record(sid, reachable, latency_ms, err, "traffic")


# ------------------------------------------------------------------- prober

def _run_probe(st, timeout):
    """Execute one probe. Must NOT be called holding _LOCK (does network I/O)."""
    t0 = time.time()
    try:
        st["_probe"](timeout)
        return True, int((time.time() - t0) * 1000), None
    except Exception as e:
        return False, int((time.time() - t0) * 1000), str(e)[:200]


def _tick():
    now = time.time()
    with _LOCK:
        due = [s for s in _STATE.values() if s["_next"] <= now]
        # local/tool checks touch no network, so they cost nothing and all run
        free = [s for s in due if s["kind"] != "remote"]
        remote = [s for s in due if s["kind"] == "remote"]
        # Cold start: cover EVERY never-checked remote source in this tick
        # rather than one per 30 s. There is no real traffic to piggyback on
        # yet and the loading screen is blocked on the result; the rate limit
        # exists to bound sustained load, not one request per source, once.
        # In practice this is still a single request -- sources sharing a host
        # are resolved by the first probe's passive observation and skipped
        # below.
        cold = [s for s in remote if not s["checked"]]
        if cold:
            batch, timeout = cold, FIRST_PROBE_TIMEOUT_S
        else:
            # steady state: one remote probe per tick, least-recently-checked
            # first, so N datasets on one host still cost 1 request per tick
            pick = min(remote, key=lambda s: s["checked"]) if remote else None
            batch, timeout = ([pick] if pick else []), PROBE_TIMEOUT_S
    for st in free + batch:
        with _LOCK:
            if cold and st["kind"] == "remote" and st["status"] != "unknown":
                continue  # a sibling's probe already answered for this host
            _PROBING.add(st["id"])
        # Budget up to (number of DNS addresses) x timeout here, not timeout:
        # urllib tries each address in turn with its own timeout, and
        # coastwatch.pfeg.noaa.gov publishes both an A and an AAAA record --
        # measured 30 s for a 15 s timeout while it was down. Harmless: one
        # thread, one probe at a time, so a slow probe only stretches the
        # cadence, i.e. errs towards less load.
        ok, ms, err = _run_probe(st, timeout)  # never raises; returns a triple
        with _LOCK:
            _PROBING.discard(st["id"])
            _record(st["id"], ok, ms, err, "probe")
            if cold and not ok:
                # the short startup timeout can misjudge a merely-slow server,
                # so confirm at full timeout on the next tick instead of
                # sitting on the 60 s failure backoff
                _STATE[st["id"]]["_next"] = time.time() + TICK_S


def _loop():
    while True:
        try:
            _tick()
        except Exception:
            pass  # a monitor that can die is worse than one that misses a tick
        # jitter so probes never lock onto a wall-clock boundary
        time.sleep(TICK_S + random.uniform(0, 5))


def start():
    """Idempotent; safe to call from a FastAPI startup hook."""
    global _thread
    with _LOCK:
        if _thread is not None:
            return
        _build()
        D.OBSERVERS.append(observe)
        _thread = threading.Thread(target=_loop, daemon=True, name="health")
        _thread.start()


def snapshot():
    now = time.time()
    with _LOCK:
        sources = [
            {k: v for k, v in s.items() if not k.startswith("_")} | {
                "age_s": None if not s["checked"] else round(now - s["checked"], 1),
                "next_check_s": max(0, round(s["_next"] - now)),
            }
            for s in _STATE.values()
        ]
    return {"tick_s": TICK_S, "fresh_s": FRESH_S, "sources": sources}
