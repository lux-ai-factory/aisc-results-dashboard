# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Feature 1: map Keycloak realm roles -> Superset (FAB) roles.

dashboard-admin  -> Admin   (full)
dashboard-editor -> Alpha   (create/edit charts & dashboards)
dashboard-viewer -> Gamma   (view + comment)
anything else    -> Gamma   (safe default; never elevate)
"""
from aisc_ext.security import extract_realm_roles, map_keycloak_roles


def test_extract_realm_roles():
    claims = {"realm_access": {"roles": ["dashboard-editor", "offline_access"]}}
    assert "dashboard-editor" in extract_realm_roles(claims)


def test_extract_handles_missing():
    assert extract_realm_roles({}) == []


def test_editor_maps_to_alpha():
    assert map_keycloak_roles(["dashboard-editor", "dashboard-viewer"]) == ["Alpha"]


def test_admin_maps_to_admin():
    assert map_keycloak_roles(["dashboard-admin"]) == ["Admin"]


def test_viewer_maps_to_gamma():
    assert map_keycloak_roles(["dashboard-viewer"]) == ["Gamma"]


def test_unknown_defaults_to_gamma_never_elevates():
    assert map_keycloak_roles(["random-role"]) == ["Gamma"]
    assert map_keycloak_roles([]) == ["Gamma"]
