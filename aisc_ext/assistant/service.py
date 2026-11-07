# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""What the dashboard tells the chart assistant about a project, and how a validated proposal becomes a chart.

The description holds the project's targets, its metrics and their dimension keys, and the values of a key only when
it is a short label (at most MAX_LABELS values, at most MAX_LABEL_LENGTH characters on average): free text such as
prompts or answers never goes to the model (D2). No count of rows. Pure: no Superset import."""
from __future__ import annotations

import hashlib
import json
import uuid

import yaml

MAX_LABELS = 50
MAX_LABEL_LENGTH = 60
HEADER_TEXT = "Assistant charts"
_NS = uuid.UUID("8b1f3f0e-6c3e-4c56-9d7a-2a1e4b6c9d10")
_VERSION = "1.0.0"
_dump = lambda o: yaml.safe_dump(o, sort_keys=False, allow_unicode=True)


def description_from(targets, rows, ranges=None) -> dict:
    """targets: labels; rows: (metric, key, values seen (at most MAX_LABELS + 1), distinct count, all numbers,
    mean length); ranges: metric -> {"score": (min, max, whole), "dimensions": {key: (min, max)}}, of the metric's first
    finished run: the only thing of the real values that goes to the assistant (it draws the mock values in them)."""
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


def may_validate(roles, project_hex: str) -> bool:
    """Validating is an editor's or an admin's act (D3)."""
    return "Admin" in roles or f"AiscProjectEditor_{project_hex}" in roles


def _quoted(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def quoted_name(name) -> str:
    """A result column the model named, as one SQL identifier: whatever text its alias holds stays a column name
    (never SQL the assistant's query check did not see), with its capitals and spaces kept."""
    return '"' + str(name).replace('"', '""') + '"'


def distinct_sql(category, sql: str) -> str:
    """The query of a radar's axes: the category's values in the validated query's result."""
    return f"SELECT DISTINCT {quoted_name(category)} FROM ({sql}) AS v ORDER BY 1"


def chart_params(chart: dict, *, axes) -> dict:
    """Superset's settings for a proposed chart. A radar needs its axes (the category values of the real result)."""
    category, value, series = chart["category"], chart["value"], chart.get("series")
    groupby = [series] if series else []
    kind = chart["kind"]
    if kind == "radar":
        when, then = quoted_name(category), quoted_name(value)
        metrics = [{"expressionType": "SQL", "label": str(a),
                    "sqlExpression": f"MAX(CASE WHEN {when} = {_quoted(a)} THEN {then} END)"} for a in axes]
        return {"viz_type": "radar", "groupby": groupby, "metrics": metrics, "adhoc_filters": [], "row_limit": 1000,
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
    db_file = "".join(ch if ch.isalnum() else "_" for ch in source["database_name"])
    dataset_name = f"assistant_{fingerprint[:12]}_{hexed}"
    note = (f"Made with the chart assistant; validated by {author}. Query fingerprint {fingerprint[:12]}. "
            f"{description}").strip()
    return {
        "metadata.yaml": _dump({"version": _VERSION, "type": "Slice", "timestamp": "2026-11-06T00:00:00+00:00"}),
        f"databases/{db_file}.yaml": _dump({
            "database_name": source["database_name"], "sqlalchemy_uri": source["sqlalchemy_uri"],
            "uuid": source["database_uuid"], "version": _VERSION, "cache_timeout": None, "expose_in_sqllab": False,
            "allow_run_async": False, "allow_ctas": False, "allow_cvas": False, "allow_dml": False,
            "allow_file_upload": False, "extra": {}}),
        f"datasets/{db_file}/{dataset_name}.yaml": _dump({
            "table_name": dataset_name, "main_dttm_col": None, "description": note, "default_endpoint": None,
            "offset": 0, "cache_timeout": None, "schema": None, "sql": sql, "params": None, "template_params": None,
            "filter_select_enabled": True, "fetch_values_predicate": None, "extra": None, "uuid": dataset_uuid,
            "database_uuid": source["database_uuid"], "version": _VERSION, "metrics": [],
            "columns": [{"column_name": c, "verbose_name": None, "is_dttm": False, "is_active": True, "type": None,
                         "groupby": True, "filterable": True, "expression": None, "description": None,
                         "python_date_format": None, "extra": {}} for c in columns]}),
        f"charts/{chart_uuid}.yaml": _dump({
            "slice_name": chart["title"], "description": note, "certified_by": None, "certification_details": None,
            "viz_type": chart_params(chart, axes=axes)["viz_type"], "params": chart_params(chart, axes=axes),
            "query_context": None, "cache_timeout": None, "uuid": chart_uuid, "version": _VERSION,
            "dataset_uuid": dataset_uuid}),
    }


def chart_uuid_of(files: dict) -> str:
    return next(k for k in files if k.startswith("charts/"))[len("charts/"):-len(".yaml")]


_HEADER = "HEADER-aisc-assistant"
_TAB = "TAB-aisc-assistant"
_NODE = "CHART-aisc-assistant-"
_KINDS = {"radar": "radar", "echarts_timeseries_bar": "bar", "echarts_timeseries_line": "line", "table": "table"}


def kind_of(viz_type: str) -> str:
    """The assistant's kind of a chart it made, read back from Superset's viz type."""
    return _KINDS.get(viz_type, viz_type)


def made_chart_ids(position: dict) -> list[int]:
    """The charts the assistant made on a dashboard, in layout order: the only ones it may change or remove."""
    return [n["meta"]["chartId"] for k, n in position.items()
            if k.startswith(_NODE) and isinstance(n, dict) and n.get("type") == "CHART"]


def to_remove(asked, made: list[dict]) -> list[tuple[int, str]] | None:
    """The plots to take off, as (number, title) with the dashboard's own titles, when every plot the assistant named is
    one it made on this dashboard; None otherwise (nothing is removed)."""
    titles = {c["id"]: c["title"] for c in made}
    if not isinstance(asked, list) or not asked:
        return None
    numbers = [a.get("chart") if isinstance(a, dict) else None for a in asked]
    if any(n not in titles for n in numbers):
        return None
    return [(n, titles[n]) for n in dict.fromkeys(numbers)]


def plots_on(position: dict) -> list[tuple[int, bool]]:
    """Every chart placed on a dashboard, in layout order, and whether the assistant made it."""
    out = []
    for k, n in position.items():
        if isinstance(n, dict) and n.get("type") == "CHART" and isinstance((n.get("meta") or {}).get("chartId"), int):
            if n["meta"]["chartId"] not in [c for c, _ in out]:
                out.append((n["meta"]["chartId"], k.startswith(_NODE)))
    return out


def to_change(asked, plots: list[dict]) -> tuple[int, dict] | None:
    """The plot to change and the changes, when the assistant named a plot on this dashboard and some change."""
    if not isinstance(asked, dict) or not isinstance(asked.get("changes"), dict) or not asked["changes"]:
        return None
    if asked.get("chart") not in {p["id"] for p in plots}:
        return None
    return asked["chart"], dict(asked["changes"])


def _node_of(position: dict, chart_id: int, any_chart: bool = False) -> str | None:
    return next((k for k, n in position.items() if (any_chart or k.startswith(_NODE)) and isinstance(n, dict)
                 and n.get("type") == "CHART" and (n.get("meta") or {}).get("chartId") == chart_id), None)


def without_chart(position: dict, chart_id: int, any_chart: bool = False) -> dict:
    """The layout with a chart taken off (wherever it is placed), its row with it when empty, and the "Assistant
    charts" header or tab when no chart of the assistant is left. Only the assistant's own charts unless any_chart:
    another chart leaves the layout unchanged."""
    if _node_of(position, chart_id, any_chart) is None:
        return position
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in position.items()}
    gone = set()
    while (node := _node_of(out, chart_id, any_chart)) is not None:
        gone.add(node)
        row = (out[node].get("parents") or [None])[-1]
        del out[node]
        if row in out and out[row].get("type") == "ROW":
            out[row]["children"] = [c for c in out[row]["children"] if c != node]
            if not out[row]["children"]:
                del out[row]
                gone.add(row)
    if not made_chart_ids(out):
        for own in (_HEADER, _TAB):
            if own in out:
                del out[own]
                gone.add(own)
    for k, n in out.items():
        if isinstance(n, dict) and isinstance(n.get("children"), list) and gone & set(n["children"]):
            n["children"] = [c for c in n["children"] if c not in gone]
    return out


def place_chart(position: dict, *, chart_id: int, chart_uuid: str, name: str, replaces: int | None = None,
                any_chart: bool = False) -> dict:
    """The dashboard's layout with the chart in a row of its own under the "Assistant charts" header (in an "Assistant
    charts" tab on a dashboard with tabs); a chart that
    replaces one of the assistant's charts takes its place (or goes to the end when that one is no longer there)."""
    out = dict(position)
    grid = next((k for k, n in out.items() if isinstance(n, dict) and n.get("type") == "GRID"), None)
    root = (out.get("ROOT_ID") or {}).get("children") or []
    tabs = root[0] if root and (out.get(root[0]) or {}).get("type") == "TABS" else None
    if grid is None and tabs is None:
        return out
    node = f"{_NODE}{chart_uuid[:8]}"
    meta = {"chartId": chart_id, "uuid": chart_uuid, "width": 12, "height": 60, "sliceName": name}
    old = _node_of(out, replaces, any_chart) if replaces is not None else None
    if old is not None and old != node:
        row = out[old]["parents"][-1]
        out[node] = {"type": "CHART", "id": node, "children": [], "parents": list(out[old]["parents"]),
                     "meta": {**out[old].get("meta", {}), **meta}}
        out[row] = {**out[row], "children": [node if c == old else c for c in out[row]["children"]]}
        del out[old]
        return out
    if grid is not None:
        # a dashboard without tabs: a header, then one row per chart
        area, parents = grid, ["ROOT_ID", grid]
        if _HEADER not in out:
            out[_HEADER] = {"type": "HEADER", "id": _HEADER, "children": [], "parents": parents,
                            "meta": {"text": HEADER_TEXT, "headerSize": "MEDIUM_HEADER",
                                     "background": "BACKGROUND_TRANSPARENT"}}
            out[grid] = {**out[grid], "children": [*out[grid]["children"], _HEADER]}
    else:
        # a dashboard with tabs: a tab of its own
        area, parents = _TAB, ["ROOT_ID", tabs, _TAB]
        if _TAB not in out:
            out[_TAB] = {"type": "TAB", "id": _TAB, "children": [], "parents": ["ROOT_ID", tabs],
                         "meta": {"text": HEADER_TEXT, "defaultText": "Tab title", "placeholder": "Tab title"}}
            out[tabs] = {**out[tabs], "children": [*out[tabs]["children"], _TAB]}
    row = f"ROW-aisc-assistant-{chart_uuid[:8]}"
    out[row] = {"type": "ROW", "id": row, "children": [node], "parents": parents,
                "meta": {"background": "BACKGROUND_TRANSPARENT"}}
    out[node] = {"type": "CHART", "id": node, "children": [], "parents": parents + [row], "meta": meta}
    if row not in out[area]["children"]:
        out[area] = {**out[area], "children": [*out[area]["children"], row]}
    return out


# ── every plot by its definition, and the changes the assistant makes in place ──

_VIZ_OF_KIND = {"bar": "echarts_timeseries_bar", "line": "echarts_timeseries_line"}
_CHANGES = {"title", "kind", "axis_min", "axis_max", "percent"}


def _filter_text(f: dict) -> str:
    if f.get("expressionType") == "SQL":
        return str(f.get("sqlExpression") or "")
    value = f.get("comparator")
    value = ", ".join(map(str, value)) if isinstance(value, list) else value
    return f"{f.get('subject')} {f.get('operator')} {value}"


def _metric_text(m) -> str:
    if isinstance(m, str):
        return m
    if m.get("expressionType") == "SQL":
        return str(m.get("sqlExpression") or m.get("label") or "")
    return f"{m.get('aggregate')}({(m.get('column') or {}).get('column_name')})"


def plot_definition(viz_type: str, params: dict) -> dict:
    """What a plot shows, as the assistant is told: its kind, axes or x axis, series, value, filters and scale.
    Read from the chart's settings only: never a value of its results."""
    kind = kind_of(viz_type)
    filters = [_filter_text(f) for f in params.get("adhoc_filters") or []]
    metrics = params.get("metrics") or []
    if kind == "radar":
        maxima = {(c or {}).get("radarMetricMaxValue") for c in (params.get("column_config") or {}).values()}
        value = _metric_text(metrics[0]) + (", one such per axis" if len(metrics) > 1 else "") if metrics else ""
        return {"kind": kind, "axes": [m.get("label") if isinstance(m, dict) else m for m in metrics],
                "series": list(params.get("groupby") or []), "value": value, "filters": filters,
                "axis_max": maxima.pop() if len(maxima) == 1 else None,
                "percent": "%" in str(params.get("number_format") or "")}
    if kind in ("bar", "line"):
        low, high = (list(params.get("y_axis_bounds") or []) + [None, None])[:2]
        return {"kind": kind, "x": params.get("x_axis"), "series": list(params.get("groupby") or []),
                "value": ", ".join(_metric_text(m) for m in metrics), "filters": filters,
                "axis_min": low, "axis_max": high, "percent": "%" in str(params.get("y_axis_format") or "")}
    return {"kind": kind, "columns": list(params.get("all_columns") or params.get("groupby") or []),
            "value": ", ".join(_metric_text(m) for m in metrics), "filters": filters}


def changed_params(viz_type: str, params: dict, changes: dict) -> tuple[str, dict]:
    """A plot's settings with the assistant's changes made (a new copy): kind between bar and line, the axis's
    minimum and maximum, percentages. The title is the chart's name, set by the caller. ValueError for a change this
    plot cannot take: anything that would need a different query is a new chart (propose_chart)."""
    unknown = set(changes) - _CHANGES
    if unknown:
        raise ValueError(f"cannot change {', '.join(sorted(unknown))}")
    kind = kind_of(viz_type)
    out = json.loads(json.dumps(params))
    for key in ("axis_min", "axis_max"):
        if key in changes and changes[key] is not None and (isinstance(changes[key], bool)
                                                            or not isinstance(changes[key], (int, float))):
            raise ValueError(f"{key} must be a number")
    if kind not in ("radar", "bar", "line") and set(changes) - {"title"}:
        raise ValueError(f"a {kind} has no axis or kind to change")
    if "kind" in changes and changes["kind"] != kind:
        if kind not in _VIZ_OF_KIND or changes["kind"] not in _VIZ_OF_KIND:
            raise ValueError(f"a {kind} cannot become a {changes['kind']} in place: it needs a new chart")
        viz_type = _VIZ_OF_KIND[changes["kind"]]
        out["viz_type"] = viz_type
        kind = changes["kind"]
    if kind == "radar":
        if changes.get("axis_min") is not None:
            raise ValueError("a radar's axes start at its centre: no minimum")
        if "axis_max" in changes:
            labels = [m.get("label") if isinstance(m, dict) else m for m in out.get("metrics") or []]
            config = out.get("column_config") or {}
            out["column_config"] = {**config, **{label: {**(config.get(label) or {}),
                                                         "radarMetricMaxValue": changes["axis_max"]}
                                                 for label in labels}}
        if "percent" in changes:
            out["number_format"] = ".0%" if changes["percent"] else "SMART_NUMBER"
    elif kind in ("bar", "line"):
        if "axis_min" in changes or "axis_max" in changes:
            low, high = (list(out.get("y_axis_bounds") or []) + [None, None])[:2]
            out["y_axis_bounds"] = [changes.get("axis_min", low), changes.get("axis_max", high)]
        if "percent" in changes:
            out["y_axis_format"] = ".0%" if changes["percent"] else "SMART_NUMBER"
    return viz_type, out
