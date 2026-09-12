"""Checks for the two bits of real logic added alongside the health monitor:
date-run clustering and the health state machine (backoff + passive observe).

Run: conda run -n mfa_env python test_health.py
"""
import time

import health as H
import reports as R


def test_date_runs():
    # the config that motivated this: 5 days each May, 2003-2026
    dates = sorted(f"{y}-05-{d:02d}" for y in range(2003, 2027)
                   for d in (1, 5, 10, 15, 20))
    runs = R._date_runs(dates)
    assert len(runs) == 24, f"expected one run per year, got {len(runs)}"
    assert all(len(r) == 5 for r in runs)
    # the whole point: timesteps on the wire, vs 8420 for a single min..max span
    span = sum((R.date.fromisoformat(r[-1]) - R.date.fromisoformat(r[0])).days + 1
               for r in runs)
    assert span == 24 * 20, span
    assert span < 500, "clustering must collapse the 8420-day span"

    # a genuinely contiguous range stays ONE request, exactly as before
    contig = [f"2020-06-{d:02d}" for d in range(1, 31)]
    assert len(R._date_runs(contig)) == 1

    # gap exactly at the threshold does not split; one past it does
    assert len(R._date_runs(["2020-01-01", "2020-02-01"])) == 1   # 31 days
    assert len(R._date_runs(["2020-01-01", "2020-02-02"])) == 2   # 32 days
    assert R._date_runs(["2020-01-01"]) == [["2020-01-01"]]
    print("ok  date runs")


def test_health_state():
    H._STATE.clear()
    H._HOSTS.clear()
    H._build()
    ids = set(H._STATE)
    assert {"oisst_local", "oisst_remote", "mur_okhotsk"} <= ids, ids
    # both ERDDAP datasets must share ONE host entry, or the rate budget is
    # per-dataset instead of per-server
    assert len(H._HOSTS) == 1, H._HOSTS
    (host, sids), = H._HOSTS.items()
    assert sorted(sids) == ["erddap_server", "mur_okhotsk", "oisst_remote"], sids

    # the server itself gets its own dot: "is ERDDAP answering" is a different
    # question from "does this dataset's data flow", and one dot cannot say both
    srv = H._STATE["erddap_server"]
    assert srv["kind"] == "host" and srv["host"] == host
    assert all(H._STATE[d]["kind"] == "remote" for d in ("oisst_remote", "mur_okhotsk"))

    # the local source needs no network at all
    assert H._STATE["oisst_local"]["kind"] == "local"
    ok, _, err = H._run_probe(H._STATE["oisst_local"], H.PROBE_TIMEOUT_S)
    assert ok, err

    # PDF rendering is checked up front too -- it used to surface only at the
    # END of a long batch fetch. It is not a data source, so it must not eat
    # into the remote request budget.
    rep = H._STATE["reports"]
    assert rep["kind"] == "tool" and rep["host"] is None
    ok, _, err = H._run_probe(rep, H.PROBE_TIMEOUT_S)
    assert ok, f"quarto not found: {err}"

    sid = "mur_okhotsk"
    st = H._STATE[sid]
    # failures back off, and never faster than the previous step
    waits = []
    for _ in range(6):
        with H._LOCK:
            H._record(sid, False, 900, "network error: boom", "probe")
        waits.append(round(st["_next"] - time.time()))
    assert st["status"] == "down" and st["fails"] == 6
    assert waits[0] < waits[1] < waits[2], waits
    assert waits[-1] == H.BACKOFF_S[-1], waits          # capped, not unbounded
    assert all(b >= a for a, b in zip(waits, waits[1:])), waits

    # success resets the counter and returns to the fast cadence
    with H._LOCK:
        H._record(sid, True, 120, None, "probe")
    assert (st["status"], st["fails"], st["error"]) == ("ok", 0, None)
    assert round(st["_next"] - time.time()) == H.FRESH_S

    # slow but answering is distinct from down
    with H._LOCK:
        H._record(sid, True, H.SLOW_MS + 1, None, "probe")
    assert st["status"] == "slow"

    # passive observation: a transport failure condemns every source on the
    # host, because that is a property of the host and not of one dataset
    H.observe(f"https://{host}/erddap/griddap/whatever.nc", False, 25000, "reset")
    assert all(H._STATE[s]["status"] == "down" for s in sids)
    assert H._STATE[sid]["via"] == "traffic"
    # ...but an HTTP error means the server ANSWERED, so it must not
    H.observe(f"https://{host}/erddap/griddap/whatever.nc", True, 80, None)
    assert all(H._STATE[s]["status"] == "ok" for s in sids)
    # an unrelated host touches nothing
    before = dict(H._STATE[sid])
    H.observe("https://example.com/x", False, 10, "nope")
    assert H._STATE[sid]["checked"] == before["checked"]

    snap = H.snapshot()
    assert {s["id"] for s in snap["sources"]} == ids
    assert all(not k.startswith("_") for s in snap["sources"] for k in s)
    print("ok  health state")


