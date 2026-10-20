# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Ledger events for dashboard comments and review requests.

A project's dashboard is ``aisc-<pid hex>``: its slug names the project, which is how an event finds its
project log (and how the gateway's witness finds the project of the request, from the slug in the path or
in ``dashboard_id=``). Superset's metadata is not a project database, so the extension keeps an outbox
of its own in it: an event is queued in the same transaction as the comment or review it describes, and
a sender posts what is queued to the platform's internal route (POST /internal/projects/<pid>/ledger/events,
X-AISC-Service-Token), once each, until the platform has it. Nothing names who acted: the witnessed request
does. No Superset import; the outbox is on SQLite."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select

from aisc_ext import ledger

PID = "0f8fad5b-d9cb-469f-a165-70867728950e"
SLUG = "aisc-" + PID.replace("-", "")
REQUEST = "b1b1b1b1-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")


@pytest.fixture
def engine():
    e = create_engine("sqlite://")
    ledger.OUTBOX.metadata.create_all(e)
    return e


def test_a_dashboards_slug_names_its_project():
    assert ledger.project_of(SLUG) == PID
    assert ledger.project_of("aisc-" + "0" * 31) is None
    assert ledger.project_of("sales") is None
    assert ledger.project_of(None) is None


def test_a_plugin_dashboards_slug_names_its_project_too():
    """Every project dashboard is a plugin's: aisc-<hex>-<plugin> (charts.plugin_slug). project_of must
    know that form as well as aisc-<hex>, or every comment and review write on one is refused."""
    from aisc_ext.charts import plugin_slug

    slug = plugin_slug(PID, "aisc-plugin-langbite::LangBiteEvaluationPlugin")
    assert ledger.project_of(slug) == PID
    assert ledger.hint_problem(slug, slug) is None
    assert ledger.project_of(SLUG + "-") is None and ledger.project_of(SLUG + "-Bad_Name") is None


#: what the gateway's middleware puts on a request whose gateway token verified (dashboard-gateway)
THROUGH_GATEWAY = {"aisc.gateway_claims": {"sub": "u1", "azp": "aisc-gateway"}}


def test_only_a_uuid_request_id_is_cited():
    assert ledger.request_id({"X-AISC-Request-Id": REQUEST}, THROUGH_GATEWAY) == REQUEST
    assert ledger.request_id({"X-AISC-Request-Id": "x; DROP"}, THROUGH_GATEWAY) is None
    assert ledger.request_id({}, THROUGH_GATEWAY) is None


def test_a_request_id_is_cited_only_on_a_request_that_came_through_the_gateway():
    """A caller on the backend network reaching dashboard:8189 directly, with no gateway token (or one that
    does not verify, so the middleware set no claims), could make an event cite any request it named (the
    control-objectives service does the same)."""
    assert ledger.request_id({"X-AISC-Request-Id": REQUEST}, {}) is None
    assert ledger.request_id({"X-AISC-Request-Id": REQUEST}, {"aisc.gateway_claims": None}) is None
    assert ledger.request_id({"X-AISC-Request-Id": REQUEST}) is None
    assert ledger.request_id({"X-AISC-Request-Id": REQUEST}, {"HTTP_X_AISC_GATEWAY_CLAIMS": "x"}) is None


def test_the_claims_key_is_the_gateways():
    import re
    from pathlib import Path

    gateway = Path(__file__).resolve().parent.parent.parent.parent / "dashboard-gateway" / "gateway_identity.py"
    if not gateway.exists():
        pytest.skip("not in an aisc checkout")
    assert re.search(r'^CLAIMS_KEY = "([^"]+)"', gateway.read_text(), re.M).group(1) == ledger.GATEWAY_CLAIMS_KEY


@pytest.mark.parametrize("path", ["aisc_ext/comments/api.py", "aisc_ext/reviews/api.py"])
def test_every_route_passes_the_requests_environ(path):
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / path).read_text()
    assert text.count("ledger.request_id(") == text.count("ledger.request_id(request.headers, request.environ)") > 0


COMMENT = {"id": 7, "dashboard_id": "12", "chart_id": 3, "parent_id": None, "author_sub": "sub-ada",
           "author_name": "Ada", "body": "The bar for MCAS looks off", "created_at": "2026-10-03T10:00:00"}


