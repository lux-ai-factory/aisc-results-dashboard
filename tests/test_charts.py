# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The translator from a plugin's default charts to Superset (plugin dashboards 2026-10-04, T3).

A plugin declares its default charts as MetricVisualization (aisc-plugin-interface): a chart type, its
metrics, a title, filters and grouping by dimensions. aisc_ext/charts.py, the only module that knows
Superset's chart and dashboard formats, turns them into an export bundle that Superset's own import takes
(P0, 02-p0-findings.md). Pure Python: no Superset here."""
import importlib
import json
import uuid

import pytest
import yaml

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
DATASET_UUID = "aaaaaaaa-0000-4000-8000-000000000001"
DATABASE_UUID = "bbbbbbbb-0000-4000-8000-000000000001"
COLUMNS = ["pid", "score", "metric", "evaluated_at", "target_label", "tool", "run", "run_order", "feature",
           "concern", "flag", "statistic", "p_value"]


@pytest.fixture
def charts():
    return importlib.import_module("aisc_ext.charts")


def viz(chart_type, metrics, **kw):
    return {"chart_type": chart_type, "metrics": metrics, **kw}


DRIFT = [viz("bars", ["Drift Score"], title="Drift Score"),
         viz("bars", ["psi"], title="PSI per feature", group_by_dimensions=["feature"]),
         viz("table", ["psi", "smd"], title="Drift tests per feature", group_by_dimensions=["feature"])]


def settings(charts, v, label="Data Drift"):
    return charts.chart_settings(v, plugin_label=label, columns=COLUMNS)


def filters_of(params):
    return {(f["subject"], f["operator"]): f["comparator"] for f in params["adhoc_filters"]}


# ── T3.1 each kind ───────────────────────────────────────────────────────────

def test_t3_1_bars_are_echarts_bars_along_the_grouping_with_a_series_per_metric_and_run(charts):
    viz_type, params, _ = settings(charts, DRIFT[1])
    assert viz_type == "echarts_timeseries_bar"
    assert params["x_axis"] == "feature" and params["groupby"] == ["metric", "run"]
    assert params["metrics"] == [{"expressionType": "SIMPLE", "aggregate": "AVG", "label": "score",
                                  "column": {"column_name": "score"}}]


def test_t3_1_bars_with_no_grouping_go_along_the_metric(charts):
    _, params, _ = settings(charts, DRIFT[0])
    assert params["x_axis"] == "metric" and params["groupby"] == ["run"]


def test_t3_1_a_label_dimension_names_the_series(charts):
    _, params, _ = settings(charts, viz("bars", ["Bias Evaluation Results"], group_by_dimensions=["concern"],
                                        metric_label_dimension="flag"))
    assert params["groupby"] == ["flag", "run"]


def test_t3_1_lines_go_along_the_runs(charts):
    viz_type, params, _ = settings(charts, viz("line", ["Drift Score"]))
    assert viz_type == "echarts_timeseries_line" and params["x_axis"] == "run_order"
    assert params["groupby"] == ["metric"]


def test_t3_1_tables_aggregate_by_run_grouping_and_metric(charts):
    viz_type, params, _ = settings(charts, DRIFT[2])
    assert viz_type == "table" and params["query_mode"] == "aggregate"
    assert params["groupby"] == ["run", "feature", "metric"]
    assert [m["aggregate"] for m in params["metrics"]] == ["AVG"]


def test_t3_1_pies_split_by_metric_and_add_up(charts):
    viz_type, params, _ = settings(charts, viz("pie", ["Anomaly Pass", "Anomaly Low"]))
    assert viz_type == "pie" and params["groupby"] == ["metric"]
    assert params["metric"]["aggregate"] == "SUM"


@pytest.mark.parametrize("kind", ["scatter", "radar", "kde", "csv"])
def test_t3_1_kinds_superset_draws_differently_become_tables_and_say_so(charts, kind):
    viz_type, _, description = settings(charts, viz(kind, ["psi"], title="x"))
    assert viz_type == "table" and f"asked for: {kind}" in description


# ── T3.2 filters ─────────────────────────────────────────────────────────────

def test_t3_2_every_chart_keeps_to_its_plugin_and_its_metrics(charts):
    _, params, _ = settings(charts, DRIFT[2])
    f = filters_of(params)
    assert f[("tool", "==")] == "Data Drift" and f[("metric", "IN")] == ["psi", "smd"]


def test_t3_2_filter_dimensions_become_in_filters(charts):
    _, params, _ = settings(charts, viz("bars", ["psi"], filter_dimensions={"flag": ["yes"]}))
    assert filters_of(params)[("flag", "IN")] == ["yes"]


# ── T3.3 the default mark ────────────────────────────────────────────────────

def test_t3_3_titles_and_descriptions_say_default(charts):
    title, description = charts.default_title(DRIFT[1]), settings(charts, DRIFT[1])[2]
    assert title == "Default · PSI per feature"
    assert description.startswith("Made by the Data Drift plugin. Use Save as to change it.")
    assert charts.default_title(viz("bars", ["Drift Score", "psi"])) == "Default · Drift Score, psi"


# ── T3.7 an unknown dimension ────────────────────────────────────────────────

def test_t3_7_an_undeclared_dimension_is_dropped_and_said(charts):
    _, params, description = settings(charts, viz("bars", ["psi"], group_by_dimensions=["segment"],
                                                  filter_dimensions={"region": ["EU"]}))
    assert params["x_axis"] == "metric"
    assert ("region", "IN") not in filters_of(params)
    assert "segment" in description and "region" in description


# ── T3.4 to T3.6 the bundle ──────────────────────────────────────────────────

def make_bundle(charts, visualizations=DRIFT, user_part=None, latest_run="Run 2 · 04 Oct 2026, 20:39"):
    return charts.bundle(pid=PID, project_name="mcas", plugin="data-monitor::DataDriftPlugin", label="Data Drift",
                         version="0.4.1", visualizations=visualizations, dataset_uuid=DATASET_UUID,
                         dataset_name="engine_results_x", database_uuid=DATABASE_UUID, database_name="AISC mcas",
                         sqlalchemy_uri="postgresql+psycopg2://dashboard_ro:XXXXXXXXXX@postgres:5432/project_x",
                         columns=COLUMNS, starter_chart_id=42, user_part=user_part, latest_run=latest_run)


def test_t3_4_the_bundle_holds_what_the_import_needs(charts):
    files = make_bundle(charts)
    assert yaml.safe_load(files["metadata.yaml"])["type"] == "Dashboard"
    db = [k for k in files if k.startswith("databases/")]
    ds = [k for k in files if k.startswith("datasets/")]
    assert len(db) == 1 and yaml.safe_load(files[db[0]])["uuid"] == DATABASE_UUID
    assert len(ds) == 1 and yaml.safe_load(files[ds[0]])["uuid"] == DATASET_UUID
    chart_files = sorted(k for k in files if k.startswith("charts/"))
    assert len(chart_files) == 3
    for k in chart_files:
        c = yaml.safe_load(files[k])
        assert c["dataset_uuid"] == DATASET_UUID and c["slice_name"].startswith("Default · ")
        assert c["params"]["aisc_chart_id"] and c["params"]["aisc_plugin"] == "data-monitor::DataDriftPlugin"
    dash = yaml.safe_load(files[next(k for k in files if k.startswith("dashboards/"))])
    assert dash["slug"] == charts.plugin_slug(PID, "data-monitor::DataDriftPlugin")
    assert dash["dashboard_title"] == "mcas · Data Drift"
    placed = [v for v in dash["position"].values() if isinstance(v, dict) and v.get("type") == "CHART"]
    assert len(placed) == 3 and all("chartId" in p["meta"] and "uuid" in p["meta"] for p in placed)


def test_t3_4_chart_uuids_are_stable_and_differ_by_project_plugin_and_chart(charts):
    a, b = make_bundle(charts), make_bundle(charts)
    assert sorted(k for k in a if k.startswith("charts/")) == sorted(k for k in b if k.startswith("charts/"))
    u = charts.chart_uuid(PID, "p::A", 0, "x")
    assert u == str(uuid.UUID(u)) and u != charts.chart_uuid(PID, "p::B", 0, "x") != charts.chart_uuid(PID, "p::A", 1, "x")


def test_t3_5_the_layout_has_defaults_then_your_charts_with_the_starter_link(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts).items() if k.startswith("dashboards/")))
    pos = dash["position"]
    order = []
    for child in pos["GRID_ID"]["children"]:
        node = pos[child]
        order.append(node["type"])
    assert order[0] == "HEADER" and pos[pos["GRID_ID"]["children"][0]]["meta"]["text"] == "Default charts · Data Drift 0.4.1"
    assert order.count("ROW") >= 2 and "MARKDOWN" in order
    headers = [pos[c]["meta"]["text"] for c in pos["GRID_ID"]["children"] if pos[c]["type"] == "HEADER"]
    assert headers == ["Default charts · Data Drift 0.4.1", "Your charts"]
    md = next(pos[c] for c in pos["GRID_ID"]["children"] if pos[c]["type"] == "MARKDOWN")
    assert "/explore/?slice_id=42" in md["meta"]["code"] and "Build a chart of your own" in md["meta"]["code"]
    # rows of two defaults
    rows = [pos[c] for c in pos["GRID_ID"]["children"] if pos[c]["type"] == "ROW"]
    assert [len(r["children"]) for r in rows] == [2, 1]


def test_t3_5_with_no_results_yet_the_tile_says_to_run_the_test(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, visualizations=[]).items() if k.startswith("dashboards/")))
    md = [v for v in dash["position"].values() if isinstance(v, dict) and v.get("type") == "MARKDOWN"]
    assert any("No results yet" in m["meta"]["code"] and "Data Drift" in m["meta"]["code"] for m in md)
    assert not any("slice_id" in m["meta"]["code"] for m in md)


def test_t3_5_the_users_part_of_the_layout_is_kept_after_your_charts(charts):
    user_part = {"CHART-mine": {"type": "CHART", "id": "CHART-mine", "children": [], "meta": {"chartId": 7,
                 "uuid": "cccccccc-0000-4000-8000-000000000001", "width": 4, "height": 50}}}
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, user_part=user_part).items() if k.startswith("dashboards/")))
    pos = dash["position"]
    grid = pos["GRID_ID"]["children"]
    assert grid[-1] == "CHART-mine" and grid.index("CHART-mine") > grid.index(
        next(c for c in grid if pos[c]["type"] == "HEADER" and pos[c]["meta"]["text"] == "Your charts"))
    assert pos["CHART-mine"]["parents"] == ["ROOT_ID", "GRID_ID"]


def test_t3_6_the_run_and_target_filters(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts).items() if k.startswith("dashboards/")))
    nf = {f["name"]: f for f in dash["metadata"]["native_filter_configuration"]}
    run, target = nf["Run"], nf["Target"]
    assert run["targets"] == [{"datasetUuid": DATASET_UUID, "column": {"name": "run"}}]
    assert run["controlValues"]["multiSelect"] and run["controlValues"]["sortAscending"] is False
    assert run["sortMetric"] == charts.LATEST_RUN_METRIC
    # Superset 4.1.1 selects a "first value by default" without applying it (P0+, 2026-10-05): the latest
    # run is written as the filter's default instead, which it applies on load
    assert run["controlValues"]["defaultToFirstItem"] is False
    assert run["defaultDataMask"]["filterState"]["value"] == ["Run 2 · 04 Oct 2026, 20:39"]
    assert run["defaultDataMask"]["extraFormData"]["filters"] == [
        {"col": "run", "op": "IN", "val": ["Run 2 · 04 Oct 2026, 20:39"]}]
    assert target["targets"][0]["column"]["name"] == "target_label"
    assert dash["metadata"]["aisc_plugin"] == "data-monitor::DataDriftPlugin" and dash["metadata"]["aisc_project"] == PID


def test_t3_6_the_dataset_carries_the_latest_run_metric(charts):
    assert charts.dataset_metrics() == [{"metric_name": charts.LATEST_RUN_METRIC, "expression": "MAX(run_order)"}]


def test_the_starter_chart_bundle(charts):
    files = charts.starter_bundle(pid=PID, plugin="data-monitor::DataDriftPlugin", label="Data Drift",
                                  dataset_uuid=DATASET_UUID, dataset_name="engine_results_x",
                                  database_uuid=DATABASE_UUID, database_name="AISC mcas",
                                  sqlalchemy_uri="postgresql+psycopg2://dashboard_ro:XXXXXXXXXX@postgres:5432/project_x",
                                  columns=COLUMNS)
    assert yaml.safe_load(files["metadata.yaml"])["type"] == "Slice"
    (chart,) = [yaml.safe_load(v) for k, v in files.items() if k.startswith("charts/")]
    assert chart["slice_name"] == "New chart · Data Drift"
    assert chart["uuid"] == charts.starter_uuid(PID, "data-monitor::DataDriftPlugin")
    assert ("tool", "==") in filters_of(chart["params"])
    assert "aisc_chart_id" not in chart["params"]           # Save as gives the user a chart AISC never touches


def test_t3_6_before_any_run_the_run_filter_falls_back_to_the_first_value(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, latest_run=None).items() if k.startswith("dashboards/")))
    run = next(f for f in dash["metadata"]["native_filter_configuration"] if f["name"] == "Run")
    assert run["controlValues"]["defaultToFirstItem"] is True and run["defaultDataMask"]["filterState"] == {}