def test_cold_sweep():
    """The loading screen blocks on the first sweep, so tick 1 must resolve
    EVERY source. One remote per 30 s tick would leave dots grey for a minute,
    and the full 15 s timeout x 2 DNS addresses would leave them grey for 30 s
    -- both are the bug this exists to prevent."""
    H._STATE.clear()
    H._HOSTS.clear()
    H._build()
    seen = []
    for s in H._STATE.values():
        s["_probe"] = lambda t, sid=s["id"]: seen.append((sid, t))
    H._tick()
    assert {sid for sid, _ in seen} == set(H._STATE), seen
    assert all(s["status"] != "unknown" for s in H._STATE.values())
    assert H.FIRST_PROBE_TIMEOUT_S < H.PROBE_TIMEOUT_S
    assert all(t == H.FIRST_PROBE_TIMEOUT_S for sid, t in seen
               if H._STATE[sid]["kind"] == "remote"), seen
    print("ok  cold sweep resolves every source in tick 1")


def test_server_down_condemns_datasets_for_free():
    """A dead server answers for every dataset on it: one /version request,
    no per-dataset probes, and the datasets say WHY they are red."""
    H._STATE.clear()
    H._HOSTS.clear()
    H._build()
    calls = []

    def probe(_t, sid):
        calls.append(sid)
        if sid == "erddap_server":
            raise OSError("connection reset")

    for s in H._STATE.values():
        s["_probe"] = lambda _t, sid=s["id"]: probe(_t, sid)
    H._tick()
    assert calls == ["oisst_local", "reports", "erddap_server"], calls
    for d in ("oisst_remote", "mur_okhotsk"):
        assert H._STATE[d]["status"] == "down", d
        assert H._STATE[d]["via"] == "server", H._STATE[d]["via"]
        assert "reset" in H._STATE[d]["error"]
    print("ok  a dead server condemns its datasets without extra requests")


def test_dataset_down_on_a_live_server():
    """The point of the split: one dataset can be red while the server, and
    the other dataset, stay green."""
    H._STATE.clear()
    H._HOSTS.clear()
    H._build()

    def probe(_t, sid):
        if sid == "mur_okhotsk":
            raise OSError("dataset not loaded")

    for s in H._STATE.values():
        s["_probe"] = lambda _t, sid=s["id"]: probe(_t, sid)
    H._tick()                                   # cold: server + both datasets
    assert H._STATE["erddap_server"]["status"] == "ok"
    assert H._STATE["oisst_remote"]["status"] == "ok"
    assert H._STATE["mur_okhotsk"]["status"] == "down"
    # a working dataset vouches for the server, so its dot costs no request
    assert H._STATE["erddap_server"]["via"] == "traffic"
    print("ok  a broken dataset does not condemn the server or its sibling")


def test_probe_budget():
    """Steady state: at most one remote request per tick regardless of how
    many remote datasets exist -- the rate-limit guarantee."""
    H._STATE.clear()
    H._HOSTS.clear()
    H._build()
    calls = []
    for s in H._STATE.values():
        if s["kind"] == "remote":
            s["_probe"] = lambda _t, sid=s["id"]: calls.append(sid)
        else:
            s["_probe"] = lambda _t: None
    H._tick()            # cold sweep; covered by its own test
    calls.clear()
    H._tick()
    assert not calls, "sources checked <60 s ago must not be re-probed"
    for s in H._STATE.values():
        s["_next"] = 0.0
    H._tick()
    assert len(calls) == 1, f"tick made {len(calls)} remote requests: {calls}"
    H._tick()
    assert len(calls) == 2 and calls[0] != calls[1], calls  # round-robin
    print(f"ok  probe budget (<=1 remote request / {H.TICK_S}s tick)")


def test_probe_not_double_counted():
    """A probe's own HTTP call also reaches observe(). Counting it twice would
    double the failure count and skip a backoff step -- but the OTHER dataset
    on the same host must still pick the signal up for free."""
    H._STATE.clear()
    H._HOSTS.clear()
    H._build()
    (host, sids), = H._HOSTS.items()
    probed, other = sids[0], sids[1]

    def failing_probe(_t):
        H.observe(f"https://{host}/erddap/griddap/x.das", False, 900, "reset")
        raise OSError("reset")

    for s in H._STATE.values():
        s["_probe"] = failing_probe if s["id"] == probed else (lambda _t: None)
        s["_next"] = 0.0
    H._STATE[other]["_next"] = time.time() + 9999   # keep it out of this tick
    H._tick()
    assert H._STATE[probed]["fails"] == 1, H._STATE[probed]["fails"]
    assert H._STATE[probed]["via"] == "probe"
    # the free 2-for-1 still happened
    assert H._STATE[other]["status"] == "down"
    assert H._STATE[other]["via"] == "traffic"
    assert not H._PROBING, H._PROBING
    print("ok  probe not double-counted")


if __name__ == "__main__":
    test_date_runs()
    test_health_state()
    test_cold_sweep()
    test_cold_sweep_shares_host()
    test_probe_budget()
    test_probe_not_double_counted()
    print("all checks passed")
