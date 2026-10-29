# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Moving from the shared "AISC Results" connection to one connection per project.

- `SupersetStore._upsert_dataset`: a dataset that moves to the project connection keeps
  its old permission names at flush, so Superset's own rename hook moves the view menu
  and the charts' perm with it.
- `scripts/verify_review.py` builds its check dataset on a project connection.
"""
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")


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
    assert len(rows["SqlaTable"]) == 1                 # moved in place, no new row
    assert dataset.database is project_db
    assert dataset.id == 7
    assert dataset.perm == f"[AISC Results].[engine_results_{HEX}](id:7)"
    assert dataset.schema_perm == "[AISC Results].[engine]"


# ---- the review check script uses a project connection ---------------------------

def test_verify_review_builds_its_dataset_on_a_project_connection():
    text = (ROOT / "scripts" / "verify_review.py").read_text()
    assert "RESULTS_DB_NAME" not in text
    # it picks a connection the bridge made: one whose extra carries the project tag
    assert "aisc_project" in text or "PROJECT_TAG" in text
