# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Native REST API for review requests, /api/v1/aisc_review_request.
Runtime-only (Flask/FAB/Superset). Audited to immudb."""
from flask import g, request
from flask_appbuilder.api import BaseApi, expose, protect, safe

from aisc_ext.audit import ImmudbClerk, clerk_kwargs_from_env
from aisc_ext.reviews.service import (
    STAKEHOLDER_GROUPS, can_resolve, is_for_user, make_request,
)

_clerk = ImmudbClerk(**clerk_kwargs_from_env())


def _user():
    u = g.user
    groups = [r.name for r in u.roles if r.name in STAKEHOLDER_GROUPS]
    is_admin = any(r.name == "Admin" for r in u.roles)
    return str(u.username), (u.get_full_name() or u.username), groups, is_admin


class ReviewRequestApi(BaseApi):
    resource_name = "aisc_review_request"
    openapi_spec_tag = "AISC Review Requests"

    @expose("/assignees", methods=["GET"])
    @protect(allow_browser_login=True)
    @safe
    def assignees(self):
        """Who can a review be assigned to: known users + stakeholder categories."""
        from superset import db
        from flask_appbuilder.security.sqla.models import User
        users = [{"sub": u.username, "name": u.get_full_name() or u.username}
                 for u in db.session.query(User).all()]
        return self.response(200, users=users, categories=STAKEHOLDER_GROUPS)

    @expose("/", methods=["GET"])
    @protect(allow_browser_login=True)
    @safe
    def list(self):
        """List requests. ?assignee=me  ?dashboard_id=  ?status=open"""
        from aisc_ext.reviews.model import AiscReviewRequest
        from superset import db
        sub, _, groups, _ = _user()
        q = db.session.query(AiscReviewRequest)
        if request.args.get("dashboard_id"):
            q = q.filter(AiscReviewRequest.dashboard_id == request.args["dashboard_id"])
        if request.args.get("status"):
            q = q.filter(AiscReviewRequest.status == request.args["status"])
        rows = [r.to_dict() for r in q.order_by(AiscReviewRequest.created_at.desc()).all()]
        if request.args.get("assignee") == "me":
            rows = [r for r in rows
                    if is_for_user(r, user_sub=sub, user_groups=groups)]
        return self.response(200, result=rows)

    @expose("/", methods=["POST"])
    @protect(allow_browser_login=True)
    @safe
    def post(self):
        from aisc_ext.reviews.model import AiscReviewRequest
        from superset import db
        sub, name, _, _ = _user()
        b = request.json or {}
        data = make_request(
            dashboard_id=b["dashboard_id"], requested_by_sub=sub, requested_by_name=name,
            message=b.get("message", ""), assignee_type=b.get("assignee_type"),
            assignee_user_sub=b.get("assignee_user_sub"),
            assignee_category=b.get("assignee_category"), chart_id=b.get("chart_id"),
        )
        row = AiscReviewRequest(**{k: v for k, v in data.items() if k != "created_at"})
        db.session.add(row); db.session.commit()
        tgt = data["assignee_user_sub"] or data["assignee_category"]
        _clerk.record(actor=name, action="review.request", target=row.dashboard_id,
                      extra={"id": row.id, "assignee": tgt, "type": data["assignee_type"]})
        return self.response(201, result=row.to_dict())

    @expose("/<int:pk>", methods=["PATCH"])
    @protect(allow_browser_login=True)
    @safe
    def patch(self, pk: int):
        from aisc_ext.reviews.model import AiscReviewRequest
        from superset import db
        from datetime import datetime, timezone
        sub, name, groups, is_admin = _user()
        row = db.session.query(AiscReviewRequest).get(pk)
        if not row:
            return self.response_404()
        if not can_resolve(row.to_dict(), user_sub=sub, user_groups=groups, is_admin=is_admin):
            return self.response(403, message="Not allowed to resolve this request")
        action = (request.json or {}).get("action", "done")
        row.status = "dismissed" if action == "dismiss" else "done"
        row.resolved_at = datetime.now(timezone.utc); row.resolved_by = name
        db.session.commit()
        _clerk.record(actor=name, action=f"review.{row.status}", target=row.dashboard_id,
                      extra={"id": pk})
        return self.response(200, result=row.to_dict())
