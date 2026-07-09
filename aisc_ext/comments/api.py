# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Native Superset REST API for comments, mounted under /api/v1/aisc_comment.

Uses the verified Superset user as the author (never the request body), enforces
delete = author-or-admin, and writes each action to the immudb audit ledger.
Runtime-only (Flask/FAB/Superset imports)."""
from flask import g, request
from flask_appbuilder.api import BaseApi, expose, protect, safe

from aisc_ext.audit import ImmudbClerk, clerk_kwargs_from_env
from aisc_ext.comments.service import can_delete, make_comment

_clerk = ImmudbClerk(**clerk_kwargs_from_env())


class CommentApi(BaseApi):
    resource_name = "aisc_comment"
    openapi_spec_tag = "AISC Comments"

    def _user(self):
        u = g.user
        return (str(u.username), u.get_full_name() or u.username,
                any(r.name == "Admin" for r in u.roles))

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

        dash = request.args.get("dashboard_id")
        q = db.session.query(AiscComment).filter(AiscComment.dashboard_id == dash)
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
        data = make_comment(
            dashboard_id=body["dashboard_id"], author_sub=sub, author_name=name,
            body=body.get("body", ""), chart_id=body.get("chart_id"),
            parent_id=body.get("parent_id"),
        )
        row = AiscComment(**{k: v for k, v in data.items() if k != "created_at"})
        db.session.add(row)
        db.session.commit()
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
        if not row:
            return self.response_404()
        if not can_delete(row.to_dict(), user_sub=sub, is_admin=is_admin):
            return self.response(403, message="Not your comment")
        db.session.delete(row)
        db.session.commit()
        _clerk.record(actor=name, action="comment.delete", target=row.dashboard_id,
                      extra={"comment_id": pk})
        return self.response(200, message="deleted")
