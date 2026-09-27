# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""What the Review page shows: a dashboard, and its conversation beside it.

Pure: no Superset, Flask or database imports, so it unit-tests on its own. The
comments API hands it rows as the model's ``to_dict`` gives them, and the charts
of the dashboard as ``(id, name)`` pairs in the order the dashboard lists them;
the view (aisc_ext.review.views) takes the frame address from here.

Threads are one level deep. A reply to a reply joins the thread it is in,
which is how people read a side conversation anyway, and it keeps the page a
list rather than a tree to scroll.
"""
from __future__ import annotations

import json
from collections import Counter

WHOLE_DASHBOARD = "Whole dashboard"
GONE_CHART = "A chart no longer on this dashboard"


def frame_url(dashboard_id) -> str:
    """The dashboard as Superset draws it, minus Superset's own menu and title.

    ``standalone=2`` is Superset's documented URL parameter for that; the page
    around the frame carries the title and the way back instead.
    """
    return f"/superset/dashboard/{dashboard_id}/?standalone=2"


def chart_choices(charts, rows) -> list[dict]:
    """What a new comment can be about, each with how many comments it has."""
    counts = Counter(r.get("chart_id") for r in rows)
    choices = [{"id": None, "label": WHOLE_DASHBOARD, "count": counts.get(None, 0)}]
    for chart_id, name in charts:
        choices.append({"id": chart_id, "label": name, "count": counts.get(chart_id, 0)})
    return choices


def chart_for_new_comment(chart_id, charts):
    """The chart a new comment is attached to, or None for the whole dashboard.

    A chart that is not on this dashboard is refused: the comment would be
    filed under a dashboard nobody could find it from.
    """
    if chart_id is None:
        return None
    if chart_id not in {c for c, _ in charts}:
        raise ValueError(f"Chart {chart_id} is not on this dashboard")
    return chart_id


def reply_target(parent, *, dashboard_id) -> dict:
    """Where a reply goes: the top of the parent's thread, on the parent's chart."""
    if parent is None:
        raise ValueError("The comment being answered no longer exists")
    if str(parent.get("dashboard_id")) != str(dashboard_id):
        raise ValueError("The comment being answered is on another dashboard")
    root = parent.get("parent_id") or parent["id"]
    return {"parent_id": root, "chart_id": parent.get("chart_id")}


def _about(chart_id, names) -> str:
    if chart_id is None:
        return WHOLE_DASHBOARD
    return names.get(chart_id, GONE_CHART)


def _shown(row, names, *, user_sub, is_admin) -> dict:
    mine = row.get("author_sub") == user_sub
    return {
        "id": row["id"],
        "author": row.get("author_name") or "",
        "body": row.get("body") or "",
        "created_at": row.get("created_at"),
        "chart_id": row.get("chart_id"),
        "about": _about(row.get("chart_id"), names),
        "mine": mine,
        "can_delete": mine or is_admin,
        "replies": [],
    }


def build_threads(rows, charts, *, user_sub, is_admin) -> list[dict]:
    """The conversation, newest thread first, replies in the order written.

    A reply whose comment was deleted is shown as a thread of its own rather
    than dropped: somebody wrote it, and it may be the only record of a point.
    """
    names = dict(charts)
    parent_of = {r["id"]: r.get("parent_id") for r in rows}

    def root(comment_id):
        seen = set()
        while parent_of.get(comment_id) in parent_of and comment_id not in seen:
            seen.add(comment_id)
            comment_id = parent_of[comment_id]
        return comment_id

    def key(r):
        return (r.get("created_at") or "", r["id"])

    tops, replies = [], []
    for r in rows:
        (tops if root(r["id"]) == r["id"] else replies).append(r)

    shown = {r["id"]: _shown(r, names, user_sub=user_sub, is_admin=is_admin)
             for r in rows}
    for r in sorted(replies, key=key):
        shown[root(r["id"])]["replies"].append(shown[r["id"]])
    return [shown[r["id"]] for r in sorted(tops, key=key, reverse=True)]


def charts_in_layout(layout, slices):
    """The dashboard's charts in reading order, under the names shown on it.

    ``layout`` is the dashboard's ``position_json`` (text or already parsed):
    a tree from ``ROOT_ID`` whose ``CHART`` leaves name a chart id and may
    rename it (``sliceNameOverride``). Walking it depth first gives rows top to
    bottom and, within a row, left to right. Charts on the dashboard that the
    layout does not place follow, in the order given; a layout that cannot be
    read changes nothing.
    """
    if isinstance(layout, str):
        try:
            layout = json.loads(layout)
        except ValueError:
            layout = None
    if not isinstance(layout, dict) or "ROOT_ID" not in layout:
        return list(slices)

    names = dict(slices)
    placed: list = []
    placed_ids: set = set()
    stack, seen = ["ROOT_ID"], set()
    while stack:
        node_id = stack.pop()
        if node_id in seen or node_id not in layout:
            continue
        seen.add(node_id)
        node = layout[node_id] or {}
        meta = node.get("meta") or {}
        chart_id = meta.get("chartId")
        if node.get("type") == "CHART" and chart_id in names and chart_id not in placed_ids:
            placed.append((chart_id, meta.get("sliceNameOverride") or names[chart_id]))
            placed_ids.add(chart_id)
        stack.extend(reversed(node.get("children") or []))
    return placed + [(c, n) for c, n in slices if c not in placed_ids]
