"""Accounts: a password store, and a signed session cookie.

Three known people on a private network, so this is deliberately small: no
database, no session table, no account UI. What it does have is the part that
actually matters -- passwords are never stored or logged in the clear, and the
cookie cannot be edited into someone else's name.

  users.json   {name: {salt, hash, created}}   scrypt, per-user salt
  secret.key   32 random bytes, generated on first use

Both are gitignored and live next to the app, not in the repo. Passwords are
set with `python scripts/users.py`, which reads them through getpass -- they
never pass through a command line, a log, or an HTTP request body we keep.
"""
import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

import config as cfg

HERE = Path(__file__).resolve().parent
USERS_FILE = HERE / "users.json"
SECRET_FILE = HERE / "secret.key"
USERS_DIR = HERE / "library" / "users"     # per-user reports/ and downloads/

COOKIE = "sst_session"
TTL_DAYS = 30

# scrypt at the interactive-login end of the scale: ~100 ms per attempt here,
# which is nothing for three people logging in occasionally and expensive for
# anyone working through a stolen users.json.
_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32

# "|" separates the cookie fields, so it must not appear in a name; the same
# rule keeps a name usable as a directory under library/users/.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


# ------------------------------------------------------------- throttling
# A public login page with no throttle is an invitation: scrypt makes each
# guess cost ~100 ms, which is slow for a person and no obstacle at all to a
# script left running overnight. Keyed on BOTH the client address and the user
# name, so one noisy address cannot lock out the other two people, and a
# distributed guess at one name is still capped. In-process on purpose -- it
# resets on restart, which for three known users is the right trade against
# running a store for it.
FAILS = {}          # key -> [count, first_failure_ts]


def login_blocked(keys):
    now = time.time()
    for k in keys:
        rec = FAILS.get(k)
        if not rec:
            continue
        if rec[0] >= cfg.LOGIN_MAX_FAILS:
            if now - rec[1] < cfg.LOGIN_LOCKOUT_S:
                return True
            del FAILS[k]            # window elapsed: forgive and start over
    return False


def login_failed(keys):
    now = time.time()
    for k in keys:
        rec = FAILS.setdefault(k, [0, now])
        if now - rec[1] >= cfg.LOGIN_LOCKOUT_S:
            rec[:] = [0, now]
        rec[0] += 1


def login_ok(keys):
    for k in keys:
        FAILS.pop(k, None)


# ------------------------------------------------------------- user store

def _load():
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}


def _save(users):
    tmp = USERS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(users, indent=1), encoding="utf-8")
    tmp.replace(USERS_FILE)


def _hash(password, salt_hex):
    return hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                          n=_N, r=_R, p=_P, dklen=_DKLEN).hex()


def add_user(name, password):
    users = _load()
    if not NAME_RE.match(name or ""):
        raise ValueError(f"bad user name {name!r}: use a-z, 0-9, _ or -")
    if name in users:
        raise ValueError(f"user {name!r} already exists (use set_password)")
    if not password:
        raise ValueError("empty password")
    salt = secrets.token_hex(16)
    users[name] = {"salt": salt, "hash": _hash(password, salt),
                   "created": time.strftime("%Y-%m-%d")}
    _save(users)
    user_dir(name)                      # so the first report has somewhere to land
    return name


def set_password(name, password):
    users = _load()
    if name not in users:
        raise ValueError(f"no such user {name!r}")
    if not password:
        raise ValueError("empty password")
    salt = secrets.token_hex(16)
    users[name].update(salt=salt, hash=_hash(password, salt))
    _save(users)


def remove_user(name):
    users = _load()
    if name not in users:
        raise ValueError(f"no such user {name!r}")
    del users[name]
    _save(users)                        # their library/users/<name> is left alone


def list_users():
    return sorted(_load())


def verify(name, password):
    """True only for a known user and the right password. Constant-time on the
    hash, and it still runs a KDF for an unknown user so the response time does
    not reveal which names exist."""
    rec = _load().get(name)
    salt = rec["salt"] if rec else secrets.token_hex(16)
    candidate = _hash(password or "", salt)
    return bool(rec) and hmac.compare_digest(candidate, rec["hash"])


def user_dir(name):
    d = USERS_DIR / name
    (d / "reports").mkdir(parents=True, exist_ok=True)
    (d / "downloads").mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------- sessions

def _secret():
    if not SECRET_FILE.exists():
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECRET_FILE.write_bytes(secrets.token_bytes(32))
    return SECRET_FILE.read_bytes()


def sign(message, secret=None):
    return hmac.new(secret or _secret(), message.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def make_cookie(name, expires_at=None):
    """`name|expiry|signature`. Stateless on purpose: a restart (every deploy,
    every edit to app.py) must not log everyone out."""
    exp = int(expires_at if expires_at is not None
              else time.time() + TTL_DAYS * 86400)
    msg = f"{name}|{exp}"
    return f"{msg}|{sign(msg)}"


def read_cookie(value):
    """The user name, or None if the cookie is missing, mangled, forged or
    expired. Never raises -- every bad input is just 'not logged in'."""
    try:
        name, exp, sig = (value or "").split("|")
        if not hmac.compare_digest(sign(f"{name}|{exp}"), sig):
            return None
        if int(exp) < time.time():
            return None
        return name if NAME_RE.match(name) else None
    except (ValueError, AttributeError):
        return None
