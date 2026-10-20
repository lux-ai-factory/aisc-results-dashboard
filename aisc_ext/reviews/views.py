# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The Assessment > Review Requests page, rendered by Flask-AppBuilder.

Imported only inside Superset."""
from flask_appbuilder import ModelView  # type: ignore
from flask_appbuilder.models.sqla.interface import SQLAInterface  # type: ignore

from aisc_ext.reviews.model import AiscReviewRequest


class AiscReviewRequestView(ModelView):
    datamodel = SQLAInterface(AiscReviewRequest)
    # Read-only, as the comments table: requests are written through the API, which checks the dashboard, sets
    # the resolver and the time, and queues the ledger event. A form here would do none of that.
    base_permissions = ["can_list", "can_show"]
    list_columns = ["dashboard_id", "chart_id", "requested_by_name",
                    "assignee_type", "assignee_category", "status", "created_at"]
    show_columns = list_columns + ["message", "assignee_user_sub", "resolved_by",
                                   "resolved_at"]
    search_columns = ["dashboard_id", "status", "assignee_category", "assignee_type"]
    base_order = ("created_at", "desc")
    label_columns = {"dashboard_id": "Dashboard", "chart_id": "Chart",
                     "requested_by_name": "Requested by", "assignee_type": "Assignee type",
                     "assignee_category": "Category", "created_at": "Created"}
