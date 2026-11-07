# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""POST /api/v1/aisc_report_export/: keeps one plot of a dashboard the caller may open, with its ledger event, as
comments do. Saving is an editor's or an admin's act (a viewer looks and comments), and the plot must name a chart
placed on that dashboard. The author is the signed-in user, never a value from the body. Imported only inside
Superset."""
import json

from flask import g, request
from flask_appbuilder.api import BaseApi, expose, protect, safe

from aisc_ext import access, ledger
from aisc_ext.comments.api import _send_queued
from aisc_ext.dashboards import open_dashboard
from aisc_ext.report_exports.service import placed_chart_names, read_plot


class ReportExportApi(BaseApi):
    resource_name = "aisc_report_export"
    openapi_spec_tag = "AISC Report exports"
    csrf_exempt = False                               # called with the session cookie, as the comments API

    @expose("/", methods=["POST"])
    @protect(allow_browser_login=True)
    @safe
    def post(self):
        """Keep one plot of a dashboard for the report.
        ---
        post:
          responses:
            201: {description: kept}
        """
        from aisc_ext.report_exports.model import AiscReportPlot
        from superset import db
        from superset.models.slice import Slice

        body = request.json or {}
        if not body.get("dashboard_id"):
            return self.response_400(message="dashboard_id is required")
        dashboard, status = open_dashboard(body["dashboard_id"])
        if status == 404:
            return self.response_404()
        if status == 403:
            return self.response_403()
        # the witness hint (?dashboard=<slug>) files the request under the slug's project: it must be this dashboard
        if (problem := ledger.hint_problem(request.args.get("dashboard"), dashboard.slug)) is not None:
            return self.response_400(message=problem)
        user = g.user
        pid = access.project_if(user, dashboard, "export")
        if pid is None:
            return self.response(403, message="Only an editor or an admin of the project can save a plot to the report.")
        try:
            plot = read_plot(body)
        except ValueError as exc:
            return self.response_400(message=str(exc))
        position = json.loads(dashboard.position_json or "{}")
        placed = [n["meta"]["chartId"] for n in position.values() if isinstance(n, dict) and n.get("type") == "CHART"
                  and isinstance((n.get("meta") or {}).get("chartId"), int)]
        names = placed_chart_names(position, {c.id: c.slice_name for c in
                                              db.session.query(Slice).filter(Slice.id.in_(placed))} if placed else {})
        if plot["chart"] not in names:
            return self.response_400(message="the plot must name a chart placed on this dashboard")
        row = AiscReportPlot(dashboard_id=dashboard.id, chart=plot["chart"], tab=plot["tab"], tags=plot["tags"],
                             svg=plot["svg"], sha256=plot["sha256"], comment=plot["comment"],
                             author_sub=str(user.username), author_name=user.get_full_name() or user.username)
        db.session.add(row)
        db.session.flush()
        ledger.emit(db.session.connection(), pid, "dashboard.export.saved",
                    ledger.export_saved(row.id, plot, slug=dashboard.slug,
                                        request=ledger.request_id(request.headers, request.environ)))
        db.session.commit()
        _send_queued()
        return self.response(201, result={"id": row.id, "dashboard": dashboard.dashboard_title, "chart": plot["chart"]})
