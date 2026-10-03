# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The dashboard's ledger events (ledger phase 9, D1-D2; docs/superpowers/ledger-2026-10-02/02-spec.md).

A project's dashboard is ``aisc-<pid hex>`` (aisc_ext.projects): its slug names the project, so an event
of a comment or a review finds its project log from the dashboard it is on. The gateway's witness reads
the same slug from the request (in the path, or in ``dashboard_id=``), which is why the Review page names
the dashboard by its slug in every call that writes.

Superset's metadata is not a project database and has no ``ledger.emit``. The extension keeps its own
outbox there (``aisc_ledger_outbox``): ``emit`` writes the event on the connection of the change, in
its transaction, so the two commit or roll back together (R2.4). ``deliver`` posts what is queued to the
platform's internal route with the dashboard's token, in order, once each: a refusal is kept with its
status and not sent again; a platform that doesn't answer leaves the row queued for the next pass.

An event never names who acted (I2): the witnessed request it cites does. A review's assignee is said as
its kind (``user``) or its group (``category:legal``), never as a person. Nothing is queued while
LEDGER_MODE is off (the default). Pure: no Superset import, so it unit-tests on SQLite.
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
    Column("refused", Integer, nullable=True),            # the platform's status when it refused the event
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
    """What is wrong with the request's witness hint (`?dashboard=<slug>`, which names the project to the
    gateway's witness), for the dashboard actually written to; None when it may go on. No hint is no
    problem: the event then cites a request filed in the platform log, and the relay says so (phase 9
    review M4). A hint naming another dashboard is refused before anything is written."""
    if hint is None:
        return None
    if project_of(slug) is None or hint != slug:
        return "the dashboard named in the request is not the one written to"
    return None


def request_id(headers) -> str | None:
    """The request the gateway witnessed (X-AISC-Request-Id), only when it is a uuid."""
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
    """The whole event the platform's internal route takes: a new event id, the action, the fields."""
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
    """Queue the event on `conn`, inside the change's own transaction. None while the ledger is off, or for
    a dashboard of no project (Superset's own, an example): there is no project log to write to."""
    if not on() or project_pid is None:
        return None
    result = conn.execute(OUTBOX.insert().values(project_pid=project_pid, event=event(action, fields),
                                                 queued_at=datetime.now(timezone.utc)))
    return result.inserted_primary_key[0]


#: The platform's answers that refuse the event itself: kept with the status, never sent again. Any other
#: answer (a wrong token, an address that isn't the route, a platform down) is fixed by the operator, so
#: the event waits for the next pass (phase 9 review M3).
REFUSALS = (409, 413, 422)
_PASS = threading.Lock()


def deliver(engine, send, limit: int = 100) -> tuple[int, int]:
    """Post what is queued, oldest first: (sent, not sent). `send(pid, event)` returns the platform's status
    (None: it can't be asked). 2xx: delivered. A refusal (REFUSALS): kept with its status, never sent again.
    Anything else: kept, and the pass stops (the order holds). One pass at a time in this process, so two
    request threads never send the same rows, or one comment's events out of order (review m9)."""
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
    """`send` for `deliver`: the platform's internal route, with the dashboard's token
    (PLATFORM_LEDGER_DASHBOARD_TOKEN). None when the token or the platform's address is not set."""
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
