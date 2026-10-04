# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Assessment › Import charts (plugin dashboards 2026-10-04, T7): extra charts, from a Superset export ZIP,
into one plugin's tile, as the person's own charts under "Your charts".

The rewrite is pure and tested here: every chart is pointed at this project's results dataset, given an id of
its own in this project (Superset imports charts by id, so the same file imported in two projects would
otherwise overwrite one project's chart with the other's), and loses any AISC mark (an imported chart is the
person's: AISC never changes it). The ZIP's own connection and dataset are never imported."""
import importlib
import io
import uuid
import zipfile

import pytest
import yaml

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
OTHER = "0b7f5c3e-2d7a-4c1e-9f64-3a1b2c3d4e5f"
SOURCE = {"dataset_uuid": "aaaaaaaa-0000-4000-8000-000000000001", "dataset_name": "engine_results_x",
          "database_uuid": "bbbbbbbb-0000-4000-8000-000000000001", "database_name": "AISC Controls mcas",
          "sqlalchemy_uri": "postgresql+psycopg2://dashboard_ro:XXXXXXXXXX@postgres:5432/project_x",
          "columns": ["score", "metric", "run", "feature"]}
CHART_UUID = "cccccccc-0000-4000-8000-000000000001"


@pytest.fixture
def imp():
    return importlib.import_module("aisc_ext.chart_import")


def export_zip(dataset_uuid="dddddddd-0000-4000-8000-000000000001", extra_params=None, kind="Slice"):
    """A Superset export of one chart, as its Export button makes it (a folder inside the ZIP)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("chart_export_20261005/metadata.yaml", yaml.safe_dump({"version": "1.0.0", "type": kind}))
        z.writestr("chart_export_20261005/databases/Elsewhere.yaml", yaml.safe_dump(
            {"database_name": "Elsewhere", "uuid": "eeeeeeee-0000-4000-8000-000000000001",
             "sqlalchemy_uri": "postgresql://someone:secret@elsewhere/db"}))
        z.writestr("chart_export_20261005/datasets/Elsewhere/results.yaml", yaml.safe_dump(
            {"table_name": "results", "uuid": dataset_uuid, "database_uuid": "eeeeeeee-0000-4000-8000-000000000001"}))
        z.writestr(f"chart_export_20261005/charts/Levene_{CHART_UUID[:4]}.yaml", yaml.safe_dump(
            {"slice_name": "Levene per feature", "viz_type": "table", "uuid": CHART_UUID, "dataset_uuid": dataset_uuid,
             "params": {"viz_type": "table", "datasource": "7__table", **(extra_params or {})}, "version": "1.0.0"}))
    return buf.getvalue()


def test_t7_1_the_charts_point_at_this_projects_dataset_and_its_connection_only(imp):
    files, charts = imp.rewrite(export_zip(), pid=PID, source=SOURCE)
    assert [c["name"] for c in charts] == ["Levene per feature"]
    datasets = [yaml.safe_load(v) for k, v in files.items() if k.startswith("datasets/")]
    databases = [yaml.safe_load(v) for k, v in files.items() if k.startswith("databases/")]
    assert [d["uuid"] for d in datasets] == [SOURCE["dataset_uuid"]]
    assert [d["uuid"] for d in databases] == [SOURCE["database_uuid"]]
    assert "secret" not in "".join(files.values()) and "Elsewhere" not in "".join(files.values())
    (chart,) = [yaml.safe_load(v) for k, v in files.items() if k.startswith("charts/")]
    assert chart["dataset_uuid"] == SOURCE["dataset_uuid"]
    assert yaml.safe_load(files["metadata.yaml"])["type"] == "Slice"


def test_t7_2_each_project_gets_a_chart_of_its_own(imp):
    _, a = imp.rewrite(export_zip(), pid=PID, source=SOURCE)
    _, b = imp.rewrite(export_zip(), pid=OTHER, source=SOURCE)
    assert a[0]["uuid"] != b[0]["uuid"] != CHART_UUID
    assert a[0]["uuid"] == str(uuid.UUID(a[0]["uuid"]))
    assert imp.rewrite(export_zip(), pid=PID, source=SOURCE)[1][0]["uuid"] == a[0]["uuid"]   # again: the same one


def test_t7_1_an_imported_chart_is_the_persons_not_aiscs(imp):
    files, _ = imp.rewrite(export_zip(extra_params={"aisc_chart_id": "x", "aisc_plugin": "p", "aisc_project": OTHER}),
                           pid=PID, source=SOURCE)
    (chart,) = [yaml.safe_load(v) for k, v in files.items() if k.startswith("charts/")]
    assert not {"aisc_chart_id", "aisc_plugin", "aisc_project"} & set(chart["params"])


@pytest.mark.parametrize("bad, message", [
    (b"not a zip", "not a ZIP"),
    ("no-charts", "no chart"),
    ("dashboard", "chart export"),
])
def test_t7_a_file_it_cannot_take_is_refused_with_why(imp, bad, message):
    if bad == "no-charts":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x/metadata.yaml", yaml.safe_dump({"version": "1.0.0", "type": "Slice"}))
        bad = buf.getvalue()
    elif bad == "dashboard":
        bad = export_zip(kind="Dashboard")
    with pytest.raises(ValueError, match=message):
        imp.rewrite(bad, pid=PID, source=SOURCE)


def test_t7_1_imported_charts_go_under_your_charts(imp):
    charts = importlib.import_module("aisc_ext.charts")
    position = charts.layout(label="Data Drift", version="0.4.1", placed=[("u1", "Default · A")], starter_chart_id=3,
                             user_part={})
    out = imp.place_under_your_charts(position, [{"id": 41, "uuid": "u-new", "name": "Levene per feature"}])
    grid = out["GRID_ID"]["children"]
    node = next(k for k in grid if out[k].get("type") == "CHART" and out[k]["meta"]["uuid"] == "u-new")
    assert grid.index(node) > grid.index("HEADER-aisc-yours") and out[node]["meta"]["chartId"] == 41
    assert imp.place_under_your_charts(out, [{"id": 41, "uuid": "u-new", "name": "x"}]) == out   # not twice
