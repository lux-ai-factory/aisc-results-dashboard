# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Ledger events for dashboard comments and review requests.

A project's dashboard has the slug ``aisc-<pid hex>`` (aisc_ext.projects), so the event of a comment or a
review finds its project's ledger from the dashboard it is on. The gateway's witness reads the same slug
from the request (in the path, or in ``dashboard_id=``), which is why the Review page names the dashboard
by its slug in every call that writes.

Superset's metadata database is not a project database and has no ``ledger.emit``, so the extension keeps
its own outbox table there (``aisc_ledger_outbox``). ``emit`` writes the event on the connection of the
change, in its transaction, so the two commit or roll back together. ``deliver`` posts the queued events
to the platform's internal ledger route with the dashboard's token, in order, once each. An event the
platform refuses is kept with its status and not sent again; when the platform does not answer, the event
stays queued for the next pass.

An event never names who acted: the witnessed request it cites does. A review's assignee is given as its
kind (``user``) or its group (``category:legal``), never as a person. Nothing is queued while LEDGER_MODE
is off (the default). The module imports nothing from Superset, so it is unit-tested on SQLite.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, select, update

_log = logging.getLogger(__name__)
_SLUG = re.compile(r"^aisc-([0-9a-f]{32})$")

OUTBOX = Table(
    "aisc_ledger_outbox", MetaData(),
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("project_pid", String(36), nullable=False),
    Column("event", JSON, nullable=False),
    Column("queued_at", DateTime(timezone=True), nullable=False),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    Column("refused", Integer, nullable=True),            # the HTTP status of the platform's refusal
)


def on() -> bool:
    return os.environ.get("LEDGER_MODE", "off").strip().lower() in ("record", "enforce")


def project_of(slug) -> str | None:
    """The project a dashboard slug names, ``aisc-<pid hex>``, or None."""
    m = _SLUG.match(str(slug or ""))
    if not m:
        return None
    return str(uuid.UUID(m.group(1)))


def hint_problem(hint, slug) -> str | None:
    """Check the request's witness hint against the dashboard actually written to.

    The hint (`?dashboard=<slug>`) names the project to the gateway's witness. Returns a message when the
    hint names another dashboard, so the request is refused before anything is written; None otherwise.
    A missing hint is allowed: the event then cites a request filed in the platform log, and the relay
    records that."""
    if hint is None:
        return None
    if project_of(slug) is None or hint != slug:
        return "the dashboard named in the request is not the one written to"
    return None


def request_id(headers) -> str | None:
    """The id of the request the gateway witnessed (X-AISC-Request-Id), or None unless it is a UUID."""
    presented = headers.get("X-AISC-Request-Id") if headers is not None else None
    try:
        return str(uuid.UUID(presented)) if presented else None
    except (ValueError, TypeError, AttributeError):
        return None


#: The actions this module builds fields for; `event` refuses any other.
ACTIONS = ("dashboard.comment.created", "dashboard.comment.deleted", "dashboard.review.requested",
           "dashboard.review.resolved")


def _fields(item_type, item_id, request, **fields) -> dict:
    out = {"request_id": request, "item_type": item_type, "item_id": item_id, "details": fields.pop("details", {})}
    out.update({k: v for k, v in fields.items() if v is not None})
    return out


def event(action: str, fields: dict) -> dict:
    """The event body the platform's internal route takes: a new event id, the action, the fields."""
    if action not in ACTIONS:
        raise ValueError(f"not a dashboard action: {action!r}")
    return {"event_id": str(uuid.uuid4()), "action": action, **fields}


def _said(row: dict) -> dict:
    return {"body": row["body"], "chart": row.get("chart_id"), "parent": row.get("parent_id")}


def comment_created(row: dict, *, slug: str, request: str | None) -> dict:
    said = _said(row)
    return _fields("comment", str(row["id"]), request,
                  details={"dashboard": slug, "chart": row.get("chart_id")}, content=said, after=said)


def comment_deleted(row: dict, *, slug: str, request: str | None) -> dict:
    said = _said(row)
    return _fields("comment", str(row["id"]), request,
                  details={"dashboard": slug}, content=said, before=said)


def _assignee(row: dict) -> str:
    if row.get("assignee_type") == "category":
        return f"category:{row.get('assignee_category')}"
    return "user"


