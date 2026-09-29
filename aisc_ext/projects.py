# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""One dashboard per platform project.

For project P (hex = its pid without dashes) `register_project` makes, and
`unregister_project` removes:

- connection ``AISC Controls <slug>`` onto P's own database ``project_<hex>``
  as dashboard_ro (the name is historical: it now carries every dataset of P);
- dataset ``engine_results_<hex>`` on that connection: the engine's
  measurements in P's database, each with the AI card version its evaluation
  was stamped with (from ``project.system`` of the same database). No pid
  filter: the database is the project (isolation I10.1);
- dataset ``controls_answers_<hex>`` on that connection: the answers with their
  stamp;
- role ``AiscProject_<hex>``, which may read those two datasets and nothing else;
- dashboard ``aisc-<hex>``, for that role only: a line of score by
  system_version and a table of answers by system_version_number.

The module decides what should exist and applies it through a store with three
methods (``upsert``, ``delete``, ``items``). Superset backs it at runtime
(``SupersetStore``); a dict backs it in the tests. Every object carries
``aisc_project: <pid>``, which is how unregister finds what is P's. No Superset
import at module level, so this unit-tests without the app.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import uuid

from aisc_ext.results_db import READ_ONLY_ROLE

_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_PID_HEX = re.compile(r"[0-9a-f]{32}")

ROLE_PREFIX = "AiscProject_"
#: The key every object of a project carries, with the project's pid as value.
PROJECT_TAG = "aisc_project"

#: The projects a person is in, read at sign-in over AISC_MEMBERSHIP_DB_URI
#: (dashboard_ro on `platform`, never a Superset connection; see results_db).
#: No trailing semicolon: callers may wrap or append.
MEMBER_PROJECTS_SQL = "SELECT project_id FROM core.project_member WHERE subject = %(subject)s"

_ENGINE_RESULTS_SQL = """
SELECT m.pid, m.score, m.unit, m.time, m.dimensions, met.name AS metric,
       e.pid AS evaluation_pid, e.created_at AS evaluated_at,
       s.pid AS system_version_pid, s.number AS system_version
  FROM engine.aisc_backend_measurement m
  JOIN engine.aisc_backend_observation o ON o.id = m.observation_id
  JOIN engine.aisc_backend_evaluation e ON e.id = o.evaluation_id
  JOIN engine.aisc_backend_metric met ON met.id = m.metric_id
  LEFT JOIN project.system s ON s.pid = e.system_id
"""

_CONTROLS_ANSWERS_SQL = """
SELECT c.title, q.text, a.answer, a.score, a.system_version_number, a.answered_at,
       s.label, s.version AS submission_version
  FROM controls.submission_answer a
  JOIN controls.submission s ON s.id = a."submissionId"
  JOIN controls.checklist_question q ON q.id = a."questionId"
  JOIN controls.checklist c ON c.id = q."checklistId"
"""


#: The columns each dataset's SQL returns, in order, with the type Superset gives them (the strings
#: its own inference produced on this stack, 2026-09-29). Declared rather than asked for: Superset
#: finds a virtual dataset's columns by running the query with LIMIT 1 and reports none when the
#: result is empty, and a project is registered before it has any row. Kept in step with the SQL by
#: tests/test_project_datasets_db.py (T5).
ENGINE_RESULTS_COLUMNS = (
    ("pid", "STRING"), ("score", "FLOAT"), ("unit", "STRING"), ("time", "DATETIMETZ"),
    ("dimensions", "JSONB"), ("metric", "STRING"), ("evaluation_pid", "STRING"),
    ("evaluated_at", "DATETIMETZ"), ("system_version_pid", "STRING"), ("system_version", "INTEGER"),
)
CONTROLS_ANSWERS_COLUMNS = (
    ("title", "STRING"), ("text", "STRING"), ("answer", "STRING"), ("score", "INTEGER"),
    ("system_version_number", "INTEGER"), ("answered_at", "DATETIMETZ"), ("label", "STRING"),
    ("submission_version", "INTEGER"),
)


