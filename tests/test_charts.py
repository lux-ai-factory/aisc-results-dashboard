# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The translator from a plugin's default charts to Superset.

A plugin declares its default charts as MetricVisualization (aisc-plugin-interface): a chart type, its
metrics, a title, filters and grouping by dimensions. aisc_ext/charts.py, the only module that knows
Superset's chart and dashboard formats, turns them into an export bundle that Superset's own import takes.
Pure Python: no Superset here."""
import importlib
import uuid

import pytest
import yaml

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
DATASET_UUID = "aaaaaaaa-0000-4000-8000-000000000001"
DATABASE_UUID = "bbbbbbbb-0000-4000-8000-000000000001"
COLUMNS = ["pid", "score", "metric", "evaluated_at", "target_label", "tool", "run", "run_order", "feature",
           "concern", "flag", "statistic", "p_value", "prompt", "response", "expected"]


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


# ── Each kind ────────────────────────────────────────────────────────────────

def test_bars_are_echarts_bars_along_the_grouping_with_a_series_per_metric_and_run(charts):
    viz_type, params, _ = settings(charts, DRIFT[1])
    assert viz_type == "echarts_timeseries_bar"
    assert params["x_axis"] == "feature" and params["groupby"] == ["metric", "run"]
    assert params["metrics"] == [{"expressionType": "SIMPLE", "aggregate": "AVG", "label": "score",
                                  "column": {"column_name": "score"}}]


def test_bars_with_no_grouping_go_along_the_metric(charts):
    _, params, _ = settings(charts, DRIFT[0])
    assert params["x_axis"] == "metric" and params["groupby"] == ["run"]


def test_a_label_dimension_names_the_series(charts):
    _, params, _ = settings(charts, viz("bars", ["Bias Evaluation Results"], group_by_dimensions=["concern"],
                                        metric_label_dimension="flag"))
    assert params["groupby"] == ["flag", "run"]


def test_lines_go_along_the_runs(charts):
    viz_type, params, _ = settings(charts, viz("line", ["Drift Score"]))
    assert viz_type == "echarts_timeseries_line" and params["x_axis"] == "run_order"
    assert params["groupby"] == ["metric"]


def test_tables_aggregate_by_run_grouping_and_metric(charts):
    viz_type, params, _ = settings(charts, DRIFT[2])
    assert viz_type == "table" and params["query_mode"] == "aggregate"
    assert params["groupby"] == ["run", "feature", "metric"]
    assert [m["aggregate"] for m in params["metrics"]] == ["AVG"]


def test_a_table_of_one_metric_needs_no_metric_column_and_names_its_value(charts):
    """LangBiTe's Failed cases: one row per answer, the value column named by the metric."""
    viz_type, params, _ = settings(charts, viz("table", ["Failed cases"], title="Failed cases",
                                               group_by_dimensions=["concern", "prompt", "response", "expected"]))
    assert viz_type == "table"
    assert params["groupby"] == ["run", "concern", "prompt", "response", "expected"]
    assert [(m["aggregate"], m["label"]) for m in params["metrics"]] == [("AVG", "Failed cases")]


def test_bars_tilt_their_labels_so_every_category_is_named(charts):
    """Five concerns side by side: without the tilt Superset (ECharts) hides every other label."""
    _, params, _ = settings(charts, viz("bars", ["Bias Evaluation Results"], group_by_dimensions=["concern"]))
    assert params["xAxisLabelRotation"] == 45


def test_a_table_shows_every_row(charts):
    """Every failed answer, not the first thousand: up to Superset's own row limit, paged in the browser."""
    _, params, _ = settings(charts, viz("table", ["Failed cases"], group_by_dimensions=["concern"]))
    assert params["row_limit"] == charts.TABLE_ROW_LIMIT == 50000
    assert params["server_pagination"] is False and params["page_length"] == 50
    assert params["include_search"] is True
    _, bars, _ = settings(charts, viz("bars", ["Drift Score"]))
    assert bars["row_limit"] == 1000


def test_pies_split_by_metric_and_add_up(charts):
    viz_type, params, _ = settings(charts, viz("pie", ["Anomaly Pass", "Anomaly Low"]))
    assert viz_type == "pie" and params["groupby"] == ["metric"]
    assert params["metric"]["aggregate"] == "SUM"


