"""Deployment knobs, read from the environment.

Every default is the development-safe one, so running the app straight off a
laptop behaves exactly as it did before any of this existed. The public
deployment turns them on in docker-compose.yml -- which means the hardening is
visible in one file instead of scattered through the code as `if production`.
"""
import os


def _flag(name, default):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return int(default)


# Secure cookies need HTTPS, so this must stay off for plain-HTTP local runs:
# a Secure cookie over http:// is simply never sent back, i.e. login silently
# fails to stick.
SECURE_COOKIES = _flag("SST_SECURE_COOKIES", "0")

# Host header allow-list. "*" disables the check (local dev, IP access).
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("SST_ALLOWED_HOSTS", "*").split(",")
                 if h.strip()] or ["*"]

# PDF reports need R + Quarto + a TeX distribution. The public image ships
# none of them, so the option is hidden rather than failing per point with
# "quarto executable not found".
ENABLE_PDF = _flag("SST_ENABLE_PDF", "1")

# Login throttle: generous enough that nobody locks themselves out by
# fumbling, tight enough that guessing is pointless.
LOGIN_MAX_FAILS = _int("SST_LOGIN_MAX_FAILS", "8")
LOGIN_LOCKOUT_S = _int("SST_LOGIN_LOCKOUT_S", "900")
