# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""A project's two datasets carry their columns from the start (plan 2026-09-29,
~/aisc-dashboard-columns-plan.md, T1 to T4 and T6).

Superset 4.1.1 finds a virtual dataset's columns by running its query with
LIMIT 1, and reports none when the result is empty (result_set.py: `if not
pa_data: column_names = []`). A project is registered before it has any row,
so asking Superset gave both datasets 0 columns and every chart failed with
"Columns missing in dataset". The columns are now declared next to the SQL
and written by the store; nothing runs the query at registration.
"""
import importlib
import json
import sys
import types

import pytest

from tests.test_projects import FakeStore, HEX, PID, _register, projects  # noqa: F401  (fixture)

ENGINE, CONTROLS = f"engine_results_{HEX}", f"controls_answers_{HEX}"


def _declared(store, key):
    return [name for name, _type in store.items("dataset")[key]["columns"]]


# ── T1 a project with no data gets its columns ──────────────────────────────

def test_t1_both_datasets_are_registered_with_their_declared_columns(projects):
    store = FakeStore()
    _register(projects, store)
    assert _declared(store, ENGINE) == ["pid", "score", "unit", "time", "dimensions", "metric", "evaluation_pid",
                                        "evaluated_at", "system_version_pid", "system_version"]
    assert _declared(store, CONTROLS) == ["title", "text", "answer", "score", "system_version_number",
                                          "answered_at", "label", "submission_version"]


def test_t1_the_types_are_the_ones_superset_itself_infers():
    p = importlib.import_module("aisc_ext.projects")
    assert dict(p.ENGINE_RESULTS_COLUMNS) == {
        "pid": "STRING", "score": "FLOAT", "unit": "STRING", "time": "DATETIMETZ", "dimensions": "JSONB",
        "metric": "STRING", "evaluation_pid": "STRING", "evaluated_at": "DATETIMETZ",
        "system_version_pid": "STRING", "system_version": "INTEGER"}
    assert dict(p.CONTROLS_ANSWERS_COLUMNS) == {
        "title": "STRING", "text": "STRING", "answer": "STRING", "score": "INTEGER",
        "system_version_number": "INTEGER", "answered_at": "DATETIMETZ", "label": "STRING",
        "submission_version": "INTEGER"}


# ── T2 every column a chart uses is declared on its dataset ─────────────────

def _chart_columns(form: dict) -> set:
    used = set()
    if isinstance(form.get("x_axis"), str):
        used.add(form["x_axis"])
    for m in form.get("metrics") or []:
        if isinstance(m, dict) and m.get("column"):
            used.add(m["column"]["column_name"])
    for key in ("groupby", "all_columns"):
        used |= {c for c in form.get(key) or [] if isinstance(c, str)}
    return used


def test_t2_every_chart_column_is_declared_on_its_dataset(projects):
    p = importlib.import_module("aisc_ext.projects")
    store = FakeStore()
    _register(projects, store)
    charts = store.items("dashboard")[f"aisc-{HEX}"]["charts"]
    assert charts
    for chart in charts:
        _viz, form = p._chart_form(chart)
        missing = _chart_columns(form) - set(_declared(store, chart["dataset"]))
        assert not missing, f"{chart['kind']} chart uses undeclared columns {missing}"


# ── T3 and T4 the Superset store writes them, and never asks Superset ────────

class Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _superset(monkeypatch, datasets):
    """A stand-in for the Superset ORM the store uses (pattern of
    test_isolation_dashboard.py::test_i10_1_supersetstore_keeps_the_dataset_id_when_it_moves)."""
    project_db = Row(id=2, database_name="AISC Controls mcas")
    rows = {"Database": [project_db], "SqlaTable": list(datasets)}

    class Query:
        def __init__(self, items):
            self.items = items

        def filter_by(self, **kw):
            return Query([i for i in self.items if all(getattr(i, k, None) == v for k, v in kw.items())])

        def one(self):
            assert len(self.items) == 1
            return self.items[0]

        def one_or_none(self):
            return self.items[0] if self.items else None

    class Session:
        def query(self, model):
            return Query(rows[model.__name__])

        def add(self, obj):
            rows["SqlaTable"].append(obj)

        def flush(self):
            pass

        def commit(self):
            pass

    class SqlaTable(Row):
        def __init__(self, **kw):
            self.columns, self.main_dttm_col = [], None
            super().__init__(**kw)

        def fetch_metadata(self):
            raise AssertionError("registration must not ask Superset for the columns")

    class TableColumn(Row):
        pass

    fake = {
        "superset": types.SimpleNamespace(db=types.SimpleNamespace(session=Session())),
        "superset.models": types.ModuleType("superset.models"),
        "superset.models.core": types.SimpleNamespace(Database=type("Database", (), {})),
        "superset.connectors": types.ModuleType("superset.connectors"),
        "superset.connectors.sqla": types.ModuleType("superset.connectors.sqla"),
        "superset.connectors.sqla.models": types.SimpleNamespace(SqlaTable=SqlaTable, TableColumn=TableColumn),
    }
    for name, module in fake.items():
        monkeypatch.setitem(sys.modules, name, module)
    return rows, SqlaTable, TableColumn


SPEC = {"aisc_project": PID, "database": "AISC Controls mcas", "sql": "SELECT ...",
        "columns": [["title", "STRING"], ["score", "INTEGER"], ["answered_at", "DATETIMETZ"]]}


def _store():
    return importlib.import_module("aisc_ext.projects").SupersetStore()


def test_t3_a_new_dataset_gets_the_declared_columns_and_its_time_column(monkeypatch):
    rows, _SqlaTable, _TableColumn = _superset(monkeypatch, [])
    _store().upsert("dataset", CONTROLS, SPEC)
    (ds,) = rows["SqlaTable"]
    got = {c.column_name: (c.type, c.is_dttm, c.groupby, c.filterable) for c in ds.columns}
    assert got == {"title": ("STRING", False, True, True), "score": ("INTEGER", False, True, True),
                   "answered_at": ("DATETIMETZ", True, True, True)}
    assert ds.main_dttm_col == "answered_at"


def test_t3_a_dataset_stored_with_no_columns_is_repaired_in_place(monkeypatch):
    _rows, SqlaTable, _TableColumn = _superset(monkeypatch, [])
    broken = SqlaTable(id=6, table_name=CONTROLS, sql="old", extra="{}")
    rows, _, _ = _superset(monkeypatch, [broken])
    _store().upsert("dataset", CONTROLS, SPEC)
    assert rows["SqlaTable"] == [broken] and broken.id == 6
    assert [c.column_name for c in broken.columns] == ["title", "score", "answered_at"]


def test_t3_a_redeclared_column_keeps_its_object_a_stale_one_goes_a_calculated_one_stays(monkeypatch):
    _rows, SqlaTable, TableColumn = _superset(monkeypatch, [])
    kept = TableColumn(id=41, column_name="score", type="BIGINT", expression="", is_dttm=False, groupby=True,
                       filterable=True)
    stale = TableColumn(id=42, column_name="gone", type="STRING", expression="", is_dttm=False, groupby=True,
                        filterable=True)
    calc = TableColumn(id=43, column_name="score_pct", type="FLOAT", expression="score * 20", is_dttm=False,
                       groupby=True, filterable=True)
    ds = SqlaTable(id=6, table_name=CONTROLS, sql="old", extra="{}")
    ds.columns = [kept, stale, calc]
    rows, _, _ = _superset(monkeypatch, [ds])
    _store().upsert("dataset", CONTROLS, SPEC)
    by_name = {c.column_name: c for c in ds.columns}
    assert by_name["score"] is kept and kept.id == 41 and kept.type == "INTEGER"
    assert "gone" not in by_name
    assert by_name["score_pct"] is calc
    assert set(by_name) == {"title", "score", "answered_at", "score_pct"}


def test_t4_registration_never_runs_the_query(monkeypatch):
    rows, _, _ = _superset(monkeypatch, [])
    _store().upsert("dataset", ENGINE, {**SPEC, "columns": [["pid", "STRING"], ["time", "DATETIMETZ"]]})
    assert rows["SqlaTable"][0].main_dttm_col == "time"   # fetch_metadata would have raised


def test_t4_the_project_tag_and_sql_are_still_written(monkeypatch):
    rows, _, _ = _superset(monkeypatch, [])
    _store().upsert("dataset", CONTROLS, SPEC)
    ds = rows["SqlaTable"][0]
    assert ds.sql == "SELECT ..." and json.loads(ds.extra) == {"aisc_project": PID}


# ── T6 registering twice changes nothing ────────────────────────────────────

def test_t6_registering_twice_gives_the_same_columns(projects):
    store = FakeStore()
    _register(projects, store)
    first = store.items("dataset")
    _register(projects, store)
    assert store.items("dataset") == first
