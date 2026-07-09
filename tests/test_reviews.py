# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Feature: review requests (assign a comment/review to a person or a
stakeholder-group category). Storage-agnostic domain logic, unit-tested."""
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
