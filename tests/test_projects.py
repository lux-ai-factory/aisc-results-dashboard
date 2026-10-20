# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""One dashboard per platform project, made by the bridge.

For project P (hex = its pid without dashes) `register_project` creates, and
`unregister_project` removes:
  - dataset engine_results_<hex> on the project's own connection ("AISC
    Controls <hex>", onto project_<hex>), the engine's measurements of that
    database, each with the system version (card version) its evaluation was
    stamped with (the database is the project, so there is no pid filter);
  - connection "AISC Controls <hex>" onto project_<hex> as dashboard_ro, with
    dataset controls_answers_<hex>: the answers with their stamp;
  - role AiscProject_<hex>, which may read those two datasets and nothing else;
  - dashboard aisc-<hex>, visible to that role only: a line chart of score by
    system_version, a table of answers by system_version_number and a bar of
    the average score by target.

The module has no Superset import: it decides what should exist and applies it
through a small store (upsert / delete / rename / items) that Superset's models back at
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
        self.renames = []

    def upsert(self, kind, key, spec):
        assert kind in self.KINDS, kind
        self.objects[kind][key] = copy.deepcopy(spec)
        self.writes += 1

    def delete(self, kind, key):
        self.objects[kind].pop(key, None)

    def rename(self, kind, key, new_key):
        """As Superset renames a row in place: the object keeps its spec, and a dataset on a renamed
        connection is on it under its new name (a dataset points at its connection's id)."""
        assert kind == "database", kind
        self.renames.append((kind, key, new_key))
        self.objects[kind][new_key] = self.objects[kind].pop(key)
        for spec in self.objects["dataset"].values():
            if spec.get("database") == key:
                spec["database"] = new_key

    def items(self, kind):
        return dict(self.objects[kind])

    def project_lock(self, pid):
        import contextlib

        return contextlib.nullcontext()


def _register(projects, store, pid=PID, slug="mcas", name="MCAS"):
    projects.register_project(pid, store=store, controls_password="pw")


# ---- names -----------------------------------------------------------------

def test_names_are_derived_from_the_pid(projects):
    """The names every other piece (role sync, bridge) relies on."""
    store = FakeStore()
    _register(projects, store)
    assert f"engine_results_{HEX}" in store.items("dataset")
    assert f"controls_answers_{HEX}" in store.items("dataset")
    assert f"AISC Controls {HEX}" in store.items("database")
    assert f"AiscProject_{HEX}" in store.items("role")


def test_registration_makes_no_project_dashboard(projects):
    """A project's charts are its plugins' tiles (aisc_ext/plugin_tiles.py),
    so registration makes no project-wide dashboard of three generic charts any more. One made before stays as
    it is: people may have added charts to it."""
    store = FakeStore()
    _register(projects, store)
    assert store.items("dashboard") == {}


def test_project_role_name_helper(projects):
    assert projects.project_role_name(PID) == f"AiscProject_{HEX}"
    assert projects.project_role_name(uuid.UUID(PID)) == f"AiscProject_{HEX}"


# ---- the engine dataset ----------------------------------------------------

def test_engine_dataset_is_on_the_project_connection_and_carries_the_version(projects):
    """engine_results_<hex> sits on the project's own connection and selects the
    stamp through project.system of that database."""
    store = FakeStore()
    _register(projects, store)
    ds = store.items("dataset")[f"engine_results_{HEX}"]
    assert ds["database"] == f"AISC Controls {HEX}"
    sql = " ".join(ds["sql"].split()).lower()
    assert "left join project.system s on s.pid = e.system_id" in sql
    assert "s.number as system_version" in sql
    assert "s.pid as system_version_pid" in sql
    for col in ("m.score", "m.unit", "m.time", "m.dimensions", "met.name as metric",
                "e.pid as evaluation_pid", "e.created_at as evaluated_at"):
        assert col in sql, col


def test_engine_dataset_filters_on_this_project_only(projects):
    """The database is the project, so the SQL names no pid and filters on nothing."""
    sql = projects.engine_results_sql()
    assert PID not in sql
    assert OTHER not in sql
    assert not re.search(r"\bwhere\b", sql, re.I)
    assert "project_id" not in sql


@pytest.mark.parametrize("bad", ["x' OR '1'='1", "", "not-a-uuid", PID + "'; drop table x; --"])
def test_a_pid_that_is_not_a_uuid_never_reaches_the_sql(projects, bad):
    """The pid becomes part of a connection URI and a role name, so it must be a UUID."""
    with pytest.raises(ValueError):
        projects.register_project(bad, store=FakeStore(), controls_password="pw")
    with pytest.raises(ValueError):
        projects.project_role_name(bad)


