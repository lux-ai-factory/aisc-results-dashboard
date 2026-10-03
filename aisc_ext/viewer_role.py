# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Build the viewer role inside Superset from the permissions Gamma holds.

Which permissions a viewer keeps is decided in `security.py`, which has no
Superset imports so it can be unit-tested without the app. This module applies
that decision through Flask-AppBuilder.
"""
from __future__ import annotations

from aisc_ext.security import VIEWER_ROLE, viewer_permissions_from

#: The role the viewer is derived from. Gamma is Superset's role for "can see
#: what has been shared with me", but it also holds can_write on Chart and
#: Dashboard, which the viewer must not.
DERIVED_FROM = "Gamma"


def pairs_of(role) -> list[tuple[str, str]]:
    return [
        (pvm.permission.name, pvm.view_menu.name)
        for pvm in getattr(role, "permissions", [])
        if pvm.permission and pvm.view_menu
    ]


def ensure_viewer_role(sm, extra_writable_views=()) -> object | None:
    """Create or refresh the AiscViewer role and return it (None without Gamma).

    It is refreshed at every start, not created once, so it follows Superset
    upgrades: permissions added to Gamma still go through the viewer filter, and
    renamed ones are picked up instead of leaving the viewer with nothing.
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
