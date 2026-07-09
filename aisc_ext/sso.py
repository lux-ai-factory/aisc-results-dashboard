# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Keycloak OIDC SecurityManager for Superset.

Reads the Keycloak userinfo, and on each login syncs the user's FAB roles from
their Keycloak realm roles via the (unit-tested) map_keycloak_roles. Runtime-only."""
import logging

from superset.security import SupersetSecurityManager  # type: ignore

from aisc_ext.security import map_keycloak_roles

log = logging.getLogger(__name__)


class KeycloakSecurityManager(SupersetSecurityManager):
    def oauth_user_info(self, provider, response=None):
        if provider != "keycloak":
            return super().oauth_user_info(provider, response)
        me = self.appbuilder.sm.oauth_remotes[provider].get("openid-connect/userinfo")
        data = me.json()
        return {
            "username": data.get("preferred_username"),
            "email": data.get("email"),
            "first_name": data.get("given_name", ""),
            "last_name": data.get("family_name", ""),
            # carried through so the role sync below can read it
            "realm_roles": (data.get("realm_access") or {}).get("roles", []),
        }

    def auth_user_oauth(self, userinfo):
        user = super().auth_user_oauth(userinfo)
        if user is None:
            return None
        desired = map_keycloak_roles(userinfo.get("realm_roles", []))
        user.roles = [self.find_role(r) for r in desired if self.find_role(r)]
        self.update_user(user)
        log.info("Synced %s -> %s", user.username, desired)
        return user
