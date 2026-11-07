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


def project_for(dashboard, user) -> str | None:
    """The project of `dashboard` when `user` is in it (its role, from this sign-in's memberships) or an Admin,
    else None: the project whose ledger a write by `user` goes to."""
    from aisc_ext.projects import project_role_name

    pid = project_of(dashboard)
    if pid is None:
        return None
    mine = _names(getattr(user, "roles", None))
    return pid if project_role_name(pid) in mine or "Admin" in mine else None
