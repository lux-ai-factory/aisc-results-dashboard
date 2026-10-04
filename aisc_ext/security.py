# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Keycloak to Superset role mapping, and which permissions a viewer keeps.

This module imports nothing from Superset or Flask-AppBuilder, so it can be
unit-tested without the app. The SecurityManager that uses it is aisc_ext.sso,
imported only inside Superset."""
from __future__ import annotations

#: The role of an ordinary signed-in account. Not Gamma: Gamma holds can_write
#: on Chart and Dashboard, so every account could edit or delete the dashboards
#: everyone else reads. This role can look and comment, nothing else.
VIEWER_ROLE = "AiscViewer"

# Most privileged first; the first match wins.
#
# admin and primary-user are the realm roles of the AISC realm
# (keycloak/aisc-realm.json in the aisc repo). The dashboard-* roles are for a
# deployment whose realm defines them.
_PRIORITY = [
    ("admin", "Admin"),
    ("dashboard-admin", "Admin"),
    ("dashboard-editor", "Alpha"),
    ("primary-user", VIEWER_ROLE),
    ("dashboard-viewer", VIEWER_ROLE),
]

#: The permissions a viewer keeps, by name. Anything not listed is not granted,
#: so a permission added by a Superset upgrade stays off until someone adds it.
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

#: The views where a viewer may write: comments and reviews. They change no
#: assessment data.
VIEWER_WRITABLE_VIEWS = ("AiscComment", "AiscReview")

#: Never granted to a viewer, whatever else matches: SQL Lab and raw SQL would
#: let a viewer query every table a connection can reach, beyond the charts
#: they were given; exports and writes are refused for the same reason.
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

    It filters what another role holds, so the viewer is built from the
    permissions this Superset version actually has rather than from a fixed list.
    """
    return [(name, view) for name, view in permissions if _viewer_keeps(name, view)]


def extract_realm_roles(claims: dict) -> list[str]:
    return list(claims.get("realm_access", {}).get("roles", []))


def _memberships(memberships):
    """[(pid, rank)] from what _member_projects gives: (pid, rank) pairs, or bare pids (read as viewers)."""
    out = []
    for m in memberships or []:
        pid, rank = (m[0], m[1]) if isinstance(m, (tuple, list)) else (m, "viewer")
        out.append((str(pid), str(rank or "viewer")))
    return out


def roles_for_login(realm_roles: list[str], memberships) -> list[str]:
    """The role mapped from the realm roles, then one project role per membership, and for an owner or
    editor the project's editor role too (plugin dashboards 2026-10-04: they build charts).

    A project's dashboards are visible to its project role only (DASHBOARD_RBAC),
    so these roles are what let a member see them and keep everyone else out."""
    from aisc_ext.projects import editor_role_name, project_role_name

    out = list(map_keycloak_roles(realm_roles))
    for pid, rank in _memberships(memberships):
        for role in [project_role_name(pid)] + ([editor_role_name(pid)] if rank in ("owner", "editor") else []):
            if role not in out:
                out.append(role)
    return out


def apply_sign_in(sm, user, realm_roles, memberships, *, sync_ownership=None) -> None:
    """What every sign-in does, whichever way the person came (the gateway's token or OAuth): the roles
    (roles_for_login), then, for owners and editors, ownership of their projects' plugin dashboards. Both
    paths call this one function: on 2026-10-05 the ownership step sat on the OAuth path only, and the stack
    signs people in through the gateway. An ownership failure is logged, never blocks the sign-in."""
    import logging

    desired = roles_for_login(realm_roles, memberships)
    user.roles = [sm.find_role(r) for r in desired if sm.find_role(r)]
    sm.update_user(user)
    if sync_ownership is None:
        return
    try:
        sync_ownership(user, memberships)
    except Exception:                                          # noqa: BLE001 - never block a sign-in
        logging.getLogger(__name__).warning("plugin dashboard owners not synced for %s",
                                            getattr(user, "username", "?"), exc_info=True)


def ownership_changes(memberships, dashboards) -> tuple[list[str], list[str]]:
    """Which plugin dashboards to make the person an owner of, and which to remove them from.

    dashboards: [(slug, project pid, the person owns it now)], the plugin dashboards (aisc_plugin in their
    metadata). An owner or editor of the project owns its plugin dashboards, which Superset needs to let them
    add charts; anyone else does not, so a rank that fell to viewer, or a membership that ended, takes it away."""
    builders = {pid for pid, rank in _memberships(memberships) if rank in ("owner", "editor")}
    add = sorted(slug for slug, pid, owns in dashboards if pid in builders and not owns)
    remove = sorted(slug for slug, pid, owns in dashboards if pid not in builders and owns)
    return add, remove


def map_keycloak_roles(realm_roles: list[str]) -> list[str]:
    roles = set(realm_roles or [])
    for kc_role, fab_role in _PRIORITY:
        if kc_role in roles:
            return [fab_role]
    # No matching realm role: the least privileged role.
    return [VIEWER_ROLE]
