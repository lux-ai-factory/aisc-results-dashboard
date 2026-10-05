# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""One dashboard per platform project, made by the bridge.

For project P (hex = its pid without dashes) `register_project` creates, and
`unregister_project` removes:
  - dataset engine_results_<hex> on the project's own connection ("AISC
    Controls <slug>", onto project_<hex>), the engine's measurements of that
    database, each with the system version (card version) its evaluation was
    stamped with (the database is the project, so there is no pid filter);
  - connection "AISC Controls <slug>" onto project_<hex> as dashboard_ro, with
    dataset controls_answers_<hex>: the answers with their stamp;
  - role AiscProject_<hex>, which may read those two datasets and nothing else;
  - dashboard aisc-<hex>, visible to that role only: a line chart of score by
    system_version, a table of answers by system_version_number and a bar of
    the average score by target.

The module has no Superset import: it decides what should exist and applies it
through a small store (upsert / delete / items) that Superset's models back at
runtime and a dict backs here. Every object it writes carries
`aisc_project: <pid>`, which is how unregister finds what is P's.
"""
import copy
import re
import uuid

import pytest

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")
OTHER = "0b7f5c3e-2d7a-4c1e-9f64-3a1b2c3d4e5f"
OTHER_HEX = OTHER.replace("-", "")


class FakeStore:
    """What Superset holds, by kind and key. Kinds: database, dataset, role,
    dashboard."""

    KINDS = ("database", "dataset", "role", "dashboard", "chart")

    def __init__(self):
        self.objects = {k: {} for k in self.KINDS}
        self.writes = 0

    def upsert(self, kind, key, spec):
        assert kind in self.KINDS, kind
        self.objects[kind][key] = copy.deepcopy(spec)
        self.writes += 1

    def delete(self, kind, key):
        self.objects[kind].pop(key, None)

    def items(self, kind):
        return dict(self.objects[kind])


def _register(projects, store, pid=PID, slug="mcas", name="MCAS"):
    projects.register_project(pid, slug, name, store=store, controls_password="pw")


# ---- names -----------------------------------------------------------------

def test_s11_names_are_derived_from_the_pid(projects):
    """The names every other piece (role sync, bridge) relies on."""
    store = FakeStore()
    _register(projects, store)
    assert f"engine_results_{HEX}" in store.items("dataset")
    assert f"controls_answers_{HEX}" in store.items("dataset")
    assert "AISC Controls mcas" in store.items("database")
    assert f"AiscProject_{HEX}" in store.items("role")


def test_o2_registration_makes_no_project_dashboard(projects):
    """Plugin dashboards 2026-10-04 (O2): a project's charts are its plugins' tiles (aisc_ext/plugin_tiles.py),
    so registration makes no project-wide dashboard of three generic charts any more. One made before stays as
    it is: people may have added charts to it."""
    store = FakeStore()
    _register(projects, store)
    assert store.items("dashboard") == {}
    assert not hasattr(projects, "_chart_form") and not hasattr(projects, "native_filter")


def test_s11_project_role_name_helper(projects):
    assert projects.project_role_name(PID) == f"AiscProject_{HEX}"
    assert projects.project_role_name(uuid.UUID(PID)) == f"AiscProject_{HEX}"


# ---- the engine dataset ----------------------------------------------------

def test_s11_1_engine_dataset_is_on_the_project_connection_and_carries_the_version(projects):
    """engine_results_<hex> sits on the project's own connection and selects the
    stamp through project.system of that database."""
    store = FakeStore()
    _register(projects, store)
    ds = store.items("dataset")[f"engine_results_{HEX}"]
    assert ds["database"] == "AISC Controls mcas"
    sql = " ".join(ds["sql"].split()).lower()
    assert "left join project.system s on s.pid = e.system_id" in sql
    assert "s.number as system_version" in sql
    assert "s.pid as system_version_pid" in sql
    for col in ("m.score", "m.unit", "m.time", "m.dimensions", "met.name as metric",
                "e.pid as evaluation_pid", "e.created_at as evaluated_at"):
        assert col in sql, col


def test_s11_4_engine_dataset_filters_on_this_project_only(projects):
    """The database is the project, so the SQL names no pid and filters on nothing."""
    sql = projects.engine_results_sql()
    assert PID not in sql
    assert OTHER not in sql
    assert not re.search(r"\bwhere\b", sql, re.I)
    assert "project_id" not in sql


@pytest.mark.parametrize("bad", ["x' OR '1'='1", "", "not-a-uuid", PID + "'; drop table x; --"])
def test_s11_4_a_pid_that_is_not_a_uuid_never_reaches_the_sql(projects, bad):
    """The pid becomes part of a connection URI and a role name, so it must be a UUID."""
    with pytest.raises(ValueError):
        projects.register_project(bad, "s", "n", store=FakeStore(), controls_password="pw")
    with pytest.raises(ValueError):
        projects.project_role_name(bad)


# ---- the controls connection and dataset -----------------------------------

def test_s11_controls_connection_reads_the_projects_own_database_as_dashboard_ro(projects):
    store = FakeStore()
    _register(projects, store)
    db = store.items("database")["AISC Controls mcas"]
    assert db["sqlalchemy_uri"] == f"postgresql+psycopg2://dashboard_ro:pw@postgres:5432/project_{HEX}"
    assert db.get("allow_dml") in (False, None)


def test_s11_1_controls_dataset_carries_the_answer_stamp(projects):
    """controls_answers_<hex> selects system_version_number."""
    store = FakeStore()
    _register(projects, store)
    ds = store.items("dataset")[f"controls_answers_{HEX}"]
    assert ds["database"] == "AISC Controls mcas"
    sql = " ".join(ds["sql"].split()).lower()
    for col in ("c.title", "q.text", "a.answer", "a.score", "a.system_version_number",
                "a.answered_at", "s.label", "s.version as submission_version"):
        assert col in sql, col
    for table in ("controls.submission_answer a", "controls.submission s",
                  "controls.checklist_question q", "controls.checklist c"):
        assert table in sql, table


# ---- role and dashboard ----------------------------------------------------

def test_s11_3_the_project_role_reads_its_two_datasets_and_nothing_else(projects):
    """A member's access comes only from this role."""
    store = FakeStore()
    _register(projects, store)
    perms = {tuple(p) for p in store.items("role")[f"AiscProject_{HEX}"]["permissions"]}
    assert perms == {
        ("datasource_access", f"engine_results_{HEX}"),
        ("datasource_access", f"controls_answers_{HEX}"),
        ("database_access", "AISC Controls mcas"),
    }


