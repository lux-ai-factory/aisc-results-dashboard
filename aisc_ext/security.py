# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Pure, testable Keycloak -> Superset role mapping.

Kept free of any Superset/FAB imports so it unit-tests without the app. The FAB
SecurityManager that *uses* this lives in aisc_ext.sso (imported only at runtime
inside Superset)."""
from __future__ import annotations

#: What an ordinary signed-in account gets. Not Gamma: Gamma holds can_write on
#: Chart and Dashboard, so every account could edit or delete the dashboards
#: everyone else reads. This role looks and comments, and nothing else.
VIEWER_ROLE = "AiscViewer"

# Most-privileged first; the highest match wins and nothing elevates beyond it.
#
# admin and primary-user are the platform's own realm roles
# (keycloak/aisc-realm.json); without them every platform account, its admin
# included, would fall through to the default. The dashboard-* ones serve a
# deployment whose realm defines them.
_PRIORITY = [
    ("admin", "Admin"),
    ("dashboard-admin", "Admin"),
    ("dashboard-editor", "Alpha"),
    ("primary-user", VIEWER_ROLE),
    ("dashboard-viewer", VIEWER_ROLE),
]

#: The permissions a viewer keeps, by name. Anything not listed is not granted,
#: so a new Superset permission is absent until somebody decides otherwise.
VIEWER_PERMISSIONS = frozenset({
    "can_read",
    "menu_access",
    "can_list",
    "can_show",
    "can_get",
    "can_this_form_get",
    "can_this_form_post",
    "can_dashboard",
    "can_explore",
    "can_explore_json",
    "can_datasources",
    "can_fetch_datasource_metadata",
    "can_recent_activity",
    "can_available_domains",
    "can_favstar",
    "can_profile",
    "can_log",
})

#: Where a viewer may write: the comments and reviews they are here to leave.
#: These change nobody's data and are the point of the review workflow.
VIEWER_WRITABLE_VIEWS = ("AiscComment", "AiscReview")

#: Never, whatever else matches. SQL Lab on this instance reads the whole
#: platform database through dashboard_ro: every module's schema, every
#: project. A viewer is not given a query window onto that.
NEVER_FOR_A_VIEWER = frozenset({
    "can_sqllab",
    "can_sql_json",
    "can_execute_sql_query",
    "can_estimate_query_cost",
    "can_csv",
    "can_export",
    "all_database_access",
    "all_datasource_access",
    "can_write",
    "can_add",
    "can_edit",
    "can_delete",
})


def _viewer_keeps(name: str, view: str) -> bool:
    if name == "can_write" and view in VIEWER_WRITABLE_VIEWS:
        return True
    if name in NEVER_FOR_A_VIEWER:
        return False
    return name in VIEWER_PERMISSIONS or view in VIEWER_WRITABLE_VIEWS


def viewer_permissions_from(permissions) -> list[tuple[str, str]]:
    """The subset of (permission, view) pairs a viewer keeps.

    Given what another role holds, so the viewer is built from what this
    Superset actually has rather than from a list that drifts from it.
    """
    return [(name, view) for name, view in permissions if _viewer_keeps(name, view)]


def extract_realm_roles(claims: dict) -> list[str]:
    return list(claims.get("realm_access", {}).get("roles", []))


def roles_for_login(realm_roles: list[str], member_project_pids) -> list[str]:
    """The realm's role, then one AiscProject_<hex> per project the person is in.

    A project's dashboard is visible to its role only (DASHBOARD_RBAC), so this
    is what lets a member see it and keeps everyone else out."""
    from aisc_ext.projects import project_role_name

    out = list(map_keycloak_roles(realm_roles))
    for pid in member_project_pids or []:
        role = project_role_name(pid)
        if role not in out:
            out.append(role)
    return out


def map_keycloak_roles(realm_roles: list[str]) -> list[str]:
    roles = set(realm_roles or [])
    for kc_role, fab_role in _PRIORITY:
        if kc_role in roles:
            return [fab_role]
    # The default has to be the least thing, not the most convenient one.
    return [VIEWER_ROLE]
