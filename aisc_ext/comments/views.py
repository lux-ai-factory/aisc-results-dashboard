# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The Assessment > Comments page: a read-only list of all comments.

Rendered by Flask-AppBuilder, so it does not depend on Superset's React
frontend. Imported only inside Superset."""
from flask_appbuilder import ModelView  # type: ignore
from flask_appbuilder.models.sqla.interface import SQLAInterface  # type: ignore

from aisc_ext.comments.model import AiscComment


class AiscCommentView(ModelView):
    datamodel = SQLAInterface(AiscComment)
    # Read-only. Comments are written on the Review page through the API,
    # which sets the author from the signed-in user and checks the dashboard
    # and the chart. A form here would do neither, and would let anyone with
    # can_edit rewrite someone else's comment.
    base_permissions = ["can_list", "can_show"]
    list_columns = ["dashboard_id", "chart_id", "author_name", "body", "created_at", "deleted_at"]
    show_columns = list_columns + ["parent_id", "author_sub"]
    search_columns = ["dashboard_id", "chart_id", "author_name"]
    add_columns = ["dashboard_id", "chart_id", "parent_id", "body"]
    edit_columns = ["body"]
    base_order = ("created_at", "desc")
    label_columns = {"dashboard_id": "Dashboard", "chart_id": "Chart",
                     "author_name": "Author", "created_at": "Created", "deleted_at": "Deleted"}