def test_s11_2_dashboard_rbac_is_switched_on():
    """Without DASHBOARD_RBAC, dashboard roles are ignored."""
    import pathlib
    text = (pathlib.Path(__file__).resolve().parents[1] / "superset_config.py").read_text()
    assert re.search(r"[\"']DASHBOARD_RBAC[\"']\s*:\s*True", text)


# ---- idempotence and removal -----------------------------------------------

def test_s11_register_is_idempotent(projects):
    """Registering twice leaves exactly what registering once does."""
    once, twice = FakeStore(), FakeStore()
    _register(projects, once)
    _register(projects, twice)
    _register(projects, twice)
    assert twice.objects == once.objects


def test_s11_everything_registered_is_tagged_with_the_project(projects):
    store = FakeStore()
    _register(projects, store)
    for kind in FakeStore.KINDS:
        for key, spec in store.items(kind).items():
            assert spec.get("aisc_project") == PID, (kind, key)


def test_s11_5_unregister_removes_every_object_of_the_project(projects):
    """Datasets, connection, role and dashboard are gone."""
    store = FakeStore()
    _register(projects, store)
    projects.unregister_project(PID, store=store)
    for kind in FakeStore.KINDS:
        assert store.items(kind) == {} or all(
            spec.get("aisc_project") != PID for spec in store.items(kind).values()), kind


def test_s11_5_unregister_leaves_other_projects_alone(projects):
    store = FakeStore()
    _register(projects, store)
    _register(projects, store, pid=OTHER, slug="other", name="Other")
    projects.unregister_project(PID, store=store)
    assert f"AiscProject_{OTHER_HEX}" in store.items("role")
    assert "AISC Controls other" in store.items("database")
    assert "AISC Controls mcas" not in store.items("database")


def test_s11_5_unregister_of_an_unknown_project_is_a_no_op(projects):
    store = FakeStore()
    projects.unregister_project(PID, store=store)
    assert all(store.items(k) == {} for k in FakeStore.KINDS)


# ---- plugin dashboards 2026-10-04 -------------------------------------------

def test_t3_6_the_results_dataset_carries_the_latest_run_metric(projects):
    store = FakeStore()
    _register(projects, store)
    assert store.items("dataset")[f"engine_results_{HEX}"]["metrics"] == [
        {"metric_name": "latest_run", "expression": "MAX(run_order)"}]
    assert "metrics" not in store.items("dataset")[f"controls_answers_{HEX}"]


def test_t4_6_unregister_also_removes_the_projects_charts(projects):
    """Plugin dashboards are tagged like the rest, and their starter charts too (they sit on no dashboard)."""
    store = FakeStore()
    _register(projects, store)
    store.upsert("dashboard", f"aisc-{HEX}-data-monitor-datadriftplugin", {"aisc_project": PID})
    store.upsert("chart", "starter-uuid", {"aisc_project": PID})
    store.upsert("chart", "other-project-chart", {"aisc_project": OTHER})
    projects.unregister_project(PID, store=store)
    assert store.items("dashboard") == {} and list(store.items("chart")) == ["other-project-chart"]
