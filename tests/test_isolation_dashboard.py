# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Isolation 2026-09-25: the dashboard reads each project from its own database only.

Requirement ids are from docs/superpowers/isolation-2026-09-25/01-specs.md
(section 10, I17.1). Pure tests: the FakeStore of test_projects.py, source scans for
the runtime-only modules (sso.py and superset_config.py import Superset, which the
unit venv does not have), and a stand-in for Superset's models to exercise
SupersetStore's dataset upsert.

The existing tests this design changes (named in 02-tests.md, not edited here):
test_projects.py::test_s11_1_engine_dataset_is_on_the_results_connection_and_carries_the_version
and ::test_s11_4_engine_dataset_filters_on_this_project_only pin the dataset on
"AISC Results" with a pid filter and core.system; test_results_database.py pins
the registration of "AISC Results"; test_project_datasets_db.py's engine tests read
core.system in `platform`.
"""
import pathlib
import re
import sys
import types

import pytest

from tests.test_projects import FakeStore

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")
OTHER = "0b7f5c3e-2d7a-4c1e-9f64-3a1b2c3d4e5f"
OTHER_HEX = OTHER.replace("-", "")
ROOT = pathlib.Path(__file__).resolve().parents[1]


def _projects():
    from aisc_ext import projects

    return projects


def _register(store, pid=PID, slug="mcas", name="MCAS"):
    _projects().register_project(pid, slug, name, store=store, controls_password="pw")


def _engine_sql(pid=PID):
    """The engine dataset SQL. Under I10.1 it needs no pid; today it takes one."""
    projects = _projects()
    try:
        return projects.engine_results_sql()
    except TypeError:
        return projects.engine_results_sql(pid)


def _flat(sql):
    return " ".join(sql.split()).lower()


# ---- I10.1: the engine dataset sits on the project's own connection ----------

def test_i10_1_the_engine_dataset_is_on_the_projects_own_connection():
    store = FakeStore()
    _register(store)
    ds = store.items("dataset")[f"engine_results_{HEX}"]
    assert ds["database"] == "AISC Controls mcas", ds["database"]


def test_i10_1_the_engine_sql_joins_project_system_and_never_core():
    sql = _flat(_engine_sql())
    assert "project.system" in sql
    assert "core." not in sql
    for table in ("engine.aisc_backend_measurement", "engine.aisc_backend_observation", "engine.aisc_backend_evaluation",
                  "engine.aisc_backend_metric"):
        assert table in sql, table
    assert "s.number as system_version" in sql and "s.pid as system_version_pid" in sql


def test_i10_1_the_engine_sql_has_no_pid_filter():
    """The database is the project: no WHERE on a platform pid."""
    sql = _engine_sql()
    assert PID not in sql
    assert "project_id" not in _flat(sql)


def test_i10_1_reregistering_moves_a_dataset_that_sits_on_aisc_results():
    """A dataset registered before isolation (on AISC Results) is upserted onto the project connection."""
    store = FakeStore()
    store.upsert("dataset", f"engine_results_{HEX}", {"aisc_project": PID, "database": "AISC Results", "sql": "old"})
    _register(store)
    assert store.items("dataset")[f"engine_results_{HEX}"]["database"] == "AISC Controls mcas"


def test_i10_1_supersetstore_keeps_the_dataset_id_when_it_moves(monkeypatch):
    """The upsert changes the dataset's database in place, so its id (and every chart on it) stays."""
    projects = _projects()

    class Row:
        def __init__(self, **kw):
            self.__dict__.update(kw)

        def fetch_metadata(self):
            pass

    results = Row(id=1, database_name="AISC Results")
    project_db = Row(id=2, database_name="AISC Controls mcas")
    dataset = Row(id=7, table_name=f"engine_results_{HEX}", database=results, sql="old", extra="{}")
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

    Database = type("Database", (), {})
    SqlaTable = type("SqlaTable", (Row,), {})
    fake = {
        "superset": types.SimpleNamespace(db=types.SimpleNamespace(session=Session())),
        "superset.models": types.ModuleType("superset.models"),
        "superset.models.core": types.SimpleNamespace(Database=Database),
        "superset.connectors": types.ModuleType("superset.connectors"),
        "superset.connectors.sqla": types.ModuleType("superset.connectors.sqla"),
        "superset.connectors.sqla.models": types.SimpleNamespace(SqlaTable=SqlaTable),
    }
    for name, module in fake.items():
        monkeypatch.setitem(sys.modules, name, module)

    projects.SupersetStore().upsert(
        "dataset", f"engine_results_{HEX}", {"aisc_project": PID, "database": "AISC Controls mcas", "sql": "new"})
    assert len(rows["SqlaTable"]) == 1
    assert dataset.id == 7
    assert dataset.database is project_db


def test_i10_1_isolation_a_projects_role_reaches_only_its_own_database():
    """Cross-project (I16.5 for the dashboard): with A and B registered, A's role names only A's
    objects, and A's two datasets sit on a connection to project_<A hex> and nothing else."""
    store = FakeStore()
    _register(store)
    _register(store, pid=OTHER, slug="other", name="Other")
    perms = store.items("role")[f"AiscProject_{HEX}"]["permissions"]
    assert all(OTHER_HEX not in name and name != "AISC Controls other" for _p, name in perms)
    uri_of = {k: v["sqlalchemy_uri"] for k, v in store.items("database").items()}
    for ds in (f"engine_results_{HEX}", f"controls_answers_{HEX}"):
        uri = uri_of.get(store.items("dataset")[ds]["database"], "")
        assert uri.endswith(f"/project_{HEX}"), (ds, uri)
    assert "AISC Results" not in uri_of


