# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Native Superset model for review requests (metadata DB). Runtime-only."""
from sqlalchemy import Column, DateTime, Integer, String, Text, func
from superset import db  # type: ignore

Model = db.Model


class AiscReviewRequest(Model):
    __tablename__ = "aisc_review_request"
    id = Column(Integer, primary_key=True, autoincrement=True)
    dashboard_id = Column(String(128), index=True, nullable=False)
    chart_id = Column(Integer, index=True, nullable=True)
    requested_by_sub = Column(String(255), nullable=False)
    requested_by_name = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    assignee_type = Column(String(16), nullable=False)        # user | category
    assignee_user_sub = Column(String(255), nullable=True, index=True)
    assignee_category = Column(String(64), nullable=True, index=True)
    status = Column(String(16), default="open", index=True)   # open|done|dismissed
    created_at = Column(DateTime, server_default=func.now())
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String(255), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "dashboard_id": self.dashboard_id, "chart_id": self.chart_id,
            "requested_by_name": self.requested_by_name, "message": self.message,
            "assignee_type": self.assignee_type,
            "assignee_user_sub": self.assignee_user_sub,
            "assignee_category": self.assignee_category, "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_by": self.resolved_by,
        }
