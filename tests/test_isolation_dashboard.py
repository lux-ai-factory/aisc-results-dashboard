# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The dashboard reads each project from that project's own database only.

No database needed: the FakeStore of test_projects.py and text scans of the modules
that import Superset (sso.py, superset_config.py, which the test environment does
not have). SupersetStore's in-place dataset move is in test_isolation_d1.py.
"""
import pathlib
import re

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
    _projects().register_project(pid, store=store, controls_password="pw")


def _engine_sql(pid=PID):
    """The engine dataset SQL, whether or not engine_results_sql takes a pid."""
    projects = _projects()
    try:
        return projects.engine_results_sql()
    except TypeError:
        return projects.engine_results_sql(pid)


def _flat(sql):
    return " ".join(sql.split()).lower()


# ---- the engine dataset sits on the project's own connection -----------------

def test_the_engine_sql_joins_project_system_and_never_core():
    sql = _flat(_engine_sql())
    assert "project.system" in sql
    assert "core." not in sql
    for table in ("engine.aisc_backend_measurement", "engine.aisc_backend_observation", "engine.aisc_backend_evaluation",
                  "engine.aisc_backend_metric"):
        assert table in sql, table
    assert "s.number as system_version" in sql and "s.pid as system_version_pid" in sql


def test_reregistering_moves_a_dataset_that_sits_on_aisc_results():
    """A dataset still on the old "AISC Results" connection is moved onto the project connection."""
    store = FakeStore()
    store.upsert("dataset", f"engine_results_{HEX}", {"aisc_project": PID, "database": "AISC Results", "sql": "old"})
    _register(store)
    assert store.items("dataset")[f"engine_results_{HEX}"]["database"] == f"AISC Controls {HEX}"


def test_isolation_a_projects_role_reaches_only_its_own_database():
    """With projects A and B registered, A's role names only A's objects, and A's two datasets
    sit on a connection to project_<A hex> and nothing else."""
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


# ---- no platform connection in Superset; membership over a plain DSN --------

def test_superset_config_no_longer_registers_aisc_results():
    text = (ROOT / "superset_config.py").read_text()
    assert "register_results_database(" not in text


def test_sso_reads_membership_over_aisc_membership_db_uri():
    text = (ROOT / "aisc_ext" / "sso.py").read_text()
    assert "AISC_MEMBERSHIP_DB_URI" in text
    assert "AISC_RESULTS_DB_URI" not in text


def test_the_membership_dsn_is_one_connection_per_sign_in():
    """Plain SQLAlchemy engine, disposed (or NullPool), never a Superset Database model."""
    text = (ROOT / "aisc_ext" / "sso.py").read_text()
    assert "create_engine(" in text
    assert "engine.dispose()" in text or "NullPool" in text
    assert "superset.models.core" not in text and "Database(" not in text


def test_the_membership_dsn_is_never_registered_as_a_connection():
    """No database the bridge registers points at `platform`."""
    store = FakeStore()
    _register(store)
    for name, spec in store.items("database").items():
        assert not re.search(r"/platform(\?|$)", spec["sqlalchemy_uri"]), name


def test_the_dashboards_compose_file_passes_the_membership_dsn():
    text = (ROOT / "docker-compose.yml").read_text()
    assert "AISC_MEMBERSHIP_DB_URI" in text


# ---- no persistent pool on query connections ---------------------------------

def test_superset_config_sets_no_analytics_pool_above_two():
    """Superset opens query engines with NullPool unless told otherwise; nothing here tells it otherwise."""
    text = (ROOT / "superset_config.py").read_text()
    for m in re.finditer(r"pool_size['\"]?\s*[:=]\s*(\d+)", text):
        assert int(m.group(1)) <= 2, m.group(0)
    assert "QueuePool" not in text


# ---- the bridge route and its token check -----------------------------------

def test_the_bridge_route_and_token_are_unchanged():
    """The bridge keeps its route and token check. The order of the platform's create and delete
    calls is tested in the aisc repo, platform/tests/test_dashboard_bridge.py."""
    projects = _projects()
    assert projects.authorize_bridge({}, {"DASHBOARD_BRIDGE_TOKEN": "t"}) == 401
    text = (ROOT / "aisc_ext" / "project_bridge_api.py").read_text()
    assert 'resource_name = "aisc_project"' in text
    assert '@expose("/<pid>", methods=["POST"])' in text and '@expose("/<pid>", methods=["DELETE"])' in text


def test_unregistering_one_project_leaves_the_other_projects_objects():
    """The bridge is addressed by pid: DELETE of A removes only A's connection, datasets, role,
    dashboard; B's stay and still point at project_<B hex>."""
    store = FakeStore()
    _register(store)
    _register(store, pid=OTHER, slug="other", name="Other")
    _projects().unregister_project(PID, store=store)
    datasets = store.items("dataset")
    assert f"engine_results_{OTHER_HEX}" in datasets and f"controls_answers_{OTHER_HEX}" in datasets
    assert not any(HEX in name for name in datasets)
    assert store.items("database")[f"AISC Controls {OTHER_HEX}"]["sqlalchemy_uri"].endswith(f"/project_{OTHER_HEX}")
    assert datasets[f"engine_results_{OTHER_HEX}"]["database"] == f"AISC Controls {OTHER_HEX}"