def test_a_comment_names_no_one():
    e = ledger.event("dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
    assert (e["action"], e["item_type"], e["item_id"], e["request_id"]) == (
        "dashboard.comment.created", "comment", "7", REQUEST)
    assert e["details"] == {"dashboard": SLUG, "chart": 3}
    assert e["content"] == {"body": "The bar for MCAS looks off", "chart": 3, "parent": None}
    assert e["after"] == e["content"]
    assert "Ada" not in json.dumps(e) and "sub-ada" not in json.dumps(e)
    uuid.UUID(e["event_id"])


def test_a_deleted_comment_keeps_what_it_said():
    e = ledger.event("dashboard.comment.deleted", ledger.comment_deleted(COMMENT, slug=SLUG, request=REQUEST))
    assert (e["action"], e["item_id"]) == ("dashboard.comment.deleted", "7")
    assert e["before"] == {"body": "The bar for MCAS looks off", "chart": 3, "parent": None}
    assert e["content"] == e["before"]


REVIEW = {"id": 4, "dashboard_id": "12", "chart_id": None, "message": "Please check the bias chart",
          "assignee_type": "category", "assignee_user_sub": None, "assignee_category": "legal",
          "status": "open", "requested_by_name": "Ada", "resolved_by": None}


def test_a_review_request_and_its_resolution():
    asked = ledger.event("dashboard.review.requested", ledger.review_requested(REVIEW, slug=SLUG, request=REQUEST))
    assert (asked["action"], asked["item_id"], asked["details"]) == (
        "dashboard.review.requested", "4", {"assignee": "category:legal"})
    assert asked["after"]["status"] == "open" and "Ada" not in json.dumps(asked)
    done = ledger.review_resolved({**REVIEW, "status": "done", "resolved_by": "Bob"}, status_before="open",
                                  slug=SLUG, request=REQUEST)
    assert done["details"] == {"status_before": "open", "status_after": "done"}
    assert done["before"] == asked["after"] and done["after"]["status"] == "done"   # the item's chain holds
    assert "Bob" not in json.dumps(done)


def test_a_person_assignee_is_named_by_nothing_personal():
    asked = ledger.review_requested({**REVIEW, "assignee_type": "user", "assignee_user_sub": "sub-bob",
                                     "assignee_category": None}, slug=SLUG, request=REQUEST)
    assert asked["details"] == {"assignee": "user"} and "sub-bob" not in json.dumps(asked)


def test_an_event_waits_in_the_outbox_until_the_platform_has_it(engine):
    sent = []
    with engine.begin() as conn:
        ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
    assert ledger.deliver(engine, lambda pid, event: 503) == (0, 1)       # the platform is down: kept
    assert ledger.deliver(engine, lambda pid, event: sent.append((pid, event)) or 202) == (1, 0)
    assert [(pid, e["action"]) for pid, e in sent] == [(PID, "dashboard.comment.created")]
    assert ledger.deliver(engine, lambda pid, event: pytest.fail("sent twice")) == (0, 0)


def test_an_event_the_platform_refuses_is_not_sent_again(engine):
    with engine.begin() as conn:
        ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
    assert ledger.deliver(engine, lambda pid, event: 422) == (0, 1)
    with engine.connect() as conn:
        row = conn.execute(select(ledger.OUTBOX)).one()
    assert row.delivered_at is None and row.refused == 422
    assert ledger.deliver(engine, lambda pid, event: pytest.fail("a refused event is not sent again")) == (0, 0)


def test_a_rolled_back_change_leaves_no_event(engine):
    with pytest.raises(RuntimeError):
        with engine.begin() as conn:
            ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
            raise RuntimeError("the comment's own write failed")
    with engine.connect() as conn:
        assert conn.execute(select(ledger.OUTBOX)).all() == []


def test_with_the_ledger_off_nothing_is_queued(engine, monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "off")
    with engine.begin() as conn:
        assert ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST)) is None
    with engine.connect() as conn:
        assert conn.execute(select(ledger.OUTBOX)).all() == []


def test_an_event_of_no_project_is_never_queued(engine):
    with engine.begin() as conn:
        assert ledger.emit(conn, None, "dashboard.comment.created", ledger.comment_created(COMMENT, slug="sales", request=REQUEST)) is None