@pytest.mark.parametrize("kind", ["scatter", "radar", "kde", "csv"])
def test_kinds_superset_draws_differently_become_tables_and_say_so(charts, kind):
    viz_type, _, description = settings(charts, viz(kind, ["psi"], title="x"))
    assert viz_type == "table" and f"asked for: {kind}" in description


# ── Radars ───────────────────────────────────────────────────────────────────

CATEGORY_BARS = viz("bars", ["Jailbreak success"], title="Jailbreak success by category",
                    group_by_dimensions=["category"], value_format="percent")
RADAR_COLUMNS = COLUMNS + ["category", "language"]


def test_a_bar_chart_along_one_dimension_gets_a_radar_beside_it(charts):
    out = charts.with_radars([DRIFT[0], CATEGORY_BARS, DRIFT[2]])
    assert out[:2] == [DRIFT[0], CATEGORY_BARS] and out[3] == DRIFT[2]
    radar = out[2]
    assert radar["chart_type"] == "radar" and radar["title"] == "Jailbreak success by category (radar)"
    assert radar["metrics"] == ["Jailbreak success"] and radar["group_by_dimensions"] == ["category"]
    assert radar["value_format"] == "percent"


def test_bars_along_no_dimension_or_two_get_no_radar(charts):
    two = viz("bars", ["psi"], title="two", group_by_dimensions=["feature", "concern"])
    assert charts.with_radars([DRIFT[0], two, DRIFT[2]]) == [DRIFT[0], two, DRIFT[2]]


def test_radars_are_not_added_twice(charts):
    once = charts.with_radars([CATEGORY_BARS])
    assert charts.with_radars(once) == once


def test_the_dimensions_a_radar_needs_values_of(charts):
    assert charts.radar_dimensions(charts.with_radars([DRIFT[0], CATEGORY_BARS])) == ["category"]


def test_a_radar_has_an_axis_per_value_and_a_polygon_per_run(charts):
    radar = charts.with_radars([CATEGORY_BARS])[1]
    viz_type, params, _ = charts.chart_settings(radar, plugin_label="StrongREJECT (Mijke)", columns=RADAR_COLUMNS,
                                                values={"category": ["cv", "health"]})
    assert viz_type == "radar" and params["groupby"] == ["run"]
    assert [m["label"] for m in params["metrics"]] == ["cv", "health"]
    assert params["metrics"][0] == {"expressionType": "SQL", "label": "cv",
                                    "sqlExpression": "AVG(CASE WHEN \"category\" = 'cv' THEN \"score\" END)"}
    assert filters_of(params)[("metric", "IN")] == ["Jailbreak success"]
    assert filters_of(params)[("tool", "==")] == "StrongREJECT (Mijke)"


def test_a_percent_radar_runs_every_axis_from_0_to_100_percent(charts):
    radar = charts.with_radars([CATEGORY_BARS])[1]
    _, params, _ = charts.chart_settings(radar, plugin_label="x", columns=RADAR_COLUMNS,
                                         values={"category": ["cv", "health"]})
    assert params["column_config"] == {"cv": {"radarMetricMaxValue": 1}, "health": {"radarMetricMaxValue": 1}}
    assert params["number_format"] == charts.PERCENT


def test_a_value_with_a_quote_cannot_break_the_axis_sql(charts):
    radar = charts.with_radars([CATEGORY_BARS])[1]
    _, params, _ = charts.chart_settings(radar, plugin_label="x", columns=RADAR_COLUMNS,
                                         values={"category": ["it's"]})
    assert params["metrics"][0]["sqlExpression"] == "AVG(CASE WHEN \"category\" = 'it''s' THEN \"score\" END)"


def test_a_radar_with_no_values_yet_is_drawn_as_a_table(charts):
    radar = charts.with_radars([CATEGORY_BARS])[1]
    viz_type, _, description = charts.chart_settings(radar, plugin_label="x", columns=RADAR_COLUMNS, values={})
    assert viz_type == "table" and "asked for: radar" in description


# ── Filters ──────────────────────────────────────────────────────────────────

