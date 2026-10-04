# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""A plugin's default charts, as a Superset export bundle (plugin dashboards 2026-10-04).

A plugin declares its default charts in its contract (aisc-plugin-interface MetricVisualization, returned by
its get_metric_visualizations): a chart type, metrics, a title, filters and grouping by dimensions. This module
is the only one that knows Superset's chart and dashboard formats. It turns those charts into the bundle that
Superset's own import takes (the ZIP of YAML its Export makes), so a Superset upgrade touches this file only,
and the upgrade check (aisc scripts/check-superset-upgrade.sh) says before an upgrade whether it still holds.

What the import needs (02-p0-findings.md): the project's connection and dataset, named by their uuids (Superset
never overwrites them on import, so their settings and the connection's password stay as the bridge made them),
and a chartId placeholder next to each chart's uuid in the layout.

Pure Python: no Superset import, so it is tested without the app."""
from __future__ import annotations

import json
import uuid

import yaml

#: the dataset's saved metric the Run filter sorts by, so the newest run comes first ("Run 10" sorts
#: before "Run 9" as text)
LATEST_RUN_METRIC = "latest_run"
#: Superset's chart type per MetricVisualization chart type; the rest are drawn as tables (and say so)
_KINDS = {"bars": "echarts_timeseries_bar", "line": "echarts_timeseries_line", "table": "table", "pie": "pie"}
_NAMESPACE = uuid.UUID("6f2a7c1e-4b3d-4e8a-9c5f-0d1e2f3a4b5c")
_VERSION = "1.0.0"
_TIMESTAMP = "2026-10-04T00:00:00+00:00"


def _value(name):
    return getattr(name, "value", name)          # a ChartType enum or its string


def default_title(v: dict) -> str:
    return "Default · " + (v.get("title") or ", ".join(v.get("metrics") or []) or "Chart")


def _score(aggregate: str) -> dict:
    return {"expressionType": "SIMPLE", "aggregate": aggregate, "label": "score", "column": {"column_name": "score"}}


def _filter(subject, operator, comparator) -> dict:
    return {"expressionType": "SIMPLE", "subject": subject, "operator": operator, "comparator": comparator,
            "clause": "WHERE"}


def chart_settings(v: dict, *, plugin_label: str, columns) -> tuple[str, dict, str]:
    """(Superset chart type, its settings, its description) for one MetricVisualization (as a dict)."""
    known = set(columns)
    kind = _value(v.get("chart_type"))
    metrics = list(v.get("metrics") or [])
    groups = [d for d in (v.get("group_by_dimensions") or []) if d in known]
    label = v.get("metric_label_dimension")
    label = label if label in known else None
    dropped = [d for d in (v.get("group_by_dimensions") or []) if d not in known]
    dropped += [d for d in (v.get("filter_dimensions") or {}) if d not in known]
    if v.get("metric_label_dimension") and not label:
        dropped.append(v["metric_label_dimension"])

    filters = [_filter("tool", "==", plugin_label), _filter("metric", "IN", metrics)]
    filters += [_filter(d, "IN", list(values)) for d, values in (v.get("filter_dimensions") or {}).items() if d in known]

    viz_type = _KINDS.get(kind, "table")
    if viz_type == "echarts_timeseries_bar":
        x_axis = groups[0] if groups else "metric"
        series = label or ("metric" if x_axis != "metric" else None)
        params = {"x_axis": x_axis, "metrics": [_score("AVG")], "groupby": [g for g in (series, "run") if g]}
    elif viz_type == "echarts_timeseries_line":
        params = {"x_axis": "run_order", "metrics": [_score("AVG")], "groupby": [label or "metric"]}
    elif viz_type == "pie":
        params = {"metric": _score("SUM"), "groupby": [label or "metric"]}
    else:
        params = {"query_mode": "aggregate", "groupby": ["run"] + groups + ["metric"], "metrics": [_score("AVG")],
                  "all_columns": [], "percent_metrics": []}
    params.update({"viz_type": viz_type, "adhoc_filters": filters, "row_limit": 1000})

    notes = [f"Made by the {plugin_label} plugin. Use Save as to change it."]
    if v.get("description"):
        notes.append(v["description"])
    if viz_type == "table" and kind not in ("table", None):
        notes.append(f"Drawn as a table (asked for: {kind}).")
    if dropped:
        notes.append("Not in the results data, so left out: " + ", ".join(sorted(set(dropped))) + ".")
    return viz_type, params, " ".join(notes)


def plugin_slug(pid: str, plugin: str) -> str:
    """The dashboard of one plugin in one project: aisc-<project hex>-<plugin>, in URL-safe lower case."""
    name = "".join(ch if ch.isalnum() else "-" for ch in plugin.lower()).strip("-")
    while "--" in name:
        name = name.replace("--", "-")
    return f"aisc-{str(pid).replace('-', '')}-{name}"[:255]


def chart_uuid(pid: str, plugin: str, index: int, title: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"chart:{pid}:{plugin}:{index}:{title}"))


def starter_uuid(pid: str, plugin: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"starter:{pid}:{plugin}"))


def dashboard_uuid(pid: str, plugin: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"dashboard:{pid}:{plugin}"))


def dataset_metrics() -> list[dict]:
    """The saved metrics the project's results dataset carries (the bridge writes them with the dataset)."""
    return [{"metric_name": LATEST_RUN_METRIC, "expression": "MAX(run_order)"}]


