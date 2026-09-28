# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Check the Review page and the comments API inside a running Superset.

    docker exec -i dashboard python - < scripts/verify_review.py

The unit tests cover what the page decides; this covers what only Superset can
answer: that the routes exist, that they ask who is calling, and that the
Comments list page cannot write rows behind the API's back.

It builds what it needs (a dataset over a project's connection, two charts, a
dashboard, three viewers, an admin and a role that may read that dataset), runs
Superset's own test client against them, and removes every one of them
afterwards, comments included, whatever the outcome. Exit status 0 means every
check held.
"""
import json
import re
import sys
import uuid

from superset.app import create_app

from aisc_ext.projects import PROJECT_TAG

app = create_app()
TAG = f"zz-verify-review-{uuid.uuid4().hex[:6]}"
results = []
CSRF_META = re.compile(r'name="csrf-token" content="([^"]+)"')


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))


def setup():
    from superset import db, security_manager as sm
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    # A project connection ("AISC Controls <slug>", made by the platform's bridge):
    # the dashboard registers no other. Its extra carries the project's pid.
    project_db = next((d for d in db.session.query(Database).order_by(Database.id)
                       if PROJECT_TAG in json.loads(d.extra or "{}")), None)
    if project_db is None:
        sys.exit("no project connection in Superset: create a project on the platform first "
                 "(its bridge registers 'AISC Controls <slug>'), then re-run this check")
    table = SqlaTable(table_name="aisc_backend_measurement", schema="engine", database=project_db)
    db.session.add(table)
    db.session.flush()
    second = Slice(slice_name=f"{TAG} second", viz_type="table", datasource_type="table",
                   datasource_id=table.id, params="{}")
    first = Slice(slice_name=f"{TAG} first", viz_type="table", datasource_type="table",
                  datasource_id=table.id, params="{}")
    db.session.add_all([second, first])
    db.session.flush()
    # the layout puts "first" above "second" although it was created later
    layout = {
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-1", "ROW-2"]},
        "ROW-1": {"type": "ROW", "id": "ROW-1", "children": ["CHART-a"]},
        "ROW-2": {"type": "ROW", "id": "ROW-2", "children": ["CHART-b"]},
        "CHART-a": {"type": "CHART", "id": "CHART-a", "children": [],
                    "meta": {"chartId": first.id}},
        "CHART-b": {"type": "CHART", "id": "CHART-b", "children": [],
                    "meta": {"chartId": second.id}},
    }
    dash = Dashboard(dashboard_title=f"{TAG} dashboard", slices=[second, first],
                     published=True, position_json=json.dumps(layout))
    db.session.add(dash)
    reader = sm.add_role(f"{TAG}-reader")
    reader.permissions.append(sm.add_permission_view_menu("datasource_access", table.perm))
    viewer, admin = sm.find_role("AiscViewer"), sm.find_role("Admin")

    def user(who, first_name, last_name, roles):
        return sm.add_user(f"{TAG}-{who}", first_name, last_name,
                           f"{TAG}-{who}@example.org", roles, password=uuid.uuid4().hex)

    users = {"alice": user("alice", "Alice", "Martin", [viewer, reader]),
             "bob": user("bob", "Bob", "Kraus", [viewer, reader]),
             "eve": user("eve", "Eve", "Outside", [viewer]),
             "ada": user("ada", "Ada", "Admin", [admin])}
    db.session.commit()
    return {"dash": dash.id, "first": first.id, "second": second.id, "table": table.id,
            "role": reader.id, "users": {k: u.id for k, u in users.items()}}


def cleanup():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice
    from flask_appbuilder.security.sqla.models import Role, User
    from aisc_ext.comments.model import AiscComment

    db.session.rollback()
    for d in db.session.query(Dashboard).filter(Dashboard.dashboard_title.like(f"{TAG}%")):
        db.session.query(AiscComment).filter(AiscComment.dashboard_id == str(d.id)).delete()
        db.session.delete(d)
    for model, col in ((Slice, Slice.slice_name), (User, User.username), (Role, Role.name)):
        for obj in db.session.query(model).filter(col.like(f"{TAG}%")):
            db.session.delete(obj)
    db.session.flush()
    for t in db.session.query(SqlaTable).filter_by(table_name="aisc_backend_measurement", schema="engine"):
        if not t.slices:
            db.session.delete(t)
    db.session.commit()
    left = db.session.query(Dashboard).filter(Dashboard.dashboard_title.like("zz-verify-review-%")).count()
    print(f"cleanup: {left} test dashboards left")


def client_for(user_id):
    c = app.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = str(user_id)
        s["_fresh"] = True
    return c


def token_of(c):
    """The CSRF token of this client's own session, as its page carries it."""
    m = CSRF_META.search(c.get("/aisc/review/").data.decode())
    return m.group(1) if m else ""


