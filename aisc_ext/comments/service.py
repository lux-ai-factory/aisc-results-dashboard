# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Pure comments domain logic — no Superset/DB imports, fully unit-tested.

The SQLAlchemy model (aisc_ext.comments.model) and the FAB REST API
(aisc_ext.comments.api) use these helpers at runtime."""
from __future__ import annotations

from datetime import datetime, timezone


def make_comment(*, dashboard_id: str, author_sub: str, author_name: str,
                 body: str, chart_id: int | None = None,
                 parent_id: int | None = None) -> dict:
    if not body or not body.strip():
        raise ValueError("Comment body must not be empty")
    return {
        "dashboard_id": dashboard_id,
        "chart_id": chart_id,            # None => dashboard-level ("overall")
        "parent_id": parent_id,          # threading
        "author_sub": author_sub,        # from the verified identity
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
