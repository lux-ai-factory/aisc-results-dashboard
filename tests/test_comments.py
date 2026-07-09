# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Feature 3: comments domain logic (storage-agnostic, unit-tested).

chart_id set  -> per-plot comment; chart_id None -> dashboard-level ("overall").
Author always comes from the authenticated identity, never the request body.
"""
import pytest

from aisc_ext.comments.service import make_comment, scope_filter, can_delete


def _row(i, dash, chart, author, body):
    return {"id": i, "dashboard_id": dash, "chart_id": chart,
            "author_sub": author, "body": body}


def test_make_comment_uses_identity_not_body():
    c = make_comment(dashboard_id="d1", author_sub="u1", author_name="alice",
                     body="hi", chart_id=5)
    assert c["author_sub"] == "u1" and c["author_name"] == "alice"
    assert c["chart_id"] == 5 and c["dashboard_id"] == "d1"


def test_make_comment_overall_when_no_chart():
    c = make_comment(dashboard_id="d1", author_sub="u1", author_name="a", body="x")
    assert c["chart_id"] is None


def test_empty_body_rejected():
    with pytest.raises(ValueError):
        make_comment(dashboard_id="d1", author_sub="u1", author_name="a", body="  ")


def test_scope_overall_vs_per_chart():
    rows = [
        _row(1, "d1", None, "u1", "overall"),
        _row(2, "d1", 5, "u1", "on chart 5"),
        _row(3, "d1", 9, "u2", "on chart 9"),
        _row(4, "d2", None, "u1", "other dash"),
    ]
    overall = scope_filter(rows, dashboard_id="d1", overall=True)
    assert [c["id"] for c in overall] == [1]
    chart5 = scope_filter(rows, dashboard_id="d1", chart_id=5)
    assert [c["id"] for c in chart5] == [2]


def test_can_delete_author_or_admin():
    row = _row(1, "d1", 5, "u1", "x")
    assert can_delete(row, user_sub="u1", is_admin=False)      # author
    assert can_delete(row, user_sub="other", is_admin=True)    # moderator
    assert not can_delete(row, user_sub="other", is_admin=False)
