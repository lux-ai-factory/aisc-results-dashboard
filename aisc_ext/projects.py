# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""A platform project's objects in the dashboard.

For project P (hex = its pid without dashes) `register_project` makes, and
`unregister_project` removes:

- connection ``AISC Controls <hex>`` onto P's own database ``project_<hex>``
  as dashboard_ro (the prefix is historical: it now carries every dataset of P). Named by the pid, not
  the slug, as a slug can change or be reused; one named ``AISC Controls <slug>`` by older code is
  renamed in place at the next registration;
- dataset ``engine_results_<hex>`` on that connection: the engine's
  measurements in P's database, each with the AI card version its evaluation
  was stamped with (from ``project.system`` of the same database). No pid
  filter: the database is the project;
- dataset ``controls_answers_<hex>`` on that connection: the answers with their
  stamp, a closed submission's with the questions as it answered them;
- role ``AiscProject_<hex>``, which may read those two datasets and nothing else.

Its charts are its plugins' tiles: one dashboard per plugin, made from the plugin's default charts
(aisc_ext/plugin_tiles.py, aisc_ext/charts.py). Older code made one dashboard ``aisc-<hex>`` of three
generic charts per project; such a dashboard is left as it is, and unregister removes it with the plugin
dashboards.

The module decides what should exist and applies it through a store with four
methods (``upsert``, ``delete``, ``rename``, ``items``). Superset backs it at runtime
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

from aisc_ext import charts
from aisc_ext.results_db import READ_ONLY_ROLE

_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_PID_HEX = re.compile(r"[0-9a-f]{32}")

ROLE_PREFIX = "AiscProject_"
#: An owner's or editor's second project role: it may write charts and dashboards, so they can build
#: charts on their plugin dashboards. What they read stays the project role's datasets, so a chart they build shows only their
#: project; which dashboards they may change is decided by ownership, given at sign-in (aisc_ext/sso.py).
EDITOR_ROLE_PREFIX = "AiscProjectEditor_"
EDITOR_PERMISSIONS = (("can_write", "Chart"), ("can_write", "Dashboard"))
#: The key every object of a project carries, with the project's pid as value.
PROJECT_TAG = "aisc_project"
#: The account the bridge's imports run as (Superset's import records who imports, for owners). Made at start
#: by superset_config._install_extension, inactive and without a password: nobody signs in with it.
BRIDGE_USER = "aisc-bridge"

#: The projects a person is in, read at sign-in over AISC_MEMBERSHIP_DB_URI
#: (dashboard_ro on `platform`, never a Superset connection; see results_db).
#: No trailing semicolon: callers may wrap or append.
MEMBER_PROJECTS_SQL = "SELECT project_id, role FROM core.project_member WHERE subject = %(subject)s"

#: Each measurement's target is its own plugin run's: an evaluation may run several plugins, each
#: with its own inputs, and the engine names an observation's plugin only in ``tool``
#: (``str(plugin)``, "<package>::<name> (v<version>)"), matched here in a nested join (one config
#: and one plugin per run, so no row is repeated; and no WHERE, test_s11_4). The run's input named
#: ``target`` points at a platform-kept mirror component, which target.target names
#: (engine_component). Of pluginconfig only id and plugin_id are read: the readers may not see its
#: config.
#: target_status: 'unassigned' (the run has no ``target`` input, as every evaluation made before
#: targets), 'not a target' (its component is no mirror), 'stale' (a component the latest card no
#: longer lists), else 'current'. target_label is never NULL, so no chart shows an empty label.
#: The dimensions plugins write: each key a column of its own, so a
#: chart can group by it. Text keys as they are; statistic and p_value are numbers sent as strings
#: (the engine takes no floats in dimensions), cast back here, NULL when not a number ("nan").
DIMENSION_COLUMNS = ("feature", "concern", "flag", "language", "input_type", "reflection_type", "model",
                     # LangBiTe's failed cases (0.2.6): the prompt as sent, the answer as given, what was expected
                     "prompt", "response", "expected")
NUMERIC_DIMENSION_COLUMNS = ("statistic", "p_value")
NUMBER_PATTERN = r"^[-+]?([0-9]+[.]?[0-9]*|[.][0-9]+)([eE][-+]?[0-9]+)?$"