def test_a_percent_chart_shows_its_ratios_as_percent(charts):
    """A pass rate is a ratio from 0 to 1: unformatted, a concern that passed shows as "1".
    A chart that says value_format "percent" is formatted so, whatever its kind."""
    _, bars, _ = settings(charts, viz("bars", ["Pass rate"], group_by_dimensions=["concern"], value_format="percent"))
    _, line, _ = settings(charts, viz("line", ["Pass rate"], value_format="percent"))
    _, pie, _ = settings(charts, viz("pie", ["Pass rate"], value_format="percent"))
    _, table, _ = settings(charts, viz("table", ["Pass rate"], value_format="percent"))
    assert bars["y_axis_format"] == ".0%" and line["y_axis_format"] == ".0%"
    assert pie["number_format"] == ".0%"
    assert table["column_config"] == {"Pass rate": {"d3NumberFormat": ".0%"}}


def test_a_chart_without_a_format_keeps_supersets_own(charts):
    for kind in ("bars", "line", "pie", "table"):
        _, params, _ = settings(charts, viz(kind, ["psi"]))
        assert not {"y_axis_format", "number_format", "column_config"} & set(params), kind


def test_every_chart_keeps_to_its_plugin_and_its_metrics(charts):
    _, params, _ = settings(charts, DRIFT[2])
    f = filters_of(params)
    assert f[("tool", "==")] == "Data Drift" and f[("metric", "IN")] == ["psi", "smd"]


def test_filter_dimensions_become_in_filters(charts):
    _, params, _ = settings(charts, viz("bars", ["psi"], filter_dimensions={"flag": ["yes"]}))
    assert filters_of(params)[("flag", "IN")] == ["yes"]


# ── The default mark ─────────────────────────────────────────────────────────

def test_titles_and_descriptions_say_default(charts):
    title, description = charts.default_title(DRIFT[1]), settings(charts, DRIFT[1])[2]
    assert title == "Default · PSI per feature"
    assert description.startswith("Made by the Data Drift plugin. Use Save as to change it.")
    assert charts.default_title(viz("bars", ["Drift Score", "psi"])) == "Default · Drift Score, psi"


# ── An unknown dimension ─────────────────────────────────────────────────────

def test_an_undeclared_dimension_is_dropped_and_said(charts):
    _, params, description = settings(charts, viz("bars", ["psi"], group_by_dimensions=["segment"],
                                                  filter_dimensions={"region": ["EU"]}))
    assert params["x_axis"] == "metric"
    assert ("region", "IN") not in filters_of(params)
    assert "segment" in description and "region" in description


# ── The bundle ───────────────────────────────────────────────────────────────

LATEST = "Run 4 · 05 Oct 2026, 09:12"
LATEST_OF_V1 = "Run 2 · 04 Oct 2026, 20:39"


def make_bundle(charts, visualizations=DRIFT, user_part=None, default_version=2, default_runs=(LATEST, LATEST_OF_V1)):
    return charts.bundle(pid=PID, plugin="data-monitor::DataDriftPlugin", label="Data Drift",
                         version="0.4.1", visualizations=visualizations, dataset_uuid=DATASET_UUID,
                         dataset_name="engine_results_x", database_uuid=DATABASE_UUID, database_name="AISC mcas",
                         sqlalchemy_uri="postgresql+psycopg2://dashboard_ro:XXXXXXXXXX@postgres:5432/project_x",
                         columns=COLUMNS, starter_chart_id=42, user_part=user_part,
                         default_version=default_version, default_runs=default_runs)


def test_the_bundle_holds_what_the_import_needs(charts):
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
    assert dash["dashboard_title"] == "Data Drift"
    placed = [v for v in dash["position"].values() if isinstance(v, dict) and v.get("type") == "CHART"]
    assert len(placed) == 3 and all("chartId" in p["meta"] and "uuid" in p["meta"] for p in placed)


@pytest.mark.parametrize("plugin", ["data-monitor::DataDriftPlugin", "LangBiTe", "données::Équité", "straße",
                                    "数据", "--a__b--", "x" * 300])