# ---- the controls connection and dataset -----------------------------------

def test_controls_connection_reads_the_projects_own_database_as_dashboard_ro(projects):
    store = FakeStore()
    _register(projects, store)
    db = store.items("database")[f"AISC Controls {HEX}"]
    assert db["sqlalchemy_uri"] == f"postgresql+psycopg2://dashboard_ro:pw@postgres:5432/project_{HEX}"
    assert db.get("allow_dml") in (False, None)


def test_controls_dataset_carries_the_answer_stamp(projects):
    """controls_answers_<hex> selects system_version_number."""
    store = FakeStore()
    _register(projects, store)
    ds = store.items("dataset")[f"controls_answers_{HEX}"]
    assert ds["database"] == f"AISC Controls {HEX}"
    sql = " ".join(ds["sql"].split()).lower()
    for col in ("c.title", "q.text", "a.answer", "a.score", "a.system_version_number",
                "a.answered_at", "s.label", "s.version as submission_version"):
        assert col in sql, col
    for table in ("controls.submission_answer a", "controls.submission s",
                  "controls.checklist_question q", "controls.checklist c"):
        assert table in sql, table


def test_controls_dataset_shows_a_closed_submission_as_it_was_answered(projects):
    """A closed submission's answer keeps its question's wording, article, category and place, and stays
    when the question is removed (questionId NULL), so the question is joined, not required; a draft
    follows today's questions. The rule of apps/controls/src/lib/answerSheet.ts."""
    store = FakeStore()
    _register(projects, store)
    sql = " ".join(store.items("dataset")[f"controls_answers_{HEX}"]["sql"].split()).lower()
    assert "left join controls.checklist_question q" in sql
    assert 'join controls.checklist c on c.id = s."checklistid"' in sql
    for kept in ("a.question_text", "a.question_article", "a.question_category", "a.question_order",
                 "s.questions_version"):
        assert kept in sql, kept
    assert "s.status = 'closed'" in sql


# ---- role and dashboard ----------------------------------------------------

def test_the_project_role_reads_its_two_datasets_and_nothing_else(projects):
    """A member's access comes only from this role."""
    store = FakeStore()
    _register(projects, store)
    perms = {tuple(p) for p in store.items("role")[f"AiscProject_{HEX}"]["permissions"]}
    assert perms == {
        ("datasource_access", f"engine_results_{HEX}"),
        ("datasource_access", f"controls_answers_{HEX}"),
        ("database_access", f"AISC Controls {HEX}"),
    }


def test_dashboard_rbac_is_switched_on():
    """Without DASHBOARD_RBAC, dashboard roles are ignored."""
    import pathlib
    text = (pathlib.Path(__file__).resolve().parents[1] / "superset_config.py").read_text()
    assert re.search(r"[\"']DASHBOARD_RBAC[\"']\s*:\s*True", text)


# ---- idempotence and removal -----------------------------------------------

def test_register_is_idempotent(projects):
    """Registering twice leaves exactly what registering once does."""
    once, twice = FakeStore(), FakeStore()
    _register(projects, once)
    _register(projects, twice)
    _register(projects, twice)
    assert twice.objects == once.objects


def test_everything_registered_is_tagged_with_the_project(projects):
    store = FakeStore()
    _register(projects, store)
    for kind in FakeStore.KINDS:
        for key, spec in store.items(kind).items():
            assert spec.get("aisc_project") == PID, (kind, key)


def test_unregister_removes_every_object_of_the_project(projects):
    """Datasets, connection, role and dashboard are gone."""
    store = FakeStore()
    _register(projects, store)
    projects.unregister_project(PID, store=store)
    for kind in FakeStore.KINDS:
        assert store.items(kind) == {} or all(
            spec.get("aisc_project") != PID for spec in store.items(kind).values()), kind


def test_unregister_of_an_unknown_project_is_a_no_op(projects):
    store = FakeStore()
    projects.unregister_project(PID, store=store)
    assert all(store.items(k) == {} for k in FakeStore.KINDS)


# ---- plugin dashboards ------------------------------------------------------

def test_the_results_dataset_carries_the_latest_run_metric(projects):
    store = FakeStore()
    _register(projects, store)
    assert store.items("dataset")[f"engine_results_{HEX}"]["metrics"] == [
        {"metric_name": "latest_run", "expression": "MAX(run_order)"}]
    assert "metrics" not in store.items("dataset")[f"controls_answers_{HEX}"]


