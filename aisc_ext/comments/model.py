# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""SQLAlchemy model of a dashboard comment, stored in Superset's metadata database.

Imported only inside Superset (it uses Superset's Model base)."""
from sqlalchemy import Column, DateTime, Integer, String, Text, func

from superset import db  # type: ignore

Model = db.Model


class AiscComment(Model):
    __tablename__ = "aisc_comment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dashboard_id = Column(String(128), index=True, nullable=False)
    chart_id = Column(Integer, index=True, nullable=True)   # None: about the whole dashboard
    parent_id = Column(Integer, nullable=True)              # the comment this one replies to
    author_sub = Column(String(255), nullable=False)
    author_name = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    # A deleted comment is hidden, not removed: its text stays here, and the ledger event
    # dashboard.comment.deleted records it too.
    deleted_at = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "dashboard_id": self.dashboard_id,
            "chart_id": self.chart_id, "parent_id": self.parent_id,
            "author_sub": self.author_sub, "author_name": self.author_name,
            "body": self.body,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
