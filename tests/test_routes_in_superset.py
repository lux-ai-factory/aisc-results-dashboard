"""The routes' wiring, run in a real Superset.

The decision logic of the fixes (a request resolved once, `ledger.project_for`, `ledger.request_id`,
`security.plugin_tiles` / `may_import_into`, the requester's own resolution, bad input) is tested by
behaviour in test_reviews.py, test_ledger.py and test_tile_binding.py; there, that the routes call it was
proven only by reading their source. Here the routes run: a Superset app on a throwaway SQLite metadata database, the extension installed
by superset_config.py's FLASK_APP_MUTATOR as in the stack, a person signed in through the Flask test client.

Runs in the dashboard image, where Superset is importable (skipped elsewhere), in a throwaway container,
never the live `dashboard` (the recipe is in test_event_logger_default.py). Superset is booted once, in a
process of its own (`superset db upgrade`, `superset init`, then the scenario below, about 80 s), and each
test reads what the scenario saw.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("superset")

REPO = Path(__file__).resolve().parents[1]

# superset_config.py as the stack loads it, with only what a test box lacks replaced: no Redis (a null
# cache). CSRF stays on: the client sends the token as the Review page does.
CONFIG = """
import importlib.util
_spec = importlib.util.spec_from_file_location("superset_config", {config!r})
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
globals().update({{k: v for k, v in vars(_module).items() if not k.startswith("__")}})
CACHE_CONFIG = DATA_CACHE_CONFIG = {{"CACHE_TYPE": "NullCache"}}
"""

SCENARIO = r'''
import json
import uuid

from superset.app import create_app

app = create_app()
seen = {}
with app.app_context():
    from superset import db, security_manager as sm
    from superset.models.dashboard import Dashboard
    from sqlalchemy import select

    from aisc_ext import ledger
    from aisc_ext.projects import BRIDGE_USER, editor_role_name, project_role_name
    from aisc_ext.security import VIEWER_ROLE

    # superset_config makes the outbox after an ALTER that only Postgres takes; on SQLite it is made here
    ledger.OUTBOX.metadata.create_all(db.engine)
    A, B = str(uuid.UUID(int=0xA)), str(uuid.UUID(int=0xB))
    role = {name: sm.add_role(name) for name in
            (project_role_name(A), editor_role_name(A), project_role_name(B))}
    ada = sm.add_user("ada", "Ada", "Lovelace", "ada@test.invalid",
                      [sm.find_role(VIEWER_ROLE), role[project_role_name(A)], role[editor_role_name(A)]],
                      password="test-only")
    bridge = sm.find_user(username=BRIDGE_USER)

    def dashboard(slug, roles, *, created_by=None, owners=(), plugin_of=None):
        meta = {"aisc_plugin": "pkg::P", "aisc_project": plugin_of} if plugin_of else {}
        d = Dashboard(dashboard_title=slug, slug=slug, published=True, json_metadata=json.dumps(meta),
                      roles=[role[r] for r in roles], owners=list(owners), created_by_fk=created_by)
        db.session.add(d)
        db.session.commit()
        return d.id

    hex_a, hex_b = uuid.UUID(A).hex, uuid.UUID(B).hex
    mine = dashboard(f"aisc-{hex_a}-p", [project_role_name(A)])
    # The slug names project B, which ada is not in; the dashboard is one she can open
    names_b = dashboard(f"aisc-{hex_b}-p", [project_role_name(A)])
    names_b_with_its_role = dashboard(f"aisc-{hex_b}-q", [project_role_name(A), project_role_name(B)])
    # Tiles: A's, made by the bridge; B's, made by the bridge, which ada owns; one ada made naming B
    tile_a = dashboard(f"aisc-{hex_a}-tile", [project_role_name(A)], created_by=bridge.id, owners=[ada],
                       plugin_of=A)
    tile_b = dashboard(f"aisc-{hex_b}-tile", [project_role_name(B), project_role_name(A)],
                       created_by=bridge.id, owners=[ada], plugin_of=B)
    planted = dashboard(f"aisc-{hex_b}-planted", [project_role_name(B), project_role_name(A)],
                        created_by=ada.id, owners=[ada], plugin_of=B)
    ada_id = ada.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(ada_id)
        session["_fresh"] = True

    token = client.get("/api/v1/security/csrf_token/")
    assert token.status_code == 200, token.get_data(as_text=True)[:500]
    csrf = token.get_json()["result"]
    RID = "a6a6a6a6-0000-4000-8000-000000000003"
    direct = {"headers": {"X-AISC-Request-Id": RID, "X-CSRFToken": csrf}}
    through = {"headers": {"X-AISC-Request-Id": RID, "X-CSRFToken": csrf},
               "environ_overrides": {ledger.GATEWAY_CLAIMS_KEY: {"sub": "ada", "azp": "aisc-gateway"}}}

    def queued():
        with db.engine.connect() as conn:
            return [{"pid": r.project_pid, "action": r.event["action"], "request_id": r.event.get("request_id")}
                    for r in conn.execute(select(ledger.OUTBOX).order_by(ledger.OUTBOX.c.id))]

    def call(name, method, url, how=direct, **kw):
        before = len(queued())
        r = getattr(client, method)(url, **how, **kw)
        body = r.get_json(silent=True) or {}
        seen[name] = {"status": r.status_code, "events": queued()[before:],
                      "id": (body.get("result") or {}).get("id") if isinstance(body.get("result"), dict) else None,
                      "text": r.get_data(as_text=True)[:20000]}
        return seen[name]

    comment = lambda d: {"dashboard_id": str(d), "body": "the bar for MCAS looks off"}
    review = lambda d: {"dashboard_id": str(d), "message": "please check", "assignee_type": "category",
                        "assignee_category": "legal"}

    # the routes keep CSRF (csrf_exempt = False): without the token a write is refused
    call("comment.post.no_csrf", "post", "/api/v1/aisc_comment/", {"headers": {}}, json=comment(mine))
    call("review.post.no_csrf", "post", "/api/v1/aisc_review_request/", {"headers": {}}, json=review(mine))
    # comments
    c_direct = call("comment.post.direct", "post", "/api/v1/aisc_comment/", json=comment(mine))
    call("comment.post.through", "post", "/api/v1/aisc_comment/", through, json=comment(mine))
    c_b = call("comment.post.names_b", "post", "/api/v1/aisc_comment/", json=comment(names_b))
    call("comment.post.names_b_with_its_role", "post", "/api/v1/aisc_comment/", json=comment(names_b_with_its_role))
    call("comment.delete.names_b", "delete", f"/api/v1/aisc_comment/{c_b['id']}")
    call("comment.delete.direct", "delete", f"/api/v1/aisc_comment/{c_direct['id']}")
    # review requests
    r1 = call("review.post.direct", "post", "/api/v1/aisc_review_request/", json=review(mine))
    call("review.post.names_b", "post", "/api/v1/aisc_review_request/", json=review(names_b))
    r_b = seen["review.post.names_b"]
    call("review.patch.first", "patch", f"/api/v1/aisc_review_request/{r1['id']}", json={"action": "done"})
    call("review.patch.second", "patch", f"/api/v1/aisc_review_request/{r1['id']}", json={"action": "dismiss"})
    call("review.patch.names_b", "patch", f"/api/v1/aisc_review_request/{r_b['id']}", json={"action": "done"})
    r2 = call("review.post.through", "post", "/api/v1/aisc_review_request/", through, json=review(mine))
    call("review.patch.unknown_action", "patch", f"/api/v1/aisc_review_request/{r2['id']}", json={"action": "bogus"})
    call("review.patch.through", "patch", f"/api/v1/aisc_review_request/{r2['id']}", through, json={"action": "done"})
    # chart import (no file: a tile she may import into answers 400, any other 403)
    call("import.form", "get", "/aisc/import/")
    for name, d in (("tile_a", tile_a), ("tile_b", tile_b), ("planted", planted)):
        call(f"import.upload.{name}", "post", "/aisc/import/", data={"dashboard": str(d), "csrf_token": csrf})
    seen["titles"] = {"tile_a": f"aisc-{hex_a}-tile", "tile_b": f"aisc-{hex_b}-tile",
                      "planted": f"aisc-{hex_b}-planted"}
    seen["A"], seen["RID"] = A, RID

print("SCENARIO-JSON " + json.dumps(seen))
'''


@pytest.fixture(scope="module")
def seen(tmp_path_factory):
    work = tmp_path_factory.mktemp("superset")
    (work / "test_superset_config.py").write_text(CONFIG.format(config=str(REPO / "superset_config.py")))
    (work / "scenario.py").write_text(SCENARIO)
    env = {**os.environ,
           "SUPERSET_CONFIG_PATH": str(work / "test_superset_config.py"),
           "SUPERSET_DB_URI": f"sqlite:///{work / 'metadata.db'}",
           "SUPERSET_SECRET_KEY": "test-only-" + "0" * 32, "SUPERSET_GUEST_TOKEN_SECRET": "test-only-" + "1" * 32,
           "DASHBOARD_REDIS_PASSWORD": "test-only", "LEDGER_MODE": "record",
           "PYTHONPATH": os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")])}
    for key in ("AISC_OAUTH", "PLATFORM_URL", "PLATFORM_LEDGER_DASHBOARD_TOKEN", "EMBED_ALLOWED_ORIGINS"):
        env.pop(key, None)
    for step in (["superset", "db", "upgrade"], ["superset", "init"]):
        done = subprocess.run(step, env=env, cwd=work, capture_output=True, text=True, timeout=600)
        assert done.returncode == 0, done.stderr[-3000:]
    done = subprocess.run([sys.executable, str(work / "scenario.py")], env=env, cwd=work,
                          capture_output=True, text=True, timeout=600)
    line = next((x for x in done.stdout.splitlines() if x.startswith("SCENARIO-JSON ")), None)
    assert line, textwrap.shorten(done.stderr[-5000:], 5000)
    return json.loads(line[len("SCENARIO-JSON "):])


def test_the_write_routes_refuse_a_request_without_the_csrf_token(seen):
    for name in ("comment.post.no_csrf", "review.post.no_csrf"):
        assert seen[name]["status"] == 400 and "CSRF" in seen[name]["text"] and seen[name]["events"] == [], name


# A request is resolved once; the second PATCH answers 409 and records nothing

def test_a_second_patch_of_a_resolved_request_is_409_and_records_nothing(seen):
    assert seen["review.post.direct"]["status"] == 201
    first, second = seen["review.patch.first"], seen["review.patch.second"]
    assert first["status"] == 200                       # the requester resolves her own request
    assert [e["action"] for e in first["events"]] == ["dashboard.review.resolved"]
    assert second["status"] == 409 and second["events"] == []


def test_an_unknown_action_is_400_and_records_nothing(seen):
    assert seen["review.patch.unknown_action"]["status"] == 400
    assert seen["review.patch.unknown_action"]["events"] == []
    assert seen["review.patch.through"]["status"] == 200       # the request stayed open


# A write on a dashboard whose slug names project B, by a person not in B, queues no event

@pytest.mark.parametrize("name", ["comment.post.names_b", "comment.post.names_b_with_its_role",
                                  "comment.delete.names_b", "review.post.names_b", "review.patch.names_b"])
def test_a_write_on_a_dashboard_naming_another_project_queues_no_event(seen, name):
    assert seen[name]["status"] in (200, 201), seen[name]["text"][:500]
    assert seen[name]["events"] == []


def test_a_write_on_the_persons_own_projects_dashboard_queues_its_event(seen):
    """The control for the test above: the same writes on project A's dashboard do reach A's ledger."""
    for name, action in (("comment.post.direct", "dashboard.comment.created"),
                         ("comment.delete.direct", "dashboard.comment.deleted"),
                         ("review.post.direct", "dashboard.review.requested"),
                         ("review.patch.first", "dashboard.review.resolved")):
        assert [(e["pid"], e["action"]) for e in seen[name]["events"]] == [(seen["A"], action)], name


# A request that did not come through the gateway cites no request id, whatever header it sends

@pytest.mark.parametrize("name", ["comment.post.direct", "comment.delete.direct", "review.post.direct",
                                  "review.patch.first"])
def test_a_direct_request_cites_no_request_id(seen, name):
    assert [e["request_id"] for e in seen[name]["events"]] == [None]


@pytest.mark.parametrize("name", ["comment.post.through", "review.post.through", "review.patch.through"])
def test_a_request_through_the_gateway_cites_its_request_id(seen, name):
    assert [e["request_id"] for e in seen[name]["events"]] == [seen["RID"]]


# Importing takes a tile the bridge made, of a project the person is an editor of

def test_the_import_page_offers_only_the_tiles_the_person_may_import_into(seen):
    page = seen["import.form"]
    assert page["status"] == 200, page["text"][:3000]
    assert seen["titles"]["tile_a"] in page["text"]
    assert seen["titles"]["tile_b"] not in page["text"] and seen["titles"]["planted"] not in page["text"]


def test_an_import_into_another_projects_tile_or_a_planted_dashboard_is_403(seen):
    assert seen["import.upload.tile_a"]["status"] == 400        # hers: refused only for the missing file
    assert seen["import.upload.tile_b"]["status"] == 403        # owned, but B's, and she is not B's editor
    assert seen["import.upload.planted"]["status"] == 403       # her own dashboard, naming B: no tile