def test_the_sender_posts_with_the_dashboards_token(monkeypatch):
    seen = {}

    class Reply:
        status_code = 202

    def post(url, data=None, headers=None, timeout=None):
        seen.update(url=url, headers=headers, body=json.loads(data))
        return Reply()
    monkeypatch.setenv("PLATFORM_URL", "http://platform:8000")
    monkeypatch.setenv("PLATFORM_LEDGER_DASHBOARD_TOKEN", "t" * 40)
    status = ledger.http_sender(post)(PID, {"event_id": "e1", "action": "dashboard.comment.created"})
    assert status == 202
    assert seen["url"] == f"http://platform:8000/internal/projects/{PID}/ledger/events"
    assert seen["headers"]["X-AISC-Service-Token"] == "t" * 40
    assert seen["body"]["event_id"] == "e1"


def test_without_a_token_nothing_is_sent(monkeypatch):
    monkeypatch.delenv("PLATFORM_LEDGER_DASHBOARD_TOKEN", raising=False)
    assert ledger.http_sender(lambda *a, **k: pytest.fail("no token, no call"))(PID, {"event_id": "e1"}) is None


def test_only_the_dashboards_actions_are_built():
    with pytest.raises(ValueError):
        ledger.event("project.deleted", {})


@pytest.mark.parametrize("status", [None, 301, 302, 401, 403, 500, 502, 503])
def test_a_fixable_answer_keeps_the_event_for_the_next_pass(engine, status):
    """A wrong token, a wrong address or a platform that is down is for the operator to fix: the event is
    kept for a later pass, and this pass stops there so the order holds."""
    with engine.begin() as conn:
        for _ in range(2):
            ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
    tried = []
    assert ledger.deliver(engine, lambda pid, event: tried.append(1) or status) == (0, 1)
    assert len(tried) == 1
    assert ledger.deliver(engine, lambda pid, event: 202) == (2, 0)


@pytest.mark.parametrize("status", [409, 413, 422])
def test_only_the_platforms_refusals_are_final(engine, status):
    with engine.begin() as conn:
        ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
    assert ledger.deliver(engine, lambda pid, event: status) == (0, 1)
    assert ledger.deliver(engine, lambda pid, event: pytest.fail("sent again")) == (0, 0)


def test_the_witness_hint_must_name_the_dashboard_written_to():
    """The Review page names the dashboard by its slug for the gateway's witness; a hint naming another
    dashboard is refused before anything is written, so no event can cite another project's request."""
    assert ledger.hint_problem(None, SLUG) is None                      # no hint: the event just goes unwitnessed
    assert ledger.hint_problem(SLUG, SLUG) is None
    assert ledger.hint_problem("aisc-" + "1" * 32, SLUG) is not None
    assert ledger.hint_problem(SLUG, "sales") is not None


def test_one_pass_at_a_time(engine):
    """Two request threads never send the same rows, or one comment's events out of order."""
    with engine.begin() as conn:
        ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
    inner = []

    def send(pid, event):
        inner.append(ledger.deliver(engine, lambda *a: pytest.fail("a second pass ran at once")))
        return 202
    assert ledger.deliver(engine, send) == (1, 0)
    assert inner == [(0, 0)]


def test_one_delivery_pass_at_a_time_across_processes():
    """Superset runs several gunicorn workers, so a threading.Lock alone would let two select the same
    undelivered rows and post them twice, or out of order. On Postgres a pass holds an advisory lock,
    so a second pass anywhere does nothing.
    Needs a throwaway Postgres: AISC_DASHBOARD_TEST_PG_URL (never the stack's, port 5432)."""
    import os
    import threading as th

    url = os.environ.get("AISC_DASHBOARD_TEST_PG_URL", "")
    if not url or ":5432/" in url:
        pytest.skip("AISC_DASHBOARD_TEST_PG_URL (a throwaway Postgres) is not set")
    engine = create_engine(url)
    ledger.OUTBOX.metadata.drop_all(engine)
    ledger.OUTBOX.metadata.create_all(engine)
    with engine.begin() as conn:
        for i in range(3):
            conn.execute(ledger.OUTBOX.insert().values(project_pid=PID, event={"event_id": str(i)},
                                                       queued_at=datetime.now(timezone.utc)))
    sent, inside, release = [], th.Event(), th.Event()

    def slow(pid, event):
        sent.append(event["event_id"])
        inside.set()
        release.wait(5)
        return 201

    first = th.Thread(target=ledger._deliver_locked, args=(engine, slow, 100))
    first.start()
    inside.wait(5)
    # another process's pass, while the first holds the lock: nothing is sent twice
    assert ledger._deliver_locked(engine, lambda p, e: sent.append("again " + e["event_id"]) or 201, 100) == (0, 0)
    release.set()
    first.join(5)
    assert sent == ["0", "1", "2"]
    ledger.OUTBOX.metadata.drop_all(engine)
    engine.dispose()


