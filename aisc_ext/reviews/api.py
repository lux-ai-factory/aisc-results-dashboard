# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""REST API for review requests, under /api/v1/aisc_review_request.

When LEDGER_MODE is on, each action is queued as a ledger event in its own
transaction. Imported only inside Superset."""
from flask import g, request
from flask_appbuilder.api import BaseApi, expose, protect, safe

from aisc_ext import ledger
from aisc_ext.comments.api import _send_queued
from aisc_ext.dashboards import open_dashboard
from aisc_ext.review.service import charts_in_layout
from aisc_ext.reviews.service import (
    STAKEHOLDER_GROUPS, NotOpen, is_for_user, list_key, may_resolve, new_request, resolution, visible,
)


def _slug_of(dashboard_id) -> str | None:
    """The slug of the dashboard a review request names by id or slug, for its ledger event."""
    from superset import db
    from superset.models.dashboard import Dashboard  # type: ignore

    key = str(dashboard_id or "")
    query = db.session.query(Dashboard)
    found = query.filter(Dashboard.id == int(key)).one_or_none() if key.isdigit() else \
        query.filter(Dashboard.slug == key).one_or_none()
    return found.slug if found is not None else None


def _user():
    u = g.user
    groups = [r.name for r in u.roles if r.name in STAKEHOLDER_GROUPS]
    is_admin = any(r.name == "Admin" for r in u.roles)
    return str(u.username), (u.get_full_name() or u.username), groups, is_admin


class ReviewRequestApi(BaseApi):
    resource_name = "aisc_review_request"
    openapi_spec_tag = "AISC Review Requests"
    # As CommentApi: called with the session cookie, so not exempt from CSRF (Flask-AppBuilder exempts
    # its APIs unless told otherwise), and every route works on a dashboard the caller can open.
    csrf_exempt = False

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

    @expose("/assignees", methods=["GET"])
    @protect(allow_browser_login=True)
    @safe
    def assignees(self):
        """Who a review of ?dashboard_id= can be assigned to: the people whose roles may open that
        dashboard, and the stakeholder groups."""
        from superset import db
        from flask_appbuilder.security.sqla.models import User
        dashboard, refused = self._dashboard(request.args.get("dashboard_id"))
        if refused is not None:
            return refused
        roles = {r.name for r in getattr(dashboard, "roles", [])}
        users = [{"sub": u.username, "name": u.get_full_name() or u.username}
                 for u in db.session.query(User).all() if roles & {r.name for r in u.roles}]
        return self.response(200, users=users, categories=STAKEHOLDER_GROUPS)

    @expose("/", methods=["GET"])
    @protect(allow_browser_login=True)
    @safe
    def list(self):
        """List review requests, filtered by ?assignee=me, ?dashboard_id= and ?status=."""
        from aisc_ext.reviews.model import AiscReviewRequest
        from superset import db
        sub, _, groups, _ = _user()
        q = db.session.query(AiscReviewRequest)
        if request.args.get("dashboard_id"):
            # Stored under the dashboard's id; the caller may name it by id or by slug
            key = list_key(request.args["dashboard_id"], lambda k: open_dashboard(k)[0])
            q = q.filter(AiscReviewRequest.dashboard_id == key)
        if request.args.get("status"):
            q = q.filter(AiscReviewRequest.status == request.args["status"])
        rows = [r.to_dict() for r in q.order_by(AiscReviewRequest.created_at.desc()).all()]
        rows = visible(rows, lambda d: open_dashboard(d)[1] is None)    # only dashboards the caller can open
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
        dashboard, refused = self._dashboard(b.get("dashboard_id"))
        if refused is not None:
            return refused
        charts = charts_in_layout(dashboard.position_json, [(s.id, s.slice_name) for s in dashboard.slices])
        try:
            data = new_request(b, dashboard, requested_by_sub=sub, requested_by_name=name, charts=charts)
        except (ValueError, TypeError) as exc:                          # said, not a 500
            return self.response_400(message=str(exc))
        slug = _slug_of(data["dashboard_id"])
        if (problem := ledger.hint_problem(request.args.get("dashboard"), slug)) is not None:
            return self.response_400(message=problem)
        row = AiscReviewRequest(**{k: v for k, v in data.items() if k != "created_at"})
        db.session.add(row)
        db.session.flush()                                              # gives the row its id, for the event
        ledger.emit(db.session.connection(), ledger.project_for(dashboard, g.user), "dashboard.review.requested",
                    ledger.review_requested(row.to_dict(), slug=slug,
                                            request=ledger.request_id(request.headers, request.environ)))
        db.session.commit()
        _send_queued()
        return self.response(201, result=row.to_dict())

    @expose("/<int:pk>", methods=["PATCH"])
    @protect(allow_browser_login=True)
    @safe
    def patch(self, pk: int):
        from aisc_ext.reviews.model import AiscReviewRequest
        from superset import db
        from datetime import datetime, timezone
        sub, name, groups, is_admin = _user()
        # Locked, so the status read here is the one this resolution replaces,
        # even when two people resolve the same request at once.
        row = db.session.query(AiscReviewRequest).filter(AiscReviewRequest.id == pk).with_for_update().one_or_none()
        if not row:
            return self.response_404()
        dashboard, refused = self._dashboard(row.dashboard_id)
        if refused is not None:
            return self.response_404()                                 # never say it exists
        if not may_resolve(row, user_sub=sub, user_groups=groups, is_admin=is_admin):
            return self.response(403, message="Not allowed to resolve this request")
        action = (request.json or {}).get("action", "done")
        slug = _slug_of(row.dashboard_id)
        if (problem := ledger.hint_problem(request.args.get("dashboard"), slug)) is not None:
            return self.response_400(message=problem)
        status_before = row.status or "open"
        try:
            status_after = resolution(row.status, action)
        except NotOpen as exc:                                          # resolved once only
            return self.response(409, message=str(exc))
        except ValueError as exc:                                       # an unknown action
            return self.response_400(message=str(exc))
        row.status = status_after
        row.resolved_at = datetime.now(timezone.utc)
        row.resolved_by = name
        ledger.emit(db.session.connection(), ledger.project_for(dashboard, g.user), "dashboard.review.resolved",
                    ledger.review_resolved(row.to_dict(), status_before=status_before, slug=slug,
                                              request=ledger.request_id(request.headers, request.environ)))
        db.session.commit()
        _send_queued()
        return self.response(200, result=row.to_dict())
