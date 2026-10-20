# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Assessment › Import charts: extra charts, from a Superset export ZIP,
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


def test_the_charts_point_at_this_projects_dataset_and_its_connection_only(imp):
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


def test_each_project_gets_a_chart_of_its_own(imp):
    _, a = imp.rewrite(export_zip(), pid=PID, source=SOURCE)
    _, b = imp.rewrite(export_zip(), pid=OTHER, source=SOURCE)
    assert a[0]["uuid"] != b[0]["uuid"] != CHART_UUID
    assert a[0]["uuid"] == str(uuid.UUID(a[0]["uuid"]))
    assert imp.rewrite(export_zip(), pid=PID, source=SOURCE)[1][0]["uuid"] == a[0]["uuid"]   # again: the same one


def test_an_imported_chart_is_the_persons_not_aiscs(imp):
    files, _ = imp.rewrite(export_zip(extra_params={"aisc_chart_id": "x", "aisc_plugin": "p", "aisc_project": OTHER}),
                           pid=PID, source=SOURCE)
    (chart,) = [yaml.safe_load(v) for k, v in files.items() if k.startswith("charts/")]
    assert not {"aisc_chart_id", "aisc_plugin", "aisc_project"} & set(chart["params"])


@pytest.mark.parametrize("bad, message", [
    (b"not a zip", "not a ZIP"),
    ("no-charts", "no chart"),
    ("dashboard", "chart export"),
])
def test_a_file_it_cannot_take_is_refused_with_why(imp, bad, message):
    if bad == "no-charts":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x/metadata.yaml", yaml.safe_dump({"version": "1.0.0", "type": "Slice"}))
        bad = buf.getvalue()
    elif bad == "dashboard":
        bad = export_zip(kind="Dashboard")
    with pytest.raises(ValueError, match=message):
        imp.rewrite(bad, pid=PID, source=SOURCE)


def test_imported_charts_go_under_your_charts(imp):
    charts = importlib.import_module("aisc_ext.charts")
    position = charts.layout(label="Data Drift", version="0.4.1", placed=[("u1", "Default · A", "echarts_timeseries_bar")], starter_chart_id=3,
                             user_part={})
    out = imp.place_under_your_charts(position, [{"id": 41, "uuid": "u-new", "name": "Levene per feature"}])
    grid = out["GRID_ID"]["children"]
    node = next(k for k in grid if out[k].get("type") == "CHART" and out[k]["meta"]["uuid"] == "u-new")
    assert grid.index(node) > grid.index("HEADER-aisc-yours") and out[node]["meta"]["chartId"] == 41
    assert imp.place_under_your_charts(out, [{"id": 41, "uuid": "u-new", "name": "x"}]) == out   # not twice


# ── A chart import wrote the tile's layout without the project's lock ───────────────────────────────────────
# A plugin tile sync (under the project's lock) and an owner's import on the same tile: the import placed its
# chart on the layout it had read when the page was posted, so it wrote back over the sync's newer layout (or
# the sync over the import's). The import now holds the project's lock and places its charts on the layout as
# it is once the lock is held.

class _Slice:
    def __init__(self, id_, uuid_):
        self.id, self.uuid = id_, uuid_


class _Tile:
    """A plugin dashboard as the import view holds it: read before the lock."""
    def __init__(self, position):
        import json

        self.position_json = json.dumps(position)
        self.slices = []


def _layout(*charts):
    """A minimal tile layout: a grid with these chart nodes [(node_id, uuid)]."""
    pos = {"ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [n for n, _ in charts]}}
    for node, u in charts:
        pos[node] = {"type": "CHART", "id": node, "children": [], "meta": {"uuid": u, "chartId": 1}}
    return pos


def _spies(tile, *, newer_layout):
    import contextlib
    import json

    events = []

    class Store:
        def project_lock(self, pid):
            @contextlib.contextmanager
            def held():
                events.append(("lock", pid))
                try:
                    yield
                finally:
                    events.append("unlock")
            return held()

    class Session:
        def refresh(self, obj):
            # what the database holds now: a tile sync committed a newer layout after the page read the tile
            events.append("refresh")
            obj.position_json = json.dumps(newer_layout)

        def commit(self):
            events.append("commit")

    def run_import(files):
        events.append("import")

    def slices_by_uuid(uuids):
        return {u: _Slice(41, u) for u in uuids}
    return events, dict(store=Store(), session=Session(), run_import=run_import, slices_by_uuid=slices_by_uuid)


def test_the_import_holds_the_projects_lock_and_places_on_the_layout_as_it_is_now(imp):
    import json

    tile = _Tile(_layout(("CHART-a", "u-a")))                            # read when the page was posted
    newer = _layout(("CHART-a", "u-a"), ("CHART-sync", "u-sync"))       # what a sync committed meanwhile
    events, spies = _spies(tile, newer_layout=newer)
    imp.import_into_tile(tile, PID, {"charts/x.yaml": ""}, [{"uuid": "u-new", "name": "Levene"}], **spies)
    assert events[0] == ("lock", PID) and events[-1] == "unlock"
    assert events.index("refresh") < events.index("commit")             # the layout is read under the lock
    grid = json.loads(tile.position_json)["GRID_ID"]["children"]
    assert "CHART-sync" in grid and "CHART-user-u-new" in grid          # the sync's chart is kept
    assert [s.uuid for s in tile.slices] == ["u-new"]


def test_the_lock_is_released_when_superset_refuses_the_file(imp):
    tile = _Tile(_layout())
    events, spies = _spies(tile, newer_layout=_layout())

    def refuse(files):
        raise RuntimeError("not a chart export")
    with pytest.raises(RuntimeError):
        imp.import_into_tile(tile, PID, {}, [], **{**spies, "run_import": refuse})
    assert events[-1] == "unlock" and "commit" not in events


def _bomb(size=50 * 1024 * 1024, members=1):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("x/metadata.yaml", yaml.safe_dump({"version": "1.0.0", "type": "Slice"}))
        for i in range(members):
            z.writestr(f"x/charts/zeros_{i}.yaml", b"\0" * size)
    return buf.getvalue()


def test_a_zip_that_unpacks_to_more_than_a_chart_export_is_refused_unread(imp):
    """The upload cap (5 MB) bounded the ZIP, not what it unpacks: a ZIP of
    deflated zeros (about 1000:1) made a gunicorn worker allocate gigabytes and be killed. What the ZIP says it
    holds is checked before anything is read."""
    import tracemalloc

    data = _bomb()
    assert len(data) < 1024 * 1024
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="unpacks to more"):
            imp.rewrite(data, pid=PID, source=SOURCE)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 10 * 1024 * 1024


def test_a_zip_of_too_many_files_is_refused(imp):
    with pytest.raises(ValueError, match="files"):
        imp.rewrite(_bomb(size=10, members=2000), pid=PID, source=SOURCE)