def test_delivery_runs_off_the_request_path(tmp_path, monkeypatch):
    """A comment or review write does not post the queued events itself, which would cost up to 5 s per
    call while the platform does not answer: the pass runs in a thread of its own."""
    import threading as th
    import time

    monkeypatch.setenv("LEDGER_MODE", "record")
    # a file, not sqlite:// (which gives each thread its own empty database)
    engine = create_engine(f"sqlite:///{tmp_path / 'outbox.db'}")
    ledger.OUTBOX.metadata.create_all(engine)
    with engine.begin() as conn:
        ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
    release, sent = th.Event(), []

    def slow(pid, event):
        release.wait(5)
        sent.append(event["action"])
        return 201

    started = time.monotonic()
    worker = ledger.deliver_in_background(engine, slow)
    assert time.monotonic() - started < 0.5 and sent == []
    release.set()
    worker.join(5)
    assert sent == ["dashboard.comment.created"]


# ── A deleted project's event stalled every project's delivery ─────────────────────────────────────────────
OTHER_PID = "2c9a1b3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def _queue(engine, *pids):
    with engine.begin() as conn:
        for pid in pids:
            ledger.emit(conn, pid, "dashboard.comment.created",
                        ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))


def test_an_event_of_a_project_the_platform_no_longer_has_is_refused_and_the_next_one_goes(engine):
    """The platform answers 404 "no project" for a deleted project. The pass kept that event queued and
    stopped, so no later dashboard event of any project was ever delivered again."""
    _queue(engine, PID, OTHER_PID)
    sent = []

    def send(pid, event):
        sent.append(pid)
        return 404 if pid == PID else 202
    assert ledger.deliver(engine, send) == (1, 1)
    assert sent == [PID, OTHER_PID]
    with engine.connect() as conn:
        rows = {r.project_pid: r for r in conn.execute(select(ledger.OUTBOX))}
    assert rows[PID].refused == 404 and rows[PID].delivered_at is None
    assert rows[OTHER_PID].delivered_at is not None
    assert ledger.deliver(engine, lambda pid, event: pytest.fail("sent again")) == (0, 0)


def test_a_project_the_platform_fails_on_waits_and_the_others_go_on(engine):
    """A failure for one project holds back that project's later events (its order holds) and no one
    else's."""
    _queue(engine, PID, OTHER_PID, PID)
    sent = []

    def send(pid, event):
        sent.append(pid)
        return 500 if pid == PID else 202
    assert ledger.deliver(engine, send) == (1, 1)
    assert sent == [PID, OTHER_PID]                                     # PID's second event is not tried
    assert ledger.deliver(engine, lambda pid, event: sent.append(pid) or 202) == (2, 0)
    assert sent[2:] == [PID, PID]


def test_when_the_platform_cannot_be_asked_the_pass_stops(engine):
    """No token, no address, the platform down: every project waits, so the pass does not go on asking."""
    _queue(engine, PID, OTHER_PID)
    tried = []
    assert ledger.deliver(engine, lambda pid, event: tried.append(pid) or None) == (0, 1)
    assert tried == [PID]


class _Reply:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


@pytest.mark.parametrize("body, status", [
    ({"detail": f"no project {PID!r}"}, 404),                          # the platform's own answer
    ({"detail": "Not Found"}, None),                                   # a wrong address: fix it, keep the event
    (None, None),                                                      # a proxy's HTML page
])
def test_only_the_platforms_no_project_answer_counts_as_a_404(monkeypatch, body, status):
    monkeypatch.setenv("PLATFORM_URL", "http://platform:8000")
    monkeypatch.setenv("PLATFORM_LEDGER_DASHBOARD_TOKEN", "t" * 40)
    post = lambda *a, **k: _Reply(404, body)                            # noqa: E731
    assert ledger.http_sender(post)(PID, {"event_id": "e1"}) == status


