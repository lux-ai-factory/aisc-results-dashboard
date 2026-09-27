# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Isolation WP D1 (03-coding-plan.md, WP D1): what the plan adds beyond the stage-2 tests.

- `results_db.remove_results_connection()`: cutover step C12 (X1) deletes the retired
  "AISC Results" connection with it. It refuses while any dataset still sits on that
  connection, and otherwise deletes the rows of every table with a foreign key to
  Superset's `dbs` for that connection, then the `dbs` row, and returns the count.
  Tested on a fake of Superset's metadata that enforces its foreign keys, so the delete
  order is proven, not assumed.
- `SupersetStore._upsert_dataset`: a dataset that moves to the project connection keeps
  its old permission names at flush, so Superset's own rename hook moves the view menu
  and the charts' perm with it (the plan asked for a refresh here; see 04-D1-notes.md).
- `scripts/verify_review.py` builds its check dataset on a project connection.
"""
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")


class FakeMetadata:
    """Superset's metadata tables, by name, as lists of row dicts, with their foreign
    keys. A delete that would leave a row pointing at a deleted row fails, as it does
    in Postgres."""

    def __init__(self, tables, foreign_keys):
        self.tables = {name: [dict(r) for r in rows] for name, rows in tables.items()}
        self.fks = list(foreign_keys)  # (table, (column,), referred_table, (referred_column,))
        self.deleted = []

    # the four calls remove_results_connection makes
    def database_id(self, name):
        for row in self.tables["dbs"]:
            if row["database_name"] == name:
                return row["id"]
        return None

    def foreign_keys(self):
        return list(self.fks)

    def count(self, table, column, value):
        return sum(1 for r in self.tables.get(table, []) if r.get(column) == value)

    def delete(self, table, column, value):
        going = [r for r in self.tables[table] if r.get(column) == value]
        for src, cols, ref, ref_cols in self.fks:
            if ref != table:
                continue
            gone = {r[ref_cols[0]] for r in going}
            if any(r.get(cols[0]) in gone for r in self.tables.get(src, [])):
                raise AssertionError(f"foreign key violation: {src}.{cols[0]} still references {table}")
        self.tables[table] = [r for r in self.tables[table] if r.get(column) != value]
        self.deleted.append(table)
        return len(going)


# The Superset 4.1 metadata tables that reference `dbs`, and the references between them
# that make the delete order matter (tab_state points at query, table_schema at tab_state).
FKS = [
    ("tables", ("database_id",), "dbs", ("id",)),
    ("saved_query", ("db_id",), "dbs", ("id",)),
    ("query", ("database_id",), "dbs", ("id",)),
    ("tab_state", ("database_id",), "dbs", ("id",)),
    ("tab_state", ("latest_query_id",), "query", ("client_id",)),
    ("table_schema", ("database_id",), "dbs", ("id",)),
    ("table_schema", ("tab_state_id",), "tab_state", ("id",)),
    ("ssh_tunnels", ("database_id",), "dbs", ("id",)),
    ("table_columns", ("table_id",), "tables", ("id",)),
]


def _metadata(datasets_on_results=0):
    return FakeMetadata({
        "dbs": [{"id": 1, "database_name": "AISC Results"}, {"id": 2, "database_name": "AISC Controls mcas"}],
        "tables": [{"id": 10 + i, "database_id": 1} for i in range(datasets_on_results)]
                  + [{"id": 20, "database_id": 2}],
        "table_columns": [{"id": 30, "table_id": 20}],
        "saved_query": [{"id": 40, "db_id": 1}, {"id": 41, "db_id": 2}],
        "query": [{"id": 50, "client_id": "q1", "database_id": 1}, {"id": 51, "client_id": "q2", "database_id": 2}],
        "tab_state": [{"id": 60, "database_id": 1, "latest_query_id": "q1"}],
        "table_schema": [{"id": 70, "database_id": 1, "tab_state_id": 60}],
        "ssh_tunnels": [],
    }, FKS)


def _results_db():
    from aisc_ext import results_db

    return results_db


def test_remove_refuses_while_a_dataset_sits_on_aisc_results():
    meta = _metadata(datasets_on_results=1)
    with pytest.raises(RuntimeError, match="dataset"):
        _results_db().remove_results_connection(store=meta)
    assert meta.deleted == []
    assert meta.database_id("AISC Results") == 1


def test_remove_deletes_the_rows_that_reference_it_then_the_connection():
    meta = _metadata()
    count = _results_db().remove_results_connection(store=meta)
    # saved_query 40, query 50, tab_state 60, table_schema 70, the dbs row
    assert count == 5
    assert meta.database_id("AISC Results") is None
    assert meta.deleted[-1] == "dbs"
    # the project connection and everything on it are untouched
    assert meta.database_id("AISC Controls mcas") == 2
    assert [r["id"] for r in meta.tables["tables"]] == [20]
    assert [r["id"] for r in meta.tables["saved_query"]] == [41]
    assert [r["id"] for r in meta.tables["query"]] == [51]
    assert meta.tables["table_columns"] == [{"id": 30, "table_id": 20}]


def test_remove_deletes_a_referencing_table_before_the_table_it_references():
    """tab_state points at query and table_schema at tab_state: deleting in any other
    order would violate a foreign key (the fake fails the same way Postgres does)."""
    meta = _metadata()
    _results_db().remove_results_connection(store=meta)
    order = meta.deleted
    assert order.index("table_schema") < order.index("tab_state") < order.index("query")


def test_remove_is_a_no_op_when_the_connection_is_gone():
    meta = _metadata()
    results_db = _results_db()
    results_db.remove_results_connection(store=meta)
    meta.deleted.clear()
    assert results_db.remove_results_connection(store=meta) == 0
    assert meta.deleted == []


def test_remove_names_the_retired_connection_only():
    results_db = _results_db()
    assert results_db.RESULTS_DB_NAME == "AISC Results"
    meta = _metadata()
    meta.tables["dbs"].append({"id": 3, "database_name": "AISC Results (copy)"})
    results_db.remove_results_connection(store=meta)
    assert meta.database_id("AISC Results (copy)") == 3


# ---- a moved dataset's permission names are Superset's to rename --------------

def test_a_moved_dataset_keeps_its_old_permission_names_for_supersets_rename_hook(monkeypatch):
    """Superset 4.1.1 (superset/security/manager.py, dataset_before_update and
    _update_dataset_perm) renames the dataset's view menu from ``target.perm`` to the
    new name when ``database_id`` changes, and rewrites tables.perm and the perm of
    every chart on the dataset. It does that only if ``perm`` still holds the old
    name when the update is flushed; had the upsert refreshed it, old and new would
    be equal, the view menu would not be renamed and the charts' perm would stay on
    "AISC Results" (the chart list filters on it). So the upsert moves the dataset
    and leaves perm and schema_perm alone."""
    from aisc_ext import projects

    class Row:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Table(Row):
        def fetch_metadata(self):
            pass

        def get_perm(self):
            return f"[{self.database.database_name}].[{self.table_name}](id:{self.id})"

        def get_schema_perm(self):
            return f"[{self.database.database_name}].[engine]"

    results = Row(id=1, database_name="AISC Results")
    project_db = Row(id=2, database_name="AISC Controls mcas")
    dataset = Table(id=7, table_name=f"engine_results_{HEX}", database=results, sql="old", extra="{}",
                    perm=f"[AISC Results].[engine_results_{HEX}](id:7)", schema_perm="[AISC Results].[engine]")
    rows = {"Database": [results, project_db], "SqlaTable": [dataset]}

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

    fake = {
        "superset": types.SimpleNamespace(db=types.SimpleNamespace(session=Session())),
        "superset.models": types.ModuleType("superset.models"),
        "superset.models.core": types.SimpleNamespace(Database=type("Database", (), {})),
        "superset.connectors": types.ModuleType("superset.connectors"),
        "superset.connectors.sqla": types.ModuleType("superset.connectors.sqla"),
        "superset.connectors.sqla.models": types.SimpleNamespace(SqlaTable=type("SqlaTable", (Table,), {})),
    }
    for name, module in fake.items():
        monkeypatch.setitem(sys.modules, name, module)

    projects.SupersetStore().upsert(
        "dataset", f"engine_results_{HEX}", {"aisc_project": PID, "database": "AISC Controls mcas", "sql": "new"})
    assert dataset.database is project_db
    assert dataset.id == 7
    assert dataset.perm == f"[AISC Results].[engine_results_{HEX}](id:7)"
    assert dataset.schema_perm == "[AISC Results].[engine]"


# ---- the review check script no longer needs the retired connection -------------

def test_verify_review_builds_its_dataset_on_a_project_connection():
    text = (ROOT / "scripts" / "verify_review.py").read_text()
    assert "RESULTS_DB_NAME" not in text
    # it picks a connection the bridge made: one whose extra carries the project tag
    assert "aisc_project" in text or "PROJECT_TAG" in text
