# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The dashboard's "← Back": one level up, to the project's AI Assessment Sandbox on the launcher (step 4),
where the dashboard is opened from.

Superset does not know which project a page belongs to (the list shows every tile of the person), so the
platform's link names it (?aisc_project=<pid>, platform_service/dashboards.py open_url) and the session keeps
it for the pages the person moves on to. The view that redirects is in back_view.py."""
import re

PARAM = "aisc_project"
_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def remember(args, session) -> None:
    """Keep the project the link names; anything that is not a project id is ignored."""
    pid = (args.get(PARAM) or "").strip().lower()
    if _PID.match(pid):
        session[PARAM] = pid


def target(session, launcher: str) -> str:
    """The project's Sandbox, or the launcher itself when no project is known."""
    pid = session.get(PARAM)
    return f"{launcher.rstrip('/')}/evidence.html?project={pid}" if pid else launcher
