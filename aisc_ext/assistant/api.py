# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""/api/v1/aisc_assistant: the chart assistant panel's door. It admits a person to a dashboard of a project (Superset's
own check), tells the assistant what the project's data looks like (service.description_from, never a row), forwards
the conversation, and on validation makes the chart from exactly the validated query on the project's own read-only
connection, with its ledger event. Imported only inside Superset."""
import json
import os
import urllib.error
import urllib.request

from flask import g, request, session
from flask_appbuilder.api import BaseApi, expose, protect, safe

from aisc_ext import ledger
from aisc_ext.assistant.service import (chart_uuid_of, description_from, kind_of, may_validate,
                                        changed_params, distinct_sql, plot_definition, plots_on, to_change,
                                        place_chart, ranges_from, to_remove, validated_files, with_conversation,
                                        without_chart)
from aisc_ext.comments.api import _send_queued
from aisc_ext.dashboards import open_dashboard

SESSION_KEY = "aisc_assistant"
TARGETS_SQL = "SELECT DISTINCT label FROM target.target WHERE label IS NOT NULL ORDER BY 1"
METRICS_SQL = """
SELECT met.name, k.key, (array_agg(DISTINCT m.dimensions->>k.key))[1:51], count(DISTINCT m.dimensions->>k.key),
       bool_and(jsonb_typeof(m.dimensions->k.key) = 'number'), avg(length(m.dimensions->>k.key))
  FROM engine.aisc_backend_measurement m
  JOIN engine.aisc_backend_metric met ON met.id = m.metric_id,
       jsonb_object_keys(COALESCE(m.dimensions, '{}'::jsonb)) AS k(key)
 GROUP BY 1, 2 ORDER BY 1, 2"""

#: per metric, the score's range in its first finished run (the earliest Done evaluation holding it)
SCORE_RANGES_SQL = """
WITH firsts AS (
  SELECT DISTINCT ON (m.metric_id) m.metric_id, o.evaluation_id
    FROM engine.aisc_backend_measurement m
    JOIN engine.aisc_backend_observation o ON o.id = m.observation_id
    JOIN engine.aisc_backend_evaluation e ON e.id = o.evaluation_id AND e.status = 'Done'
   ORDER BY m.metric_id, e.created_at, e.id)
SELECT met.name, min(m.score), max(m.score), bool_and(m.score = trunc(m.score))
  FROM firsts f
  JOIN engine.aisc_backend_metric met ON met.id = f.metric_id
  JOIN engine.aisc_backend_observation o ON o.evaluation_id = f.evaluation_id
  JOIN engine.aisc_backend_measurement m ON m.observation_id = o.id AND m.metric_id = f.metric_id
 GROUP BY met.name"""
#: per metric and numeric label, its range in the metric's first finished run
LABEL_RANGES_SQL = """
WITH firsts AS (
  SELECT DISTINCT ON (m.metric_id) m.metric_id, o.evaluation_id
    FROM engine.aisc_backend_measurement m
    JOIN engine.aisc_backend_observation o ON o.id = m.observation_id
    JOIN engine.aisc_backend_evaluation e ON e.id = o.evaluation_id AND e.status = 'Done'
   ORDER BY m.metric_id, e.created_at, e.id)