def test_unregister_also_removes_the_projects_charts(projects):
    """Plugin dashboards are tagged like the rest, and their starter charts too (they sit on no dashboard)."""
    store = FakeStore()
    _register(projects, store)
    store.upsert("dashboard", f"aisc-{HEX}-data-monitor-datadriftplugin", {"aisc_project": PID})
    store.upsert("chart", "starter-uuid", {"aisc_project": PID})
    store.upsert("chart", "other-project-chart", {"aisc_project": OTHER})
    projects.unregister_project(PID, store=store)
    assert store.items("dashboard") == {} and list(store.items("chart")) == ["other-project-chart"]


# ---- Two registrations of one project at once -----------------------------------------------------------
# The platform registers a project right after creating it and again on its first pass after a start (and on
# retries); two at once both found no dataset and both inserted one (Superset's unique key does not hold with
# a NULL schema), so every later lookup of the project's dataset raised MultipleResultsFound. Registration and
# unregistration now hold the project's lock, as a plugin tile sync does.

class LockSpyStore(FakeStore):
    """A FakeStore that records, in order, when the project's lock is taken and released and each write."""

    def __init__(self):
        super().__init__()
        self.events = []
        self.locks = []

    def upsert(self, kind, key, spec):
        self.events.append(("upsert", kind))
        super().upsert(kind, key, spec)

    def delete(self, kind, key):
        self.events.append(("delete", kind))
        super().delete(kind, key)

    def project_lock(self, pid):
        import contextlib

        self.locks.append(pid)

        @contextlib.contextmanager
        def held():
            self.events.append("lock")
            try:
                yield
            finally:
                self.events.append("unlock")
        return held()


def test_registration_holds_the_projects_lock_around_every_write(projects):
    store = LockSpyStore()
    _register(projects, store, pid=PID.upper())
    assert store.locks == [PID]                                          # the project's own lock, by its pid
    assert store.events[0] == "lock" and store.events[-1] == "unlock"
    assert store.events.count("lock") == 1 and len(store.events) == 2 + store.writes


def test_unregistration_holds_the_projects_lock_too(projects):
    store = LockSpyStore()
    _register(projects, store)
    store.events.clear()
    projects.unregister_project(PID, store=store)
    assert store.events[0] == "lock" and store.events[-1] == "unlock"
    assert ("delete", "dataset") in store.events and store.events.count("lock") == 1


def test_the_lock_is_released_when_a_write_fails(projects):
    class Failing(LockSpyStore):
        def upsert(self, kind, key, spec):
            if kind == "role":
                raise RuntimeError("the metadata database went away")
            super().upsert(kind, key, spec)
    store = Failing()
    with pytest.raises(RuntimeError):
        _register(projects, store)
    assert store.events[-1] == "unlock"


# ---- The project connection is named by the pid, not the slug ------------------------------------------
# It was "AISC Controls <slug>": a project registered again under a new slug got a second connection, and a
# project registered with a slug another project once had took over that project's connection (its URI and
# tag). Now it is "AISC Controls <hex>"; one named by slug is renamed in place at the next registration, so
# it keeps its id and every dataset, chart and permission on it.

def _db_name(hex_=HEX):
    return f"AISC Controls {hex_}"


def test_the_connection_is_named_by_the_pid(projects):
    store = FakeStore()
    _register(projects, store)
    assert list(store.items("database")) == [_db_name()]
    assert projects.controls_database_name(PID) == _db_name()
    assert projects.controls_database_name(uuid.UUID(PID)) == _db_name()


def test_a_new_slug_keeps_the_projects_one_connection(projects):
    store = FakeStore()
    _register(projects, store)
    _register(projects, store, slug="renamed")
    assert list(store.items("database")) == [_db_name()]
    assert store.items("dataset")[f"engine_results_{HEX}"]["database"] == _db_name()
    assert ("database_access", _db_name()) in store.items("role")[f"AiscProject_{HEX}"]["permissions"]


def test_another_project_with_the_same_slug_leaves_this_connection_alone(projects):
    store = FakeStore()
    _register(projects, store)
    _register(projects, store, pid=OTHER, slug="mcas", name="Other")
    dbs = store.items("database")
    assert dbs[_db_name()]["aisc_project"] == PID
    assert dbs[_db_name()]["sqlalchemy_uri"].endswith(f"/project_{HEX}")
    assert dbs[_db_name(OTHER_HEX)]["sqlalchemy_uri"].endswith(f"/project_{OTHER_HEX}")
    assert store.items("dataset")[f"engine_results_{HEX}"]["database"] == _db_name()


