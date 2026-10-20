"""The dashboard has no immudb path of its own.

Superset's actions go to Superset's own action log (its default DBEventLogger, the `logs` table);
comments and reviews reach the platform ledger through aisc_ext/ledger.py, inside their transaction.
No ImmudbEventLogger, no ImmudbClerk, no IMMUDB_* setting. Needs no Superset: the routes are read with
`ast`, bootstrap.sh runs on a scratch copy. The in-image half is tests/test_event_logger_default.py.
"""
import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]


# No module refers to immudb


def test_no_module_references_immudb_or_the_clerk():
    offenders = []
    for path in sorted((REPO / "aisc_ext").rglob("*.py")):
        text = path.read_text()
        for needle in ("immudb", "ImmudbClerk", "ImmudbEventLogger", "aisc_ext.audit", "from .audit",
                       "from ..audit"):
            if needle in text:
                offenders.append(f"{path.relative_to(REPO)}: {needle}")
    assert not offenders, offenders
    assert not (REPO / "aisc_ext/audit.py").exists() and not (REPO / "aisc_ext/event_logger.py").exists()


def test_superset_config_sets_no_event_logger():
    tree = ast.parse((REPO / "superset_config.py").read_text())
    assigned = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert "EVENT_LOGGER" not in assigned, "superset_config.py still replaces Superset's event logger"


# The write routes still emit to the ledger


ROUTES = [("aisc_ext/comments/api.py", "CommentApi", "post"), ("aisc_ext/comments/api.py", "CommentApi", "delete"),
          ("aisc_ext/reviews/api.py", "ReviewRequestApi", "post"), ("aisc_ext/reviews/api.py", "ReviewRequestApi", "patch")]


@pytest.mark.parametrize("path, cls, fn", ROUTES, ids=[f"{c}.{f}" for _, c, f in ROUTES])
def test_each_write_route_still_emits_to_the_ledger_before_its_commit(path, cls, fn):
    src = (REPO / path).read_text()
    owner = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == cls)
    text = ast.get_source_segment(src, next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == fn))
    assert "ledger.emit(" in text and "db.session.commit()" in text
    assert text.index("ledger.emit(") < text.index("db.session.commit()"), "the event is no longer in the transaction"
    assert "_clerk" not in text, f"{cls}.{fn} still writes to immudb directly"


# No immudb in the standalone stack, its example env or its bootstrap


def test_the_standalone_stack_has_no_immudb():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    assert "immudb" not in (compose.get("services") or {})
    for svc, body in (compose.get("services") or {}).items():
        assert "immudb" not in (body.get("depends_on") or {}), svc
    env = compose.get("x-superset-env") or {}
    names = sorted(k for k in env if k.startswith("IMMUDB_") or k == "AISC_AUDIT_ENABLED")
    assert not names, names
    assert not [v for v in (compose.get("volumes") or {}) if "immudb" in v]


def test_the_example_env_sets_no_immudb_name():
    names = [l.split("=", 1)[0] for l in (REPO / ".env.example").read_text().splitlines()
             if re.match(r"^[A-Z_][A-Z0-9_]*=", l)]
    assert not [n for n in names if n.startswith("IMMUDB_") or n == "AISC_AUDIT_ENABLED"], names


def test_bootstrap_generates_no_immudb_password(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts/bootstrap.sh", tmp_path / "scripts/bootstrap.sh")
    shutil.copy(REPO / ".env.example", tmp_path / ".env.example")
    run = subprocess.run(["bash", "scripts/bootstrap.sh", "--env-only"], cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-1000:]
    written = [l.split("=", 1)[0] for l in (tmp_path / ".env").read_text().splitlines() if "=" in l and not l.startswith("#")]
    assert not [n for n in written if n.startswith("IMMUDB_")], [n for n in written if n.startswith("IMMUDB_")]
    assert "immudb" not in (REPO / "scripts/bootstrap.sh").read_text()


# The README (only text exists)


def test_the_readme_names_no_immudb_setting_and_says_where_actions_go():
    readme = (REPO / "README.md").read_text()
    for needle in ("IMMUDB_", "AISC_AUDIT_ENABLED", "audit.py", "event_logger.py", "immudb-py"):
        assert needle not in readme, needle
    flat = " ".join(readme.split())
    assert re.search(r"action log", flat, re.I), "the README does not say actions go to Superset's action log"
    assert re.search(r"comments and reviews[^.]*ledger", flat, re.I), \
        "the README does not say comments and reviews reach the platform ledger"
