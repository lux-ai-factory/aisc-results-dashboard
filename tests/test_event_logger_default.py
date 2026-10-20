"""Superset falls back to its own event logger (the dashboard has no immudb logger).

Runs in the dashboard image, where Superset is importable (skipped elsewhere), in a throwaway container,
never the live `dashboard`:

    docker run --rm --name aisc-t-dash-$(openssl rand -hex 3) -v "$PWD":/src:ro,Z \
      -v "$PWD/../../dashboard-gateway":/gw:ro,Z -e AISC_TEST_GATEWAY_CONFIG=/gw/superset_gateway_config.py \
      -w /src --entrypoint sh aisc-results-dashboard:<tag> \
      -c 'pip install -q pytest && python -m pytest -q -p no:cacheprovider tests/test_event_logger_default.py'

Each check runs in a process of its own, as Superset loads its config: SUPERSET_CONFIG_PATH names the file
compose names (dashboard-gateway's, which loads superset_config.py by path), and `superset.config` is
imported fresh.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("superset")

REPO = Path(__file__).resolve().parents[1]
GATEWAY = os.environ.get("AISC_TEST_GATEWAY_CONFIG", "")
BASE = {"SUPERSET_SECRET_KEY": "k" * 32, "SUPERSET_GUEST_TOKEN_SECRET": "g" * 32, "SUPERSET_DB_URI": "sqlite://",
        "DASHBOARD_REDIS_PASSWORD": "pw", "OIDC_CLIENT_SECRET": "o" * 16}


def _run(code: str, **env) -> dict:
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                         env={**{k: v for k, v in os.environ.items() if not k.startswith("IMMUDB_")}, **BASE, **env,
                              "PYTHONPATH": os.pathsep.join(p for p in (str(REPO), str(Path(GATEWAY).parent)
                                                                         if GATEWAY else "") if p)})
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


EFFECTIVE = ("import json, superset.config as c; l = c.EVENT_LOGGER; "
             "print(json.dumps({'type': type(l).__module__ + '.' + type(l).__name__}))")


def test_superset_config_defines_no_event_logger():
    got = _run("import json, runpy; ns = runpy.run_path('superset_config.py'); "
               "print(json.dumps({'defined': 'EVENT_LOGGER' in ns}))")
    assert got["defined"] is False


def test_the_effective_event_logger_is_supersets_own():
    got = _run(EFFECTIVE, SUPERSET_CONFIG_PATH=str(REPO / "superset_config.py"))
    assert got["type"] == "superset.utils.log.DBEventLogger", got


def test_the_effective_event_logger_is_supersets_own_through_the_gateway_config():
    """The stack's dashboard loads dashboard-gateway/superset_gateway_config.py, which loads
    superset_config.py by path (AISC_ORIGINAL_SUPERSET_CONFIG)."""
    assert GATEWAY and Path(GATEWAY).exists(), "set AISC_TEST_GATEWAY_CONFIG to dashboard-gateway's config (see top)"
    got = _run(EFFECTIVE, SUPERSET_CONFIG_PATH=GATEWAY,
               AISC_ORIGINAL_SUPERSET_CONFIG=str(REPO / "superset_config.py"))
    assert got["type"] == "superset.utils.log.DBEventLogger", got


def test_config_and_every_module_load_without_immudb():
    """immudb made unimportable: the config runs and every module under aisc_ext imports."""
    modules = sorted(".".join(p.relative_to(REPO).with_suffix("").parts) for p in (REPO / "aisc_ext").rglob("*.py"))
    modules = [m[: -len(".__init__")] if m.endswith(".__init__") else m for m in modules]
    code = ("import sys, json, runpy, importlib; sys.modules['immudb'] = None; "
            "runpy.run_path('superset_config.py'); failed = []\n"
            f"for m in {modules!r}:\n"
            "    try: importlib.import_module(m)\n"
            "    except Exception as e:\n"
            "        if 'immudb' in str(e): failed.append(m)\n"
            "print(json.dumps({'failed': failed}))")
    got = _run(code)
    assert got["failed"] == [], got


def test_the_image_has_no_immudb_py_but_keeps_authlib_and_psycopg2():
    got = _run("import json, importlib.util as u; "
               "print(json.dumps({m: u.find_spec(m) is not None for m in ('immudb', 'authlib', 'psycopg2')}))")
    assert got == {"immudb": False, "authlib": True, "psycopg2": True}, got