def _legacy(store, pid=PID, hex_=HEX, slug="mcas"):
    """What older code left: the connection named by slug, the datasets on it."""
    store.upsert("database", f"AISC Controls {slug}", {
        "aisc_project": pid, "sqlalchemy_uri": f"postgresql+psycopg2://dashboard_ro:pw@postgres:5432/project_{hex_}",
        "allow_dml": False})
    for ds in (f"engine_results_{hex_}", f"controls_answers_{hex_}"):
        store.upsert("dataset", ds, {"aisc_project": pid, "database": f"AISC Controls {slug}", "sql": "old"})


def test_a_connection_named_by_slug_is_renamed_in_place_at_the_next_registration(projects):
    store = FakeStore()
    _legacy(store)
    _register(projects, store, slug="mcas")
    assert store.renames == [("database", "AISC Controls mcas", _db_name())]
    assert list(store.items("database")) == [_db_name()]
    assert store.items("dataset")[f"controls_answers_{HEX}"]["database"] == _db_name()
    _register(projects, store, slug="mcas")
    assert len(store.renames) == 1                                       # done once


def test_another_projects_slug_connection_is_not_renamed(projects):
    store = FakeStore()
    _legacy(store, pid=OTHER, hex_=OTHER_HEX, slug="other")
    _register(projects, store)
    assert store.renames == []
    assert store.items("database")["AISC Controls other"]["aisc_project"] == OTHER


def test_a_second_slug_connection_is_left_for_unregister(projects):
    """Registered under two slugs by older code: one connection is renamed, the other stays tagged with the
    project (nothing reads it; deleting it could trip over SQL Lab rows on it) and unregister removes it."""
    store = FakeStore()
    _legacy(store, slug="mcas")
    _legacy(store, slug="old")
    _register(projects, store)
    assert len(store.renames) == 1 and _db_name() in store.items("database")
    projects.unregister_project(PID, store=store)
    assert store.items("database") == {}


def test_superset_store_renames_the_connection_row_in_place(monkeypatch):
    """SupersetStore.rename changes database_name on the same row (same id, same uuid), and is a no-op when
    no connection has the old name."""
    import sys
    import types

    from aisc_ext import projects as p

    class Row:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    row = Row(id=5, database_name="AISC Controls mcas")
    commits = []

    class Query:
        def __init__(self, items):
            self.items = items

        def filter_by(self, **kw):
            return Query([i for i in self.items if all(getattr(i, k) == v for k, v in kw.items())])

        def one_or_none(self):
            return self.items[0] if self.items else None

    session = types.SimpleNamespace(query=lambda model: Query([row]), commit=lambda: commits.append(1))
    monkeypatch.setitem(sys.modules, "superset", types.SimpleNamespace(db=types.SimpleNamespace(session=session)))
    monkeypatch.setitem(sys.modules, "superset.models", types.ModuleType("superset.models"))
    monkeypatch.setitem(sys.modules, "superset.models.core",
                        types.SimpleNamespace(Database=type("Database", (), {})))
    store = p.SupersetStore()
    store.rename("database", "AISC Controls mcas", _db_name())
    assert row.database_name == _db_name() and row.id == 5 and commits
    store.rename("database", "AISC Controls gone", "AISC Controls x")
    assert row.database_name == _db_name()


def test_a_persons_untagged_chart_on_the_projects_dataset_is_the_projects(projects):
    """Unregister found charts by their aisc_project tag only. An imported chart
    (the import strips the tag) or one built from the dataset list carries none: once off every dashboard, it
    stayed after the project was deleted, on a dataset id that no longer exists, with its name and filters
    (people's text). A chart reading one of the project's datasets is the project's, tag or not."""
    import json

    datasets = {5: PID, 6: OTHER}
    found = projects.charts_of([
        ("u-tagged", json.dumps({projects.PROJECT_TAG: PID}), "table", 99),
        ("u-mine", json.dumps({"viz_type": "table"}), "table", 5),
        ("u-other", json.dumps({}), "table", 6),
        ("u-elsewhere", json.dumps({}), "table", 7),
        ("u-query", json.dumps({}), "query", 5),
        ("u-broken", "not json", "table", 5),
    ], datasets)
    assert found == {"u-tagged": {projects.PROJECT_TAG: PID}, "u-mine": {projects.PROJECT_TAG: PID},
                     "u-other": {projects.PROJECT_TAG: OTHER}, "u-broken": {projects.PROJECT_TAG: PID}}


def test_the_store_reads_charts_through_it():
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "aisc_ext/projects.py").read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "SupersetStore")
    text = ast.get_source_segment(src, next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_items_chart"))
    assert "charts_of(" in text
