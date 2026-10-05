# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""REST API for dashboard comments, under /api/v1/aisc_comment.

The author is the signed-in Superset user, never a value from the request body.
Only the author or an Admin may delete a comment. Each action is written to the
immudb audit log and, when LEDGER_MODE is on, queued as a ledger event.

Every route first checks, with Superset's own check, that the caller may open
the dashboard the comment is on: a person who cannot see a dashboard cannot
read, write or delete its comments either. Imported only inside Superset."""
from flask import g, request
from flask_appbuilder.api import BaseApi, expose, protect, safe

from aisc_ext import ledger
from aisc_ext.audit import ImmudbClerk, clerk_kwargs_from_env
from aisc_ext.comments.service import can_delete, make_comment
from aisc_ext.dashboards import open_dashboard
from aisc_ext.review.service import (
    build_threads, chart_choices, chart_for_new_comment, charts_in_layout, reply_target,
)

_clerk = ImmudbClerk(**clerk_kwargs_from_env())


def _send_queued():
    """Post the queued ledger events to the platform, in a thread of its own: the request that queued
    them does not wait for the platform. A failure is logged and never breaks the request."""
    from superset import db

    try:
        ledger.deliver_in_background(db.engine, ledger.http_sender())
    except Exception:                                                   # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("ledger: dashboard events stay queued")


class CommentApi(BaseApi):
    resource_name = "aisc_comment"
    openapi_spec_tag = "AISC Comments"
    # Flask-AppBuilder exempts its APIs from CSRF unless told otherwise, as
    # Superset's own APIs do (superset/views/base_api.py). This API is called
    # with the session cookie from the Review page, and every AISC tool is
    # served from localhost, which a browser counts as one site: without the
    # CSRF token, any of them could write here as the signed-in user.
    csrf_exempt = False

    def _user(self):
        u = g.user
        return (str(u.username), u.get_full_name() or u.username,
                any(r.name == "Admin" for r in u.roles))

    def _dashboard(self, id_or_slug):
        """(dashboard, None) when the caller may open it, else (None, response)."""
        if not id_or_slug:
            return None, self.response_400(message="dashboard_id is required")
        dashboard, status = open_dashboard(id_or_slug)
        if status == 404:
            return None, self.response_404()
        if status == 403:
            return None, self.response_403()
        return dashboard, None

    @staticmethod
    def _charts(dashboard):
        return charts_in_layout(dashboard.position_json,
                                [(s.id, s.slice_name) for s in dashboard.slices])

    def _placement(self, body, dashboard):
        """Where a new comment goes, as ``{"parent_id", "chart_id"}``.

        A reply goes under the top comment of its parent's thread; a new
        comment goes on a chart of this dashboard, or on the whole dashboard.
        Raises ValueError when it cannot go where the request asks (TypeError
        for a parent id that is not a number)."""
        from aisc_ext.comments.model import AiscComment
        from superset import db

        if body.get("parent_id"):
            parent = db.session.query(AiscComment).get(int(body["parent_id"]))
            if parent is not None and parent.deleted_at is not None:
                parent = None                                           # no reply under a hidden comment
            return reply_target(parent.to_dict() if parent else None,
                                dashboard_id=str(dashboard.id))
        return {"parent_id": None,
                "chart_id": chart_for_new_comment(body.get("chart_id"), self._charts(dashboard))}

    @expose("/threads", methods=["GET"])
    @protect(allow_browser_login=True)
    @safe
    def threads(self):
        """A dashboard's comments as threads, with the charts a comment can be about.
        ---
        get:
          parameters:
          - in: query
            name: dashboard_id
            schema: {type: string}
        """
        from aisc_ext.comments.model import AiscComment
        from superset import db

        dashboard, refused = self._dashboard(request.args.get("dashboard_id"))
        if refused:
            return refused
        sub, _, is_admin = self._user()
        rows = [r.to_dict() for r in db.session.query(AiscComment)
                .filter(AiscComment.dashboard_id == str(dashboard.id), AiscComment.deleted_at.is_(None)).all()]
        charts = self._charts(dashboard)
        return self.response(200, result={
            "dashboard": {"id": dashboard.id, "title": dashboard.dashboard_title},
            "charts": chart_choices(charts, rows),
            "threads": build_threads(rows, charts, user_sub=sub, is_admin=is_admin),
        })

    @expose("/", methods=["GET"])
    @protect(allow_browser_login=True)
    @safe
    def list(self):
        """List comments for a dashboard, scoped to a chart or overall.
        ---
        get:
          parameters:
          - in: query
            name: dashboard_id
            schema: {type: string}
          - in: query
            name: chart_id
            schema: {type: integer}
          - in: query
            name: overall
            schema: {type: boolean}
        """
        from aisc_ext.comments.model import AiscComment
        from superset import db

        dashboard, refused = self._dashboard(request.args.get("dashboard_id"))
        if refused:
            return refused
        q = db.session.query(AiscComment).filter(AiscComment.dashboard_id == str(dashboard.id),
                                                 AiscComment.deleted_at.is_(None))
        if request.args.get("overall") == "true":
            q = q.filter(AiscComment.chart_id.is_(None))
        elif request.args.get("chart_id"):
            q = q.filter(AiscComment.chart_id == int(request.args["chart_id"]))
        rows = q.order_by(AiscComment.created_at).all()
        return self.response(200, result=[r.to_dict() for r in rows])

    @expose("/", methods=["POST"])
    @protect(allow_browser_login=True)
    @safe
    def post(self):
        from aisc_ext.comments.model import AiscComment
        from superset import db

        sub, name, _ = self._user()
        body = request.json or {}
        dashboard, refused = self._dashboard(body.get("dashboard_id"))
        if refused:
            return refused
        if (problem := ledger.hint_problem(request.args.get("dashboard"), dashboard.slug)) is not None:
            return self.response_400(message=problem)
        try:
            where = self._placement(body, dashboard)
            data = make_comment(
                dashboard_id=str(dashboard.id), author_sub=sub, author_name=name,
                body=body.get("body", ""), chart_id=where["chart_id"],
                parent_id=where["parent_id"],
            )
        except (ValueError, TypeError) as exc:
            return self.response_400(message=str(exc))
        row = AiscComment(**{k: v for k, v in data.items() if k != "created_at"})
        db.session.add(row)
        db.session.flush()                                              # gives the row its id, for the event
        # the ledger event goes in the comment's own transaction: both commit, or neither
        ledger.emit(db.session.connection(), ledger.project_of(dashboard.slug), "dashboard.comment.created",
                    ledger.comment_created(row.to_dict(), slug=dashboard.slug,
                                              request=ledger.request_id(request.headers)))
        db.session.commit()
        _send_queued()
        scope = f"chart {row.chart_id}" if row.chart_id else "overall"
        _clerk.record(actor=name, action="comment.create", target=row.dashboard_id,
                      extra={"comment_id": row.id, "scope": scope})
        return self.response(201, result=row.to_dict())

    @expose("/<int:pk>", methods=["DELETE"])
    @protect(allow_browser_login=True)
    @safe
    def delete(self, pk: int):
        from aisc_ext.comments.model import AiscComment
        from superset import db

        sub, name, is_admin = self._user()
        row = db.session.query(AiscComment).get(pk)
        if not row or row.deleted_at is not None:
            return self.response_404()
        dashboard, refused = self._dashboard(row.dashboard_id)
        if refused:
            return refused
        if (problem := ledger.hint_problem(request.args.get("dashboard"), dashboard.slug)) is not None:
            return self.response_400(message=problem)
        if not can_delete(row.to_dict(), user_sub=sub, is_admin=is_admin):
            return self.response(403, message="Not your comment")
        from datetime import datetime, timezone

        row.deleted_at = datetime.now(timezone.utc)                    # hidden, not removed
        ledger.emit(db.session.connection(), ledger.project_of(dashboard.slug), "dashboard.comment.deleted",
                    ledger.comment_deleted(row.to_dict(), slug=dashboard.slug,
                                              request=ledger.request_id(request.headers)))
        db.session.commit()
        _send_queued()
        _clerk.record(actor=name, action="comment.delete", target=row.dashboard_id,
                      extra={"comment_id": pk})
        return self.response(200, message="deleted")
