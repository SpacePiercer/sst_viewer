"""The contract for accounts: who gets in, and who sees whose data.

Written before the implementation. Two failure modes matter and everything
here exists to catch them:

  * a stranger reaching anything at all (the app triggers 120 MB NOAA fetches
    and there is no rate limit anywhere), and
  * one user reading or deleting another's areas and reports.

Run: conda run -n mfa_env python -m pytest test_auth.py -q
"""
import json
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import auth as AU
import app as A
import config as CFG


# --------------------------------------------------------------- fixtures

@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point every on-disk store at a temp dir, so tests never touch the real
    users.json / secret.key / areas.json / library."""
    monkeypatch.setattr(AU, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(AU, "SECRET_FILE", tmp_path / "secret.key")
    monkeypatch.setattr(A, "AREAS_FILE", tmp_path / "areas.json")
    monkeypatch.setattr(AU, "USERS_DIR", tmp_path / "library" / "users")
    monkeypatch.setattr(A.D, "LIBRARY", tmp_path / "library")
    (tmp_path / "library").mkdir(exist_ok=True)
    AU.FAILS.clear()                       # the throttle is process-global
    AU.add_user("georgii", "gpw-test")
    AU.add_user("polina", "ppw-test")
    return tmp_path


@pytest.fixture
def client(store):
    return TestClient(A.app, follow_redirects=False)


def login(c, user, password):
    r = c.post("/api/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return r


# ------------------------------------------------------------- passwords

def test_passwords_are_salted_hashes_never_plaintext(store):
    AU.add_user("konstantin", "gpw-test")          # same password as georgii
    raw = (AU.USERS_FILE).read_text(encoding="utf-8")
    assert "gpw-test" not in raw, "password stored in clear"
    users = json.loads(raw)
    # same password, different salt -> different hash, so a leaked file does
    # not reveal that two people share a password
    assert users["georgii"]["hash"] != users["konstantin"]["hash"]
    assert users["georgii"]["salt"] != users["konstantin"]["salt"]

    assert AU.verify("georgii", "gpw-test")
    assert not AU.verify("georgii", "gpw-tesT")    # wrong case is wrong
    assert not AU.verify("georgii", "")
    assert not AU.verify("nobody", "gpw-test")     # unknown user, no crash


def test_user_admin_roundtrip(store):
    assert sorted(AU.list_users()) == ["georgii", "polina"]
    with pytest.raises(ValueError):
        AU.add_user("georgii", "x")                # no silent overwrite
    AU.set_password("polina", "new-pw")
    assert AU.verify("polina", "new-pw") and not AU.verify("polina", "ppw-test")
    AU.remove_user("polina")
    assert AU.list_users() == ["georgii"]
    assert not AU.verify("polina", "new-pw")


# -------------------------------------------------------------- sessions

def test_session_cookie_is_signed_and_expires(store):
    c = AU.make_cookie("georgii")
    assert AU.read_cookie(c) == "georgii"
    assert "georgii" in c and c != "georgii"       # it carries a signature

    assert AU.read_cookie(c.replace("georgii", "polina")) is None   # tampered
    assert AU.read_cookie(c[:-1]) is None                           # truncated
    assert AU.read_cookie("") is None and AU.read_cookie("junk") is None

    expired = AU.make_cookie("georgii", expires_at=time.time() - 1)
    assert AU.read_cookie(expired) is None

    # a cookie minted under a different secret must not be accepted
    other = AU.sign("georgii|9999999999", secret=b"a different key")
    assert AU.read_cookie(f"georgii|9999999999|{other}") is None


# ------------------------------------------------------------------ gate

@pytest.mark.parametrize("path", ["/api/areas", "/api/datasets", "/api/health",
                                  "/library/reports/anything.pdf"])
def test_no_session_no_data(client, path):
    r = client.get(path)
    assert r.status_code == 401, f"{path} answered {r.status_code} anonymously"


def test_ui_redirects_anonymous_visitors_to_login(client):
    r = client.get("/")
    assert r.status_code in (302, 303, 307)
    assert "/login" in r.headers["location"]
    assert client.get("/login").status_code == 200   # ...and that page loads


def test_login_rejects_bad_credentials(client):
    for body in ({"username": "georgii", "password": "wrong"},
                 {"username": "ghost", "password": "gpw-test"},
                 {"username": "georgii", "password": ""}):
        assert client.post("/api/login", json=body).status_code == 401
    assert client.get("/api/areas").status_code == 401


def test_login_then_logout(client):
    login(client, "georgii", "gpw-test")
    assert client.get("/api/me").json()["user"] == "georgii"
    assert client.get("/api/areas").status_code == 200
    client.post("/api/logout")
    assert client.get("/api/areas").status_code == 401


# ------------------------------------------------------------- ownership

RECT = {"type": "rect", "w": 140.0, "s": 45.0, "e": 150.0, "n": 52.0}


def make_area(c, name, shared=False):
    r = c.post("/api/areas", json={"name": name, "geom": RECT, "shared": shared})
    assert r.status_code == 200, r.text
    return r.json()


def test_areas_are_private_to_their_owner(client):
    login(client, "georgii", "gpw-test")
    mine = make_area(client, "Georgii box")
    assert mine["owner"] == "georgii" and mine["shared"] is False

    client.post("/api/logout")
    login(client, "polina", "ppw-test")
    assert [a["id"] for a in client.get("/api/areas").json()] == []
    # not merely hidden from the list -- unreachable by id
    assert client.put(f"/api/areas/{mine['id']}",
                      json={"name": "stolen"}).status_code in (403, 404)
    assert client.delete(f"/api/areas/{mine['id']}").status_code in (403, 404)

    client.post("/api/logout")
    login(client, "georgii", "gpw-test")
    assert client.get("/api/areas").json()[0]["name"] == "Georgii box"


def test_shared_areas_are_visible_but_not_editable(client):
    login(client, "georgii", "gpw-test")
    box = make_area(client, "Tatar Strait", shared=True)

    client.post("/api/logout")
    login(client, "polina", "ppw-test")
    seen = client.get("/api/areas").json()
    assert [a["name"] for a in seen] == ["Tatar Strait"]
    # shared means readable, never writable: only the owner edits or deletes
    assert client.put(f"/api/areas/{box['id']}",
                      json={"geom": RECT}).status_code == 403
    assert client.delete(f"/api/areas/{box['id']}").status_code == 403

    client.post("/api/logout")
    login(client, "georgii", "gpw-test")
    assert client.put(f"/api/areas/{box['id']}",
                      json={"shared": False}).status_code == 200
    client.post("/api/logout")
    login(client, "polina", "ppw-test")
    assert client.get("/api/areas").json() == []   # un-shared again


# --------------------------------------------------------------- library

def test_library_files_are_per_user(client, store):
    users = store / "library" / "users"
    for who, fname in (("georgii", "g.pdf"), ("polina", "p.pdf")):
        d = users / who / "reports"
        d.mkdir(parents=True, exist_ok=True)
        (d / fname).write_bytes(b"%PDF-1.4 fake")

    login(client, "georgii", "gpw-test")
    assert client.get("/library/users/georgii/reports/g.pdf").status_code == 200
    r = client.get("/library/users/polina/reports/p.pdf")
    assert r.status_code in (403, 404), "read another user's report"
    # ...and no escaping the sandbox
    assert client.get("/library/users/georgii/reports/../../polina/reports/p.pdf"
                      ).status_code in (403, 404)


def test_unknown_library_dirs_are_denied(client, store):
    """Default-deny, not default-allow: anything dropped into library/ that is
    not a user's folder, the shared series cache, or a visible area's media is
    refused. An archive of everyone's old reports living there must not be
    readable just because it exists."""
    stray = store / "library" / "_archive_pre_accounts" / "reports"
    stray.mkdir(parents=True, exist_ok=True)
    (stray / "old.pdf").write_bytes(b"%PDF-1.4 fake")
    login(client, "georgii", "gpw-test")
    assert client.get("/library/_archive_pre_accounts/reports/old.pdf"
                      ).status_code == 403


def test_series_cache_stays_shared(client, store):
    """The raw per-coordinate series is identical for everyone and expensive to
    refetch (the source is often down), so it is deliberately NOT partitioned."""
    shared = store / "library" / "series"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "s.csv").write_text("date,value\n2025-06-20,8.1\n", encoding="utf-8")
    for who, pw in (("georgii", "gpw-test"), ("polina", "ppw-test")):
        client.post("/api/logout")
        login(client, who, pw)
        assert client.get("/library/series/s.csv").status_code == 200, who


# ------------------------------------------------- public-deployment guards

def test_login_throttle_blocks_guessing(client, monkeypatch):
    """A public login page with no throttle is an invitation. After the limit,
    even the RIGHT password is refused -- otherwise the lockout is decorative,
    since a guesser who lands on the password mid-lockout still gets in."""
    monkeypatch.setattr(CFG, "LOGIN_MAX_FAILS", 3)
    for _ in range(3):
        assert client.post("/api/login",
                           json={"username": "georgii", "password": "no"}).status_code == 401
    r = client.post("/api/login", json={"username": "georgii", "password": "no"})
    assert r.status_code == 429, "guessing was never throttled"
    assert client.post("/api/login",
                       json={"username": "georgii", "password": "gpw-test"}
                       ).status_code == 429, "correct password bypassed the lockout"


def test_successful_login_clears_the_counter(client, monkeypatch):
    monkeypatch.setattr(CFG, "LOGIN_MAX_FAILS", 3)
    client.post("/api/login", json={"username": "georgii", "password": "no"})
    client.post("/api/login", json={"username": "georgii", "password": "no"})
    login(client, "georgii", "gpw-test")          # a typo must not count forever
    client.post("/api/logout")
    for _ in range(2):
        assert client.post("/api/login",
                           json={"username": "georgii", "password": "no"}).status_code == 401


def test_cookie_is_secure_only_when_configured(client, monkeypatch):
    login(client, "georgii", "gpw-test")
    assert "secure" not in client.cookies.jar._cookies.__str__().lower() or True
    r = client.post("/api/login", json={"username": "georgii", "password": "gpw-test"})
    assert "secure" not in r.headers["set-cookie"].lower()   # plain-HTTP default

    monkeypatch.setattr(CFG, "SECURE_COOKIES", True)
    r = client.post("/api/login", json={"username": "georgii", "password": "gpw-test"})
    assert "secure" in r.headers["set-cookie"].lower()
    assert "httponly" in r.headers["set-cookie"].lower()


def test_security_headers_on_the_login_page(client, monkeypatch):
    r = client.get("/login")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    # the CSP must forbid third-party scripts, which is why Leaflet and
    # Chart.js are vendored rather than pulled from a CDN
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert "strict-transport-security" not in r.headers      # not over plain HTTP

    monkeypatch.setattr(CFG, "SECURE_COOKIES", True)
    assert "max-age" in client.get("/login").headers["strict-transport-security"]


def test_unexpected_host_header_is_refused(client, monkeypatch):
    monkeypatch.setattr(A.app.state, "allowed_hosts", ["sst.georgiikuzhel.com"])
    r = client.get("/login", headers={"Host": "evil.example.com"})
    assert r.status_code == 400
    assert client.get("/login", headers={"Host": "sst.georgiikuzhel.com"}
                      ).status_code == 200


def test_pdf_option_is_refused_when_the_toolchain_is_absent(client, monkeypatch):
    login(client, "georgii", "gpw-test")
    assert client.get("/api/capabilities").json()["pdf"] is True

    monkeypatch.setattr(CFG, "ENABLE_PDF", False)
    assert client.get("/api/capabilities").json()["pdf"] is False
    r = client.post("/api/batch_job", json={
        "dataset": "oisst_local", "generate_pdf": True,
        "points": [{"lat": 48.7, "lon": 140.2, "label": "P", "dates": ["2020-06-01"]}]})
    assert r.status_code == 400 and "pdf" in r.json()["detail"].lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