def _review_state(row: dict) -> dict:
    return {"message": row.get("message"), "chart": row.get("chart_id"), "assignee": _assignee(row),
            "status": row.get("status") or "open"}


def review_requested(row: dict, *, slug: str, request: str | None) -> dict:
    state = _review_state({**row, "status": row.get("status") or "open"})
    return _fields("review_request", str(row["id"]), request,
                  details={"assignee": _assignee(row)}, content=state, after=state)


def review_resolved(row: dict, *, status_before: str, slug: str, request: str | None) -> dict:
    after = _review_state(row)
    return _fields("review_request", str(row["id"]), request,
                  details={"status_before": status_before, "status_after": row.get("status")},
                  before={**after, "status": status_before}, after=after)


def emit(conn, project_pid: str | None, action: str, fields: dict) -> int | None:
    """Queue the event on `conn`, inside the change's own transaction, and return the outbox row id.

    Returns None while the ledger is off, or for a dashboard that belongs to no project (an example
    dashboard, say): there is no project ledger to write to."""
    if not on() or project_pid is None:
        return None
    result = conn.execute(OUTBOX.insert().values(project_pid=project_pid, event=event(action, fields),
                                                 queued_at=datetime.now(timezone.utc)))
    return result.inserted_primary_key[0]


#: The platform's statuses that refuse the event itself: the event is kept with the status and never sent
#: again. Any other failure (a wrong token, a wrong address, the platform down) is for the operator to fix,
#: so the event waits for the next pass.
REFUSALS = (409, 413, 422)
_PASS = threading.Lock()


def deliver(engine, send, limit: int = 100) -> tuple[int, int]:
    """Post the queued events, oldest first, and return (sent, not sent).

    `send(pid, event)` returns the platform's HTTP status, or None when the platform cannot be asked. A 2xx
    marks the event delivered. A status in REFUSALS keeps the event with that status, never sent again.
    Anything else keeps the event queued and stops the pass, so the order holds. Only one pass runs at a
    time in this process, so two request threads never send the same rows, or one comment's events out of
    order."""
    if not _PASS.acquire(blocking=False):
        return 0, 0
    try:
        return _deliver(engine, send, limit)
    finally:
        _PASS.release()


def _deliver(engine, send, limit: int) -> tuple[int, int]:
    sent = failed = 0
    with engine.connect() as conn:
        rows = conn.execute(select(OUTBOX).where(OUTBOX.c.delivered_at.is_(None), OUTBOX.c.refused.is_(None))
                            .order_by(OUTBOX.c.id).limit(limit)).all()
    for row in rows:
        status = send(row.project_pid, row.event)
        if status is not None and 200 <= status < 300:
            with engine.begin() as conn:
                conn.execute(update(OUTBOX).where(OUTBOX.c.id == row.id)
                             .values(delivered_at=datetime.now(timezone.utc)))
            sent += 1
            continue
        failed += 1
        if status not in REFUSALS:
            _log.warning("ledger: the platform answered %s for dashboard event %s; it stays queued",
                         status, row.event.get("event_id"))
            break
        _log.error("ledger: the platform refused dashboard event %s (%s, status %s); kept, not sent again",
                   row.event.get("event_id"), row.event.get("action"), status)
        with engine.begin() as conn:
            conn.execute(update(OUTBOX).where(OUTBOX.c.id == row.id).values(refused=status))
    return sent, failed


def http_sender(post=None):
    """A `send` function for `deliver` that posts to the platform's internal ledger route.

    It authenticates with PLATFORM_LEDGER_DASHBOARD_TOKEN and returns None (event stays queued) when that
    token or PLATFORM_URL is not set."""
    if post is None:
        import requests

        post = requests.post

    def send(pid: str, event: dict) -> int | None:
        token = os.environ.get("PLATFORM_LEDGER_DASHBOARD_TOKEN", "")
        base = os.environ.get("PLATFORM_URL", "").rstrip("/")
        if not token or not base:
            return None
        try:
            r = post(f"{base}/internal/projects/{pid}/ledger/events", data=json.dumps(event),
                     headers={"Content-Type": "application/json", "X-AISC-Service-Token": token}, timeout=5)
        except Exception:                                               # noqa: BLE001 (the platform is down)
            _log.warning("ledger: the platform can't be reached; dashboard events stay queued")
            return None
        return r.status_code
    return send
