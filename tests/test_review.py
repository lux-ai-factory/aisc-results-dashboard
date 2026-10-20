# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The Review page: a dashboard with its conversation beside it.

Everything the page shows is decided here, in Python; the page's script only
draws what it is given and sends back what the person typed.
"""
import pytest

from aisc_ext.review.service import (
    build_threads,
    chart_choices,
    chart_for_new_comment,
    charts_in_layout,
    frame_url,
    reply_target,
)


def _row(i, chart, author, body, when, parent=None, name=None):
    return {"id": i, "dashboard_id": "7", "chart_id": chart, "parent_id": parent,
            "author_sub": author, "author_name": name or author, "body": body,
            "created_at": when}


CHARTS = [(5, "Wasserstein Drift"), (9, "Model Performance")]


# -- the frame --------------------------------------------------------------

def test_frame_shows_the_dashboard_without_superset_chrome():
    assert frame_url(7) == "/superset/dashboard/7/?standalone=2"


# -- what a comment can be about --------------------------------------------

def test_choices_start_with_the_whole_dashboard_then_charts_in_dashboard_order():
    rows = [_row(1, None, "u1", "a", "2026-09-23T10:00:00"),
            _row(2, 9, "u1", "b", "2026-09-23T10:01:00"),
            _row(3, 9, "u2", "c", "2026-09-23T10:02:00")]
    assert chart_choices(CHARTS, rows) == [
        {"id": None, "label": "Whole dashboard", "count": 1},
        {"id": 5, "label": "Wasserstein Drift", "count": 0},
        {"id": 9, "label": "Model Performance", "count": 2},
    ]


def test_new_comment_on_a_chart_of_another_dashboard_is_refused():
    with pytest.raises(ValueError):
        chart_for_new_comment(42, CHARTS)


def test_new_comment_without_a_chart_is_about_the_whole_dashboard():
    assert chart_for_new_comment(None, CHARTS) is None
    assert chart_for_new_comment(9, CHARTS) == 9


# -- replies ----------------------------------------------------------------

def test_a_reply_joins_the_thread_of_the_comment_it_answers_and_its_chart():
    parent = _row(1, 5, "u1", "why?", "2026-09-23T10:00:00")
    assert reply_target(parent, dashboard_id="7") == {"parent_id": 1, "chart_id": 5}


def test_a_reply_to_a_reply_goes_to_the_top_of_that_thread():
    reply = _row(2, 5, "u2", "because", "2026-09-23T10:01:00", parent=1)
    assert reply_target(reply, dashboard_id="7") == {"parent_id": 1, "chart_id": 5}


def test_a_reply_to_a_comment_on_another_dashboard_is_refused():
    parent = _row(1, 5, "u1", "why?", "2026-09-23T10:00:00")
    with pytest.raises(ValueError):
        reply_target(parent, dashboard_id="8")


def test_a_reply_to_nothing_is_refused():
    with pytest.raises(ValueError):
        reply_target(None, dashboard_id="7")


# -- threads ----------------------------------------------------------------

def test_threads_newest_first_with_replies_underneath_in_the_order_written():
    rows = [_row(1, 5, "u1", "old", "2026-09-23T09:00:00"),
            _row(2, None, "u2", "new", "2026-09-23T11:00:00"),
            _row(4, 5, "u1", "second reply", "2026-09-23T09:30:00", parent=1),
            _row(3, 5, "u2", "first reply", "2026-09-23T09:10:00", parent=1)]
    threads = build_threads(rows, CHARTS, user_sub="u1", is_admin=False)
    assert [t["id"] for t in threads] == [2, 1]
    assert [r["body"] for r in threads[1]["replies"]] == ["first reply", "second reply"]
    assert threads[0]["replies"] == []


def test_each_comment_says_what_it_is_about():
    rows = [_row(1, 5, "u1", "x", "2026-09-23T09:00:00"),
            _row(2, None, "u1", "y", "2026-09-23T10:00:00")]
    by_id = {t["id"]: t for t in build_threads(rows, CHARTS, user_sub="u1", is_admin=False)}
    assert by_id[1]["about"] == "Wasserstein Drift"
    assert by_id[2]["about"] == "Whole dashboard"


def test_a_chart_no_longer_on_the_dashboard_is_still_named_honestly():
    rows = [_row(1, 77, "u1", "x", "2026-09-23T09:00:00")]
    [t] = build_threads(rows, CHARTS, user_sub="u1", is_admin=False)
    assert t["about"] == "A chart no longer on this dashboard"


def test_only_the_author_sees_delete_on_their_own_comments():
    rows = [_row(1, None, "u1", "mine", "2026-09-23T09:00:00"),
            _row(2, None, "u2", "theirs", "2026-09-23T10:00:00", parent=1)]
    [t] = build_threads(rows, CHARTS, user_sub="u1", is_admin=False)
    assert t["can_delete"] is True and t["mine"] is True
    assert t["replies"][0]["can_delete"] is False and t["replies"][0]["mine"] is False


def test_an_admin_may_delete_anyone_s_comment():
    rows = [_row(1, None, "u2", "theirs", "2026-09-23T09:00:00")]
    [t] = build_threads(rows, CHARTS, user_sub="u1", is_admin=True)
    assert t["can_delete"] is True and t["mine"] is False


def test_a_reply_whose_comment_was_deleted_is_not_lost():
    rows = [_row(3, 5, "u2", "orphan", "2026-09-23T09:10:00", parent=1)]
    [t] = build_threads(rows, CHARTS, user_sub="u1", is_admin=False)
    assert t["id"] == 3 and t["body"] == "orphan"


def test_the_author_s_internal_id_is_not_sent_to_the_page():
    rows = [_row(1, None, "u1", "x", "2026-09-23T09:00:00", name="Alice Martin")]
    [t] = build_threads(rows, CHARTS, user_sub="u1", is_admin=False)
    assert t["author"] == "Alice Martin"
    assert "author_sub" not in t


def test_a_reply_filed_under_a_reply_is_shown_in_that_thread():
    # a reply to a reply, as older rows may have
    rows = [_row(1, None, "u1", "top", "2026-09-23T09:00:00"),
            _row(2, None, "u2", "reply", "2026-09-23T09:10:00", parent=1),
            _row(3, None, "u1", "reply to reply", "2026-09-23T09:20:00", parent=2)]
    [t] = build_threads(rows, CHARTS, user_sub="u1", is_admin=False)
    assert [r["body"] for r in t["replies"]] == ["reply", "reply to reply"]


# -- the dashboard's charts, as the reader sees them --------------------------

LAYOUT = {
    "ROOT_ID": {"type": "ROOT", "children": ["GRID_ID"]},
    "GRID_ID": {"type": "GRID", "children": ["ROW-1", "TABS-1"]},
    "ROW-1": {"type": "ROW", "children": ["CHART-x", "CHART-y"]},
    "TABS-1": {"type": "TABS", "children": ["TAB-1"]},
    "TAB-1": {"type": "TAB", "children": ["CHART-z"]},
    "CHART-x": {"type": "CHART", "children": [], "meta": {"chartId": 9, "sliceName": "Model Performance"}},
    "CHART-y": {"type": "CHART", "children": [], "meta": {"chartId": 5, "sliceNameOverride": "Drift (WS)"}},
    "CHART-z": {"type": "CHART", "children": [], "meta": {"chartId": 3}},
}
SLICES = [(3, "Failed Responses"), (5, "Wasserstein Drift"), (9, "Model Performance"),
          (11, "Not placed yet")]


def test_charts_follow_the_layout_top_to_bottom_left_to_right_then_the_rest():
    assert [c for c, _ in charts_in_layout(LAYOUT, SLICES)] == [9, 5, 3, 11]


def test_a_chart_renamed_on_the_dashboard_goes_by_the_name_shown_there():
    assert dict(charts_in_layout(LAYOUT, SLICES))[5] == "Drift (WS)"


def test_without_a_layout_the_charts_keep_the_order_given():
    assert charts_in_layout(None, SLICES) == SLICES
    assert charts_in_layout("not json", SLICES) == SLICES


def test_a_layout_naming_a_chart_that_is_not_on_the_dashboard_adds_nothing():
    layout = {"ROOT_ID": {"type": "ROOT", "children": ["CHART-q"]},
              "CHART-q": {"type": "CHART", "children": [], "meta": {"chartId": 404}}}
    assert charts_in_layout(layout, SLICES) == SLICES
