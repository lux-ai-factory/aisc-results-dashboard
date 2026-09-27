# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Keycloak OIDC SecurityManager for Superset.

Reads the Keycloak userinfo, and on each login syncs the user's FAB roles from
their Keycloak realm roles and project memberships via the (unit-tested)
roles_for_login. Runtime-only."""
import logging
import os

from superset.security import SupersetSecurityManager  # type: ignore

from aisc_ext.projects import MEMBER_PROJECTS_SQL
from aisc_ext.security import roles_for_login

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
            # the Keycloak subject, which is what core.project_member records
            "subject": data.get("sub"),
        }

    def _member_projects(self, subject):
        """The projects this subject is in, over the dashboard_ro results
        connection. None known (or the database down) means no project role."""
        if not subject:
            return []
        uri = os.environ.get("AISC_RESULTS_DB_URI", "")
        if not uri:
            return []
        try:
            from sqlalchemy import create_engine

            engine = create_engine(uri)
            try:
                with engine.connect() as connection:
                    rows = connection.exec_driver_sql(MEMBER_PROJECTS_SQL, {"subject": subject})
                    return [str(r[0]) for r in rows]
            finally:
                engine.dispose()
        except Exception:
            log.warning("could not read the projects of %s", subject, exc_info=True)
            return []

    def auth_user_oauth(self, userinfo):
        user = super().auth_user_oauth(userinfo)
        if user is None:
            return None
        desired = roles_for_login(
            userinfo.get("realm_roles", []), self._member_projects(userinfo.get("subject")))
        user.roles = [self.find_role(r) for r in desired if self.find_role(r)]
        self.update_user(user)
        log.info("Synced %s -> %s", user.username, desired)
        return user

def skip_provider_picker(path, method, authenticated, provider="keycloak"):
    """The provider to jump to for this request, or None to leave it alone.

    With a single OAuth provider, Flask-AppBuilder's /login/ is a page with one
    button on it. Anyone arriving there already has a session at the identity
    provider more often than not, so the button is pure friction: sending them
    straight to /login/<provider> logs them in without a visible sign-in screen,
    and sends them to the provider's own form when they do need to authenticate.

    Deliberately narrow: only an anonymous GET of the login page itself. The
    provider route is left alone (it is where this sends people, so redirecting
    it would loop), POSTs are left alone (FAB's own form), and an authenticated
    visitor is left to FAB, which already redirects them to the index rather
    than starting another OAuth round trip."""
    if method != "GET" or authenticated:
        return None
    if path.rstrip("/") != "/login":
        return None
    return provider