def test_every_plugin_slug_is_one_the_ledger_reads_as_its_project(charts, plugin):
    """The ledger (and the platform's witness, with the same pattern) reads a dashboard's project from its
    slug, ASCII letters and digits only: a slug it cannot read is an event with no project."""
    from aisc_ext import ledger

    slug = charts.plugin_slug(PID, plugin)
    assert ledger._SLUG.match(slug), slug
    assert ledger.project_of(slug) == PID


def test_chart_uuids_are_stable_and_differ_by_project_plugin_and_chart(charts):
    a, b = make_bundle(charts), make_bundle(charts)
    assert sorted(k for k in a if k.startswith("charts/")) == sorted(k for k in b if k.startswith("charts/"))
    u = charts.chart_uuid(PID, "p::A", 0, "x")
    assert u == str(uuid.UUID(u)) and u != charts.chart_uuid(PID, "p::B", 0, "x") != charts.chart_uuid(PID, "p::A", 1, "x")


def test_the_layout_has_defaults_then_your_charts_with_the_starter_link(charts):
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


def _rows(dash):
    pos = dash["position"]
    return [[pos[c]["meta"] for c in pos[r]["children"]] for r in pos["GRID_ID"]["children"]
            if pos[r]["type"] == "ROW"]


def test_a_table_takes_a_full_row_below_and_a_lone_chart_the_full_width(charts):
    """LangBiTe: the pass rate per concern, and below it the failed cases, both full width; a
    table is taller (it lists every failed answer). Two charts that are not tables still share a row."""
    lb = [viz("bars", ["Bias Evaluation Results"], title="Pass rate per concern", group_by_dimensions=["concern"]),
          viz("table", ["Failed cases"], title="Failed cases", group_by_dimensions=["concern", "prompt"])]
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, visualizations=lb).items()
                               if k.startswith("dashboards/")))
    rows = _rows(dash)
    assert [[(m["sliceName"], m["width"], m["height"]) for m in r] for r in rows] == [
        [("Default · Pass rate per concern", 12, 50)], [("Default · Failed cases", 12, 90)]]
    drift = _rows(yaml.safe_load(next(v for k, v in make_bundle(charts).items() if k.startswith("dashboards/"))))
    assert [[(m["width"], m["height"]) for m in r] for r in drift] == [[(6, 50), (6, 50)], [(12, 90)]]


def test_with_no_results_yet_the_tile_says_to_run_the_test(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, visualizations=[], default_version=None,
                                                         default_runs=()).items()
                               if k.startswith("dashboards/")))
    md = [v for v in dash["position"].values() if isinstance(v, dict) and v.get("type") == "MARKDOWN"]
    assert any("No results yet" in m["meta"]["code"] and "Data Drift" in m["meta"]["code"] for m in md)
    assert not any("slice_id" in m["meta"]["code"] for m in md)


def test_a_run_with_no_default_charts_says_the_version_declares_none(charts):
    """Results, but a plugin version with no default charts (LangBiTe 0.2.4, for one): not "No results
    yet", and the starter link is offered."""
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, visualizations=[]).items()
                               if k.startswith("dashboards/")))
    md = [v["meta"]["code"] for v in dash["position"].values() if isinstance(v, dict) and v.get("type") == "MARKDOWN"]
    assert not any("No results yet" in m for m in md)
    assert any("Data Drift 0.4.1 declares no default charts" in m for m in md)
    assert any("/explore/?slice_id=42" in m for m in md)


def test_the_users_part_of_the_layout_is_kept_after_your_charts(charts):
    user_part = {"CHART-mine": {"type": "CHART", "id": "CHART-mine", "children": [], "meta": {"chartId": 7,
                 "uuid": "cccccccc-0000-4000-8000-000000000001", "width": 4, "height": 50}}}
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, user_part=user_part).items() if k.startswith("dashboards/")))
    pos = dash["position"]
    grid = pos["GRID_ID"]["children"]
    assert grid[-1] == "CHART-mine" and grid.index("CHART-mine") > grid.index(
        next(c for c in grid if pos[c]["type"] == "HEADER" and pos[c]["meta"]["text"] == "Your charts"))
    assert pos["CHART-mine"]["parents"] == ["ROOT_ID", "GRID_ID"]


