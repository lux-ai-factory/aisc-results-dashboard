# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Feature 1: map Keycloak realm roles -> Superset (FAB) roles.

dashboard-admin  -> Admin   (full)
dashboard-editor -> Alpha   (create/edit charts & dashboards)
dashboard-viewer -> AiscViewer (view + comment)
anything else    -> AiscViewer (safe default; never elevate)

The viewer used to be Gamma, which also holds can_write on Chart and Dashboard:
every signed-in account could edit what everybody else reads. See tests/test_roles.py.
"""
from aisc_ext.security import VIEWER_ROLE, extract_realm_roles, map_keycloak_roles


def test_extract_realm_roles():
    claims = {"realm_access": {"roles": ["dashboard-editor", "offline_access"]}}
    assert "dashboard-editor" in extract_realm_roles(claims)


def test_extract_handles_missing():
    assert extract_realm_roles({}) == []


def test_editor_maps_to_alpha():
    assert map_keycloak_roles(["dashboard-editor", "dashboard-viewer"]) == ["Alpha"]


def test_admin_maps_to_admin():
    assert map_keycloak_roles(["dashboard-admin"]) == ["Admin"]


def test_viewer_maps_to_the_viewer_role():
    assert map_keycloak_roles(["dashboard-viewer"]) == [VIEWER_ROLE]


def test_unknown_defaults_to_the_viewer_never_elevates():
    assert map_keycloak_roles(["random-role"]) == [VIEWER_ROLE]
    assert map_keycloak_roles([]) == [VIEWER_ROLE]
