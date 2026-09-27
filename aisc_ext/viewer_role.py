# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Build the viewer role inside Superset, from what Gamma actually holds.

Kept apart from `security.py`, which stays free of Superset imports so it can
be unit-tested without the app. The decision about which permissions a viewer
keeps is there; this is the part that talks to Flask-AppBuilder.
"""
from __future__ import annotations

from aisc_ext.security import VIEWER_ROLE, viewer_permissions_from

#: The role the viewer is derived from. Gamma is Superset's own "can look at
#: what has been shared with me", which is the right starting point; what it
#: also holds, and should not, is can_write on Chart and Dashboard.
DERIVED_FROM = "Gamma"


def pairs_of(role) -> list[tuple[str, str]]:
    return [
        (pvm.permission.name, pvm.view_menu.name)
        for pvm in getattr(role, "permissions", [])
        if pvm.permission and pvm.view_menu
    ]


def ensure_viewer_role(sm, extra_writable_views=()) -> object | None:
    """Create or refresh AiscViewer. Returns the role.

    Refreshed on every start rather than created once, so a Superset upgrade
    that adds permissions to Gamma does not silently add them here too, and one
    that renames them does not leave the viewer holding nothing.
    """
    source = sm.find_role(DERIVED_FROM)
    if source is None:
        return None
    wanted = set(viewer_permissions_from(pairs_of(source)))
    for view in extra_writable_views:
        wanted.add(("can_write", view))
        wanted.add(("can_read", view))

    role = sm.find_role(VIEWER_ROLE) or sm.add_role(VIEWER_ROLE)
    current = set(pairs_of(role))
    for permission, view in sorted(wanted - current):
        pvm = sm.add_permission_view_menu(permission, view)
        if pvm is not None:
            role.permissions.append(pvm)
    for pvm in list(getattr(role, "permissions", [])):
        if pvm.permission and pvm.view_menu:
            if (pvm.permission.name, pvm.view_menu.name) not in wanted:
                role.permissions.remove(pvm)
    return role