def test_the_version_run_target_and_local_filters(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts).items() if k.startswith("dashboards/")))
    nf = {f["name"]: f for f in dash["metadata"]["native_filter_configuration"]}
    assert list(nf) == ["Version", "Run", "Target", "Local"]
    run, target = nf["Run"], nf["Target"]
    assert run["targets"] == [{"datasetUuid": DATASET_UUID, "column": {"name": "run"}}]
    assert run["controlValues"]["multiSelect"] and run["controlValues"]["sortAscending"] is False
    assert run["sortMetric"] == charts.LATEST_RUN_METRIC
    # Superset 4.1.1 selects a "first value by default" without applying it: the latest
    # run is written as the filter's default instead, which it applies on load
    assert run["controlValues"]["defaultToFirstItem"] is False
    assert run["defaultDataMask"]["filterState"]["value"] == [LATEST, LATEST_OF_V1]
    assert run["defaultDataMask"]["extraFormData"]["filters"] == [
        {"col": "run", "op": "IN", "val": [LATEST, LATEST_OF_V1]}]
    assert target["targets"][0]["column"]["name"] == "target_label"
    # which project and plugin the tile is, the bridge records apart: Superset refuses keys of its own here
    assert not any(k.startswith("aisc_") for k in dash["metadata"])


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
    assert chart["params"]["aisc_project"] == PID           # so unregister finds it (it is on no dashboard)


def test_before_any_run_the_run_filter_falls_back_to_the_first_value(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, default_version=None, default_runs=()).items()
                               if k.startswith("dashboards/")))
    run = next(f for f in dash["metadata"]["native_filter_configuration"] if f["name"] == "Run")
    assert run["controlValues"]["defaultToFirstItem"] is True and run["defaultDataMask"]["filterState"] == {}


def test_the_tile_opens_on_one_ai_card_version(charts):
    """The Version filter has a fixed id, so the platform's link sets it the way it sets the Target filter
    (Superset's native_filters); without one in the link, the default is the version the sync chose."""
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts).items() if k.startswith("dashboards/")))
    version = next(f for f in dash["metadata"]["native_filter_configuration"] if f["name"] == "Version")
    assert version["id"] == charts.VERSION_FILTER == "NATIVE_FILTER-version"
    assert version["targets"] == [{"datasetUuid": DATASET_UUID, "column": {"name": "system_version"}}]
    assert version["controlValues"]["sortAscending"] is False
    assert version["controlValues"]["defaultToFirstItem"] is False
    assert version["defaultDataMask"]["filterState"]["value"] == [2]
    assert version["defaultDataMask"]["extraFormData"]["filters"] == [
        {"col": "system_version", "op": "IN", "val": [2]}]


def test_runs_on_a_local_model_file_are_left_out_until_the_local_filter_is_on(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts).items() if k.startswith("dashboards/")))
    local = next(f for f in dash["metadata"]["native_filter_configuration"] if f["name"] == "Local")
    assert local["id"] == "NATIVE_FILTER-local"
    assert local["targets"] == [{"datasetUuid": DATASET_UUID, "column": {"name": "local_run"}}]
    assert local["defaultDataMask"]["filterState"]["value"] == ["no"]
    assert local["defaultDataMask"]["extraFormData"]["filters"] == [{"col": "local_run", "op": "IN", "val": ["no"]}]


def test_before_any_run_no_version_is_chosen(charts):
    dash = yaml.safe_load(next(v for k, v in make_bundle(charts, default_version=None, default_runs=()).items()
                               if k.startswith("dashboards/")))
    version = next(f for f in dash["metadata"]["native_filter_configuration"] if f["name"] == "Version")
    assert version["defaultDataMask"]["filterState"] == {}


def test_every_filter_offers_only_the_values_of_its_plugins_own_results(charts):
    """The results dataset holds every plugin's rows: each filter of a plugin's tile is pre-filtered to its tool, so a
    run, target or version of another test is never offered."""
    filters = charts.native_filters("ds-uuid", 1, ["Run 37"], tool="StrongREJECT (Mijke)")
    for f in filters:
        assert f["adhoc_filters"] == [{"expressionType": "SIMPLE", "subject": "tool", "operator": "==",
                                       "comparator": "StrongREJECT (Mijke)", "clause": "WHERE"}], f["name"]


