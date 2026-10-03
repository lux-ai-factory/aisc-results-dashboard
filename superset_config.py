# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Superset configuration for the AISC results dashboard.

This file and the ``aisc_ext`` package are the whole customisation. Both are
mounted into the stock ``apache/superset`` image and found through PYTHONPATH;
Superset's own source is not changed, so an upgrade is an image tag bump.

Each customisation uses a documented Superset config hook:
  - branding          -> APP_NAME, APP_ICON, THEME_OVERRIDES (from env vars)
  - audit ledger      -> EVENT_LOGGER
  - Keycloak SSO      -> CUSTOM_SECURITY_MANAGER
  - comments, reviews -> FLASK_APP_MUTATOR (REST APIs and Flask-AppBuilder views)
  - embedding         -> FEATURE_FLAGS and the Talisman frame-ancestors policy
"""
import logging
import os

from aisc_ext import branding

# No default on purpose. This key signs every session cookie, so a value shipped
# in the repository would let anyone who read it forge a session as any user,
# Admin included. Without it the dashboard refuses to start.
try:
    SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
except KeyError:  # pragma: no cover - the message is the point
    raise RuntimeError(
        "SUPERSET_SECRET_KEY is not set. Generate one with `openssl rand -hex 32` "
        "and put it in .env; see .env.example."
    ) from None
SQLALCHEMY_DATABASE_URI = os.environ["SUPERSET_DB_URI"]

REDIS_HOST = os.environ.get("REDIS_HOST", "superset-redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
CACHE_CONFIG = {"CACHE_TYPE": "RedisCache", "CACHE_REDIS_HOST": REDIS_HOST,
                "CACHE_REDIS_PORT": REDIS_PORT, "CACHE_DEFAULT_TIMEOUT": 300}

# Branding comes from BRANDING_* env vars, with AISC as the default. A company
# rebrands by mounting its logo and setting those variables, without rebuilding
# the image. See aisc_ext/branding.py and .env.example.
APP_NAME = branding.app_name()
APP_ICON = branding.app_icon()
# The dashboard is step 5 of AISC, so its logo leads back to the AISC launcher
# rather than to Superset's home. Superset does not know which project the user
# came from, so this is the project list.
LOGO_TARGET_PATH = os.environ.get("LAUNCHER_URL", "http://localhost:8100/")
FAVICONS = branding.favicons()
THEME_OVERRIDES = branding.theme_overrides()
EXTRA_CATEGORICAL_COLOR_SCHEMES = branding.categorical_schemes()

# Only the features an assessment dashboard needs.
FEATURE_FLAGS = {
    "DASHBOARD_CROSS_FILTERS": True,   # click a bar to filter the other charts
    "DRILL_BY": True,
    "DRILL_TO_DETAIL": True,           # show the rows behind a chart
    "ALERT_REPORTS": False,            # would need SMTP and a Celery beat worker
    "THUMBNAILS": False,               # would need screenshot workers
    "GLOBAL_ASYNC_QUERIES": False,     # the data is small; synchronous queries suffice
    "TAGGING_SYSTEM": False,
    "ESTIMATE_QUERY_COST": False,
    "SSH_TUNNELING": False,            # the databases are on the same network
    "DYNAMIC_PLUGINS": False,
    "ENABLE_JAVASCRIPT_CONTROLS": False,  # would let chart authors run JavaScript (XSS)
    "ENABLE_FACTORY_RESET_COMMAND": False,  # destructive
    # Embedding: a host page can show a chart in an iframe and it stays
    # interactive (legend, cross-filters, drill), because Superset itself
    # renders it there.
    "EMBEDDED_SUPERSET": True,
    # Each project has one dashboard, visible only to that project's role, so a
    # member sees their project's dashboard and no other.
    "DASHBOARD_RBAC": True,
    "EMBEDDABLE_CHARTS": True,
}

PUBLIC_ROLE_LIKE = None  # no anonymous access

# Hide map charts and niche chart types that are hard to read (see README).
VIZ_TYPE_DENYLIST = [
    "world_map", "country_map", "mapbox",
    "deck_arc", "deck_grid", "deck_hex", "deck_multi", "deck_path",
    "deck_polygon", "deck_scatter", "deck_screengrid", "deck_geojson",
    "deck_contour", "deck_heatmap",
    "sankey", "sankey_v2", "chord", "sunburst", "sunburst_v2", "partition",
    "tree_chart", "graph_chart", "parallel_coordinates", "horizon", "rose",
    "paired_ttest",
]

PREVENT_UNSAFE_DB_CONNECTIONS = True

# Let the pages in EMBED_ALLOWED_ORIGINS (comma separated) frame the dashboard.
# The iframe uses the viewer's existing Keycloak session. The session cookie is
# then sent cross-site, which needs SameSite=None and Secure, so embedding only
# works over HTTPS. A browser that blocks third-party cookies outright needs
# Superset's guest tokens (/api/v1/security/guest_token/) instead.
#
# Superset's own Talisman policy is copied and only frame-ancestors is set, so
# no other CSP directive is lost. Check the resulting header against the running
# image before relying on it.
_embed_origins = [o.strip() for o in os.environ.get("EMBED_ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _embed_origins:
    from copy import deepcopy

    SESSION_COOKIE_SAMESITE = "None"
    SESSION_COOKIE_SECURE = True
    TALISMAN_ENABLED = True
    try:
        from superset.config import TALISMAN_CONFIG as _BASE_TALISMAN  # type: ignore

        TALISMAN_CONFIG = deepcopy(_BASE_TALISMAN)
    except Exception:  # pragma: no cover - defensive; shape verified at runtime
        TALISMAN_CONFIG = {"content_security_policy": {}}
    _csp = TALISMAN_CONFIG.setdefault("content_security_policy", {}) or {}
    _csp["frame-ancestors"] = ["'self'", *_embed_origins]
    TALISMAN_CONFIG["content_security_policy"] = _csp

# Superset events go to the AISC audit ledger (immudb).
from aisc_ext.event_logger import ImmudbEventLogger  # noqa: E402

EVENT_LOGGER = ImmudbEventLogger()

# Keycloak sign-in (OIDC), on when AISC_OAUTH=1.
if os.environ.get("AISC_OAUTH") == "1":
    from flask_appbuilder.security.manager import AUTH_OAUTH  # noqa: E402
    from aisc_ext.sso import KeycloakSecurityManager  # noqa: E402

    AUTH_TYPE = AUTH_OAUTH
    CUSTOM_SECURITY_MANAGER = KeycloakSecurityManager
    AUTH_USER_REGISTRATION = True
    # New users get the read-only viewer role, not Gamma: Gamma can edit charts
    # and dashboards that everyone else reads.
    from aisc_ext.security import VIEWER_ROLE  # noqa: E402

    AUTH_USER_REGISTRATION_ROLE = VIEWER_ROLE
    # Recompute roles at every sign-in, so a role changed in Keycloak (or a
    # project membership) takes effect at the next login.
    AUTH_ROLES_SYNC_AT_LOGIN = True
    OIDC_ISSUER = (os.environ.get("OIDC_ISSUER")
                   or "http://keycloak.localhost:8080/realms/dashboard")
    OAUTH_PROVIDERS = [{
        "name": "keycloak",
        "icon": "fa-key",
        "token_key": "access_token",
        "remote_app": {
            "client_id": os.environ.get("OIDC_CLIENT_ID") or "superset",
            "client_secret": os.environ.get("OIDC_CLIENT_SECRET") or "superset-secret",
            "server_metadata_url": f"{OIDC_ISSUER}/.well-known/openid-configuration",
            "api_base_url": f"{OIDC_ISSUER}/protocol/",
            "client_kwargs": {"scope": "openid email profile"},
        },
    }]


# Comments and review requests are Flask-AppBuilder views and REST APIs, so they
# do not depend on Superset's React frontend.

#: Permissions given, per view, to Admin, Alpha, Gamma and the viewer role, so
#: editors and viewers alike can use the Review page and its APIs.
_EXTENSION_GRANTS = {
    "CommentApi": ("can_list", "can_threads", "can_post", "can_delete"),
    "AiscReviewView": ("can_list", "can_show"),
    "Review dashboards": ("menu_access",),
    "ReviewRequestApi": ("can_list", "can_post", "can_patch", "can_assignees"),
}


def FLASK_APP_MUTATOR(app):  # noqa: N802 (Superset hook name)
    # There is only one identity provider, so an anonymous GET of /login/ goes
    # straight to Keycloak instead of showing a page with a single button. With
    # a Keycloak session the user is signed in without seeing anything.
    if os.environ.get("AISC_OAUTH") == "1":
        from flask import redirect, request, url_for  # noqa: E402
        from aisc_ext.sso import skip_provider_picker  # noqa: E402

        @app.before_request
        def _skip_provider_picker():  # pragma: no cover - exercised in the app
            try:
                from flask_login import current_user
                authenticated = bool(getattr(current_user, "is_authenticated", False))
            except Exception:
                authenticated = False
            provider = skip_provider_picker(request.path, request.method, authenticated)
            if provider is None:
                return None
            target = url_for("AuthOAuthView.login", provider=provider)
            nxt = request.args.get("next")
            return redirect(f"{target}?next={nxt}" if nxt else target)

    with app.app_context():
        # No Superset connection to the shared `platform` database is made
        # here. Each project's datasets use that project's own connection, which
        # the platform creates through the bridge API (aisc_ext/projects.py).
        # Memberships are read at sign-in over a plain DSN (aisc_ext/sso.py).
        # Query connections use Superset's default engines, which keep no
        # persistent pool.
        _install_extension(app)


def _install_extension(app):
    """Register the extension's APIs, views, tables, permissions and roles.

    The modules are imported outside the try on purpose: a module that fails to
    import is a broken deployment and should stop startup, while a failure while
    writing to Superset's metadata database should only be logged."""
    from aisc_ext.comments.api import CommentApi
    from aisc_ext.project_bridge_api import ProjectBridgeApi
    from aisc_ext.comments.model import AiscComment
    from aisc_ext.comments.views import AiscCommentView
    from aisc_ext.reviews.api import ReviewRequestApi
    from aisc_ext.reviews.model import AiscReviewRequest
    from aisc_ext.reviews.service import STAKEHOLDER_GROUPS
    from aisc_ext.reviews.views import AiscReviewRequestView
    from aisc_ext.review.views import AiscReviewView
    from superset import db
    appbuilder = app.appbuilder
    sm = appbuilder.sm
    try:
        # REST APIs for the Review page, the embedding host and the platform's
        # bridge (which creates and removes a project's dashboard).
        for api in (CommentApi, ProjectBridgeApi, ReviewRequestApi):
            appbuilder.add_api(api)
        # The Review page comes first in the menu: it is where people read and
        # write comments.
        for view, name, icon in (
            (AiscReviewView, "Review dashboards", "fa-comment-dots"),
            (AiscCommentView, "Comments", "fa-comments"),
            (AiscReviewRequestView, "Review Requests", "fa-clipboard-check"),
        ):
            appbuilder.add_view(view, name, category="Assessment", icon=icon)
        for model in (AiscComment, AiscReviewRequest):
            model.__table__.create(bind=db.engine, checkfirst=True)
        # A deleted comment is hidden, not removed, via aisc_comment.deleted_at.
        # Tables created before that column existed get it here. The ledger
        # outbox table lives in this same metadata database.
        from sqlalchemy import text

        from aisc_ext import ledger

        # Idempotent on Postgres. Two workers starting at once may still race;
        # the first one's work stays in place, so a failure is logged and
        # startup continues.
        try:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE aisc_comment ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP"))
            ledger.OUTBOX.metadata.create_all(db.engine)
        except Exception:                                               # noqa: BLE001
            logging.getLogger(__name__).exception("ledger: the comment column or the outbox was not made here")

        # The viewer role is Gamma without write permissions. It is created
        # before the grants below so that it can receive them.
        from aisc_ext.security import VIEWER_ROLE
        from aisc_ext.viewer_role import ensure_viewer_role

        ensure_viewer_role(sm, extra_writable_views=("AiscComment", "AiscReviewRequest"))
        _grant(sm, _EXTENSION_GRANTS, ("Admin", "Alpha", "Gamma", VIEWER_ROLE))

        # One role per stakeholder group, to assign review requests to.
        for group in STAKEHOLDER_GROUPS:
            sm.add_role(group)
        sm.get_session.commit()
    except Exception as exc:  # logged, startup continues
        app.logger.warning("AISC extension init skipped: %s", exc)


def _grant(sm, grants, role_names):
    """Give each named role that exists every (permission, view) in grants."""
    for view, perms in grants.items():
        for perm in perms:
            pvm = sm.add_permission_view_menu(perm, view)
            for role_name in role_names:
                role = sm.find_role(role_name)
                if role and pvm and pvm not in role.permissions:
                    role.permissions.append(pvm)
