# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""What the dashboard tells the chart assistant about a project, and how a validated proposal becomes a chart.

The description holds the project's targets (their real labels), its metrics and their dimension keys, and the real
values of a key when it is a short label (at most MAX_LABELS values, at most MAX_LABEL_LENGTH characters on average):
these travel as they are to the project's chosen model and into its mock database. Free text such as prompts or
answers never goes to the model (D2). No count of rows. Pure: no Superset import."""
from __future__ import annotations

import base64
import decimal
import hashlib
import hmac
import json
import math
import re
import uuid

from aisc_ext import charts
from aisc_ext.charts import quoted_name

#: the targets that have results: what was tested, as the person names it (a target with none would be a series of
#: invented values in every preview)
TARGETS_SQL = """
SELECT DISTINCT t.label
  FROM target.target t
  JOIN engine.aisc_backend_aicomponent tc ON tc.pid = t.engine_component
  JOIN engine.aisc_backend_evaluationinput ti ON ti.component_id = tc.id AND ti.name = 'target'
  JOIN engine.aisc_backend_observation o ON o.evaluation_plugin_id = ti.evaluation_plugin_id
 WHERE t.label IS NOT NULL
   AND EXISTS (SELECT 1 FROM engine.aisc_backend_measurement m WHERE m.observation_id = o.id)
 ORDER BY 1"""

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


#: how long a person has to confirm or undo an act of the assistant, in seconds
TOKEN_MAX_AGE = 900


def sign(payload: dict, key: str, *, now: float) -> str:
    """A token holding `payload`, signed with `key`: the panel keeps it and sends it back to confirm or undo an act,
    so nothing waits on the server meanwhile."""
    body = base64.urlsafe_b64encode(json.dumps({"at": now, "payload": payload}, sort_keys=True).encode()).decode()
    return body + "." + hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()


def read_signed(token: str, key: str, *, now: float, max_age: int = TOKEN_MAX_AGE) -> dict | None:
    """The payload of a token this dashboard signed less than `max_age` seconds ago; None for anything else."""
    body, _, mac = str(token or "").rpartition(".")
    if not body or not hmac.compare_digest(mac, hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        held = json.loads(base64.urlsafe_b64decode(body.encode()))
    except ValueError:
        return None
    if not isinstance(held, dict) or not isinstance(held.get("at"), (int, float)) or now - held["at"] > max_age:
        return None
    return held.get("payload")


def _value(value) -> str:
    return f'"{value}"' if isinstance(value, str) else str(value)


#: how each change is said, in the order a confirmation names them
_SAID = (("title", lambda v: f'title to "{v}"'), ("percent", lambda v: "percentages on" if v else "percentages off"),
         ("axis_min", lambda v: f"axis minimum to {v}"), ("axis_max", lambda v: f"axis maximum to {v}"),
         ("kind", lambda v: f"kind to {v}"))


def confirmation(answer: dict, plots: list[dict]) -> dict | None:
    """What a person confirms before the assistant's change or removal is made: the act and a sentence naming it.
    None when a plot it names is not on the dashboard."""
    titles = {p["id"]: p["title"] for p in plots}
    if "change" in answer:
        found = to_change(answer["change"], plots)
        if found is None:
            return None
        chart, changes = found
        said = ", ".join(say(changes[k]) for k, say in _SAID if k in changes)
        return {"kind": "change", "chart": chart, "changes": changes, "text": f'Change "{titles[chart]}": {said}?'}
    removed = to_remove(answer.get("remove"), plots)
    if removed is None:
        return None
    names = ", ".join(f'"{title}"' for _, title in removed)
    return {"kind": "remove", "charts": [chart for chart, _ in removed],
            "text": f"Remove {names} from this dashboard? The charts stay in Superset."}


def _said_number(value) -> str:
    """Whole numbers as they are; others with three significant digits, large ones rounded whole (never 1.23e+04)."""
    number = float(value)
    if number.is_integer() or abs(number) >= 1000:
        return str(round(number))
    return format(number, ".3g")


def _is_number(value) -> bool:
    return isinstance(value, (int, float, decimal.Decimal)) and not isinstance(value, bool) and \
        math.isfinite(float(value))


def result_sentence(chart: dict, columns: list[str], rows: list) -> str:
    """One sentence about a validated chart's result on the real data, written by code from the rows (the model has no
    part in it, R2): the highest and the lowest value with the category (and series) they belong to."""
    if not rows:
        return "The query returns no rows on your data."
    at = {name: i for i, name in enumerate(columns)}
    value = at.get(chart.get("value"))
    places = [at[chart[key]] for key in ("category", "series") if chart.get(key) in at]
    found = [(float(row[value]), row) for row in rows if value is not None and _is_number(row[value])]
    if not found:
        return "No value to compare."

    def said(entry):
        number, row = entry
        return f"{', '.join(str(row[i]) for i in places)} ({_said_number(row[value])})"
    if len(found) == 1:
        return f"One value: {said(found[0])}."
    highest = max(found, key=lambda entry: entry[0])
    lowest = min(found, key=lambda entry: entry[0])
    return f"Highest: {said(highest)}. Lowest: {said(lowest)}."


#: the rows of a validated chart's result the panel shows
RESULT_ROWS = 50


def _json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def validated_result(read, sql: str, chart: dict) -> dict:
    """The real result of a validated chart, for the person's browser only (R1: never sent to the assistant): its first
    rows and a sentence about them. read(sql) -> (columns, rows) on the project's data. A failure to read them never
    undoes the chart: the answer then says so and holds no result."""
    try:
        columns, rows = read(f"SELECT * FROM ({sql}) AS validated LIMIT {RESULT_ROWS + 1}")
    except Exception:                                       # noqa: BLE001 - the chart is made; only its values are missing
        return {"sentence": "The chart was made; its values could not be read here."}
    shown = [[_json_value(v) for v in row] for row in rows[:RESULT_ROWS]]
    return {"result": {"columns": list(columns), "rows": shown, "more": len(rows) > RESULT_ROWS},
            "sentence": result_sentence(chart, list(columns), rows[:RESULT_ROWS])}
