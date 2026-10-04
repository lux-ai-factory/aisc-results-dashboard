# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Keycloak OIDC SecurityManager for Superset.

Reads the Keycloak userinfo and, at each login, sets the user's Flask-AppBuilder
roles from their Keycloak realm roles and project memberships, using
security.roles_for_login. Imported only inside Superset."""
import logging
import os

from superset.security import SupersetSecurityManager  # type: ignore

from aisc_ext.projects import MEMBER_PROJECTS_SQL
from aisc_ext.results_db import membership_uri
from aisc_ext.security import ownership_changes, roles_for_login

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
            # passed on so auth_user_oauth can map them to roles
            "realm_roles": (data.get("realm_access") or {}).get("roles", []),
            # the Keycloak subject, which is what core.project_member records
            "subject": data.get("sub"),
        }

    def _member_projects(self, subject):
        """The project ids this Keycloak subject is a member of.

        Read from core.project_member over AISC_MEMBERSHIP_DB_URI (dashboard_ro on
        `platform`), with a plain SQLAlchemy engine without a pool that is
        disposed after this sign-in. It is never a Superset connection, so SQL
        Lab cannot reach `platform`. An unset DSN, a DSN that is not read-only,
        or an unreachable database gives an empty list (no project roles)."""
        if not subject:
            return []
        try:
            uri = membership_uri(os.environ)
        except ValueError as exc:
            log.error("memberships not read: %s", exc)
            return []
        if not uri:
            return []
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.pool import NullPool

            engine = create_engine(uri, poolclass=NullPool)
            try:
                with engine.connect() as connection:
                    rows = connection.exec_driver_sql(MEMBER_PROJECTS_SQL, {"subject": subject})
                    return [(str(r[0]), str(r[1])) for r in rows]          # (pid, rank)
            finally:
                engine.dispose()
        except Exception:
            log.warning("could not read the projects of %s", subject, exc_info=True)
            return []

    def auth_user_oauth(self, userinfo):
        user = super().auth_user_oauth(userinfo)
        if user is None:
            return None
        memberships = self._member_projects(userinfo.get("subject"))
        desired = roles_for_login(userinfo.get("realm_roles", []), memberships)
        user.roles = [self.find_role(r) for r in desired if self.find_role(r)]
        self.update_user(user)
        log.info("Synced %s -> %s", user.username, desired)
        try:
            self._sync_dashboard_ownership(user, memberships)
        except Exception:                                          # noqa: BLE001 - never block a sign-in
            log.warning("plugin dashboard owners not synced for %s", user.username, exc_info=True)
        return user

    def _sync_dashboard_ownership(self, user, memberships):
        """Owners and editors own their projects' plugin dashboards, so they can add charts to them
        (plugin dashboards 2026-10-04); anyone else is removed (security.ownership_changes)."""
        import json

        from superset import db  # type: ignore
        from superset.models.dashboard import Dashboard  # type: ignore

        found = []
        for d in db.session.query(Dashboard):
            try:
                meta = json.loads(d.json_metadata or "{}")
            except ValueError:
                continue
            if meta.get("aisc_plugin") and meta.get("aisc_project"):
                found.append((d, meta["aisc_project"]))
        add, remove = ownership_changes(memberships, [(d.slug, pid, user in d.owners) for d, pid in found])
        for d, _pid in found:
            if d.slug in add:
                d.owners = list(d.owners) + [user]
            elif d.slug in remove:
                d.owners = [o for o in d.owners if o.id != user.id]
        if add or remove:
            db.session.commit()
            log.info("plugin dashboards of %s: owner of %s, no longer of %s", user.username, add, remove)

def skip_provider_picker(path, method, authenticated, provider="keycloak"):
    """The provider to redirect this request to, or None to leave it alone.

    With a single OAuth provider, Flask-AppBuilder's /login/ is a page with one
    button. Most visitors already have a Keycloak session, so sending them
    straight to /login/<provider> signs them in without a visible step, and
    shows Keycloak's own form to those who must authenticate.

    Only an anonymous GET of /login itself is redirected. /login/<provider> is
    left alone (redirecting it would loop), so are POSTs (FAB's own form) and
    signed-in visitors, whom FAB already sends to the index."""
    if method != "GET" or authenticated:
        return None
    if path.rstrip("/") != "/login":
        return None
    return provider
