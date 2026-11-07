# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""What the dashboard tells the chart assistant about a project, and how a validated proposal becomes a chart.

The description holds the project's targets (their real labels), its metrics and their dimension keys, and the real
values of a key when it is a short label (at most MAX_LABELS values, at most MAX_LABEL_LENGTH characters on average):
these travel as they are to the project's chosen model and into its mock database. Free text such as prompts or
answers never goes to the model (D2). No count of rows. Pure: no Superset import."""
from __future__ import annotations

import hashlib
import re
import uuid

from aisc_ext import charts
from aisc_ext.charts import quoted_name

MAX_LABELS = 50
MAX_LABEL_LENGTH = 60
_NS = uuid.UUID("8b1f3f0e-6c3e-4c56-9d7a-2a1e4b6c9d10")


def description_from(targets, rows, ranges=None) -> dict:
    """targets: labels; rows: (metric, key, values seen (at most MAX_LABELS + 1), distinct count, all numbers,
    mean length); ranges: metric -> {"score": (min, max, whole), "dimensions": {key: (min, max)}}, of the metric's first
    finished run (the assistant draws the mock values in them).

    Of the real data, the assistant gets the target labels, every label of a dimension with few distinct short values
    (as they are), and these ranges; never a row, a count or free text. The labels reach the project's chosen model
    and the mock database's rows."""
    ranges = ranges or {}
    metrics: dict[str, dict] = {}
    for metric, key, values, distinct, numeric, mean_length in rows:
        listed = distinct <= MAX_LABELS and (mean_length or 0) <= MAX_LABEL_LENGTH
        shown = None
        if listed:
            shown = sorted({float(v) if "." in str(v) else int(v) for v in values} if numeric else {str(v) for v in values})
        entry = {"type": "number" if numeric else "text", "values": shown}
        span = (ranges.get(metric) or {}).get("dimensions", {}).get(key)
        if numeric and shown is None and span:
            entry.update(min=span[0], max=span[1])
        metrics.setdefault(metric, {"name": metric, "dimensions": {}})["dimensions"][key] = entry
    for metric, r in ranges.items():
        if r.get("score") and r["score"][0] is not None:
            low, high, whole = r["score"]
            metrics.setdefault(metric, {"name": metric, "dimensions": {}})["score"] = {"min": low, "max": high,
                                                                                     "whole": bool(whole)}
    return {"targets": list(targets), "metrics": [metrics[m] for m in sorted(metrics)]}


#: conversations a person's session remembers (the signed session cookie must stay under a browser's 4 KB)
MAX_CONVERSATIONS = 10


def with_conversation(held: dict | None, cid: str, dashboard_id) -> dict:
    """The session's conversations (id -> dashboard) with a new one added last, only the MAX_CONVERSATIONS most
    recent kept: an older conversation is started again by the panel."""
    out = {k: v for k, v in (held or {}).items() if k != cid}
    out[cid] = dashboard_id
    return dict(list(out.items())[-MAX_CONVERSATIONS:])


def ranges_from(score_rows, label_rows) -> dict:
    """description_from's ranges, from (metric, min, max, whole) score rows and (metric, key, min, max) rows of
    numeric labels, of each metric's first finished run."""
    out: dict = {}
    for name, low, high, whole in score_rows:
        out.setdefault(name, {"dimensions": {}})["score"] = (
            None if low is None else float(low), None if high is None else float(high), bool(whole))
    for name, key, low, high in label_rows:
        out.setdefault(name, {"dimensions": {}})["dimensions"][key] = (_number(low), _number(high))
    return out


def _number(value):
    """A label's bound as it is: whole numbers as int, anything else as float (never truncated)."""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else float(value)


def distinct_sql(category, sql: str) -> str:
    """The query of a radar's axes: the category's values in the validated query's result."""
    return f"SELECT DISTINCT {quoted_name(category)} FROM ({sql}) AS v ORDER BY 1"


def chart_params(chart: dict, *, axes) -> dict:
    """Superset's settings for a proposed chart. A radar needs its axes (the category values of the real result)."""
    category, value, series = chart["category"], chart["value"], chart.get("series")
    groupby = [series] if series else []
    kind = chart["kind"]
    if kind == "radar":
        return {"viz_type": "radar", "groupby": groupby, "metrics": charts.radar_metrics(category, value, axes, aggregate="MAX"), "adhoc_filters": [], "row_limit": 1000,
                "show_legend": True, "legendOrientation": "bottom", "number_format": "SMART_NUMBER",
                "column_config": {}}
    if kind in ("bar", "line"):
        return {"viz_type": "echarts_timeseries_bar" if kind == "bar" else "echarts_timeseries_line",
                "x_axis": category, "groupby": groupby, "adhoc_filters": [], "row_limit": 1000,
                "metrics": [{"expressionType": "SQL", "label": value, "sqlExpression": f"MAX({quoted_name(value)})"}],
                "show_legend": True, "legendOrientation": "bottom", "xAxisLabelRotation": 45}
    return {"viz_type": "table", "query_mode": "raw", "all_columns": [c for c in (category, series, value) if c],
            "adhoc_filters": [], "row_limit": 1000, "server_pagination": False}


