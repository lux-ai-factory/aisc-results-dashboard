# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Review request rules, without storage: a request is assigned to one person
or to a stakeholder group."""
import pytest

from aisc_ext.reviews.service import (
    STAKEHOLDER_GROUPS, can_resolve, is_for_user, make_request,
)


def test_make_request_to_user():
    r = make_request(dashboard_id="mcas", requested_by_sub="u1",
                     requested_by_name="alice", message="please review drift",
                     assignee_type="user", assignee_user_sub="u2", chart_id=5)
    assert r["assignee_type"] == "user" and r["assignee_user_sub"] == "u2"
    assert r["status"] == "open" and r["chart_id"] == 5


def test_make_request_to_category():
    r = make_request(dashboard_id="mcas", requested_by_sub="u1",
                     requested_by_name="alice", message="legal check",
                     assignee_type="category", assignee_category="legal")
    assert r["assignee_category"] == "legal" and r["chart_id"] is None


def test_invalid_category_rejected():
    with pytest.raises(ValueError):
        make_request(dashboard_id="d", requested_by_sub="u1",
                     requested_by_name="a", message="x",
                     assignee_type="category", assignee_category="marketing")


def test_user_assignment_requires_sub():
    with pytest.raises(ValueError):
        make_request(dashboard_id="d", requested_by_sub="u1",
                     requested_by_name="a", message="x", assignee_type="user")


def test_message_required():
    with pytest.raises(ValueError):
        make_request(dashboard_id="d", requested_by_sub="u1",
                     requested_by_name="a", message="  ",
                     assignee_type="category", assignee_category="ethics")


def test_is_for_user_specific():
    r = make_request(dashboard_id="d", requested_by_sub="u1", requested_by_name="a",
                     message="x", assignee_type="user", assignee_user_sub="u2")
    assert is_for_user(r, user_sub="u2", user_groups=[])
    assert not is_for_user(r, user_sub="u3", user_groups=["legal"])


def test_is_for_user_category_membership():
    r = make_request(dashboard_id="d", requested_by_sub="u1", requested_by_name="a",
                     message="x", assignee_type="category", assignee_category="legal")
    assert is_for_user(r, user_sub="u9", user_groups=["legal", "ethics"])
    assert not is_for_user(r, user_sub="u9", user_groups=["technical"])


def test_can_resolve_rules():
    r = make_request(dashboard_id="d", requested_by_sub="u1", requested_by_name="a",
                     message="x", assignee_type="category", assignee_category="legal")
    assert can_resolve(r, user_sub="u1", user_groups=[], is_admin=False)        # requester
    assert can_resolve(r, user_sub="u5", user_groups=["legal"], is_admin=False) # in category
    assert can_resolve(r, user_sub="x", user_groups=[], is_admin=True)          # admin
    assert not can_resolve(r, user_sub="x", user_groups=["technical"], is_admin=False)


def test_groups_taxonomy():
    assert {"legal", "compliance", "ethics", "technical", "business", "domain"} \
        <= set(STAKEHOLDER_GROUPS)


# ── access (code review 2026-10-05) ─────────────────────────────────────────
# ReviewRequestApi listed, created and resolved review requests of every project, and inherited
# Flask-AppBuilder's CSRF exemption; CommentApi had been hardened against both.

def test_only_requests_on_dashboards_the_caller_can_open_are_listed():
    from aisc_ext.reviews.service import visible

    rows = [{"id": 1, "dashboard_id": "aisc-a"}, {"id": 2, "dashboard_id": "aisc-b"},
            {"id": 3, "dashboard_id": "aisc-a"}]
    asked = []

    def can_open(d):
        asked.append(d)
        return d == "aisc-a"

    assert [r["id"] for r in visible(rows, can_open)] == [1, 3]
    assert asked == ["aisc-a", "aisc-b"]                  # each dashboard asked once


def test_the_api_checks_the_dashboard_on_every_route_and_keeps_csrf():
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "aisc_ext/reviews/api.py").read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "ReviewRequestApi")
    assigned = {t.id: ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
    assert assigned.get("csrf_exempt") is False
    for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ("assignees", "list", "post", "patch")):
        text = ast.get_source_segment(src, fn)
        assert "open_dashboard(" in text or "self._dashboard(" in text or "visible(" in text, fn.name
