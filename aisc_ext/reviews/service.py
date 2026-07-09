# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Pure review-request domain logic (no Superset/DB imports; unit-tested).

A review request asks a specific user OR a stakeholder-group category to comment
on a scope (dashboard overall, or one chart)."""
from __future__ import annotations

from datetime import datetime, timezone

STAKEHOLDER_GROUPS = ["legal", "compliance", "ethics", "technical", "business", "domain"]


def make_request(*, dashboard_id: str, requested_by_sub: str, requested_by_name: str,
                 message: str, assignee_type: str,
                 assignee_user_sub: str | None = None,
                 assignee_category: str | None = None,
                 chart_id: int | None = None) -> dict:
    if not message or not message.strip():
        raise ValueError("A review request needs a message")
    if assignee_type == "user":
        if not assignee_user_sub:
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
