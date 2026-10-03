# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Comment rules: building a comment, filtering by scope, who may delete.

No Superset or database imports, so it is unit-tested on its own. The REST API
(aisc_ext.comments.api) uses these helpers."""
from __future__ import annotations

from datetime import datetime, timezone


def make_comment(*, dashboard_id: str, author_sub: str, author_name: str,
                 body: str, chart_id: int | None = None,
                 parent_id: int | None = None) -> dict:
    if not body or not body.strip():
        raise ValueError("Comment body must not be empty")
    return {
        "dashboard_id": dashboard_id,
        "chart_id": chart_id,            # None: about the whole dashboard ("overall")
        "parent_id": parent_id,          # the comment this one replies to
        "author_sub": author_sub,        # from the signed-in user, never the request
        "author_name": author_name,
        "body": body.strip(),
        "created_at": datetime.now(timezone.utc),
    }


def scope_filter(rows: list[dict], *, dashboard_id: str,
                 chart_id: int | None = None, overall: bool = False) -> list[dict]:
    out = [r for r in rows if r["dashboard_id"] == dashboard_id]
    if overall:
        return [r for r in out if r.get("chart_id") is None]
    if chart_id is not None:
        return [r for r in out if r.get("chart_id") == chart_id]
    return out


def can_delete(row: dict, *, user_sub: str, is_admin: bool) -> bool:
    return is_admin or row.get("author_sub") == user_sub
