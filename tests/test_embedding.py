"""With EMBED_ALLOWED_ORIGINS set, the config set SESSION_COOKIE_SAMESITE="None",
but Superset then calls talisman.init_app(app, **TALISMAN_CONFIG) and flask-talisman sets
SESSION_COOKIE_SAMESITE from its own `session_cookie_samesite` argument, "Lax" by default: the session cookie
stayed Lax, so a cross-site frame showed the login page instead of the dashboard. The Talisman config now
carries the cookie's SameSite=None and Secure itself."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _config(**env):
    """superset_config's names, loaded in a process of its own with this environment (needs Superset)."""
    pytest.importorskip("superset")
    code = ("import json, runpy; ns = runpy.run_path('superset_config.py'); "
            "print(json.dumps({k: ns.get(k) for k in ('TALISMAN_CONFIG', 'SESSION_COOKIE_SAMESITE', "
            "'SESSION_COOKIE_SECURE')}, default=str))")
    base = {"SUPERSET_SECRET_KEY": "k" * 32, "SUPERSET_GUEST_TOKEN_SECRET": "g" * 32,
            "SUPERSET_DB_URI": "sqlite://", "DASHBOARD_REDIS_PASSWORD": "pw"}
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                         env={**os.environ, **base, **env})
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_embedding_sends_the_session_cookie_cross_site():
    config = _config(EMBED_ALLOWED_ORIGINS="https://portal.example.com")
    assert config["SESSION_COOKIE_SAMESITE"] == "None" and config["SESSION_COOKIE_SECURE"] is True
    talisman = config["TALISMAN_CONFIG"]
    assert talisman["session_cookie_samesite"] == "None"
    assert talisman["session_cookie_secure"] is True
    assert "https://portal.example.com" in talisman["content_security_policy"]["frame-ancestors"]


def test_talisman_keeps_what_the_config_says():
    """The same, through flask-talisman itself: after init_app the app's cookie is still SameSite=None."""
    pytest.importorskip("flask_talisman")
    from flask import Flask
    from flask_talisman import Talisman

    talisman = _config(EMBED_ALLOWED_ORIGINS="https://portal.example.com")["TALISMAN_CONFIG"]
    app = Flask(__name__)
    app.config.update(SESSION_COOKIE_SAMESITE="None", SESSION_COOKIE_SECURE=True)    # as the config sets them
    Talisman().init_app(app, **talisman)
    assert (app.config["SESSION_COOKIE_SAMESITE"], app.config["SESSION_COOKIE_SECURE"]) == ("None", True)
