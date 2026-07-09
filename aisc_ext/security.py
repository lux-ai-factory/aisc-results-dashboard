# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Pure, testable Keycloak -> Superset role mapping.

Kept free of any Superset/FAB imports so it unit-tests without the app. The FAB
SecurityManager that *uses* this lives in aisc_ext.sso (imported only at runtime
inside Superset)."""
from __future__ import annotations

# Most-privileged first; we pick the highest match and never elevate beyond it.
_PRIORITY = [
    ("dashboard-admin", "Admin"),
    ("dashboard-editor", "Alpha"),
    ("dashboard-viewer", "Gamma"),
]


def extract_realm_roles(claims: dict) -> list[str]:
    return list(claims.get("realm_access", {}).get("roles", []))


def map_keycloak_roles(realm_roles: list[str]) -> list[str]:
    roles = set(realm_roles or [])
    for kc_role, fab_role in _PRIORITY:
        if kc_role in roles:
            return [fab_role]
    return ["Gamma"]  # safe default: view + comment, never elevate
