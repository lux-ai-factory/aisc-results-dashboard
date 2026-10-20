# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Whether the caller may open a dashboard, decided by Superset's own check.

The Review page and the comments API both call `open_dashboard`, so a person who
cannot see a dashboard can neither open its Review page nor read, write or
delete its comments. Imported only inside Superset."""


def open_dashboard(id_or_slug):
    """(dashboard, None) when the caller may open it, else (None, 404 or 403)."""
    from superset.commands.dashboard.exceptions import (  # type: ignore
        DashboardAccessDeniedError, DashboardNotFoundError,
    )
    from superset.daos.dashboard import DashboardDAO  # type: ignore

    try:
        return DashboardDAO.get_by_id_or_slug(str(id_or_slug)), None
    except DashboardNotFoundError:
        return None, 404
    except DashboardAccessDeniedError:
        return None, 403