def _pid(value) -> str:
    """A project pid as lowercase text; ValueError unless it is a uuid. It
    becomes part of a connection URI, a role and object names, so nothing else
    may get through."""
    text = str(value).lower()
    if not _PID.match(text):
        raise ValueError(f"not a project pid: {value!r}")
    return text


def _hex(pid) -> str:
    return _pid(pid).replace("-", "")


def project_role_name(pid) -> str:
    """The Superset role a member of the project gets at login."""
    return f"{ROLE_PREFIX}{_hex(pid)}"


def engine_results_sql() -> str:
    """The engine's measurements of the project database the connection points
    at, with the card version. Takes no pid: each project database holds exactly
    one project's engine rows."""
    return _ENGINE_RESULTS_SQL


def controls_answers_sql() -> str:
    """The answers of the project database the connection points at, with their stamp."""
    return _CONTROLS_ANSWERS_SQL


def controls_database_name(slug: str) -> str:
    return f"AISC Controls {slug}"


def register_project(pid, slug: str, name: str, *, store, controls_password: str) -> None:
    """Make (or bring up to date) every dashboard object of the project. Idempotent."""
    pid = _pid(pid)
    hex_ = _hex(pid)
    database = controls_database_name(slug)
    engine_ds, controls_ds = f"engine_results_{hex_}", f"controls_answers_{hex_}"
    role = project_role_name(pid)
    host = os.environ.get("AISC_PROJECT_DB_HOSTPORT", "postgres:5432")
    tag = {PROJECT_TAG: pid}
    store.upsert("database", database, {
        **tag,
        "sqlalchemy_uri": f"postgresql+psycopg2://{READ_ONLY_ROLE}:{controls_password}@{host}/project_{hex_}",
        "allow_dml": False,
    })
    # A dataset registered before the isolation sits on "AISC Results"; this
    # upsert moves it onto the project connection and keeps its id (I10.1).
    store.upsert("dataset", engine_ds, {**tag, "database": database, "sql": engine_results_sql(),
                                        "columns": [list(c) for c in ENGINE_RESULTS_COLUMNS]})
    store.upsert("dataset", controls_ds, {**tag, "database": database, "sql": controls_answers_sql(),
                                          "columns": [list(c) for c in CONTROLS_ANSWERS_COLUMNS]})
    store.upsert("role", role, {**tag, "permissions": [
        ("datasource_access", engine_ds),
        ("datasource_access", controls_ds),
        ("database_access", database),
    ]})
    store.upsert("dashboard", f"aisc-{hex_}", {
        **tag,
        "title": name,
        "roles": [role],
        # Superset's DashboardAccessFilter shows an unpublished dashboard to
        # nobody but its owners and admins. This dashboard has no owners
        # (S11.2/S11.3: DASHBOARD_RBAC and the project role decide who may see
        # it), so it must be published or every member gets 0 dashboards.
        # Unconditional, so a project registered before this existed heals on
        # its next registration pass too.
        "published": True,
        "charts": [
            {"kind": "line", "dataset": engine_ds, "by": "system_version", "metric": "score"},
            {"kind": "table", "dataset": controls_ds, "by": "system_version_number"},
        ],
    })


def unregister_project(pid, *, store) -> None:
    """Remove every dashboard object of the project; an unknown project is a no-op."""
    pid = _pid(pid)
    # the dashboard first, then what it reads, then who may read it
    for kind in ("dashboard", "dataset", "database", "role"):
        for key, spec in list(store.items(kind).items()):
            if spec.get(PROJECT_TAG) == pid:
                store.delete(kind, key)


def authorize_bridge(headers, env) -> int | None:
    """401 unless the call carries the bridge token; None when it may go on.

    No DASHBOARD_BRIDGE_TOKEN configured means no bridge, not an open one.
    Compared in constant time."""
    expected = env.get("DASHBOARD_BRIDGE_TOKEN") or ""
    given = headers.get("X-AISC-Bridge-Token") or ""
    if not expected or not hmac.compare_digest(given, expected):
        return 401
    return None


