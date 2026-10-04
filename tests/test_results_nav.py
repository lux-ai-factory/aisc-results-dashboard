# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Results navigation (docs/superpowers/results-nav-2026-10-03/01-specs.md, R1): the engine results
name each result's tool, and the project dashboard carries two native filters with fixed ids,
Target and Tool, so the launcher's buttons can open it with both set."""
import importlib
import json
import sys
import types

from tests.test_projects import FakeStore, HEX, PID, _register

TARGET, TOOL = "NATIVE_FILTER-target", "NATIVE_FILTER-tool"


def projects():
    return importlib.import_module("aisc_ext.projects")


# ── R1.1 the tool column ────────────────────────────────────────────────────

def test_r1_1_engine_results_name_the_tool_never_null():
    sql = projects().engine_results_sql()
    assert "COALESCE(p.display_name, p.name, 'unknown') AS tool" in " ".join(sql.split())


def test_r1_1_the_tool_column_is_declared_after_the_target_ones_as_a_string():
    """Last until 2026-10-04, when the run and the plugins' dimensions came after it (plugin dashboards T2.1)."""
    columns = projects().ENGINE_RESULTS_COLUMNS
    names = [n for n, _ in columns]
    assert ("tool", "STRING") in columns and names.index("tool") == names.index("target_status") + 1


# ── R1.2 the two filters in the dashboard spec ──────────────────────────────

def test_r1_2_the_dashboard_spec_has_the_target_and_tool_filters():
    store = FakeStore()
    _register(projects(), store)
    filters = store.items("dashboard")[f"aisc-{HEX}"]["filters"]
    assert filters == [
        {"id": TARGET, "name": "Target", "dataset": f"engine_results_{HEX}", "column": "target_label"},
        {"id": TOOL, "name": "Tool", "dataset": f"engine_results_{HEX}", "column": "tool"},
    ]


def test_r1_2_a_native_filter_in_superset_shape():
    native = projects().native_filter({"id": TOOL, "name": "Tool", "column": "tool"}, dataset_id=7,
                                      excluded=[12])
    assert native == {
        "id": TOOL, "name": "Tool", "type": "NATIVE_FILTER", "filterType": "filter_select",
        "targets": [{"datasetId": 7, "column": {"name": "tool"}}],
        "controlValues": {"enableEmptyFilter": False, "defaultToFirstItem": False, "multiSelect": False,
                          "searchAllOptions": False, "inverseSelection": False},
        "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
        "cascadeParentIds": [], "scope": {"rootPath": ["ROOT_ID"], "excluded": [12]}, "description": "",
    }


# ── R1.2, R1.3 the Superset store writes them, keeping the project tag ──────

class Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _superset(monkeypatch, rows, role):
    class Query:
        def __init__(self, items):
            self.items = items

        def filter_by(self, **kw):
            return Query([i for i in self.items if all(getattr(i, k, None) == v for k, v in kw.items())])

        def one_or_none(self):
            return self.items[0] if self.items else None

    class Session:
        def query(self, model):
            return Query(rows[model.__name__])

        def add(self, obj):
            name = type(obj).__name__
            if obj not in rows[name]:
                rows[name].append(obj)

        def flush(self):
            for obj in rows["Slice"]:
                if getattr(obj, "id", None) is None:
                    obj.id = 100 + rows["Slice"].index(obj)

        def commit(self):
            pass

    class SecurityManager:
        def find_role(self, name):
            return role if name == role.name else None

    Dashboard = type("Dashboard", (Row,), {})
    Slice = type("Slice", (Row,), {})
    SqlaTable = type("SqlaTable", (Row,), {})
    fake = {
        "superset": types.SimpleNamespace(db=types.SimpleNamespace(session=Session())),
        "superset.models": types.ModuleType("superset.models"),
        "superset.models.dashboard": types.SimpleNamespace(Dashboard=Dashboard),
        "superset.models.slice": types.SimpleNamespace(Slice=Slice),
        "superset.connectors": types.ModuleType("superset.connectors"),
        "superset.connectors.sqla": types.ModuleType("superset.connectors.sqla"),
        "superset.connectors.sqla.models": types.SimpleNamespace(SqlaTable=SqlaTable),
        "flask": types.SimpleNamespace(
            current_app=types.SimpleNamespace(appbuilder=types.SimpleNamespace(sm=SecurityManager()))),
    }
    for name, module in fake.items():
        monkeypatch.setitem(sys.modules, name, module)
    return SqlaTable


def test_r1_2_r1_3_the_store_writes_the_filters_with_real_ids_and_keeps_the_tag(monkeypatch):
    role = Row(name=f"AiscProject_{HEX}")
    rows = {"Dashboard": [], "SqlaTable": [], "Slice": []}
    SqlaTable = _superset(monkeypatch, rows, role)
    rows["SqlaTable"] += [SqlaTable(id=1, table_name=f"engine_results_{HEX}"),
                          SqlaTable(id=2, table_name=f"controls_answers_{HEX}")]
    store = FakeStore()
    _register(projects(), store)
    spec = store.items("dashboard")[f"aisc-{HEX}"]

    projects().SupersetStore().upsert("dashboard", f"aisc-{HEX}", spec)

    dash = rows["Dashboard"][0]
    meta = json.loads(dash.json_metadata)
    assert meta["aisc_project"] == PID
    natives = {f["id"]: f for f in meta["native_filter_configuration"]}
    assert set(natives) == {TARGET, TOOL}
    controls_chart = [s.id for s in dash.slices if s.datasource_id == 2]
    assert len(controls_chart) == 1
    for f in natives.values():
        assert f["targets"][0]["datasetId"] == 1          # the engine results dataset's own id
        assert f["scope"]["excluded"] == controls_chart  # the answers table has no target or tool
    assert natives[TOOL]["targets"][0]["column"] == {"name": "tool"}
    assert natives[TARGET]["targets"][0]["column"] == {"name": "target_label"}


def test_r1_2_no_filter_when_its_dataset_is_missing(monkeypatch):
    role = Row(name=f"AiscProject_{HEX}")
    rows = {"Dashboard": [], "SqlaTable": [], "Slice": []}
    _superset(monkeypatch, rows, role)
    store = FakeStore()
    _register(projects(), store)
    projects().SupersetStore().upsert("dashboard", f"aisc-{HEX}", store.items("dashboard")[f"aisc-{HEX}"])
    meta = json.loads(rows["Dashboard"][0].json_metadata)
    assert meta["native_filter_configuration"] == [] and meta["aisc_project"] == PID
