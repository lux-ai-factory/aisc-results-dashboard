"""The routes' wiring, run in a real Superset.

The decision logic of the fixes (a request resolved once, `access.may` / `access.project_if`, `ledger.request_id`,
`security.plugin_tiles`, the requester's own resolution, bad input) is tested by
behaviour in test_reviews.py, test_ledger.py and test_tile_binding.py; there, that the routes call it was
proven only by reading their source. Here the routes run: a Superset app on a throwaway SQLite metadata database, the extension installed
by superset_config.py's FLASK_APP_MUTATOR as in the stack, a person signed in through the Flask test client.
Save to report and the chart assistant's routes run the same way, with the assistant service and the project's
connection replaced by stand-ins.

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
    from flask import g
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

    def fresh_request_globals():
        # the scenario runs in one app context, so `g` would carry the signed-in user and the CSRF token from one
        # request to the next; a second person's requests need it fresh, as each real request has it
        for key in list(vars(g)):
            g.pop(key)

    def call(name, method, url, how=direct, who=None, **kw):
        before = len(queued())
        fresh_request_globals()
        r = getattr(who or client, method)(url, **how, **kw)
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

    # ── Save to report and the chart assistant, on a dashboard of A with two charts placed ──
    from superset.models.slice import Slice

    import aisc_ext.assistant.api as assistant_api
    from aisc_ext.report_exports.model import AiscReportPlot

    def chart(name):
        c = Slice(slice_name=name, viz_type="echarts_timeseries_bar", params="{}", datasource_type="table",
                  datasource_id=999)
        db.session.add(c)
        db.session.commit()
        return c

    bars, drift = chart("Pass rate by model"), chart("Drift by feature")
    row = ["ROOT_ID", "GRID_ID", "ROW-1"]
    position = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
                "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-1"], "parents": ["ROOT_ID"]},
                "ROW-1": {"type": "ROW", "id": "ROW-1", "children": ["CHART-1", "CHART-2"],
                          "parents": ["ROOT_ID", "GRID_ID"]},
                "CHART-1": {"type": "CHART", "id": "CHART-1", "children": [], "parents": row,
                            "meta": {"chartId": bars.id, "uuid": str(bars.uuid)}},
                "CHART-2": {"type": "CHART", "id": "CHART-2", "children": [], "parents": row,
                            "meta": {"chartId": drift.id, "uuid": str(drift.uuid),
                                     "sliceNameOverride": "Drift, named on this dashboard"}}}
    charts_slug = f"aisc-{hex_a}-charts"
    d = Dashboard(dashboard_title=charts_slug, slug=charts_slug, published=True, json_metadata="{}",
                  position_json=json.dumps(position), roles=[role[project_role_name(A)]], slices=[bars, drift])
    db.session.add(d)
    db.session.commit()
    with_charts = d.id
    vic = sm.add_user("vic", "Vic", "Viewer", "vic@test.invalid",
                      [sm.find_role(VIEWER_ROLE), role[project_role_name(A)]], password="test-only")
    viewer = app.test_client()
    with viewer.session_transaction() as session:
        session["_user_id"] = str(vic.id)
        session["_fresh"] = True
    fresh_request_globals()
    as_viewer = {"headers": {"X-CSRFToken": viewer.get("/api/v1/security/csrf_token/").get_json()["result"]}}
    root = sm.add_user("root", "Ro", "Ot", "root@test.invalid", [sm.find_role("Admin")], password="test-only")
    admin = app.test_client()
    with admin.session_transaction() as session:
        session["_user_id"] = str(root.id)
        session["_fresh"] = True
    fresh_request_globals()
    as_admin = {"headers": {"X-CSRFToken": admin.get("/api/v1/security/csrf_token/").get_json()["result"]}}
    no_project = dashboard("sales", [project_role_name(A)])

    # the chart assistant service, its project connection and the project's data are not here: stand-ins
    answers = {}

    def assistant(path, body):
        if path.endswith("/conversations"):
            answers["started"] = answers.get("started", 0) + 1
            return 201, {"conversation": f"conversation-{answers['started']}"}
        return 200, answers[path.rsplit("/", 1)[-1]]

    assistant_api._assistant = assistant
    assistant_api._database = lambda pid: ({"database_name": "project"}, object())
    assistant_api._rows = lambda database, sql: ([], [])

    def plots():
        return db.session.query(AiscReportPlot).count()

    def save(name, chart_name, how=direct, who=None, hint=charts_slug, on=None, **extra):
        before = plots()
        call(name, "post", "/api/v1/aisc_report_export/" + (f"?dashboard={hint}" if hint else ""), how,
             who=who, json={"dashboard_id": on or with_charts, "chart": chart_name,
                            "svg": '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', **extra})
        seen[name]["rows"] = plots() - before
        newest = db.session.query(AiscReportPlot).order_by(AiscReportPlot.id.desc()).first()
        seen[name]["stored_rows"] = newest.rows if newest is not None and plots() > before else "nothing stored"

    save("export.viewer", "Pass rate by model", as_viewer, viewer)
    save("export.not_on_the_dashboard", "A plot made up")
    save("export.other_hint", "Pass rate by model", hint=f"aisc-{hex_b}-p")
    save("export.editor", "Pass rate by model")
    save("export.override_name", "Drift, named on this dashboard")
    save("export.with_rows", "Pass rate by model", rows=2)
    save("export.bad_rows", "Pass rate by model", rows=-1)
    save("export.admin_no_project", "Pass rate by model", as_admin, admin, hint=None, on=no_project)

    here = f"?dashboard={charts_slug}"
    mine_c = call("assistant.start.editor", "post", "/api/v1/aisc_assistant/conversations" + here,
                  json={"dashboard_id": with_charts})
    vic_c = call("assistant.start.viewer", "post", "/api/v1/aisc_assistant/conversations" + here, as_viewer,
                 who=viewer, json={"dashboard_id": with_charts})
    call("assistant.start.other_hint", "post", f"/api/v1/aisc_assistant/conversations?dashboard=aisc-{hex_b}-p",
         json={"dashboard_id": with_charts})
    mine_c, vic_c = (json.loads(c["text"]).get("conversation") for c in (mine_c, vic_c))
    answers["messages"] = {"change": {"chart": bars.id, "changes": {"title": "Renamed by a viewer"}}}
    call("assistant.change.viewer", "post", f"/api/v1/aisc_assistant/conversations/{vic_c}/messages{here}",
         as_viewer, who=viewer, json={"text": "rename it"})
    answers["messages"] = {"remove": [{"chart": bars.id}]}
    call("assistant.remove.viewer", "post", f"/api/v1/aisc_assistant/conversations/{vic_c}/messages{here}",
         as_viewer, who=viewer, json={"text": "remove it"})
    answers["validate"] = {"project": A, "sql": "SELECT 1", "fingerprint": "f",
                           "chart": {"kind": "table", "title": "t", "category": "c", "value": "v"}}
    call("assistant.validate.viewer", "post", f"/api/v1/aisc_assistant/conversations/{vic_c}/validate{here}",
         as_viewer, who=viewer, json={"fingerprint": "f"})
    call("assistant.someone_elses_conversation", "post",
         f"/api/v1/aisc_assistant/conversations/{mine_c}/messages{here}", as_viewer, who=viewer, json={"text": "hi"})
    answers["validate"] = {**answers["validate"], "project": B}
    call("assistant.validate.other_project", "post", f"/api/v1/aisc_assistant/conversations/{mine_c}/validate{here}",
         json={"fingerprint": "f"})
    answers["messages"] = {"change": {"chart": bars.id, "changes": {"title": "Pass rate, renamed"}}}
    call("assistant.change.other_hint", "post",
         f"/api/v1/aisc_assistant/conversations/{mine_c}/messages?dashboard=aisc-{hex_b}-p", json={"text": "rename"})
    call("assistant.change.editor", "post", f"/api/v1/aisc_assistant/conversations/{mine_c}/messages{here}",
         json={"text": "rename it"})
    answers["messages"] = {"remove": [{"chart": drift.id}]}
    call("assistant.remove.editor", "post", f"/api/v1/aisc_assistant/conversations/{mine_c}/messages{here}",
         json={"text": "remove it"})
    seen["charts_title"] = db.session.query(Slice).get(bars.id).slice_name

    # validate: the chart, its place on the dashboard and its ledger event commit together, or not at all
    import hashlib

    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database

    from aisc_ext.assistant.service import chart_uuid_of, validated_files

    project_db = Database(database_name="project-a", sqlalchemy_uri="sqlite://")
    db.session.add(project_db)
    db.session.commit()
    source = {"database_name": "project-a", "database_uuid": str(project_db.uuid), "sqlalchemy_uri": "sqlite://"}
    assistant_api._database = lambda pid: (source, project_db)
    assistant_api._rows = lambda database, sql: (["c", "v"], [])

    def proposal(title):
        sql = f"SELECT 1 AS c, 2 AS v -- {title}"
        return {"project": A, "sql": sql, "fingerprint": hashlib.sha256(sql.encode()).hexdigest(),
                "chart": {"kind": "table", "title": title, "category": "c", "value": "v"}}

    def stored(p):
        """(chart, dataset) of this proposal as committed: read on a connection of its own."""
        files = validated_files(source, pid=A, sql=p["sql"], fingerprint=p["fingerprint"], chart=p["chart"],
                                columns=["c", "v"], axes=[], description="", author="ada")
        uid = uuid.UUID(chart_uuid_of(files))
        name = next(k for k in files if k.startswith("datasets/")).rsplit("/", 1)[-1][:-len(".yaml")]
        with db.engine.connect() as conn:
            chart_row = conn.execute(select(Slice.__table__.c.id).where(Slice.__table__.c.uuid == uid)).first()
            dataset_row = conn.execute(select(SqlaTable.__table__.c.id)
                                       .where(SqlaTable.__table__.c.table_name == name)).first()
            layout = conn.execute(select(Dashboard.__table__.c.position_json)
                                  .where(Dashboard.__table__.c.id == with_charts)).scalar()
        return {"chart": chart_row[0] if chart_row else None, "dataset": dataset_row is not None,
                "placed": bool(chart_row) and f'"chartId": {chart_row[0]}' in (layout or "")}

    broken = proposal("Fails after the import")
    answers["validate"] = broken
    placing = assistant_api.place_chart

    def fails(*args, **kwargs):
        raise RuntimeError("the layout could not be written")

    assistant_api.place_chart = fails
    call("assistant.validate.fails_after_import", "post",
         f"/api/v1/aisc_assistant/conversations/{mine_c}/validate{here}", json={"fingerprint": broken["fingerprint"]})
    assistant_api.place_chart = placing
    seen["assistant.validate.fails_after_import"]["stored"] = stored(broken)
    db.session.rollback()
    good = proposal("Made by validate")
    answers["validate"] = good
    call("assistant.validate.editor", "post", f"/api/v1/aisc_assistant/conversations/{mine_c}/validate{here}",
         json={"fingerprint": good["fingerprint"]})
    seen["assistant.validate.editor"]["stored"] = stored(good)

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


# Save to report and the chart assistant: who may write, on which project, with its ledger event

def test_a_viewer_may_not_save_a_plot_to_the_report(seen):
    assert seen["export.viewer"]["status"] == 403
    assert seen["export.viewer"]["rows"] == 0 and seen["export.viewer"]["events"] == []


def test_a_plot_of_a_dashboard_of_no_project_is_not_saved_even_by_an_admin(seen):
    assert seen["export.admin_no_project"]["status"] == 403, seen["export.admin_no_project"]["text"][:500]
    assert seen["export.admin_no_project"]["rows"] == 0 and seen["export.admin_no_project"]["events"] == []


def test_a_saved_plot_must_name_a_chart_placed_on_the_dashboard(seen):
    assert seen["export.not_on_the_dashboard"]["status"] == 400, seen["export.not_on_the_dashboard"]["text"][:500]
    assert seen["export.not_on_the_dashboard"]["rows"] == 0
    assert seen["export.override_name"]["status"] == 201       # the name the dashboard gives the chart counts too


def test_an_editors_save_writes_one_row_and_one_event_of_the_project(seen):
    saved = seen["export.editor"]
    assert saved["status"] == 201, saved["text"][:500]
    assert saved["rows"] == 1 and [(e["pid"], e["action"]) for e in saved["events"]] == [
        (seen["A"], "dashboard.export.saved")]


def test_a_saved_plot_keeps_the_rows_its_chart_drew_and_none_when_not_sent(seen):
    assert seen["export.with_rows"]["status"] == 201, seen["export.with_rows"]["text"][:500]
    assert seen["export.with_rows"]["stored_rows"] == 2
    assert seen["export.editor"]["stored_rows"] is None
    assert seen["export.bad_rows"]["status"] == 400 and seen["export.bad_rows"]["rows"] == 0


@pytest.mark.parametrize("name", ["export.other_hint", "assistant.start.other_hint", "assistant.change.other_hint"])
def test_a_write_whose_dashboard_hint_names_another_dashboard_is_refused(seen, name):
    assert seen[name]["status"] == 400, seen[name]["text"][:500]
    assert seen[name]["events"] == [] and seen[name].get("rows", 0) == 0


def test_a_viewer_may_talk_to_the_assistant(seen):
    assert seen["assistant.start.viewer"]["status"] == 201, seen["assistant.start.viewer"]["text"][:500]


@pytest.mark.parametrize("name", ["assistant.change.viewer", "assistant.remove.viewer", "assistant.validate.viewer"])
def test_a_viewer_may_not_change_remove_or_validate_through_the_assistant(seen, name):
    assert seen[name]["status"] == 403, seen[name]["text"][:500]
    assert seen[name]["events"] == []


def test_a_conversation_started_by_someone_else_is_not_found(seen):
    assert seen["assistant.someone_elses_conversation"]["status"] == 404


def test_a_validated_proposal_of_another_project_is_refused(seen):
    assert seen["assistant.validate.other_project"]["status"] == 403
    assert seen["assistant.validate.other_project"]["events"] == []


def test_an_editors_change_and_removal_through_the_assistant_reach_the_projects_ledger(seen):
    for name, action in (("assistant.change.editor", "dashboard.assistant.changed"),
                         ("assistant.remove.editor", "dashboard.assistant.removed")):
        assert seen[name]["status"] == 200, seen[name]["text"][:500]
        assert [(e["pid"], e["action"]) for e in seen[name]["events"]] == [(seen["A"], action)], name
    assert seen["charts_title"] == "Pass rate, renamed"



# Validate: the chart is built in the request's own transaction, so chart, layout and ledger event commit together

def test_a_validated_chart_its_place_and_its_event_commit_together(seen):
    made = seen["assistant.validate.editor"]
    assert made["status"] == 201, made["text"][:3000]
    assert made["stored"]["chart"] and made["stored"]["dataset"] and made["stored"]["placed"], made["stored"]
    assert [(e["pid"], e["action"]) for e in made["events"]] == [(seen["A"], "dashboard.assistant.validated")]


def test_a_validate_that_fails_after_the_import_leaves_no_chart_dataset_or_event(seen):
    failed = seen["assistant.validate.fails_after_import"]
    assert failed["status"] == 500, failed["text"][:3000]
    assert failed["stored"] == {"chart": None, "dataset": False, "placed": False}
    assert failed["events"] == []
