# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""One tile per plugin per project (plugin dashboards 2026-10-04).

sync_plugin makes or updates one plugin's dashboard in one project from the plugin's default charts (its
MetricVisualization list, read by the platform from the engine), through Superset's own import, and keeps what
people put under "Your charts":

1. the starter chart (off the dashboard; "+ Build a chart of your own" opens it), once the plugin has a run;
2. the dashboard: the defaults, then "Your charts" with the layout people made there, the Run filter's default
   set to the latest run (read from the project's own results);
3. every chart of the layout linked to the dashboard by the bridge itself: Superset's import stops linking at
   the first chart of the layout that is not in the bundle, and it walks them in no fixed order;
4. defaults a new plugin version dropped are deleted; people's charts never are;
5. the dashboard is visible to the project's role only (DASHBOARD_RBAC).

The store and the importer are passed in: Superset backs them at runtime (aisc_ext/projects.py), fakes in the
tests. No Superset import here."""
from __future__ import annotations

import copy

from aisc_ext import charts
from aisc_ext.projects import _pid, project_role_name, results_dataset_current, results_dataset_spec

_AISC_NODES = ("HEADER-aisc-", "MARKDOWN-aisc-", "ROW-aisc-", "CHART-aisc-")


def plugin_request(body: dict) -> dict:
    """The bridge's request body, checked: what is wrong is said before anything reaches Superset."""
    plugin = body.get("plugin")
    if not isinstance(plugin, str) or not plugin.strip():
        raise ValueError("plugin: the engine's name of the plugin, as <package>::<class>")
    label = body.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label: the plugin's display name")
    visualizations = body.get("visualizations", [])
    if not isinstance(visualizations, list):
        raise ValueError("visualizations: a list of the plugin's default charts")
    for i, v in enumerate(visualizations):
        if not isinstance(v, dict) or not v.get("chart_type") or not isinstance(v.get("metrics"), list):
            raise ValueError(f"visualizations[{i}]: chart_type and metrics are required")
    return {"plugin": plugin, "label": label, "version": str(body.get("version") or ""),
            "project_name": str(body.get("project_name") or ""), "visualizations": visualizations}


def user_part(position: dict | None, linked: list[dict]) -> dict:
    """The layout people made under "Your charts", as nodes to put back after a re-import, plus a node for
    each of their charts linked to the dashboard but placed nowhere. AISC's own nodes and charts are left
    out: the bundle brings them."""
    if not position:
        return {}
    grid = (position.get("GRID_ID") or {}).get("children", [])
    out: dict[str, dict] = {}

    def keep(node_id):
        node = position.get(node_id)
        if not isinstance(node, dict) or node_id.startswith(_AISC_NODES):
            return
        out[node_id] = copy.deepcopy(node)
        for child in node.get("children", []):
            keep(child)

    after = grid[grid.index("HEADER-aisc-yours") + 1:] if "HEADER-aisc-yours" in grid else \
        [c for c in grid if not c.startswith(_AISC_NODES)]
    for node_id in after:
        keep(node_id)
    placed = {n["meta"].get("uuid") for n in position.values()
              if isinstance(n, dict) and n.get("type") == "CHART" and isinstance(n.get("meta"), dict)}
    for chart in linked:
        if not chart["aisc"] and chart["uuid"] not in placed:
            node_id = f"CHART-user-{chart['uuid'][:8]}"
            out[node_id] = {"type": "CHART", "id": node_id, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                            "meta": {"chartId": chart["id"], "uuid": chart["uuid"], "width": 4, "height": 50}}
    return out


def sync_plugin(pid, project_name: str, plugin: str, label: str, version: str, visualizations: list[dict], *,
                store, importer) -> dict:
    """Make or update the plugin's dashboard in the project. Idempotent: a second sync with the same input
    changes nothing. Returns {"slug", "charts"} (the number of default charts).

    Holds the project's lock throughout: two syncs at once would both make a new dashboard (2026-10-05). The
    results dataset is first brought up to date when older code registered it, so the tile never waits on
    the platform's next registration."""
    pid = _pid(pid)
    with store.project_lock(pid):
        return _sync(pid, project_name, plugin, label, version, visualizations, store=store, importer=importer)


def _sync(pid, project_name, plugin, label, version, visualizations, *, store, importer) -> dict:
    source = store.source(pid)
    if source is None:
        raise LookupError(f"project {pid} is not registered in the dashboard")
    if not results_dataset_current(store.dataset_sql(pid), source["columns"]):
        store.upsert("dataset", source["dataset_name"], results_dataset_spec(pid, source["database_name"]))
        source = store.source(pid)
    common = dict(pid=pid, plugin=plugin, label=label, **source)
    slug = charts.plugin_slug(pid, plugin)
    latest_run = store.latest_run(pid, label)

    starter_id = None
    if latest_run is not None or visualizations:
        importer.import_charts(charts.starter_bundle(**common))
        starter_id = store.chart_id(charts.starter_uuid(pid, plugin))

    state = store.dashboard_state(slug)
    kept = user_part(state["position"], state["charts"]) if state else {}
    previous_defaults = {c["uuid"] for c in state["charts"] if c["aisc"]} if state else set()

    files = charts.bundle(project_name=project_name or pid, version=version, visualizations=visualizations,
                          starter_chart_id=starter_id, user_part=kept,
                          latest_run=latest_run, **common)
    importer.import_dashboard(files)

    defaults = [charts.chart_uuid(pid, plugin, i, v.get("title") or "") for i, v in enumerate(visualizations)]
    people = [n["meta"]["uuid"] for n in kept.values() if n.get("type") == "CHART"]
    store.link_charts(slug, defaults + people)
    store.delete_charts(sorted(previous_defaults - set(defaults)))
    store.set_dashboard_roles(slug, [project_role_name(pid)])
    return {"slug": slug, "charts": len(defaults)}