def validated_files(source: dict, *, pid: str, sql: str, fingerprint: str, chart: dict, columns, axes, description: str,
                    author: str) -> dict:
    """The import bundle of a validated chart: a dataset holding exactly the validated query on the project's
    connection, and its chart. ValueError when the query is not the one validated (R3)."""
    if hashlib.sha256(sql.encode("utf-8")).hexdigest() != fingerprint:
        raise ValueError("the query does not match the validated fingerprint")
    hexed = pid.replace("-", "")
    dataset_uuid = str(uuid.uuid5(_NS, f"{pid}/dataset/{fingerprint}"))
    chart_uuid = str(uuid.uuid5(_NS, f"{pid}/chart/{fingerprint}/{chart.get('kind')}/{chart.get('title')}"))
    dataset_name = f"assistant_{fingerprint[:12]}_{hexed}"
    note = (f"Made with the chart assistant; validated by {author}. Query fingerprint {fingerprint[:12]}. "
            f"{description}").strip()
    params = chart_params(chart, axes=axes)
    return {"metadata.yaml": charts.metadata("Slice"),
            **charts.source_files(dataset_uuid=dataset_uuid, dataset_name=dataset_name,
                                  database_uuid=source["database_uuid"], database_name=source["database_name"],
                                  sqlalchemy_uri=source["sqlalchemy_uri"], columns=columns, sql=sql, description=note,
                                  metrics=[]),
            f"charts/{chart_uuid}.yaml": charts.chart_file(chart_id=chart_uuid, name=chart["title"],
                                                           viz_type=params["viz_type"], params=params,
                                                           description=note, dataset_uuid=dataset_uuid)}


def chart_uuid_of(files: dict) -> str:
    return next(k for k in files if k.startswith("charts/"))[len("charts/"):-len(".yaml")]


def to_remove(asked, plots: list[dict]) -> list[tuple[int, str]] | None:
    """The plots to take off, as (number, title) with the dashboard's own titles, when every plot the assistant named is
    on this dashboard (plots: every chart placed there, whoever made it); None otherwise (nothing is removed)."""
    titles = {c["id"]: c["title"] for c in plots}
    if not isinstance(asked, list) or not asked:
        return None
    numbers = [a.get("chart") if isinstance(a, dict) else None for a in asked]
    if any(n not in titles for n in numbers):
        return None
    return [(n, titles[n]) for n in dict.fromkeys(numbers)]


#: a plot's scale: two plots that differ only in it show the same thing
_SCALE = ("axis_min", "axis_max", "percent")


def subject(title) -> str:
    """What a plot shows, from its title: lower case, without a leading "Default ·", parentheses and numbers."""
    text = re.sub(r"^\s*default\s*·\s*", "", str(title or "").lower())
    text = re.sub(r"\([^)]*\)|[\d%]+", " ", text)
    return " ".join(text.split())


def plots_for_model(placed, found: dict) -> list[dict]:
    """Every chart placed on a dashboard (placed: plots_on's (id, made by the assistant)), as the model is told of it:
    number, title, kind, whether the assistant made it (and then its query), its definition (never a value), the changes
    it takes in place (can_change) and the other plots showing the same thing (same_as: the same definition but for the
    scale, or titles showing the same subject), about which the model asks before changing or removing one. found: id -> {title,
    viz_type, params, sql} of the charts still there."""
    out = []
    for i, mine in placed:
        if i not in found:
            continue
        chart = found[i]
        out.append({"id": i, "title": chart["title"], "kind": charts.kind_of(chart["viz_type"]), "mine": mine,
                    "definition": charts.plot_definition(chart["viz_type"], chart["params"]),
                    "can_change": charts.can_change(chart["viz_type"]),
                    **({"sql": chart.get("sql") or ""} if mine else {})})

    def shows(plot):
        return {k: v for k, v in plot["definition"].items() if k not in _SCALE}
    for plot in out:
        plot["same_as"] = [p["id"] for p in out if p is not plot and (
            shows(p) == shows(plot) or (subject(p["title"]) and subject(p["title"]) == subject(plot["title"])))]
    return out


def to_change(asked, plots: list[dict]) -> tuple[int, dict] | None:
    """The plot to change and the changes, when the assistant named a plot on this dashboard and some change."""
    if not isinstance(asked, dict) or not isinstance(asked.get("changes"), dict) or not asked["changes"]:
        return None
    if asked.get("chart") not in {p["id"] for p in plots}:
        return None
    return asked["chart"], dict(asked["changes"])