SELECT met.name, k.key, min((m.dimensions->>k.key)::numeric), max((m.dimensions->>k.key)::numeric)
  FROM firsts f
  JOIN engine.aisc_backend_metric met ON met.id = f.metric_id
  JOIN engine.aisc_backend_observation o ON o.evaluation_id = f.evaluation_id
  JOIN engine.aisc_backend_measurement m ON m.observation_id = o.id AND m.metric_id = f.metric_id,
       jsonb_object_keys(COALESCE(m.dimensions, '{}'::jsonb)) AS k(key)
 WHERE jsonb_typeof(m.dimensions->k.key) = 'number'
 GROUP BY 1, 2"""


def _ranges(database) -> dict:
    return ranges_from(_rows(database, SCORE_RANGES_SQL)[1], _rows(database, LABEL_RANGES_SQL)[1])


def _assistant(path: str, body: dict) -> tuple[int, dict]:
    """POST to the assistant with the dashboard's token; (status, answer). The standard library only: the dashboard
    image carries no HTTP client of its own."""
    base = (os.environ.get("ASSISTANT_URL") or "http://chart-assistant:8096").rstrip("/")
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "X-AISC-Service-Token": os.environ.get("ASSISTANT_DASHBOARD_TOKEN", "")})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return 502, {"message": f"the chart assistant did not answer ({type(exc).__name__})"}
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        data = {}
    if status >= 400:
        return status, {"message": data.get("detail") or f"the chart assistant answered {status}"}
    return status, data


def _database(pid):
    from superset import db
    from superset.models.core import Database

    from aisc_ext.projects import SupersetStore

    source = SupersetStore().source(pid)
    if source is None:
        return None, None
    return source, db.session.query(Database).filter_by(uuid=source["database_uuid"]).one()


def _rows(database, sql):
    with database.get_sqla_engine() as engine:
        with engine.connect() as conn:
            result = conn.exec_driver_sql(sql.replace("%", "%%"))
            return list(result.keys()), [tuple(r) for r in result.fetchall()]


def _plots_on(dashboard) -> list[dict]:
    """Every chart placed on this dashboard, as the model sees it: number, title, kind, whether the assistant made it,
    and the query of those it made. Any of them may be changed in place or removed (by a project editor or admin)."""
    from superset import db
    from superset.models.slice import Slice

    placed = plots_on(json.loads(dashboard.position_json or "{}"))
    ids = [i for i, _ in placed]
    found = {c.id: c for c in db.session.query(Slice).filter(Slice.id.in_(ids))} if ids else {}
    return [{"id": i, "title": found[i].slice_name, "kind": kind_of(found[i].viz_type), "mine": mine,
             "definition": plot_definition(found[i].viz_type, json.loads(found[i].params or "{}")),
             **({"sql": getattr(found[i].datasource, "sql", None) or ""} if mine else {})}
            for i, mine in placed if i in found]


def _change(dashboard, chart_id, changes) -> tuple[dict, dict, str]:
    """Changes one chart in place (settings and name, never its query) and, for a plugin's default chart, remembers
    the change so a sync keeps it. (before, after, title); ValueError when the chart cannot take it. Any chart on the
    dashboard: the caller checks only that the person is an editor or admin of the project, not Superset ownership."""
    from superset import db
    from superset.models.slice import Slice

    from aisc_ext.made_tiles import AiscChangedChart

    chart = db.session.query(Slice).get(chart_id)
    params = json.loads(chart.params or "{}")
    viz_type, new = changed_params(chart.viz_type, params, {k: v for k, v in changes.items() if k != "title"})
    before = {"title": chart.slice_name, "viz_type": chart.viz_type, "params": params}
    chart.viz_type, chart.params = viz_type, json.dumps(new)
    chart.slice_name = str(changes.get("title") or chart.slice_name)[:250]
    if new.get("aisc_chart_id"):
        row = db.session.query(AiscChangedChart).get((dashboard.slug, str(chart.uuid)))
        if row is None:
            db.session.add(AiscChangedChart(slug=dashboard.slug, chart_uuid=str(chart.uuid), changes=json.dumps(changes)))
        else:
            row.changes = json.dumps({**json.loads(row.changes), **changes})
    return before, {"title": chart.slice_name, "viz_type": viz_type, "params": new}, chart.slice_name


def _forget_default(slug, chart_id):
    """Remembers that a chart left a dashboard on purpose, so a plugin tile's sync does not put a default back."""
    from superset import db
    from superset.models.slice import Slice

    from aisc_ext.made_tiles import AiscRemovedChart

    chart = db.session.query(Slice).get(chart_id)
    if chart is not None and db.session.query(AiscRemovedChart).get((slug, str(chart.uuid))) is None:
        db.session.add(AiscRemovedChart(slug=slug, chart_uuid=str(chart.uuid)))


