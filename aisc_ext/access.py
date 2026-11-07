# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Which project a dashboard is, and who may act on it in that project.

Superset's own check (dashboards.open_dashboard) says who may open a dashboard; this module says which
project's dashboard it is, from the binding the bridge records, and what a person may do there. Role names
come only from projects.project_role_name / editor_role_name. Pure: no Superset import."""
from __future__ import annotations


def _names(roles) -> set[str]:
    return {r.name for r in roles or []}


def project_of(dashboard) -> str | None:
    """The project a dashboard is of, or None.

    The slug alone is no binding: any owner of a dashboard may set it, so an editor of one project could name
    another's in it. The slug's project (``aisc-<pid hex>[-<plugin>]``) counts only when the dashboard carries
    that project's role (the bridge sets it; DASHBOARD_RBAC shows it to the project's members)."""
    from aisc_ext.ledger import project_of as slug_project
    from aisc_ext.projects import project_role_name

    pid = slug_project(getattr(dashboard, "slug", None))
    if pid is None or project_role_name(pid) not in _names(getattr(dashboard, "roles", None)):
        return None
    return pid


#: what a person may do on a project's dashboard (may)
ACTS = ("read", "comment", "export", "change_chart", "import")


def may(user, dashboard, act: str) -> bool:
    """Whether `user` may `act` on `dashboard`, in its project (project_of; on a dashboard of no project, nobody):

    - read, comment: a member of the project (its role, from this sign-in's memberships);
    - export (Save to report), change_chart (the chart assistant: change, remove, validate): an editor of the
      project, on any plot of the dashboard, without Superset's ownership check;
    - import (charts into a plugin tile): an editor who also owns the dashboard in Superset.

    An Admin may every act. Opening the dashboard at all is Superset's own check (dashboards.open_dashboard),
    made first by every route."""
    from aisc_ext.projects import editor_role_name, project_role_name

    if act not in ACTS:
        raise ValueError(f"no rule for {act!r}")
    pid = project_of(dashboard)
    if pid is None:
        return False
    mine = _names(getattr(user, "roles", None))
    if "Admin" in mine:
        return True
    member = project_role_name(pid) in mine
    editor = member and editor_role_name(pid) in mine
    if act in ("read", "comment"):
        return member
    if act in ("export", "change_chart"):
        return editor
    owns = any(getattr(o, "id", None) == getattr(user, "id", None) for o in getattr(dashboard, "owners", None) or [])
    return editor and owns


def project_if(user, dashboard, act: str) -> str | None:
    """The project of `dashboard` when `user` may `act` on it, else None: the project a route works in and whose
    ledger its event goes to."""
    return project_of(dashboard) if may(user, dashboard, act) else None