def _dump(obj) -> str:
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)


def _source_files(*, dataset_uuid, dataset_name, database_uuid, database_name, sqlalchemy_uri, columns) -> dict:
    """The connection and the dataset, by their uuids. Superset imports both with overwrite=False whatever
    the command says (v1/__init__.py), so these only have to pass its schema: what is stored stays."""
    db_file = "".join(ch if ch.isalnum() else "_" for ch in database_name)
    return {
        f"databases/{db_file}.yaml": _dump({
            "database_name": database_name, "sqlalchemy_uri": sqlalchemy_uri, "uuid": database_uuid,
            "version": _VERSION, "cache_timeout": None, "expose_in_sqllab": False, "allow_run_async": False,
            "allow_ctas": False, "allow_cvas": False, "allow_dml": False, "allow_file_upload": False,
            "extra": {}}),
        f"datasets/{db_file}/{dataset_name}.yaml": _dump({
            "table_name": dataset_name, "main_dttm_col": None, "description": None, "default_endpoint": None,
            "offset": 0, "cache_timeout": None, "schema": None, "sql": None, "params": None,
            "template_params": None, "filter_select_enabled": True, "fetch_values_predicate": None,
            "extra": None, "uuid": dataset_uuid, "database_uuid": database_uuid, "version": _VERSION,
            "metrics": [{"metric_name": m["metric_name"], "verbose_name": None, "metric_type": None,
                         "expression": m["expression"], "description": None, "d3format": None, "extra": {},
                         "warning_text": None} for m in dataset_metrics()],
            "columns": [{"column_name": c, "verbose_name": None, "is_dttm": False, "is_active": True,
                         "type": None, "groupby": True, "filterable": True, "expression": None,
                         "description": None, "python_date_format": None, "extra": {}} for c in columns]}),
    }


def _chart_file(*, chart_id, name, viz_type, params, description, dataset_uuid) -> str:
    return _dump({"slice_name": name, "description": description, "certified_by": None,
                  "certification_details": None, "viz_type": viz_type, "params": params, "query_context": None,
                  "cache_timeout": None, "uuid": chart_id, "version": _VERSION, "dataset_uuid": dataset_uuid})


def _markdown(node_id, code, parents) -> dict:
    return {"type": "MARKDOWN", "id": node_id, "children": [], "parents": parents,
            "meta": {"width": 12, "height": 18, "code": code}}


