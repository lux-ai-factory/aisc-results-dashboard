# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""WP11a: one dashboard per platform project, made by the bridge.

For project P (hex = its pid without dashes) `register_project` creates, and
`unregister_project` removes:
  - dataset engine_results_<hex> on the project's own connection ("AISC
    Controls <slug>", onto project_<hex>), the engine's measurements of that
    database, each with the system version (card version) its evaluation was
    stamped with (isolation I10.1: the database is the project);
  - connection "AISC Controls <slug>" onto project_<hex> as dashboard_ro, with
    dataset controls_answers_<hex>: the answers with their stamp;
  - role AiscProject_<hex>, which may read those two datasets and nothing else;
  - dashboard aisc-<hex>, visible to that role only: a line chart of score by
    system_version and a table of answers by system_version_number.

Kept free of Superset: the module decides what should exist, and applies it
through a small store (upsert / delete / items) that Superset's models back at
runtime and a dict backs here. Every object it writes carries
`aisc_project: <pid>`, which is how unregister finds what is P's.

Rule ids are from docs/superpowers/pipeline-2026-09-23/03-specs.md.
"""
import copy
import importlib
import re
import sys
import types
import uuid

import pytest

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")
OTHER = "0b7f5c3e-2d7a-4c1e-9f64-3a1b2c3d4e5f"
OTHER_HEX = OTHER.replace("-", "")


class _Missing:
    """The module under test, imported on first use, so a missing module fails
    the test that uses it (not its setup, not collection)."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        try:
            mod = importlib.import_module(self._name)
        except ModuleNotFoundError as exc:
            pytest.fail(f"WP11 not built yet: {exc}")
        return getattr(mod, attr)


@pytest.fixture
def projects():
    return _Missing("aisc_ext.projects")


class FakeStore:
    """What Superset holds, by kind and key. Kinds: database, dataset, role,
    dashboard."""

    KINDS = ("database", "dataset", "role", "dashboard")

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
    """S11.1 / 11a: the names every other piece (role sync, bridge) relies on."""
    store = FakeStore()
    _register(projects, store)
    assert f"engine_results_{HEX}" in store.items("dataset")
    assert f"controls_answers_{HEX}" in store.items("dataset")
    assert "AISC Controls mcas" in store.items("database")
    assert f"AiscProject_{HEX}" in store.items("role")
    assert f"aisc-{HEX}" in store.items("dashboard")


def test_s11_project_role_name_helper(projects):
    assert projects.project_role_name(PID) == f"AiscProject_{HEX}"
    assert projects.project_role_name(uuid.UUID(PID)) == f"AiscProject_{HEX}"


# ---- the engine dataset ----------------------------------------------------

def test_s11_1_engine_dataset_is_on_the_project_connection_and_carries_the_version(projects):
    """S11.1 as changed by I10.1: engine_results_<hex> sits on the project's own
    connection and selects the stamp through project.system of that database."""
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
    """S11.4 as changed by I10.1: the database is the project, so the SQL names
    no pid at all and filters on nothing."""
    sql = projects.engine_results_sql()
    assert PID not in sql
    assert OTHER not in sql
    assert not re.search(r"\bwhere\b", sql, re.I)
    assert "project_id" not in sql


@pytest.mark.parametrize("bad", ["x' OR '1'='1", "", "not-a-uuid", PID + "'; drop table x; --"])
def test_s11_4_a_pid_that_is_not_a_uuid_never_reaches_the_sql(projects, bad):
    """S11.4: the pid becomes part of a connection URI and a role name, so it must be a uuid."""
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
    """S11.1: controls_answers_<hex> selects system_version_number."""
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
    """S11.3: a member's access comes only from this role."""
    store = FakeStore()
    _register(projects, store)
    perms = {tuple(p) for p in store.items("role")[f"AiscProject_{HEX}"]["permissions"]}
    assert perms == {
        ("datasource_access", f"engine_results_{HEX}"),
        ("datasource_access", f"controls_answers_{HEX}"),
        ("database_access", "AISC Controls mcas"),
    }