def run(ids):
    # Requests run outside any app context we pushed: Flask reuses one that is
    # already there, and Flask-Login caches the signed-in user on it, so every
    # client would otherwise be whoever made the first request.
    dash, first, second = ids["dash"], ids["first"], ids["second"]
    u = ids["users"]
    a, b, e, x = (client_for(u[k]) for k in ("alice", "bob", "eve", "ada"))

    # -- the page -------------------------------------------------------------
    r = a.get("/aisc/review/")
    check("dashboard list opens for a viewer", r.status_code == 200, r.status_code)
    check("dashboard list shows the dashboards the viewer can read",
          f"{TAG} dashboard".encode() in r.data)
    r = e.get("/aisc/review/")
    check("dashboard list hides dashboards the viewer cannot read",
          r.status_code == 200 and f"{TAG} dashboard".encode() not in r.data, r.status_code)

    r = a.get(f"/aisc/review/{dash}/")
    page = r.data.decode()
    check("review page opens", r.status_code == 200, r.status_code)
    check("review page frames the dashboard in standalone mode",
          f"/superset/dashboard/{dash}/?standalone=2" in page)
    m = CSRF_META.search(page)
    check("review page carries a CSRF token", bool(m))
    check("review page script carries the CSP nonce",
          re.search(r'<script nonce="[^"]+"', page) is not None)
    r = e.get(f"/aisc/review/{dash}/")
    check("review page refuses a viewer who cannot read the dashboard",
          r.status_code in (403, 404), r.status_code)

    # -- the conversation -------------------------------------------------------
    api = "/api/v1/aisc_comment/"

    tokens = {id(c): token_of(c) for c in (a, b, e, x)}
    check("each reader gets a CSRF token of their own", all(tokens.values()))

    def post(c, body):
        return c.post(api, json=body, headers={"X-CSRFToken": tokens[id(c)]})

    def delete(c, comment_id):
        return c.delete(f"{api}{comment_id}", headers={"X-CSRFToken": tokens[id(c)]})

    r = a.get(f"{api}threads?dashboard_id={dash}")
    check("threads open for the dashboard", r.status_code == 200, r.status_code)
    choices = ((r.json or {}).get("result") or {}).get("charts", [])
    check("charts are offered in the order the dashboard shows them",
          [c["label"] for c in choices] == ["Whole dashboard", f"{TAG} first", f"{TAG} second"],
          [c.get("label") for c in choices])
    r = e.get(f"{api}threads?dashboard_id={dash}")
    check("threads refused to a viewer who cannot read the dashboard",
          r.status_code in (403, 404), r.status_code)

    r = post(a, {"dashboard_id": str(dash), "chart_id": 999999, "body": "nowhere"})
    check("a comment on a chart that is not on the dashboard is refused",
          r.status_code == 400, r.status_code)
    r = post(a, {"dashboard_id": str(dash), "chart_id": first, "body": "Drift looks high",
                 "author_name": "Mallory"})
    check("a viewer can comment on a chart", r.status_code == 201, (r.status_code, r.data[:200]))
    top = (r.json or {}).get("result") or {}
    check("the author is the signed-in person, not what the request says",
          top.get("author_name") == "Alice Martin", top.get("author_name"))

    r = post(b, {"dashboard_id": str(dash), "parent_id": top.get("id"), "chart_id": second,
                 "body": "Agreed"})
    reply = (r.json or {}).get("result") or {}
    check("another viewer can reply", r.status_code == 201, (r.status_code, r.data[:200]))
    check("a reply stays on the chart of the comment it answers",
          reply.get("chart_id") == first, reply.get("chart_id"))
    check("the reply is bob's", reply.get("author_name") == "Bob Kraus", reply.get("author_name"))
    r = post(a, {"dashboard_id": str(dash), "parent_id": reply.get("id"), "body": "Thanks"})
    check("a reply to a reply joins the top of the thread",
          ((r.json or {}).get("result") or {}).get("parent_id") == top.get("id"),
          (r.status_code, r.data[:200]))

    r = a.post(api, json={"dashboard_id": str(dash), "body": "no token"})
    check("a comment without the CSRF token is refused", r.status_code == 400, r.status_code)
    r = a.delete(f"{api}{top.get('id')}")
    # Superset answers a CSRF failure on a request without a JSON body by
    # sending the browser to the login page rather than with a 400
    # (superset/views/error_handling.py); either way nothing may be deleted.
    still = [t["id"] for t in ((a.get(f"{api}threads?dashboard_id={dash}").json or {})
                               .get("result") or {}).get("threads", [])]
    check("a delete without the CSRF token is refused",
          r.status_code in (400, 302) and top.get("id") in still, (r.status_code, still))

    r = post(e, {"dashboard_id": str(dash), "body": "sneaking in"})
    check("a viewer who cannot read the dashboard cannot comment on it",
          r.status_code in (403, 404), r.status_code)

    r = b.get(f"{api}threads?dashboard_id={dash}")
    threads = ((r.json or {}).get("result") or {}).get("threads", [])
    check("the thread comes back with its replies",
          len(threads) == 1 and len(threads[0]["replies"]) == 2, threads)
    if threads and threads[0]["replies"]:
        check("the page is told bob may delete his reply and not alice's comment",
              threads[0]["can_delete"] is False and threads[0]["replies"][0]["can_delete"] is True)

    r = delete(b, top.get("id"))
    check("deleting someone else's comment is refused", r.status_code == 403, r.status_code)
    r = delete(b, reply.get("id"))
    check("deleting your own comment works", r.status_code == 200, r.status_code)
    r = delete(e, top.get("id"))
    check("a viewer who cannot read the dashboard cannot delete on it",
          r.status_code in (403, 404), r.status_code)

    # -- the Comments list page is read-only ------------------------------------
    r = a.get("/aisccommentview/add")
    check("the Comments list page offers no add form to a viewer", r.status_code != 200, r.status_code)
    for path in ("/aisccommentview/add", f"/aisccommentview/edit/{top.get('id')}"):
        r = x.get(path)
        check(f"{path.split('/')[2]} is not offered even to an admin", r.status_code != 200, r.status_code)
    r = x.get("/aisccommentview/list/")
    check("the Comments list page still lists", r.status_code == 200, r.status_code)


try:
    with app.app_context():
        ids = setup()
    run(ids)
finally:
    with app.app_context():
        cleanup()

print(f"{sum(results)}/{len(results)} checks passed")
sys.exit(0 if results and all(results) else 1)
