# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Comment rules: building a comment, who may delete.

No Superset imports, so it is unit-tested on its own (hide_once on SQLite). The REST API
(aisc_ext.comments.api) uses these helpers."""
from __future__ import annotations

from datetime import datetime, timezone


def make_comment(*, dashboard_id: str, author_sub: str, author_name: str,
                 body: str, chart_id: int | None = None,
                 parent_id: int | None = None) -> dict:
    if not isinstance(body, str) or not body.strip():                  # a number or a list was a 500
        raise ValueError("Comment body must be text, not empty")
    return {
        "dashboard_id": dashboard_id,
        "chart_id": chart_id,            # None: about the whole dashboard ("overall")
        "parent_id": parent_id,          # the comment this one replies to
        "author_sub": author_sub,        # from the signed-in user, never the request
        "author_name": author_name,
        "body": body.strip(),
        "created_at": datetime.now(timezone.utc),
    }


def chart_filter(value: str) -> int:
    """The ?chart_id= of a comment list as a number; ValueError otherwise (it was a 500)."""
    if not isinstance(value, str) or not value.isdigit():
        raise ValueError("chart_id must be a chart's number")
    return int(value)


def can_delete(row: dict, *, user_sub: str, is_admin: bool) -> bool:
    return is_admin or row.get("author_sub") == user_sub


def hide_once(session, model, pk: int, when) -> bool:
    """Hide comment `pk`; True when this call hid it, False when it is gone or already hidden.

    One conditional UPDATE (``WHERE deleted_at IS NULL``), not a read and then a write: two deletes of
    one comment at once both read it as not hidden, so only the database can say which one hid it, and
    only that one queues dashboard.comment.deleted. On Postgres the
    second UPDATE waits for the first and then matches no row."""
    from sqlalchemy import update

    result = session.execute(update(model).where(model.id == pk, model.deleted_at.is_(None))
                             .values(deleted_at=when).execution_options(synchronize_session=False))
    return result.rowcount == 1
