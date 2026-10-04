# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Assessment › Import charts (plugin dashboards 2026-10-04, T7): extra charts from a Superset export ZIP,
into one plugin's tile, as the person's own charts under "Your charts".

Only an owner of the tile may import into it (owners and editors of the project are its owners from sign-in,
aisc_ext/sso.py); anyone else is refused, whatever they post. The rewrite (aisc_ext/chart_import.py) points
every chart at the project's own dataset and gives it an id of its own; the import is Superset's own, run as the
person. Imported only inside Superset."""
import json
import os
import uuid

from flask import abort, g, redirect, request
from flask_appbuilder import BaseView, expose, has_access

from aisc_ext import branding
from aisc_ext.chart_import import place_under_your_charts, rewrite

_TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review", "templates")
#: a chart export of a few charts is a few kilobytes; this keeps a mistaken upload from filling memory
MAX_BYTES = 5 * 1024 * 1024


def _plugin_tiles():
    """The plugin dashboards, with their project: [(dashboard, pid)]."""
    from superset import db
    from superset.models.dashboard import Dashboard

    out = []
    for d in db.session.query(Dashboard):
        try:
            meta = json.loads(d.json_metadata or "{}")
        except ValueError:
            continue
        if meta.get("aisc_plugin") and meta.get("aisc_project"):
            out.append((d, meta["aisc_project"]))
    return out


class AiscChartImportView(BaseView):
    route_base = "/aisc/import"
    default_view = "form"
    template_folder = _TEMPLATES

    def _mine(self):
        """The tiles this person may import into: the ones they own; every one for an admin."""
        admin = any(r.name == "Admin" for r in g.user.roles)
        return [(d, pid) for d, pid in _plugin_tiles() if admin or any(o.id == g.user.id for o in d.owners)]

    def _page(self, error=None, status=200):
        tiles = sorted(({"id": d.id, "title": d.dashboard_title} for d, _ in self._mine()),
                       key=lambda t: t["title"].lower())
        return self.render_template("aisc_import/import.html", tiles=tiles, error=error,
                                    app_name=branding.app_name(), logo=branding.app_icon(),
                                    primary=branding.theme_overrides()["colors"]["primary"],
                                    me=g.user.get_full_name() or g.user.username), status

    @expose("/", methods=["GET"])
    @has_access
    def form(self):
        return self._page()

    @expose("/", methods=["POST"])
    @has_access
    def upload(self):
        from superset import db
        from superset.commands.chart.importers.dispatcher import ImportChartsCommand
        from superset.models.slice import Slice

        from aisc_ext.projects import SupersetStore

        mine = {str(d.id): (d, pid) for d, pid in self._mine()}
        chosen = mine.get(request.form.get("dashboard", ""))
        if chosen is None:
            abort(403)                                      # not an owner of that tile (or no such tile)
        file = request.files.get("file")
        data = file.read(MAX_BYTES + 1) if file else b""
        if not data:
            return self._page("Choose a chart export (.zip).", 400)
        if len(data) > MAX_BYTES:
            return self._page("That file is larger than a chart export can be (5 MB).", 400)
        dashboard, pid = chosen
        source = SupersetStore().source(pid)
        if source is None:
            return self._page("This tile's project is no longer in the dashboard.", 404)
        try:
            files, charts = rewrite(data, pid=pid, source=source)
            ImportChartsCommand(files, overwrite=True).run()
        except ValueError as exc:
            return self._page(str(exc), 400)
        except Exception as exc:                            # noqa: BLE001 - Superset's own refusal, said as is
            return self._page(f"Superset did not take the file: {exc}", 400)
        pieces = {str(s.uuid): s for s in db.session.query(Slice).filter(
            Slice.uuid.in_([uuid.UUID(c["uuid"]) for c in charts]))}
        placed = [{"id": pieces[c["uuid"]].id, "uuid": c["uuid"], "name": c["name"]} for c in charts if c["uuid"] in pieces]
        position = place_under_your_charts(json.loads(dashboard.position_json or "{}"), placed)
        dashboard.position_json = json.dumps(position)
        have = {s.id for s in dashboard.slices}
        dashboard.slices = list(dashboard.slices) + [pieces[c["uuid"]] for c in charts
                                                     if c["uuid"] in pieces and pieces[c["uuid"]].id not in have]
        db.session.commit()
        return redirect(f"/superset/dashboard/{dashboard.slug or dashboard.id}/")
