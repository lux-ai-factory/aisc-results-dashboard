# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The Review page, served by Superset through Flask-AppBuilder's own views.

``/aisc/review/`` lists the dashboards the caller may open; ``/aisc/review/<id>/``
shows one of them in a frame, in Superset's standalone mode, with the
conversation beside it. The frame is Superset drawing its own dashboard at its
own address, so nothing here reads or changes Superset's pages, and an upgrade
that redraws the dashboard cannot break the conversation around it.

Same origin as Superset: the frame, the session and the comments API need no
embedding headers, no third-party cookies and no CORS. Runtime-only.
"""
import os

from flask import abort, g
from flask_appbuilder import BaseView, expose, has_access

from aisc_ext import branding
from aisc_ext.dashboards import open_dashboard
from aisc_ext.review.service import frame_url

_TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


class AiscReviewView(BaseView):
    route_base = "/aisc/review"
    default_view = "list"
    template_folder = _TEMPLATES

    def _brand(self):
        return {"app_name": branding.app_name(), "logo": branding.app_icon(),
                "primary": branding.theme_overrides()["colors"]["primary"],
                "me": g.user.get_full_name() or g.user.username}

    @expose("/")
    @has_access
    def list(self):
        from sqlalchemy import func
        from superset import db
        from superset.daos.dashboard import DashboardDAO

        from aisc_ext.comments.model import AiscComment

        dashboards = sorted(DashboardDAO.find_all(),
                            key=lambda d: (d.dashboard_title or "").lower())
        counts = dict(db.session.query(AiscComment.dashboard_id, func.count(AiscComment.id))
                      .group_by(AiscComment.dashboard_id).all())
        rows = [{"id": d.id, "title": d.dashboard_title or f"Dashboard {d.id}",
                 "charts": len(d.slices), "comments": counts.get(str(d.id), 0),
                 "changed": d.changed_on} for d in dashboards]
        return self.render_template("aisc_review/list.html", dashboards=rows,
                                    **self._brand())

    @expose("/<id_or_slug>/")
    @has_access
    def show(self, id_or_slug):
        dashboard, status = open_dashboard(id_or_slug)
        if status is not None:
            abort(status)
        return self.render_template(
            "aisc_review/show.html",
            dashboard={"id": dashboard.id, "title": dashboard.dashboard_title, "slug": dashboard.slug or ""},
            frame=frame_url(dashboard.id),
            **self._brand(),
        )
