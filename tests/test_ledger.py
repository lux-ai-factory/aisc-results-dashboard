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
    """Every project dashboard is a plugin's since 2026-10-04: aisc-<hex>-<plugin> (charts.plugin_slug).
    project_of knew only aisc-<hex>, so every comment and review write on one was refused (code review
    2026-10-05)."""
    from aisc_ext.charts import plugin_slug

    slug = plugin_slug(PID, "aisc-plugin-langbite::LangBiteEvaluationPlugin")
    assert ledger.project_of(slug) == PID
    assert ledger.hint_problem(slug, slug) is None
    assert ledger.project_of(SLUG + "-") is None and ledger.project_of(SLUG + "-Bad_Name") is None


def test_only_a_uuid_request_id_is_cited():
    assert ledger.request_id({"X-AISC-Request-Id": REQUEST}) == REQUEST
    assert ledger.request_id({"X-AISC-Request-Id": "x; DROP"}) is None
    assert ledger.request_id({}) is None


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


@pytest.mark.parametrize("status", [None, 301, 302, 401, 403, 404, 500, 502, 503])
def test_m3_review_a_fixable_answer_keeps_the_event_for_the_next_pass(engine, status):
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
def test_m3_review_only_the_platforms_refusals_are_final(engine, status):
    with engine.begin() as conn:
        ledger.emit(conn, PID, "dashboard.comment.created", ledger.comment_created(COMMENT, slug=SLUG, request=REQUEST))
    assert ledger.deliver(engine, lambda pid, event: status) == (0, 1)
    assert ledger.deliver(engine, lambda pid, event: pytest.fail("sent again")) == (0, 0)


def test_m4_review_the_witness_hint_must_name_the_dashboard_written_to():
    """The Review page names the dashboard by its slug for the gateway's witness; a hint naming another
    dashboard is refused before anything is written, so no event can cite another project's request."""
    assert ledger.hint_problem(None, SLUG) is None                      # no hint: the event just goes unwitnessed
    assert ledger.hint_problem(SLUG, SLUG) is None
    assert ledger.hint_problem("aisc-" + "1" * 32, SLUG) is not None
    assert ledger.hint_problem(SLUG, "sales") is not None


def test_m9_review_one_pass_at_a_time(engine):
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
    """The pass was serialised by a threading.Lock only, and Superset runs several gunicorn workers:
    two could select the same undelivered rows and post them twice, or out of order (code review
    2026-10-05). On Postgres a pass holds an advisory lock, so a second pass anywhere does nothing.
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
    """Each comment and review write posted the queued events itself, up to 5 s per call while the
    platform did not answer (code review 2026-10-05). The pass now runs in a thread of its own."""
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