def test_s11_2_the_dashboard_is_for_the_project_role_and_has_both_charts(projects):
    """S11.2 / S11.3: DASHBOARD_RBAC roles, a line by version, a table by version."""
    store = FakeStore()
    _register(projects, store)
    dash = store.items("dashboard")[f"aisc-{HEX}"]
    assert dash["roles"] == [f"AiscProject_{HEX}"]
    charts = dash["charts"]
    assert any(c["kind"] == "line" and c["dataset"] == f"engine_results_{HEX}"
               and c["by"] == "system_version" for c in charts), charts
    assert any(c["kind"] == "table" and c["dataset"] == f"controls_answers_{HEX}"
               and c["by"] == "system_version_number" for c in charts), charts


def test_targets_the_dashboard_has_an_average_score_by_target_bar(projects):
    """Targets plan step 6: the average score of each metric by target, next to the two charts."""
    store = FakeStore()
    _register(projects, store)
    charts = store.items("dashboard")[f"aisc-{HEX}"]["charts"]
    assert {"kind": "bar", "dataset": f"engine_results_{HEX}", "by": "target_label", "metric": "score"} in charts
    assert len(charts) == 3


def test_targets_the_bar_chart_is_a_superset_bar_of_avg_score_by_target_per_metric(projects):
    viz, form = projects._chart_form({"kind": "bar", "dataset": "d", "by": "target_label", "metric": "score"})
    assert viz == "echarts_timeseries_bar"
    assert form["x_axis"] == "target_label"
    assert form["metrics"] == [{"label": "score", "expressionType": "SIMPLE", "aggregate": "AVG",
                                "column": {"column_name": "score"}}]
    assert form["groupby"] == ["metric"]

def test_s13_dashboard_is_published_on_registration(projects):
    """Controller ruling 13: an unpublished dashboard is invisible to every
    non-admin member (Superset's DashboardAccessFilter requires
    Dashboard.published), so register_project must publish it."""
    store = FakeStore()
    _register(projects, store)
    dash = store.items("dashboard")[f"aisc-{HEX}"]
    assert dash["published"] is True


def test_s13_supersetstore_publishes_an_existing_unpublished_dashboard_row(monkeypatch):
    """A project registered before this fix left a real Superset Dashboard row
    with published=False; the next registration pass must flip it to True in
    place, keeping its id and its role, not replace the row. Exercises
    SupersetStore._upsert_dashboard itself (the FakeStore used elsewhere is a
    plain dict and can't show this: its upsert always replaces the whole spec,
    so it can't tell "flipped in place" from "never set"), with a stand-in for
    Superset's ORM, following the pattern of
    test_isolation_dashboard.py::test_i10_1_supersetstore_keeps_the_dataset_id_when_it_moves."""
    projects = importlib.import_module("aisc_ext.projects")

    class Row:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    role = Row(name=f"AiscProject_{HEX}")
    dash = Row(id=9, slug=f"aisc-{HEX}", dashboard_title="old", json_metadata="{}",
               published=False, roles=[], slices=[])
    rows = {"Dashboard": [dash], "SqlaTable": [], "Slice": []}

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
            rows["Dashboard"].append(obj)

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

    projects.SupersetStore().upsert("dashboard", f"aisc-{HEX}", {
        "aisc_project": PID, "title": "MCAS", "roles": [role.name], "charts": [], "published": True,
    })
    assert len(rows["Dashboard"]) == 1
    assert dash.id == 9
    assert dash.published is True
    assert dash.roles == [role]


def test_s11_2_dashboard_rbac_is_switched_on():
    """S11.2 / S11.3: without DASHBOARD_RBAC, dashboard roles are ignored."""
    import pathlib
    text = (pathlib.Path(__file__).resolve().parents[1] / "superset_config.py").read_text()
    assert re.search(r"[\"']DASHBOARD_RBAC[\"']\s*:\s*True", text)


# ---- idempotence and removal -----------------------------------------------

def test_s11_register_is_idempotent(projects):
    """11a: registering twice leaves exactly what registering once does."""
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
    """S11.5: datasets, connection, role and dashboard are gone."""
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
    assert f"aisc-{OTHER_HEX}" in store.items("dashboard")
    assert f"AiscProject_{OTHER_HEX}" in store.items("role")
    assert "AISC Controls other" in store.items("database")
    assert f"aisc-{HEX}" not in store.items("dashboard")
    assert "AISC Controls mcas" not in store.items("database")


def test_s11_5_unregister_of_an_unknown_project_is_a_no_op(projects):
    store = FakeStore()
    projects.unregister_project(PID, store=store)
    assert all(store.items(k) == {} for k in FakeStore.KINDS)