_ENGINE_RESULTS_SQL = """
SELECT m.pid, m.score, m.unit, m.time, m.dimensions, met.name AS metric,
       e.pid AS evaluation_pid, e.created_at AS evaluated_at,
       s.pid AS system_version_pid, s.number AS system_version,
       t.key AS target_key, t.kind AS target_kind, t.component_kind AS target_component_kind,
       CASE WHEN ti.id IS NULL THEN 'unassigned'
            WHEN t.key IS NULL THEN tc.name::text
            ELSE t.label END AS target_label,
       CASE WHEN ti.id IS NULL THEN 'unassigned'
            WHEN t.key IS NULL THEN 'not a target'
            WHEN t.kind = 'component'
                 AND t.last_card_number < (SELECT max(number) FROM project.system) THEN 'stale'
            ELSE 'current' END AS target_status,
       COALESCE(p.display_name, p.name, 'unknown') AS tool,
       -- the run as people name it: its number among the project's evaluations, and when it ran
       'Run ' || dense_rank() OVER (ORDER BY e.created_at, e.id) || ' · ' ||
           to_char(e.created_at, 'DD Mon YYYY, HH24:MI') AS run,
       dense_rank() OVER (ORDER BY e.created_at, e.id) AS run_order,
       {dimensions}
  FROM engine.aisc_backend_measurement m
  JOIN engine.aisc_backend_observation o ON o.id = m.observation_id
  JOIN engine.aisc_backend_evaluation e ON e.id = o.evaluation_id
  JOIN engine.aisc_backend_metric met ON met.id = m.metric_id
  LEFT JOIN project.system s ON s.pid = e.system_id
  LEFT JOIN (engine.aisc_backend_evaluationplugin ep
             JOIN engine.aisc_backend_pluginconfig pc ON pc.id = ep.plugin_config_id
             JOIN engine.aisc_backend_plugin p ON p.id = pc.plugin_id)
         ON ep.evaluation_id = e.id
        AND o.tool = p.package_name || '::' || p.name || ' (v' || p.version || ')'
  LEFT JOIN engine.aisc_backend_evaluationinput ti ON ti.evaluation_plugin_id = ep.id AND ti.name = 'target'
  LEFT JOIN engine.aisc_backend_aicomponent tc ON tc.id = ti.component_id
  LEFT JOIN target.target t ON t.engine_component = tc.pid
"""
_ENGINE_RESULTS_SQL = _ENGINE_RESULTS_SQL.replace("{dimensions}", ",\n       ".join(
    [f"m.dimensions->>'{key}' AS {key}" for key in DIMENSION_COLUMNS]
    + [f"CASE WHEN m.dimensions->>'{key}' ~ '{NUMBER_PATTERN}' THEN (m.dimensions->>'{key}')::double precision "
       f"END AS {key}" for key in NUMERIC_DIMENSION_COLUMNS]))

#: The answers as their submission shows them (the controls app's rule, apps/controls/src/lib/answerSheet.ts):
#: a draft follows today's questions; a closed submission shows each answer with its question as it was
#: when closed (text, article, category, place), an answer to a question removed since included (its
#: questionId is NULL). An answer closed before the wording was kept (question_text NULL) takes today's
#: question, and is left out when that is gone too. Unanswered questions have no row here.
_CONTROLS_ANSWERS_SQL = """
SELECT c.title,
       CASE WHEN kept THEN a.question_text ELSE q.text END AS text,
       CASE WHEN kept THEN a.question_article ELSE q.article END AS article,
       CASE WHEN kept THEN a.question_category ELSE q.category END AS category,
       CASE WHEN kept THEN COALESCE(a.question_order, q."order", 0) ELSE q."order" END AS question_order,
       a.answer, a.score, a.system_version_number, a.answered_at,
       s.label, s.version AS submission_version, s.questions_version
  FROM controls.submission_answer a
  JOIN controls.submission s ON s.id = a."submissionId"
  JOIN controls.checklist c ON c.id = s."checklistId"
  LEFT JOIN controls.checklist_question q ON q.id = a."questionId"
  CROSS JOIN LATERAL (SELECT s.status = 'Closed' AND a.question_text IS NOT NULL AS kept) k
 WHERE kept OR q.id IS NOT NULL
"""


