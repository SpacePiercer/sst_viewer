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

Both questions are worth asking, so they get their own dots: one `host` source
probing `/erddap/version` (is the server answering at all?) and one `remote`
source per dataset probing its time axis (does this dataset's data come
through?). They are not independent -- a dead server condemns every dataset
without a further request, and a dataset that returns data proves the server
is alive without one -- so the pair still costs about one request per tick in
steady state. The /version probe fires only when the datasets stop vouching,
which is exactly when the distinction matters.
"""
import random
import re
import threading
import time
import urllib.parse

import datasets as D

TICK_S = 30           # thread wake interval; at most ONE remote probe per tick
FRESH_S = 60          # a source seen this recently (probe or real traffic) is skipped
PROBE_TIMEOUT_S = 15  # per address tried, not per probe -- see _tick()
# The first sweep used to run on a 3 s timeout so the loading screen got a fast
# verdict. It got a fast WRONG verdict: any source slower than 3 s came up red,
# the app opened claiming the server was offline, and the next tick quietly
# corrected it to green 30 s later. The splash now waits for the real answer
# (SPLASH_HEALTH_CAP_MS in app.js), so there is one timeout and it is honest.
SLOW_MS = 4000        # answered, but slow enough that the user should know
# consecutive-failure backoff: don't hammer a source that is already down
BACKOFF_S = (60, 120, 300, 600, 900)

# ERDDAP ships a per-server status page (uptime, load, recent failures) at
# /erddap/status.html -- the only outage signal that is about the machine this
# app talks to rather than NOAA/NASA in general. Deliberately upwell's and not
# the data host's: upwell is the sibling node that stays reachable when
# coastwatch.pfeg.noaa.gov goes dark, which is exactly when someone clicks it.
ERDDAP_STATUS_URL = "https://upwell.pfeg.noaa.gov/erddap/status.html"

# ERDDAP's status page is the only place that says WHY the host is unhappy, and
# it is plain enough to read: one <pre> block with a handful of summary lines,
# then a per-dataset "Reasons for failing to load" section. We pull the summary
# for the server dot, and look our own dataset ids up in the reasons so a
# dataset only gets its own note when the page actually names it. As of
# Sep 2026 neither jplMURSST41 nor ncdcOisst21Agg_LonPM180 appears there, so
# that lookup is normally empty -- which is the honest answer, not a gap.
STATUS_TTL_OK_S = 900     # refresh at most every 15 min while things are fine
STATUS_TTL_BAD_S = 120    # ...and more eagerly while something is down
_STATUS = {"fetched": 0.0, "summary": None, "reasons": {}, "error": None}

_SUMMARY_KEYS = (
    "Startup was at",
    "Last major LoadDatasets",
    "nTotalDatasets",
    "n Datasets Failed To Load",
)


def _parse_status(text):
    """(summary lines, {datasetID: reason}) from the status page HTML."""
    import html as _html

    blocks = re.findall(r"<pre>(.*?)</pre>", text, re.S)
    if not blocks:
        return [], {}
    body = _html.unescape(re.sub(r"<[^>]+>", "", blocks[0]))
    lines = [x.strip() for x in body.splitlines()]

    summary = [l for l in lines if any(l.startswith(k) for k in _SUMMARY_KEYS)]
    # "datasetID: <whatever went wrong>" inside the reasons section
    reasons = {}
    for l in lines:
        m = re.match(r"^([A-Za-z0-9_]{4,}):\s+(\S.*)$", l)
        if m:
            reasons.setdefault(m.group(1), m.group(2)[:200])
    return summary, reasons


def _refresh_status(force=False):
    """Fetch + parse the status page, at most once per TTL. Never raises."""
    any_down = any(v["status"] == "down" for v in _STATUS_SOURCES())
    ttl = STATUS_TTL_BAD_S if any_down else STATUS_TTL_OK_S
    if not force and time.time() - _STATUS["fetched"] < ttl:
        return
    _STATUS["fetched"] = time.time()
    try:
        raw = D._http_get_raw(ERDDAP_STATUS_URL, timeout=20)
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        summary, reasons = _parse_status(text)
        _STATUS.update(summary=summary, reasons=reasons, error=None)
    except Exception as e:
        # The status page lives on upwell precisely so it survives coastwatch
        # going dark -- but if it is unreachable too, say so rather than
        # showing a stale cause as if it were current.
        _STATUS["error"] = str(e)[:160]


def _STATUS_SOURCES():
    with _LOCK:
        return [dict(v) for v in _STATE.values()]


_LOCK = threading.RLock()
_STATE = {}           # source id -> mutable status dict
_HOSTS = {}           # netloc -> [source id, ...]  (for passive observation)
_PROBING = set()      # source ids with an in-flight probe
_ERDDAP_IDS = {}      # source id -> ERDDAP datasetID (for status-page lookups)
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


def _server_probe():
    """Is the ERDDAP process answering at all? /erddap/version is 20 bytes and
    touches no dataset -- the cheapest honest answer to that question, and the
    complement of _erddap_probe, which asks whether one dataset's DATA flows.
    Split on purpose: a server can serve metadata in 0.1 s while every real
    read hangs (PFEG, Sep 2026), and one dataset can be unloaded on a server
    that is otherwise fine. One dot cannot say both."""
    url = f"{D.ERDDAP}/version"

    def probe(timeout):
        D._http_get_raw(url, timeout=timeout)
    return probe


def _build():
    host = _host_of(D.ERDDAP)
    _STATE["erddap_server"] = {
        "id": "erddap_server", "name": host, "kind": "host",
        "host": host, "notices": ERDDAP_STATUS_URL,
        "status": "unknown", "latency_ms": None, "checked": 0.0, "error": None,
        "fails": 0, "since": time.time(), "via": None,
        "_probe": _server_probe(), "_next": 0.0,
    }
    _HOSTS.setdefault(host, []).append("erddap_server")
    for ds in D.DATASETS.values():
        remote = bool(getattr(ds, "ERDDAP_ID", ""))
        host = _host_of(D.ERDDAP) if remote else None
        _STATE[ds.id] = {
            "id": ds.id, "name": ds.name,
            "kind": "remote" if remote else "local",
            "host": host, "notices": ERDDAP_STATUS_URL if host else None,
            "status": "unknown", "latency_ms": None,
            "checked": 0.0, "error": None, "fails": 0,
            "since": time.time(), "via": None,
            "_probe": _erddap_probe(ds) if remote else _local_probe(ds),
            "_next": 0.0,
        }
        if host:
            _HOSTS.setdefault(host, []).append(ds.id)
            _ERDDAP_IDS[ds.id] = ds.ERDDAP_ID
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
        free = [s for s in due if s["kind"] not in ("remote", "host")]
        server = [s for s in due if s["kind"] == "host"]
        remote = [s for s in due if s["kind"] == "remote"]
        # Cold start: cover EVERY never-checked dataset in this tick rather
        # than one per 30 s. There is no real traffic to piggyback on yet and
        # the loading screen is blocked on the result; the rate limit exists to
        # bound sustained load, not one request per source, once.
        cold = [s for s in remote if not s["checked"]]
        if cold:
            batch, timeout = cold, PROBE_TIMEOUT_S
        else:
            # steady state: one dataset probe per tick, least-recently-checked
            # first, so N datasets cost 1 dataset request per tick
            pick = min(remote, key=lambda s: s["checked"]) if remote else None
            batch, timeout = ([pick] if pick else []), PROBE_TIMEOUT_S
    # The server probe runs first and gates the dataset probes: if ERDDAP is
    # not answering at all, asking each dataset the same question again only
    # adds load to a struggling host and tells the user nothing new.
    for st in free + server:
        with _LOCK:
            _PROBING.add(st["id"])
        ok, ms, err = _run_probe(st, PROBE_TIMEOUT_S)
        with _LOCK:
            _PROBING.discard(st["id"])
            _record(st["id"], ok, ms, err, "probe")
    with _LOCK:
        srv = _STATE["erddap_server"]
        if srv["status"] == "down":
            for st in remote:
                _record(st["id"], False, None, srv["error"], "server")
            batch = []
        else:
            # A dataset last judged only by the server being down carries no
            # dataset-level evidence, and its failure backoff can be 15 min --
            # far too long to keep it red once ERDDAP is answering again.
            for st in _STATE.values():
                if st["kind"] == "remote" and st["via"] == "server":
                    st["_next"] = 0.0
    for st in batch:
        with _LOCK:
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
            if ok:
                # A dataset that returned data PROVES the server answered, so
                # the server dot costs nothing while things are working -- the
                # /version probe only fires when the datasets stop vouching.
                _record("erddap_server", True, ms, None, "traffic")
            else:
                # ...and when one fails, re-probe the server next tick: that is
                # what separates "ERDDAP is down" from "this dataset is broken".
                _STATE["erddap_server"]["_next"] = 0.0


def _loop():
    while True:
        try:
            _tick()
            _refresh_status()
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
    # Attach the cause, so a red dot can say WHY rather than just "down".
    # A dataset gets its own note only when the status page names its id;
    # otherwise the server's note is the whole story and repeating it on every
    # dataset would just be noise.
    for src in sources:
        eid = _ERDDAP_IDS.get(src["id"])
        if eid and eid in _STATUS["reasons"]:
            src["cause"] = _STATUS["reasons"][eid]
        elif src["kind"] == "host":
            src["cause"] = "\n".join(_STATUS["summary"] or [])
    return {"tick_s": TICK_S, "fresh_s": FRESH_S, "sources": sources,
            "status_url": ERDDAP_STATUS_URL,
            "status_error": _STATUS["error"],
            "status_age_s": (None if not _STATUS["fetched"]
                             else round(now - _STATUS["fetched"]))}