# ── The ledger project was read from the slug, which any owner writes ───────────────────────────────────────
# An editor of their own project made a dashboard with slug aisc-<victim hex>-notes and commented on it: the
# event went into the victim's ledger. The project is now the slug's only when the dashboard carries that
# project's role and the person writing is in the project (or an Admin); otherwise no event is queued.

OTHER = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"


def _named(*names):
    from types import SimpleNamespace as NS

    return [NS(name=n) for n in names]


def _dash(slug, *roles):
    from types import SimpleNamespace as NS

    return NS(slug=slug, roles=_named(*roles))


def _user(*roles):
    from types import SimpleNamespace as NS

    return NS(roles=_named(*roles))


def test_a_dashboard_of_the_project_written_by_a_member_names_its_project():
    from aisc_ext.projects import project_role_name

    role = project_role_name(PID)
    assert ledger.project_for(_dash(SLUG + "-langbite", role), _user(role, "AiscViewer")) == PID
    assert ledger.project_for(_dash(SLUG, role), _user("Admin")) == PID


def test_a_slug_alone_names_no_project():
    from aisc_ext.projects import project_role_name

    victim, mine = project_role_name(PID), project_role_name(OTHER)
    planted = SLUG + "-notes"
    assert ledger.project_for(_dash(planted), _user(mine)) is None                  # no role on the dashboard
    assert ledger.project_for(_dash(planted, victim), _user(mine)) is None          # role set, writer not in it
    assert ledger.project_for(_dash(planted, mine), _user(mine)) is None            # another project's role
    assert ledger.project_for(_dash("sales"), _user("Admin")) is None


def _route(path, cls, fn):
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / path).read_text()
    owner = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == cls)
    return ast.get_source_segment(src, next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == fn))


@pytest.mark.parametrize("path,cls,fn", [("aisc_ext/comments/api.py", "CommentApi", "post"),
                                         ("aisc_ext/comments/api.py", "CommentApi", "delete"),
                                         ("aisc_ext/reviews/api.py", "ReviewRequestApi", "post"),
                                         ("aisc_ext/reviews/api.py", "ReviewRequestApi", "patch")])
def test_every_write_takes_its_project_from_the_binding(path, cls, fn):
    text = _route(path, cls, fn)
    assert "ledger.project_for(" in text and "ledger.project_of(" not in text


def test_a_pass_on_postgres_ends_cleanly_on_the_images_sqlalchemy(monkeypatch):
    """The pass ended with held.commit(), and a Connection of SQLAlchemy 1.4 (what
    Superset 4.1 runs) has no commit: every pass that took the lock raised AttributeError in its thread. The
    advisory lock is session-level, so nothing needs committing. The connection here is 1.4's shape."""
    calls = []

    class _Held:                                                        # SQLAlchemy 1.4 Connection: no commit()
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def exec_driver_sql(self, sql):
            calls.append(sql)
            return type("R", (), {"scalar": lambda self: True})()

    engine = type("E", (), {"dialect": type("D", (), {"name": "postgresql"})(), "connect": lambda self: _Held()})()
    monkeypatch.setattr(ledger, "_deliver", lambda engine, send, limit: (1, 0))
    assert ledger._deliver_locked(engine, None, 100) == (1, 0)
    assert [c.split("(")[0] for c in calls] == ["SELECT pg_try_advisory_lock", "SELECT pg_advisory_unlock"]


def test_a_hundred_waiting_events_of_one_project_hold_back_no_one_else(engine):
    """A pass read the 100 oldest undelivered rows and skipped a waiting project's;
    once one project had 100 events queued behind a failure, no other project's event was ever read."""
    _queue(engine, *([PID] * 100), OTHER_PID)
    sent = []

    def send(pid, event):
        sent.append(pid)
        return 503 if pid == PID else 202
    assert ledger.deliver(engine, send) == (1, 1)
    assert sent == [PID, OTHER_PID]                                     # A tried once, B delivered


def test_a_dashboard_of_no_project_takes_its_own_slug_as_hint():
    """The Review page sends ?dashboard=<slug> for every dashboard with a slug, and
    hint_problem refused any slug that names no project, so commenting on a dashboard slugged `sales` answered
    400 although hint and slug were equal. Only a hint naming another dashboard is refused; emit already
    queues nothing for a dashboard of no project."""
    assert ledger.hint_problem("sales", "sales") is None
    assert ledger.hint_problem("sales", "other") is not None
    assert ledger.hint_problem("sales", None) is not None