def test_i10_1_unregister_leaves_no_engine_dataset_of_the_project():
    """Unchanged behaviour, now with the dataset on the project connection."""
    store = FakeStore()
    _register(store)
    _projects().unregister_project(PID, store=store)
    assert f"engine_results_{HEX}" not in store.items("dataset")
    assert "AISC Controls mcas" not in store.items("database")


# ---- I10.2: no platform connection in Superset; membership over a plain DSN --

def test_i10_2_superset_config_no_longer_registers_aisc_results():
    text = (ROOT / "superset_config.py").read_text()
    assert "register_results_database(" not in text


def test_i10_2_results_db_registers_nothing_named_aisc_results():
    from aisc_ext import results_db

    uri = "postgresql+psycopg2://dashboard_ro:x@postgres:5432/platform"
    found = getattr(results_db, "registration_for", lambda env: None)({"AISC_RESULTS_DB_URI": uri})
    assert found is None or found.get("database_name") != "AISC Results"
    assert not hasattr(results_db, "register_results_database")


def test_i10_2_sso_reads_membership_over_aisc_membership_db_uri():
    text = (ROOT / "aisc_ext" / "sso.py").read_text()
    assert "AISC_MEMBERSHIP_DB_URI" in text
    assert "AISC_RESULTS_DB_URI" not in text


def test_i10_2_i17_1_the_membership_dsn_is_one_connection_per_sign_in():
    """Plain SQLAlchemy engine, disposed (or NullPool), never a Superset Database model."""
    text = (ROOT / "aisc_ext" / "sso.py").read_text()
    assert "create_engine(" in text
    assert "engine.dispose()" in text or "NullPool" in text
    assert "superset.models.core" not in text and "Database(" not in text


def test_i10_2_the_membership_dsn_is_never_registered_as_a_connection():
    """No database the bridge registers points at `platform`."""
    store = FakeStore()
    _register(store)
    for name, spec in store.items("database").items():
        assert not re.search(r"/platform(\?|$)", spec["sqlalchemy_uri"]), name


def test_i10_2_the_dashboards_compose_file_passes_the_membership_dsn():
    text = (ROOT / "docker-compose.yml").read_text()
    assert "AISC_MEMBERSHIP_DB_URI" in text


# ---- I10.4 / I17.1: no persistent pool on analytics connections --------------

def _pool_size_in(extra: str) -> int | None:
    m = re.search(r'"pool_size"\s*:\s*(\d+)', extra or "")
    return int(m.group(1)) if m else None


def test_i10_4_superset_config_sets_no_analytics_pool_above_two():
    """Superset opens query engines with NullPool unless told otherwise; nothing here tells it otherwise."""
    text = (ROOT / "superset_config.py").read_text()
    for m in re.finditer(r"pool_size['\"]?\s*[:=]\s*(\d+)", text):
        assert int(m.group(1)) <= 2, m.group(0)
    assert "QueuePool" not in text


def test_i10_4_the_project_connection_asks_for_no_pool_above_two():
    store = FakeStore()
    _register(store)
    spec = store.items("database")["AISC Controls mcas"]
    size = _pool_size_in(str(spec.get("extra", "")))
    assert size is None or size <= 2


# ---- I10.5: bridge ordering is the platform's; the bridge contract is unchanged

def test_i10_5_the_bridge_route_and_token_are_unchanged():
    """Ordering on create/delete is pinned by platform/tests/test_dashboard_bridge.py; here the
    bridge keeps its route and token check (test_project_bridge.py S11.6 cases stay green)."""
    projects = _projects()
    assert projects.authorize_bridge({}, {"DASHBOARD_BRIDGE_TOKEN": "t"}) == 401
    text = (ROOT / "aisc_ext" / "project_bridge_api.py").read_text()
    assert 'resource_name = "aisc_project"' in text
    assert '@expose("/<pid>", methods=["POST"])' in text and '@expose("/<pid>", methods=["DELETE"])' in text


@pytest.mark.parametrize("bad", ["x' OR '1'='1", "", "not-a-uuid"])
def test_i1_8_register_still_refuses_a_pid_that_is_not_a_uuid(bad):
    with pytest.raises(ValueError):
        _register(FakeStore(), pid=bad)


def test_i16_5_unregistering_one_project_leaves_the_other_projects_objects():
    """The bridge is addressed by pid: DELETE of A removes only A's connection, datasets, role,
    dashboard; B's stay and still point at project_<B hex>."""
    store = FakeStore()
    _register(store)
    _register(store, pid=OTHER, slug="other", name="Other")
    _projects().unregister_project(PID, store=store)
    datasets = store.items("dataset")
    assert f"engine_results_{OTHER_HEX}" in datasets and f"controls_answers_{OTHER_HEX}" in datasets
    assert not any(HEX in name for name in datasets)
    assert store.items("database")["AISC Controls other"]["sqlalchemy_uri"].endswith(f"/project_{OTHER_HEX}")
    assert datasets[f"engine_results_{OTHER_HEX}"]["database"] == "AISC Controls other"