def _chart_form(chart) -> tuple[str, dict]:
    """The Superset viz type and form data for one chart of a project dashboard:
    a line of the average metric along ``by``, or a raw table of the answers."""
    if chart["kind"] == "line":
        return "echarts_timeseries_line", {
            "x_axis": chart["by"],
            "metrics": [{"label": chart["metric"], "expressionType": "SIMPLE", "aggregate": "AVG",
                         "column": {"column_name": chart["metric"]}}],
            "groupby": ["metric"],
        }
    columns = [chart["by"], "title", "text", "answer", "score"]
    return "table", {"groupby": columns, "query_mode": "raw", "all_columns": list(columns)}


class SupersetStore:
    """The store on Superset's own models. Runtime only: every import is inside
    a method, and it is not covered by the unit tests; it is checked by hand
    on a live Superset."""

    def _db(self):
        from superset import db  # type: ignore

        return db

    @staticmethod
    def _extra(obj) -> dict:
        try:
            return json.loads(getattr(obj, "extra", None) or getattr(obj, "json_metadata", None) or "{}")
        except ValueError:
            return {}

    def upsert(self, kind: str, key: str, spec: dict) -> None:
        getattr(self, f"_upsert_{kind}")(key, spec)
        self._db().session.commit()

    def delete(self, kind: str, key: str) -> None:
        getattr(self, f"_delete_{kind}")(key)
        self._db().session.commit()

    def items(self, kind: str) -> dict[str, dict]:
        return getattr(self, f"_items_{kind}")()

    def _tagged(self, objects, name_of) -> dict[str, dict]:
        """The objects that carry a project tag, by name, as ``{tag: pid}``."""
        out = {}
        for obj in objects:
            extra = self._extra(obj)
            if PROJECT_TAG in extra:
                out[name_of(obj)] = {PROJECT_TAG: extra[PROJECT_TAG]}
        return out

    # ---- databases -------------------------------------------------------
    def _upsert_database(self, key, spec):
        from superset.models.core import Database  # type: ignore

        session = self._db().session
        found = session.query(Database).filter_by(database_name=key).one_or_none()
        if found is None:
            found = Database(database_name=key)
            session.add(found)
        found.sqlalchemy_uri = spec["sqlalchemy_uri"]
        found.set_sqlalchemy_uri(spec["sqlalchemy_uri"])
        found.allow_dml = bool(spec.get("allow_dml"))
        found.extra = json.dumps({PROJECT_TAG: spec[PROJECT_TAG]})

    def _delete_database(self, key):
        from superset.models.core import Database  # type: ignore

        session = self._db().session
        for found in session.query(Database).filter_by(database_name=key):
            session.delete(found)

    def _items_database(self):
        from superset.models.core import Database  # type: ignore

        return self._tagged(self._db().session.query(Database), lambda d: d.database_name)

    # ---- datasets --------------------------------------------------------
    def _upsert_dataset(self, key, spec):
        from superset.connectors.sqla.models import SqlaTable  # type: ignore
        from superset.models.core import Database  # type: ignore

        session = self._db().session
        database = session.query(Database).filter_by(database_name=spec["database"]).one()
        found = session.query(SqlaTable).filter_by(table_name=key).one_or_none()
        if found is None:
            found = SqlaTable(table_name=key)
            session.add(found)
        # A dataset that moves connection keeps its id. Its permission names
        # (perm, schema_perm) are left alone on purpose: Superset's own
        # dataset_before_update hook sees the database change, renames the
        # dataset's view menu from the old perm (so every role that held it keeps
        # it) and rewrites tables.perm and the perm of every chart on it. Setting
        # perm here first would make old and new names equal and skip all that.
        found.database = database
        found.sql = spec["sql"]
        found.extra = json.dumps({PROJECT_TAG: spec[PROJECT_TAG]})
        session.flush()
        if spec.get("columns"):
            self._sync_columns(found, spec["columns"])

    @staticmethod
    def _sync_columns(dataset, declared) -> None:
        """Make the dataset's columns the declared ones, the way fetch_metadata would from a row:
        a column already there keeps its object (and id), a new one is made, one no longer
        declared goes, a calculated one (with an expression) stays. Never runs the query."""
        from superset.connectors.sqla.models import TableColumn  # type: ignore

        existing = {c.column_name: c for c in dataset.columns}
        columns = []
        for name, type_ in declared:
            column = existing.get(name)
            if column is None or column.expression:
                column = TableColumn(column_name=name)
            column.type, column.expression = type_, ""
            column.is_dttm = type_.startswith("DATETIME")
            column.groupby = column.filterable = True
            columns.append(column)
        declared_names = {name for name, _ in declared}
        columns += [c for c in dataset.columns if c.expression and c.column_name not in declared_names]
        dataset.columns = columns
        dataset.main_dttm_col = next((c.column_name for c in columns if c.is_dttm), None)

    def _delete_dataset(self, key):
        from superset.connectors.sqla.models import SqlaTable  # type: ignore

        session = self._db().session
        for found in session.query(SqlaTable).filter_by(table_name=key):
            session.delete(found)

    def _items_dataset(self):
        from superset.connectors.sqla.models import SqlaTable  # type: ignore

        return self._tagged(self._db().session.query(SqlaTable), lambda t: t.table_name)

    # ---- roles -----------------------------------------------------------
    def _sm(self):
        from flask import current_app

        return current_app.appbuilder.sm

    def _upsert_role(self, key, spec):
        from superset.connectors.sqla.models import SqlaTable  # type: ignore
        from superset.models.core import Database  # type: ignore

        sm, session = self._sm(), self._db().session
        role = sm.find_role(key) or sm.add_role(key)
        wanted = []
        for permission, name in spec["permissions"]:
            if permission == "datasource_access":
                obj = session.query(SqlaTable).filter_by(table_name=name).one_or_none()
            else:
                obj = session.query(Database).filter_by(database_name=name).one_or_none()
            if obj is None:
                continue
            pv = sm.add_permission_view_menu(permission, obj.perm)
            wanted.append(pv)
        role.permissions = wanted

    def _delete_role(self, key):
        sm = self._sm()
        role = sm.find_role(key)
        if role is not None:
            self._db().session.delete(role)

    def _items_role(self):
        out = {}
        for role in self._sm().get_all_roles():
            if role.name.startswith(ROLE_PREFIX):
                hex_ = role.name[len(ROLE_PREFIX):]
                if _PID_HEX.fullmatch(hex_):
                    out[role.name] = {PROJECT_TAG: str(uuid.UUID(hex_))}
        return out

    # ---- dashboards ------------------------------------------------------
    def _upsert_dashboard(self, key, spec):
        from superset.connectors.sqla.models import SqlaTable  # type: ignore
        from superset.models.dashboard import Dashboard  # type: ignore
        from superset.models.slice import Slice  # type: ignore

        sm, session = self._sm(), self._db().session
        found = session.query(Dashboard).filter_by(slug=key).one_or_none()
        if found is None:
            found = Dashboard(slug=key)
            session.add(found)
        found.dashboard_title = spec.get("title") or key
        found.json_metadata = json.dumps({PROJECT_TAG: spec[PROJECT_TAG]})
        found.published = bool(spec.get("published"))
        found.roles = [r for r in (sm.find_role(name) for name in spec["roles"]) if r is not None]
        slices = []
        for chart in spec["charts"]:
            table = session.query(SqlaTable).filter_by(table_name=chart["dataset"]).one_or_none()
            if table is None:
                continue
            name = f"{key} {chart['kind']} by {chart['by']}"
            piece = session.query(Slice).filter_by(slice_name=name).one_or_none() or Slice(slice_name=name)
            piece.viz_type, params = _chart_form(chart)
            piece.datasource_type = "table"
            piece.datasource_id = table.id
            piece.params = json.dumps({**params, "datasource": f"{table.id}__table"})
            session.add(piece)
            slices.append(piece)
        found.slices = slices

    def _delete_dashboard(self, key):
        from superset.models.dashboard import Dashboard  # type: ignore

        session = self._db().session
        for found in session.query(Dashboard).filter_by(slug=key):
            for piece in list(found.slices):
                session.delete(piece)
            session.delete(found)

    def _items_dashboard(self):
        from superset.models.dashboard import Dashboard  # type: ignore

        dashboards = (d for d in self._db().session.query(Dashboard) if d.slug)
        return self._tagged(dashboards, lambda d: d.slug)
