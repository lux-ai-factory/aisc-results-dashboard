# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Which dashboard role a person gets, from the roles the AISC realm has.

The realm defines admin and primary-user, not the dashboard-* roles, so those
two must map, or every account (the admin included) falls to the default. The
default is the viewer role, not Gamma: Gamma holds can_write on Chart and
Dashboard, so every signed-in account could edit or delete the shared dashboards.
"""
from aisc_ext.security import VIEWER_ROLE, map_keycloak_roles


def test_the_platform_admin_administers_the_dashboard():
    assert map_keycloak_roles(["admin", "default-roles-aisc"]) == ["Admin"]


def test_an_ordinary_account_can_look_and_comment_only():
    assert map_keycloak_roles(["primary-user"]) == [VIEWER_ROLE]


def test_somebody_with_no_roles_at_all_gets_the_viewer_too():
    """The default is the least privileged role."""
    assert map_keycloak_roles([]) == [VIEWER_ROLE]
    assert map_keycloak_roles(None) == [VIEWER_ROLE]


def test_the_default_is_not_gamma_any_more():
    """Gamma may write charts and dashboards. A viewer may not."""
    assert map_keycloak_roles(["primary-user"]) != ["Gamma"]


def test_the_older_dashboard_specific_roles_still_work():
    """A deployment whose realm defines them keeps the finer grain."""
    assert map_keycloak_roles(["dashboard-admin"]) == ["Admin"]
    assert map_keycloak_roles(["dashboard-editor"]) == ["Alpha"]
    assert map_keycloak_roles(["dashboard-viewer"]) == [VIEWER_ROLE]


def test_the_most_privileged_match_wins_and_nothing_elevates_beyond_it():
    assert map_keycloak_roles(["primary-user", "admin"]) == ["Admin"]


def test_what_a_viewer_is_allowed_to_do():
    """The permissions the role is built from, so changing them means changing this list."""
    from aisc_ext.security import VIEWER_PERMISSIONS, viewer_permissions_from

    gamma_like = [
        ("can_read", "Chart"),
        ("can_write", "Chart"),
        ("can_read", "Dashboard"),
        ("can_write", "Dashboard"),
        ("can_sqllab", "Superset"),
        ("can_execute_sql_query", "SQLLab"),
        ("menu_access", "Dashboards"),
        ("can_read", "AiscComment"),
        ("can_write", "AiscComment"),
    ]
    kept = viewer_permissions_from(gamma_like)

    assert ("can_read", "Chart") in kept
    assert ("menu_access", "Dashboards") in kept
    # comments are the one thing a viewer writes; they change no assessment data
    assert ("can_write", "AiscComment") in kept
    assert ("can_write", "Chart") not in kept
    assert ("can_write", "Dashboard") not in kept
    assert ("can_sqllab", "Superset") not in kept
    assert ("can_execute_sql_query", "SQLLab") not in kept
    assert VIEWER_PERMISSIONS  # the names the role is built from are declared


def test_a_viewer_can_never_reach_sql_lab():
    """SQL Lab would let a viewer query every table a connection can reach."""
    from aisc_ext.security import viewer_permissions_from

    for permission in ("can_sqllab", "can_sql_json", "can_execute_sql_query", "can_csv"):
        assert viewer_permissions_from([(permission, "Superset")]) == []


# ── building the role inside Superset ────────────────────────────────────────
# The mapping above says which role a person gets. This says what that role
# holds: it is derived from the permissions this Superset actually has.


class _Named:
    def __init__(self, name):
        self.name = name


class _Pvm:
    def __init__(self, permission, view):
        self.permission = _Named(permission)
        self.view_menu = _Named(view)

    def __repr__(self):
        return f"{self.permission.name} on {self.view_menu.name}"


class _SecurityManager:
    """Just enough Flask-AppBuilder to build a role against."""

    def __init__(self, roles):
        self.roles = roles

    def find_role(self, name):
        return self.roles.get(name)

    def add_role(self, name):
        role = self.roles[name] = type("Role", (), {"name": name, "permissions": []})()
        return role

    def add_permission_view_menu(self, permission, view):
        return _Pvm(permission, view)


def _gamma_like():
    return type("Role", (), {"permissions": [
        _Pvm("can_read", "Chart"),
        _Pvm("can_write", "Chart"),
        _Pvm("can_read", "Dashboard"),
        _Pvm("can_write", "Dashboard"),
        _Pvm("menu_access", "Dashboards"),
        _Pvm("can_csv", "Superset"),
    ]})()


def test_the_viewer_is_gamma_without_the_writing():
    from aisc_ext.viewer_role import ensure_viewer_role

    sm = _SecurityManager({"Gamma": _gamma_like()})
    role = ensure_viewer_role(sm)

    held = {(p.permission.name, p.view_menu.name) for p in role.permissions}
    assert ("can_read", "Chart") in held
    assert ("menu_access", "Dashboards") in held
    assert ("can_write", "Chart") not in held
    assert ("can_write", "Dashboard") not in held
    assert ("can_csv", "Superset") not in held


def test_a_viewer_may_still_comment():
    from aisc_ext.viewer_role import ensure_viewer_role

    sm = _SecurityManager({"Gamma": _gamma_like()})
    role = ensure_viewer_role(sm, extra_writable_views=("AiscComment",))

    held = {(p.permission.name, p.view_menu.name) for p in role.permissions}
    assert ("can_write", "AiscComment") in held


def test_the_role_is_refreshed_not_only_created():
    """A Superset upgrade that adds a permission to Gamma must not add it here
    by inheritance, and one that removes it must not leave it behind."""
    from aisc_ext.viewer_role import ensure_viewer_role

    existing = type("Role", (), {"name": "AiscViewer", "permissions": [
        _Pvm("can_write", "Dashboard"),  # granted by an older start
        _Pvm("can_read", "Chart"),
    ]})()
    sm = _SecurityManager({"Gamma": _gamma_like(), "AiscViewer": existing})
    role = ensure_viewer_role(sm)

    held = {(p.permission.name, p.view_menu.name) for p in role.permissions}
    assert ("can_write", "Dashboard") not in held
    assert ("can_read", "Chart") in held


def test_no_gamma_to_derive_from_is_no_role_rather_than_an_empty_one():
    from aisc_ext.viewer_role import ensure_viewer_role

    assert ensure_viewer_role(_SecurityManager({})) is None