def _header(node_id, text, parents) -> dict:
    return {"type": "HEADER", "id": node_id, "children": [], "parents": parents,
            "meta": {"text": text, "headerSize": "MEDIUM_HEADER", "background": "BACKGROUND_TRANSPARENT"}}


YOUR_CHARTS = "Your charts"


def layout(*, label, version, placed, starter_chart_id, user_part) -> dict:
    """The dashboard layout: "Default charts · <plugin> <version>", the defaults in rows of two, "Your
    charts", the starter link (or, before any run, how to get results), then whatever people placed there
    (user_part: their layout nodes, kept as they were)."""
    grid = ["ROOT_ID", "GRID_ID"]
    pos = {"DASHBOARD_VERSION_KEY": "v2",
           "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
           "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": label}}}
    children = pos["GRID_ID"]["children"]

    def add(node):
        pos[node["id"]] = node
        children.append(node["id"])

    add(_header("HEADER-aisc-defaults", f"Default charts · {label} {version}".rstrip(), grid))
    if placed:
        for r, start in enumerate(range(0, len(placed), 2)):
            row_id = f"ROW-aisc-defaults-{r}"
            row = {"type": "ROW", "id": row_id, "children": [], "parents": grid,
                   "meta": {"background": "BACKGROUND_TRANSPARENT"}}
            add(row)
            for chart_id, name in placed[start:start + 2]:
                node_id = f"CHART-aisc-{chart_id[:8]}"
                row["children"].append(node_id)
                pos[node_id] = {"type": "CHART", "id": node_id, "children": [], "parents": grid + [row_id],
                                "meta": {"chartId": 0, "uuid": chart_id, "width": 6, "height": 50,
                                         "sliceName": name}}
    else:
        add(_markdown("MARKDOWN-aisc-no-results",
                      f"**No results yet.** Run {label} in the engine: its default charts appear here after "
                      f"its first run.", grid))
    add(_header("HEADER-aisc-yours", YOUR_CHARTS, grid))
    if starter_chart_id is not None:
        add(_markdown("MARKDOWN-aisc-starter",
                      f"**[+ Build a chart of your own](/explore/?slice_id={starter_chart_id})**  \n"
                      f"Opens the chart builder on this project's {label} results. Save it under a new name "
                      f"and add it to this dashboard: it goes here, and AISC never changes it.", grid))
    for node_id, node in (user_part or {}).items():
        node = dict(node)
        top = node_id not in {c for n in (user_part or {}).values() for c in n.get("children", [])}
        node["parents"] = grid if top else node.get("parents") or grid
        pos[node_id] = node
        if top:
            children.append(node_id)
    for i, (chart_id, _name) in enumerate(placed):
        pos[f"CHART-aisc-{chart_id[:8]}"]["meta"]["chartId"] = i + 1      # a placeholder: import remaps it
    return pos


def native_filters(dataset_uuid: str, latest_run: str | None = None) -> list[dict]:
    """Run (the latest preselected, several to compare) and Target, on every plugin dashboard.

    Superset 4.1.1 selects a "first value by default" without applying it, so the charts would show every run
    until someone pressed Apply (checked 2026-10-05). The latest run is therefore written as the filter's
    default value, which Superset applies on load; each sync brings the latest run, so it stays current. Before
    any run there is none to name, and the first value is preselected instead."""
    def select(fid, name, column, **control):
        return {"id": fid, "name": name, "filterType": "filter_select", "type": "NATIVE_FILTER",
                "targets": [{"datasetUuid": dataset_uuid, "column": {"name": column}}],
                "controlValues": {"multiSelect": True, "enableEmptyFilter": False, "inverseSelection": False,
                                  "searchAllOptions": False, **control},
                "defaultDataMask": {"filterState": {}, "extraFormData": {}, "ownState": {}},
                "cascadeParentIds": [], "scope": {"rootPath": ["ROOT_ID"], "excluded": []}}
    run = select("NATIVE_FILTER-run", "Run", "run", defaultToFirstItem=latest_run is None, sortAscending=False)
    run["sortMetric"] = LATEST_RUN_METRIC
    if latest_run is not None:
        run["defaultDataMask"] = {"filterState": {"value": [latest_run]},
                                  "extraFormData": {"filters": [{"col": "run", "op": "IN", "val": [latest_run]}]},
                                  "ownState": {}}
    return [run, select("NATIVE_FILTER-target", "Target", "target_label")]