def test_the_tile_names_its_tool_in_its_filters(charts):
    files = charts.bundle(pid="p", plugin="pkg::Plugin", label="StrongREJECT (Mijke)", version="1",
                          visualizations=[], dataset_uuid="ds", dataset_name="engine_results_x", database_uuid="db",
                          database_name="db", sqlalchemy_uri="postgresql://x", columns=["tool", "run"],
                          starter_chart_id=None)
    import yaml
    dashboard = yaml.safe_load(next(v for k, v in files.items() if k.startswith("dashboards/")))
    assert all(f["adhoc_filters"][0]["comparator"] == "StrongREJECT (Mijke)"
               for f in dashboard["metadata"]["native_filter_configuration"])


def test_the_superset_format_module_depends_on_no_assistant_code():
    """charts.py is the only adapter to Superset's formats: the generic bundle never reaches into the assistant."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parents[1] / "aisc_ext" / "charts.py").read_text())
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    assert not [m for m in imported if m.startswith("aisc_ext.assistant")]


def test_a_plugin_radar_reads_its_dimension_and_the_score_as_quoted_column_names(charts):
    """Both radars (a plugin's and the chart assistant's) are written by one radar_metrics: a column name keeps its
    capitals and a quote in an axis stays inside the text."""
    v = viz("radar", ["m"], group_by_dimensions=["Model"], title="t")
    _, params, _ = charts.chart_settings(v, plugin_label="P", columns=COLUMNS + ["Model"],
                                         values={"Model": ["it's", "b"]})
    assert params["metrics"][0]["sqlExpression"] == 'AVG(CASE WHEN "Model" = \'it\'\'s\' THEN "score" END)'
    assert charts.radar_metrics("Model", "Pass rate", ["m"], aggregate="MAX")[0]["sqlExpression"] == \
        'MAX(CASE WHEN "Model" = \'m\' THEN "Pass rate" END)'


# ── the chart assistant's plots in a dashboard's layout ──

from aisc_ext.charts import place_chart, plots_on, without_chart  # noqa: E402


def made_chart_ids(position):
    return [chart for chart, made in plots_on(position) if made]


def test_the_chart_goes_under_assistant_charts_on_the_dashboard():
    position = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
                "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]}}
    out = place_chart(position, chart_id=77, chart_uuid="u-1", name="Mean by category")
    header = [n for n in out.values() if isinstance(n, dict) and n.get("type") == "HEADER"]
    assert header and header[0]["meta"]["text"] == "Assistant charts"
    charts = [n for n in out.values() if isinstance(n, dict) and n.get("type") == "CHART"]
    assert charts[0]["meta"]["chartId"] == 77 and charts[0]["meta"]["uuid"] == "u-1"
    again = place_chart(out, chart_id=78, chart_uuid="u-2", name="Second")
    assert sum(1 for n in again.values() if isinstance(n, dict) and n.get("type") == "HEADER") == 1


def _dashboard_with_two_made_plots():
    position = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
                "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-mine"], "parents": ["ROOT_ID"]},
                "ROW-mine": {"type": "ROW", "id": "ROW-mine", "children": ["CHART-mine"], "parents": ["ROOT_ID", "GRID_ID"]},
                "CHART-mine": {"type": "CHART", "id": "CHART-mine", "children": [],
                               "parents": ["ROOT_ID", "GRID_ID", "ROW-mine"], "meta": {"chartId": 5, "uuid": "u-0"}}}
    out = place_chart(position, chart_id=77, chart_uuid="u-1", name="First")
    return place_chart(out, chart_id=78, chart_uuid="u-2", name="Second")


def _charts(position):
    return [n["meta"]["chartId"] for n in position.values() if isinstance(n, dict) and n.get("type") == "CHART"]


def test_the_plots_it_made_are_only_those_under_assistant_charts():
    assert made_chart_ids(_dashboard_with_two_made_plots()) == [77, 78]


def test_removing_a_plot_takes_it_and_its_row_off_and_leaves_the_others_where_they_were():
    position = _dashboard_with_two_made_plots()
    out = without_chart(position, 77)
    assert sorted(_charts(out)) == [5, 78]
    grid = out["GRID_ID"]["children"]
    assert all(child in out for child in grid)
    assert grid == [c for c in position["GRID_ID"]["children"] if c in out]
    assert "HEADER-aisc-assistant" in out


def test_removing_the_last_plot_it_made_takes_the_header_off_too():
    out = without_chart(without_chart(_dashboard_with_two_made_plots(), 77), 78)
    assert _charts(out) == [5] and "HEADER-aisc-assistant" not in out
    assert "HEADER-aisc-assistant" not in out["GRID_ID"]["children"]


def test_a_replacement_takes_the_old_plots_place():
    position = _dashboard_with_two_made_plots()
    out = place_chart(position, chart_id=79, chart_uuid="u-3", name="First, as bars", replaces=77)
    assert sorted(_charts(out)) == [5, 78, 79]
    order = [out[r]["children"][0] for r in out["GRID_ID"]["children"] if r.startswith("ROW-")]
    assert [out[n]["meta"]["chartId"] for n in order] == [5, 79, 78]


def test_a_replacement_of_a_plot_no_longer_there_is_added_at_the_end():
    out = place_chart(without_chart(_dashboard_with_two_made_plots(), 77), chart_id=79, chart_uuid="u-3",
                      name="x", replaces=77)
    assert made_chart_ids(out) == [78, 79]


def _tabbed_dashboard():
    return {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["TABS-x"]},
            "TABS-x": {"type": "TABS", "id": "TABS-x", "children": ["TAB-a"], "parents": ["ROOT_ID"], "meta": {}},
            "TAB-a": {"type": "TAB", "id": "TAB-a", "children": [], "parents": ["ROOT_ID", "TABS-x"],
                      "meta": {"text": "Against the baseline"}}}


def test_on_a_dashboard_with_tabs_its_plots_go_in_a_tab_of_their_own():
    out = place_chart(_tabbed_dashboard(), chart_id=77, chart_uuid="u-1", name="First")
    tabs = out["TABS-x"]["children"]
    assert tabs[0] == "TAB-a" and len(tabs) == 2
    tab = out[tabs[1]]
    assert tab["type"] == "TAB" and tab["meta"]["text"] == "Assistant charts"
    row = out[tab["children"][0]]
    node = out[row["children"][0]]
    assert node["meta"]["chartId"] == 77 and node["parents"] == ["ROOT_ID", "TABS-x", tabs[1], row["id"]]
    assert made_chart_ids(out) == [77]


def test_removing_its_last_plot_on_a_tabbed_dashboard_takes_its_tab_off():
    out = place_chart(_tabbed_dashboard(), chart_id=77, chart_uuid="u-1", name="First")
    assert without_chart(out, 77) == _tabbed_dashboard()


def test_any_plot_on_the_dashboard_is_taken_off_whoever_made_it():
    position = _dashboard_with_two_made_plots()
    out = without_chart(position, 5)
    assert sorted(_charts(out)) == [77, 78] and "ROW-mine" not in out
    assert "ROW-mine" not in out["GRID_ID"]["children"]


def test_every_plot_on_the_dashboard_is_listed_saying_which_the_assistant_made():
    assert plots_on(_dashboard_with_two_made_plots()) == [(5, False), (77, True), (78, True)]


def test_a_new_query_can_take_the_place_of_a_plot_the_assistant_did_not_make():
    position = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
                "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-d"], "parents": ["ROOT_ID"]},
                "ROW-d": {"type": "ROW", "id": "ROW-d", "children": ["CHART-aisc-d1"], "parents": ["ROOT_ID", "GRID_ID"]},
                "CHART-aisc-d1": {"type": "CHART", "id": "CHART-aisc-d1", "children": [],
                                  "parents": ["ROOT_ID", "GRID_ID", "ROW-d"], "meta": {"chartId": 126, "uuid": "d"}}}
    out = place_chart(position, chart_id=140, chart_uuid="n-1", name="per run", replaces=126)
    assert plots_on(out) == [(140, True)]
    assert out["ROW-d"]["children"] == ["CHART-aisc-assistant-n-1"]