#: The columns each dataset's SQL returns, in order, with the type Superset gives them (the strings
#: its own inference produces for this SQL). Declared rather than asked for: Superset
#: finds a virtual dataset's columns by running the query with LIMIT 1 and reports none when the
#: result is empty, and a project is registered before it has any row. Kept in step with the SQL by
#: tests/test_project_datasets_db.py.
ENGINE_RESULTS_COLUMNS = (
    ("pid", "STRING"), ("score", "FLOAT"), ("unit", "STRING"), ("time", "DATETIMETZ"),
    ("dimensions", "JSONB"), ("metric", "STRING"), ("evaluation_pid", "STRING"),
    ("evaluated_at", "DATETIMETZ"), ("system_version_pid", "STRING"), ("system_version", "INTEGER"),
    ("target_key", "STRING"), ("target_kind", "STRING"), ("target_component_kind", "STRING"),
    ("target_label", "STRING"), ("target_status", "STRING"), ("tool", "STRING"),
    ("run", "STRING"), ("run_order", "INTEGER"),
) + tuple((key, "STRING") for key in DIMENSION_COLUMNS) + tuple((key, "FLOAT") for key in NUMERIC_DIMENSION_COLUMNS)
CONTROLS_ANSWERS_COLUMNS = (
    ("title", "STRING"), ("text", "STRING"), ("article", "STRING"), ("category", "STRING"),
    ("question_order", "INTEGER"), ("answer", "STRING"), ("score", "INTEGER"),
    ("system_version_number", "INTEGER"), ("answered_at", "DATETIMETZ"), ("label", "STRING"),
    ("submission_version", "INTEGER"), ("questions_version", "INTEGER"),
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


def editor_role_name(pid) -> str:
    return f"{EDITOR_ROLE_PREFIX}{_hex(pid)}"


def project_role_name(pid) -> str:
    """The Superset role a member of the project gets at login."""
    return f"{ROLE_PREFIX}{_hex(pid)}"


def engine_results_sql() -> str:
    """The engine's measurements of the project database the connection points
    at, with the card version. Takes no pid: each project database holds exactly
    one project's engine rows."""
    return _ENGINE_RESULTS_SQL


def controls_answers_sql() -> str:
    """The answers of the project database the connection points at, with their stamp, as their submission
    shows them (_CONTROLS_ANSWERS_SQL)."""
    return _CONTROLS_ANSWERS_SQL


def controls_database_name(pid) -> str:
    """The project's connection, by its pid: a slug can change or be reused by another project."""
    return f"AISC Controls {_hex(pid)}"


def project_lock_key(pid) -> int:
    """The project's key for pg_advisory_lock (a bigint): the first 8 bytes of its uuid."""
    return int.from_bytes(uuid.UUID(_pid(pid)).bytes[:8], "big", signed=True)


def results_dataset_spec(pid, database: str) -> dict:
    """The project's results dataset as this code defines it: what register_project writes, and what a tile
    sync writes again when the dataset was registered by older code (aisc_ext/plugin_tiles.py)."""
    return {PROJECT_TAG: str(_pid(pid)), "database": database, "sql": engine_results_sql(),
            "columns": [list(c) for c in ENGINE_RESULTS_COLUMNS],
            # the Run filter sorts by it, newest first (aisc_ext/charts.py)
            "metrics": charts.dataset_metrics()}


def results_dataset_current(sql: str | None, columns) -> bool:
    """Whether the registered dataset is the one this code defines: its SQL, and every column."""
    return sql == engine_results_sql() and {c[0] for c in ENGINE_RESULTS_COLUMNS} <= set(columns or [])


def register_project(pid, *, store, controls_password: str) -> None:
    """Make (or bring up to date) every dashboard object of the project. Idempotent.

    Holds the project's lock throughout, as a plugin tile sync does: the platform may register one project
    twice at once (right after creating it, and on its pass over unregistered projects), and two upserts of
    one dataset would both insert it."""
    pid = _pid(pid)
    with store.project_lock(pid):
        _register(pid, store=store, controls_password=controls_password)


def _register(pid, *, store, controls_password: str) -> None:
    hex_ = _hex(pid)
    database = controls_database_name(pid)
    engine_ds, controls_ds = f"engine_results_{hex_}", f"controls_answers_{hex_}"
    role = project_role_name(pid)
    host = os.environ.get("AISC_PROJECT_DB_HOSTPORT", "postgres:5432")
    tag = {PROJECT_TAG: pid}
    _rename_slug_connection(pid, database, store=store)
    store.upsert("database", database, {
        **tag,
        "sqlalchemy_uri": f"postgresql+psycopg2://{READ_ONLY_ROLE}:{controls_password}@{host}/project_{hex_}",
        "allow_dml": False,
    })
    # A dataset registered before the isolation sits on "AISC Results"; this
    # upsert moves it onto the project connection and keeps its id.
    store.upsert("dataset", engine_ds, results_dataset_spec(pid, database))
    store.upsert("dataset", controls_ds, {**tag, "database": database, "sql": controls_answers_sql(),
                                          "columns": [list(c) for c in CONTROLS_ANSWERS_COLUMNS]})
    store.upsert("role", role, {**tag, "permissions": [
        ("datasource_access", engine_ds),
        ("datasource_access", controls_ds),
        ("database_access", database),
    ]})
    store.upsert("role", editor_role_name(pid), {**tag, "permissions": [list(p) for p in EDITOR_PERMISSIONS]})
    # No project-wide dashboard any more: a project's charts are its
    # plugins' tiles (aisc_ext/plugin_tiles.py). One made before is left as it is.


def _rename_slug_connection(pid, database: str, *, store) -> None:
    """A connection of the project named by its slug (by older code) gets the pid name, in place: it keeps
    its id, so its datasets, their charts and the roles' permissions stay on it. Only when the pid name is
    not taken yet; a second slug connection stays tagged with the project, unread, until unregister."""
    current = store.items("database")
    if database in current:
        return
    for name in sorted(current):
        if current[name].get(PROJECT_TAG) == pid:
            store.rename("database", name, database)
            return


def unregister_project(pid, *, store) -> None:
    """Remove every dashboard object of the project; an unknown project is a no-op. Under the project's lock,
    so it never interleaves with a registration or a tile sync of the same project."""
    pid = _pid(pid)
    with store.project_lock(pid):
        _unregister(pid, store=store)


def _unregister(pid, *, store) -> None:
    # the dashboards first (their charts with them), then the charts on none (the plugins' starters), then
    # what they read, then who may read it
    for kind in ("dashboard", "chart", "dataset", "database", "role"):
        for key, spec in list(store.items(kind).items()):
            if spec.get(PROJECT_TAG) == pid:
                store.delete(kind, key)


def charts_of(charts, datasets) -> dict[str, dict]:
    """The charts that are a project's, by uuid, as ``{PROJECT_TAG: pid}``.

    charts: [(uuid, params JSON, datasource_type, datasource_id)]; datasets: {dataset id: pid}, the projects'
    datasets. A chart is a project's when its params carry the tag (the plugins' starters) or when it reads
    one of the project's datasets: an imported chart (the import strips the tag) or one built from the
    dataset list carries none, and stayed behind when the project was deleted."""
    out = {}
    for key, params, source_type, source_id in charts:
        try:
            tag = (json.loads(params or "{}") or {}).get(PROJECT_TAG)
        except (TypeError, ValueError, AttributeError):
            tag = None
        if tag is None and source_type == "table":
            tag = datasets.get(source_id)
        if tag is not None:
            out[str(key)] = {PROJECT_TAG: tag}
    return out


def dashboard_ro_password(env) -> str:
    """dashboard_ro's password for the project connections, from DASHBOARD_RO_PASSWORD only (made by the
    aisc repo's scripts/secrets.sh). Raises LookupError without one: the role's own name is no password."""
    password = (env.get("DASHBOARD_RO_PASSWORD") or "").strip()
    if not password:
        raise LookupError("DASHBOARD_RO_PASSWORD is not set: run the aisc repo's scripts/secrets.sh")
    return password


def authorize_bridge(headers, env) -> int | None:
    """401 unless the call carries the bridge token; None when it may go on.

    No DASHBOARD_BRIDGE_TOKEN configured means no bridge, not an open one.
    Compared in constant time."""
    expected = env.get("DASHBOARD_BRIDGE_TOKEN") or ""
    given = headers.get("X-AISC-Bridge-Token") or ""
    if not expected or not hmac.compare_digest(given, expected):
        return 401
    return None


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

    def rename(self, kind: str, key: str, new_key: str) -> None:
        getattr(self, f"_rename_{kind}")(key, new_key)
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

    def _rename_database(self, key, new_key):
        """The same row under a new name. Its datasets point at its id, so they follow; the permission
        names that carry the connection's name are Superset's to rename, as for a moved dataset."""
        from superset.models.core import Database  # type: ignore

        found = self._db().session.query(Database).filter_by(database_name=key).one_or_none()
        if found is not None:
            found.database_name = new_key

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
        if spec.get("metrics"):
            self._sync_metrics(found, spec["metrics"])

    @staticmethod
    def _sync_metrics(dataset, declared) -> None:
        """The dataset's saved metrics: each declared one made or brought up to date by name; others kept."""
        from superset.connectors.sqla.models import SqlMetric  # type: ignore

        existing = {m.metric_name: m for m in dataset.metrics}
        for spec in declared:
            metric = existing.get(spec["metric_name"]) or SqlMetric(metric_name=spec["metric_name"])
            metric.expression = spec["expression"]
            if spec["metric_name"] not in existing:
                dataset.metrics.append(metric)

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
            elif permission == "database_access":
                obj = session.query(Database).filter_by(database_name=name).one_or_none()
            else:                                   # a view permission, such as can_write on Chart
                wanted.append(sm.add_permission_view_menu(permission, name))
                continue
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
            for prefix in (EDITOR_ROLE_PREFIX, ROLE_PREFIX):
                if role.name.startswith(prefix):
                    hex_ = role.name[len(prefix):]
                    if _PID_HEX.fullmatch(hex_):
                        out[role.name] = {PROJECT_TAG: str(uuid.UUID(hex_))}
                    break
        return out

    # ---- dashboards ------------------------------------------------------

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

    # ---- charts on no dashboard (the plugins' starter charts) ---------------
    def _items_chart(self):
        """The charts tagged with a project, and every chart on a project's dataset (charts_of)."""
        from superset.connectors.sqla.models import SqlaTable  # type: ignore
        from superset.models.slice import Slice  # type: ignore

        session = self._db().session
        datasets = {}
        for table in session.query(SqlaTable):
            tag = self._extra(table).get(PROJECT_TAG)
            if tag is not None:
                datasets[table.id] = tag
        return charts_of(((p.uuid, p.params, p.datasource_type, p.datasource_id) for p in session.query(Slice)),
                         datasets)

    def _delete_chart(self, key):
        from superset.models.slice import Slice  # type: ignore

        for piece in self._db().session.query(Slice).filter_by(uuid=uuid.UUID(key)):
            self._db().session.delete(piece)

    # ---- plugin tiles (aisc_ext/plugin_tiles.py): what a sync reads and writes ----
    def source(self, pid):
        """The project's connection and results dataset, as the bundle names them; None if not registered."""
        from superset.connectors.sqla.models import SqlaTable  # type: ignore

        dataset = self._db().session.query(SqlaTable).filter_by(table_name=f"engine_results_{_hex(pid)}").one_or_none()
        if dataset is None or dataset.database is None:
            return None
        database = dataset.database
        return {"dataset_uuid": str(dataset.uuid), "dataset_name": dataset.table_name,
                "database_uuid": str(database.uuid), "database_name": database.database_name,
                # with the password masked: Superset never overwrites a connection on import
                "sqlalchemy_uri": database.sqlalchemy_uri, "columns": [c.column_name for c in dataset.columns]}

    def dataset_sql(self, pid):
        """The SQL the project's results dataset is registered with; None if not registered."""
        from superset.connectors.sqla.models import SqlaTable  # type: ignore

        dataset = self._db().session.query(SqlaTable).filter_by(table_name=f"engine_results_{_hex(pid)}").one_or_none()
        return None if dataset is None else dataset.sql

    def project_lock(self, pid):
        """One registration, unregistration or tile sync of the project at a time, across Superset's workers: a Postgres advisory lock on
        Superset's own database, held on a connection of its own (the imports commit, so a transaction's
        lock would not last). Another metadata database (SQLite in development) has no lock."""
        import contextlib

        from sqlalchemy import text  # type: ignore

        key = project_lock_key(pid)

        @contextlib.contextmanager
        def held():
            engine = self._db().engine
            if engine.dialect.name != "postgresql":
                yield
                return
            with engine.connect() as conn:
                conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": key})
                try:
                    yield
                finally:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        return held()

    def latest_run(self, pid, label):
        """The plugin's latest run in the project, named as the dataset names it; None before any run."""
        from sqlalchemy import text  # type: ignore
        from superset.connectors.sqla.models import SqlaTable  # type: ignore

        dataset = self._db().session.query(SqlaTable).filter_by(table_name=f"engine_results_{_hex(pid)}").one_or_none()
        if dataset is None:
            return None
        query = text(f"SELECT run FROM ({engine_results_sql()}) t WHERE tool = :label ORDER BY run_order DESC LIMIT 1")
        with dataset.database.get_sqla_engine() as engine, engine.connect() as conn:
            row = conn.execute(query, {"label": label}).first()
        return row[0] if row else None

    def chart_id(self, chart_uuid):
        from superset.models.slice import Slice  # type: ignore

        piece = self._db().session.query(Slice).filter_by(uuid=uuid.UUID(chart_uuid)).one_or_none()
        return piece.id if piece else None

    def dashboard_state(self, slug):
        """{"position", "charts": [{"id", "uuid", "aisc"}]} of a dashboard, or None. aisc: made by a sync."""
        from superset.models.dashboard import Dashboard  # type: ignore

        from aisc_ext import charts

        found = self._db().session.query(Dashboard).filter_by(slug=slug).one_or_none()
        if found is None:
            return None
        out = []
        for piece in found.slices:
            try:
                params = json.loads(piece.params or "{}")
            except ValueError:
                params = {}
            out.append({"id": piece.id, "uuid": str(piece.uuid),
                        "aisc": charts.made_by_sync(params, str(piece.uuid))})
        return {"position": json.loads(found.position_json or "{}"), "charts": out}

    def link_charts(self, slug, chart_uuids):
        """Every chart of the layout on the dashboard: Superset's import stops linking at the first chart of
        the layout that is not in its bundle, so the bridge does it."""
        from superset.models.dashboard import Dashboard  # type: ignore
        from superset.models.slice import Slice  # type: ignore

        session = self._db().session
        found = session.query(Dashboard).filter_by(slug=slug).one()
        have = {s.id for s in found.slices}
        wanted = session.query(Slice).filter(Slice.uuid.in_([uuid.UUID(u) for u in chart_uuids])).all()
        found.slices = list(found.slices) + [s for s in wanted if s.id not in have]
        session.commit()

    def delete_charts(self, chart_uuids):
        """Defaults a new plugin version dropped. Only charts a sync made: a person's chart is never deleted,
        whatever is asked."""
        from superset.models.slice import Slice  # type: ignore

        session = self._db().session
        for key in chart_uuids:
            piece = session.query(Slice).filter_by(uuid=uuid.UUID(key)).one_or_none()
            if piece is not None and "aisc_chart_id" in json.loads(piece.params or "{}"):
                session.delete(piece)
        session.commit()

    def set_dashboard_roles(self, slug, roles):
        from superset.models.dashboard import Dashboard  # type: ignore

        found = self._db().session.query(Dashboard).filter_by(slug=slug).one()
        found.roles = [r for r in (self._sm().find_role(name) for name in roles) if r is not None]
        self._db().session.commit()

    # ---- the importer: Superset's own import, as the bridge's service account ----
    def _as_bridge(self, command):
        from flask import g  # type: ignore

        before = getattr(g, "user", None)
        g.user = self._sm().find_user(username=BRIDGE_USER)
        try:
            command.run()
        finally:
            g.user = before

    def import_charts(self, files):
        from superset.commands.chart.importers.dispatcher import ImportChartsCommand  # type: ignore

        self._as_bridge(ImportChartsCommand(files, overwrite=True))

    def import_dashboard(self, files):
        from superset.commands.dashboard.importers.dispatcher import ImportDashboardsCommand  # type: ignore

        self._as_bridge(ImportDashboardsCommand(files, overwrite=True))