def _take_off(dashboard_id, chart_id):
    """Takes one chart off a dashboard (layout and chart list) and remembers it, so a plugin tile's sync does not put
    a default back; the chart stays in Superset. Any chart on the dashboard, whoever owns it: the caller checks only
    that the person is an editor or admin of the project."""
    from superset import db
    from superset.models.dashboard import Dashboard

    fresh = db.session.query(Dashboard).get(dashboard_id)
    fresh.position_json = json.dumps(without_chart(json.loads(fresh.position_json or "{}"), chart_id, any_chart=True))
    fresh.slices = [c for c in fresh.slices if c.id != chart_id]
    _forget_default(fresh.slug, chart_id)
    return fresh


class AssistantApi(BaseApi):
    resource_name = "aisc_assistant"
    openapi_spec_tag = "AISC Chart assistant"
    csrf_exempt = False

    def _project(self, dashboard_id):
        dashboard, status = open_dashboard(dashboard_id)
        if status:
            return None, None, (self.response_404() if status == 404 else self.response_403())
        pid = ledger.project_for(dashboard, g.user)
        if pid is None:
            return None, None, self.response_403()
        # the witness hint (?dashboard=<slug>) files the request under the slug's project: it must be this dashboard
        if (problem := ledger.hint_problem(request.args.get("dashboard"), dashboard.slug)) is not None:
            return None, None, self.response_400(message=problem)
        return dashboard, pid, None

    def _mine(self, cid):
        return (session.get(SESSION_KEY) or {}).get(cid)

    @expose("/conversations", methods=["POST"])
    @protect(allow_browser_login=True)
    @safe
    def start(self):
        """Start a conversation on a dashboard of a project.
        ---
        post:
          responses:
            201: {description: started}
        """
        dashboard, pid, refused = self._project((request.json or {}).get("dashboard_id"))
        if refused:
            return refused
        source, database = _database(pid)
        if database is None:
            return self.response_404()
        _, targets = _rows(database, TARGETS_SQL)
        _, metrics = _rows(database, METRICS_SQL)
        status, data = _assistant(f"/v1/projects/{pid}/conversations",
                                  {"description": description_from([t[0] for t in targets], metrics, _ranges(database))})
        if status != 201:
            return self.response(status, **data)
        session[SESSION_KEY] = with_conversation(session.get(SESSION_KEY), data["conversation"], dashboard.id)
        return self.response(201, conversation=data["conversation"])

    @expose("/conversations/<cid>/messages", methods=["POST"])
    @protect(allow_browser_login=True)
    @safe
    def message(self, cid):
        """Ask for a chart or a change. Anyone who may open the dashboard may ask; a change or a removal is made only
        for an editor or admin of the project, on any plot of the dashboard (other people's charts and plugin
        defaults too: Superset ownership is not checked, by design).
        ---
        post:
          responses:
            200: {description: a proposal on mock data, or a question}
        """
        from superset import db

        dashboard_id = self._mine(cid)
        if dashboard_id is None:
            return self.response_404()
        dashboard, pid, refused = self._project(dashboard_id)
        if refused:
            return refused
        made = _plots_on(dashboard)
        status, data = _assistant(f"/v1/conversations/{cid}/messages",
                                  {"text": (request.json or {}).get("text", ""), "charts": made})
        if status == 200 and "change" in data:
            return self._apply_change(dashboard, pid, made, data["change"], action="dashboard.assistant.changed")
        if status != 200 or "remove" not in data:
            return self.response(status, **data)
        plots = to_remove(data["remove"], made)
        if plots is None:
            return self.response(409, message="Only plots on this dashboard can be removed.")
        if not may_validate({r.name for r in g.user.roles}, pid.replace("-", "")):
            return self.response(403, message="Only an editor or an admin of the project can remove a plot.")
        for chart_id, title in plots:
            fresh = _take_off(dashboard.id, chart_id)
            ledger.emit(db.session.connection(), pid, "dashboard.assistant.removed",
                        ledger.assistant_removed(chart_id, title, slug=fresh.slug,
                                                 request=ledger.request_id(request.headers, request.environ)))
        db.session.commit()
        _send_queued()
        return self.response(200, removed=[{"chart": c, "title": t} for c, t in plots])

    def _apply_change(self, dashboard, pid, plots, asked, *, action):
        from superset import db

        found = to_change(asked, plots)
        if found is None:
            return self.response(409, message="Only plots on this dashboard can be changed.")
        if not may_validate({r.name for r in g.user.roles}, pid.replace("-", "")):
            return self.response(403, message="Only an editor or an admin of the project can change a plot.")
        chart_id, changes = found
        try:
            before, after, title = _change(dashboard, chart_id, changes)
        except ValueError as exc:
            db.session.rollback()
            return self.response(409, message=f"That plot cannot be changed that way: {exc}.")
        ledger.emit(db.session.connection(), pid, action,
                    ledger.assistant_changed(chart_id, slug=dashboard.slug, changes=changes, before=before, after=after,
                                             request=ledger.request_id(request.headers, request.environ)))
        db.session.commit()
        _send_queued()
        return self.response(200, changed={"chart": chart_id, "title": title})

    @expose("/conversations/<cid>/validate", methods=["POST"])
    @protect(allow_browser_login=True)
    @safe
    def validate(self, cid):
        """Validate a proposal: the same query, unchanged, becomes a chart on the project's data. An editor's or an
        admin's act; a proposal replacing a plot may replace any plot on the dashboard, whoever owns it.
        ---
        post:
          responses:
            201: {description: the chart was made}
        """
        from superset import db
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        from aisc_ext.projects import SupersetStore

        dashboard_id = self._mine(cid)
        if dashboard_id is None:
            return self.response_404()
        dashboard, pid, refused = self._project(dashboard_id)
        if refused:
            return refused
        if not may_validate({r.name for r in g.user.roles}, pid.replace("-", "")):
            return self.response_403()
        status, chosen = _assistant(f"/v1/conversations/{cid}/validate",
                                    {key: (request.json or {})[key] for key in ("fingerprint", "proposal")
                                     if key in (request.json or {})})
        if status != 200:
            return self.response(status, **chosen)
        if chosen.get("project") != pid:
            return self.response_403()
        source, database = _database(pid)
        columns, _ = _rows(database, f"SELECT * FROM ({chosen['sql']}) AS validated LIMIT 0")
        axes = []
        if chosen["chart"]["kind"] == "radar":
            _, found = _rows(database, distinct_sql(chosen["chart"]["category"], chosen["sql"]))
            axes = [str(r[0]) for r in found if r[0] is not None][:60]
        try:
            files = validated_files(source, pid=pid, sql=chosen["sql"], fingerprint=chosen["fingerprint"],
                                    chart=chosen["chart"], columns=columns, axes=axes,
                                    description=chosen.get("description", ""), author=g.user.username)
        except ValueError as exc:
            return self.response_400(message=str(exc))
        store = SupersetStore()
        store.import_charts(files)
        uid = chart_uuid_of(files)
        chart = db.session.query(Slice).filter_by(uuid=uid).one()
        chart.owners = list({*chart.owners, g.user})
        fresh = db.session.query(Dashboard).get(dashboard.id)
        position = json.loads(fresh.position_json or "{}")
        replaces = chosen.get("replaces")
        replaces = replaces if replaces in [i for i, _ in plots_on(position)] and replaces != chart.id else None
        if chart not in fresh.slices:
            fresh.slices.append(chart)
        fresh.position_json = json.dumps(place_chart(position, chart_id=chart.id, chart_uuid=uid,
                                                     name=chart.slice_name, replaces=replaces, any_chart=True))
        if replaces is not None:
            _forget_default(fresh.slug, replaces)
            fresh.slices = [c for c in fresh.slices if c.id != replaces]
            chosen = {**chosen, "replaces": replaces}
        ledger.emit(db.session.connection(), pid, "dashboard.assistant.validated",
                    ledger.assistant_validated(chart.id, chosen, slug=fresh.slug,
                                               request=ledger.request_id(request.headers, request.environ)))
        db.session.commit()
        _send_queued()
        return self.response(201, chart=chart.id, fingerprint=chosen["fingerprint"], replaced=replaces)