def bundle(*, pid, project_name, plugin, label, version, visualizations, dataset_uuid, dataset_name,
           database_uuid, database_name, sqlalchemy_uri, columns, starter_chart_id, user_part=None,
           latest_run=None) -> dict:
    """The export bundle of one plugin's dashboard in one project: {path in the ZIP: YAML text}."""
    files = {"metadata.yaml": _dump({"version": _VERSION, "type": "Dashboard", "timestamp": _TIMESTAMP})}
    files.update(_source_files(dataset_uuid=dataset_uuid, dataset_name=dataset_name, database_uuid=database_uuid,
                               database_name=database_name, sqlalchemy_uri=sqlalchemy_uri, columns=columns))
    placed = []
    for index, v in enumerate(visualizations):
        viz_type, params, description = chart_settings(v, plugin_label=label, columns=columns)
        cid = chart_uuid(pid, plugin, index, v.get("title") or "")
        params.update({"aisc_project": pid, "aisc_plugin": plugin, "aisc_chart_id": cid})
        name = default_title(v)
        files[f"charts/{cid}.yaml"] = _chart_file(chart_id=cid, name=name, viz_type=viz_type, params=params,
                                                  description=description, dataset_uuid=dataset_uuid)
        placed.append((cid, name))
    files[f"dashboards/{dashboard_uuid(pid, plugin)}.yaml"] = _dump({
        "dashboard_title": f"{project_name} · {label}", "description": None, "css": None,
        "slug": plugin_slug(pid, plugin), "certified_by": None, "certification_details": None, "published": True,
        "uuid": dashboard_uuid(pid, plugin), "version": _VERSION,
        "position": layout(label=label, version=version, placed=placed,
                           starter_chart_id=starter_chart_id if placed else None, user_part=user_part),
        "metadata": {"native_filter_configuration": native_filters(dataset_uuid, latest_run), "color_scheme": "",
                     "aisc_project": pid, "aisc_plugin": plugin, "aisc_version": version,
                     "aisc_charts": [cid for cid, _ in placed]}})
    return files


def starter_bundle(*, pid, plugin, label, dataset_uuid, dataset_name, database_uuid, database_name,
                   sqlalchemy_uri, columns) -> dict:
    """The starter chart of one plugin's dashboard: a table of its results, kept off the dashboard, which the
    "+ Build a chart of your own" link opens. Save as makes the user's own chart: no aisc_chart_id, so AISC
    never touches it."""
    files = {"metadata.yaml": _dump({"version": _VERSION, "type": "Slice", "timestamp": _TIMESTAMP})}
    files.update(_source_files(dataset_uuid=dataset_uuid, dataset_name=dataset_name, database_uuid=database_uuid,
                               database_name=database_name, sqlalchemy_uri=sqlalchemy_uri, columns=columns))
    params = {"viz_type": "table", "query_mode": "raw",
              "all_columns": [c for c in ("run", "target_label", "metric", "feature", "concern", "score", "statistic",
                                          "p_value", "flag") if c in set(columns)],
              "adhoc_filters": [_filter("tool", "==", label)], "row_limit": 1000, "aisc_starter": plugin}
    cid = starter_uuid(pid, plugin)
    files[f"charts/{cid}.yaml"] = _chart_file(
        chart_id=cid, name=f"New chart · {label}", viz_type="table", params=params, dataset_uuid=dataset_uuid,
        description=f"A starting point on this project's {label} results. Change it, then Save as a new chart.")
    return files


def to_json(position: dict) -> str:
    return json.dumps(position)
