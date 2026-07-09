# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Menu-accessible comment surface, rendered by Superset's own Flask-AppBuilder.

This replaces the retired DOM-injected widget: no coupling to Superset's React
markup, so a Superset upgrade cannot break it. Runtime-only (imports FAB)."""
from flask_appbuilder import ModelView  # type: ignore
from flask_appbuilder.models.sqla.interface import SQLAInterface  # type: ignore

from aisc_ext.comments.model import AiscComment


class AiscCommentView(ModelView):
    datamodel = SQLAInterface(AiscComment)
    list_columns = ["dashboard_id", "chart_id", "author_name", "body", "created_at"]
    show_columns = list_columns + ["parent_id", "author_sub"]
    search_columns = ["dashboard_id", "chart_id", "author_name"]
    add_columns = ["dashboard_id", "chart_id", "parent_id", "body"]
    edit_columns = ["body"]
    base_order = ("created_at", "desc")
    label_columns = {"dashboard_id": "Dashboard", "chart_id": "Chart",
                     "author_name": "Author", "created_at": "Created"}
