# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Review request rules: building a request, who it is for, who may resolve it.

A review request asks one user, or everyone in a stakeholder group, to comment
on a dashboard as a whole or on one of its charts. No Superset imports, so it
is unit-tested on its own (rekey_by_id on SQLite)."""
from __future__ import annotations

from datetime import datetime, timezone

STAKEHOLDER_GROUPS = ["legal", "compliance", "ethics", "technical", "business", "domain"]


def make_request(*, dashboard_id: str, requested_by_sub: str, requested_by_name: str,
                 message: str, assignee_type: str,
                 assignee_user_sub: str | None = None,
                 assignee_category: str | None = None,
                 chart_id: int | None = None) -> dict:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("A review request needs a message")
    if assignee_type == "user":
        if not assignee_user_sub or not isinstance(assignee_user_sub, str):
            raise ValueError("user assignment needs assignee_user_sub")
        assignee_category = None
    elif assignee_type == "category":
        if assignee_category not in STAKEHOLDER_GROUPS:
            raise ValueError(f"unknown category: {assignee_category}")
        assignee_user_sub = None
    else:
        raise ValueError("assignee_type must be 'user' or 'category'")
    return {
        "dashboard_id": dashboard_id, "chart_id": chart_id,
        "requested_by_sub": requested_by_sub, "requested_by_name": requested_by_name,
        "message": message.strip(), "assignee_type": assignee_type,
        "assignee_user_sub": assignee_user_sub, "assignee_category": assignee_category,
        "status": "open", "created_at": datetime.now(timezone.utc),
    }


def is_for_user(req: dict, *, user_sub: str, user_groups: list[str]) -> bool:
    if req["assignee_type"] == "user":
        return req.get("assignee_user_sub") == user_sub
    return req.get("assignee_category") in (user_groups or [])


def can_resolve(req: dict, *, user_sub: str, user_groups: list[str], is_admin: bool) -> bool:
    return (is_admin
            or req.get("requested_by_sub") == user_sub
            or is_for_user(req, user_sub=user_sub, user_groups=user_groups))


def may_resolve(row, *, user_sub: str, user_groups: list[str], is_admin: bool) -> bool:
    """can_resolve on a stored request (the model's row). Its to_dict, the API's output, leaves out
    requested_by_sub, so deciding on it never matched the requester."""
    return can_resolve({**row.to_dict(), "requested_by_sub": row.requested_by_sub},
                       user_sub=user_sub, user_groups=user_groups, is_admin=is_admin)


class NotOpen(Exception):
    """The request is done or dismissed already: it is not resolved again."""


def resolution(status_before: str | None, action: str) -> str:
    """The status a resolution sets: "dismissed" for the dismiss action, else "done". Only an open request
    is resolved; another raises NotOpen, so a dismissed request is never turned into a done one and the
    ledger never says it was resolved twice."""
    if action not in ("done", "dismiss"):                              # any other action resolved it
        raise ValueError("action must be 'done' or 'dismiss'")
    if (status_before or "open") != "open":
        raise NotOpen(f"this request is {status_before} already")
    return "dismissed" if action == "dismiss" else "done"


def visible(rows: list[dict], can_open) -> list[dict]:
    """The requests on dashboards the caller can open, asking `can_open` once per dashboard."""
    seen: dict[str, bool] = {}
    out = []
    for row in rows:
        key = str(row.get("dashboard_id"))
        if key not in seen:
            seen[key] = bool(can_open(key))
        if seen[key]:
            out.append(row)
    return out


def new_request(body: dict, dashboard, *, requested_by_sub: str, requested_by_name: str, charts=()) -> dict:
    """The review request a POST body asks for, on `dashboard` (the one the body named, already opened).

    Stored under the dashboard's id, as comments are, whether the body named it by id or by slug. A chart
    must be one of `charts`, the dashboard's [(id, name)], as for a comment: a chart of another dashboard,
    or an id that is not one, was stored as asked."""
    from aisc_ext.review.service import chart_for_new_comment

    return make_request(
        dashboard_id=str(dashboard.id), requested_by_sub=requested_by_sub,
        requested_by_name=requested_by_name, message=body.get("message", ""),
        assignee_type=body.get("assignee_type"), assignee_user_sub=body.get("assignee_user_sub"),
        assignee_category=body.get("assignee_category"),
        chart_id=chart_for_new_comment(body.get("chart_id"), charts),
    )


def list_key(key: str, resolve) -> str:
    """The stored key to list a dashboard's requests by: its id, whether `key` is its id or its slug.
    `resolve(key)` returns the dashboard or None; an unknown key is kept (it matches nothing)."""
    dashboard = resolve(key)
    return str(dashboard.id) if dashboard is not None else key


def rekey_by_id(conn) -> int:
    """Move requests stored under a dashboard's slug (by older code) to its id; returns how many moved.

    Idempotent, run at every start. A key of digits is already an id; a slug of no dashboard is kept."""
    from sqlalchemy import text

    ids = {slug: str(did) for did, slug in conn.execute(
        text("SELECT id, slug FROM dashboards WHERE slug IS NOT NULL")).all()}
    moved = 0
    for rid, key in conn.execute(text("SELECT id, dashboard_id FROM aisc_review_request")).all():
        if key is None or str(key).isdigit() or key not in ids:
            continue
        conn.execute(text("UPDATE aisc_review_request SET dashboard_id = :new WHERE id = :id"),
                     {"new": ids[key], "id": rid})
        moved += 1
    return moved
