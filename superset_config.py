# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Superset configuration overlay.

This file (plus the mounted ``aisc_ext`` package) is the ENTIRE customization:
it is layered onto the stock ``apache/superset`` image via PYTHONPATH. Nothing in
Superset's own source is touched, so upgrades are a one-line image-tag bump.

Every customization rides an official Superset config seam:
  - branding          -> APP_NAME / APP_ICON / THEME_OVERRIDES  (env-driven)
  - audit ledger      -> EVENT_LOGGER
  - Keycloak SSO      -> CUSTOM_SECURITY_MANAGER
  - comments/reviews  -> FLASK_APP_MUTATOR (API + native FAB views)
  - interactive embed -> FEATURE_FLAGS + Talisman frame-ancestors
"""
import os

from aisc_ext import branding

# ---- core ----
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "aisc-dev-secret-change-me")
SQLALCHEMY_DATABASE_URI = os.environ["SUPERSET_DB_URI"]

# ---- redis cache ----
REDIS_HOST = os.environ.get("REDIS_HOST", "superset-redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
CACHE_CONFIG = {"CACHE_TYPE": "RedisCache", "CACHE_REDIS_HOST": REDIS_HOST,
                "CACHE_REDIS_PORT": REDIS_PORT, "CACHE_DEFAULT_TIMEOUT": 300}

# ---- branding (Layer A) — resolved from env, AISC is the default tenant ----
# A company rebrands by mounting its logo and setting BRANDING_* env vars; no
# image rebuild. See aisc_ext/branding.py and .env.example.
APP_NAME = branding.app_name()
APP_ICON = branding.app_icon()
# The dashboard is one of the six steps, so its logo leads back out to the
# launcher rather than to Superset's own home. Superset knows nothing of a
# project, so it returns to the project list.
LOGO_TARGET_PATH = os.environ.get("LAUNCHER_URL", "http://localhost:8100/")
FAVICONS = branding.favicons()
THEME_OVERRIDES = branding.theme_overrides()
EXTRA_CATEGORICAL_COLOR_SCHEMES = branding.categorical_schemes()

# ---- feature flags: lean "curated assessment dashboard" posture ----
FEATURE_FLAGS = {
    "DASHBOARD_CROSS_FILTERS": True,   # click a bar -> filter others (useful)
    "DRILL_BY": True,                  # drill into a dimension (useful)
    "DRILL_TO_DETAIL": True,           # see underlying rows (useful)
    "ALERT_REPORTS": False,            # no scheduled email reports (needs SMTP+beat)
    "THUMBNAILS": False,               # no async screenshot workers
    "GLOBAL_ASYNC_QUERIES": False,     # small data -> synchronous; no worker needed
    "TAGGING_SYSTEM": False,           # BI clutter
    "ESTIMATE_QUERY_COST": False,      # analyst feature, unused
    "SSH_TUNNELING": False,            # single local DB
    "DYNAMIC_PLUGINS": False,          # curated plugins only
    "ENABLE_JAVASCRIPT_CONTROLS": False,  # XSS surface, keep off
    "ENABLE_FACTORY_RESET_COMMAND": False,  # destructive, keep off
    # ---- interactive embedding (Layer C): keep charts LIVE in a host iframe ----
    # Legend select/deselect, cross-filters and drill survive because Superset
    # itself renders the chart in the iframe. Native flags, no DOM patching.
    "EMBEDDED_SUPERSET": True,
    "EMBEDDABLE_CHARTS": True,
}

PUBLIC_ROLE_LIKE = None               # no anonymous access

# Chart curation: drop geospatial + hard-to-read niche types (see README).
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

# ---- interactive embedding: let host pages frame us (Layer C, cont.) ----
# Auth model = shared Keycloak SSO session: the iframe rides the viewer's
# existing AISC login. Set EMBED_ALLOWED_ORIGINS to the host origin(s).
#
# Cross-origin note: the session cookie must be sent in a third-party context,
# so we set SameSite=None; Secure -> this REQUIRES serving over HTTPS. If the
# browser still blocks the cookie (strict third-party-cookie policies), fall
# back to guest tokens (native /api/v1/security/guest_token/).
#
# VERIFY: confirm the resulting CSP against the running image before relying on
# it -- we extend Superset's shipped Talisman default rather than replace it, so
# no directive is dropped, but frame embedding is worth an end-to-end check.
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

# ---- audit -> immudb ----
from aisc_ext.event_logger import ImmudbEventLogger  # noqa: E402

EVENT_LOGGER = ImmudbEventLogger()

# ---- Keycloak OIDC (enabled when AISC_OAUTH=1) ----
if os.environ.get("AISC_OAUTH") == "1":
    from flask_appbuilder.security.manager import AUTH_OAUTH  # noqa: E402
    from aisc_ext.sso import KeycloakSecurityManager  # noqa: E402

    AUTH_TYPE = AUTH_OAUTH
    CUSTOM_SECURITY_MANAGER = KeycloakSecurityManager
    AUTH_USER_REGISTRATION = True
    AUTH_USER_REGISTRATION_ROLE = "Gamma"
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


# ---- register native comments/reviews: API + menu-accessible FAB views ----
# The old in-page widget (DOM-injected via an nginx sidecar) is GONE -- it was
# the one upgrade-fragile piece. Superset's own Flask-AppBuilder renders these
# views, so there is zero coupling to Superset's React/DOM.
def FLASK_APP_MUTATOR(app):  # noqa: N802 (Superset hook name)
    # ---- one provider, so skip FAB's one-button login page ----
    # An anonymous GET of /login/ goes straight to the provider. With a session
    # at the identity provider that is invisible; without one it lands on the
    # provider's own form instead of a page asking which provider to use.
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
        from aisc_ext.comments.api import CommentApi
        from aisc_ext.comments.model import AiscComment
        from aisc_ext.comments.views import AiscCommentView
        from aisc_ext.reviews.api import ReviewRequestApi
        from aisc_ext.reviews.model import AiscReviewRequest
        from aisc_ext.reviews.service import STAKEHOLDER_GROUPS
        from aisc_ext.reviews.views import AiscReviewRequestView
        from superset import db
        sm = app.appbuilder.sm
        try:
            # --- REST APIs (for the embedding host / programmatic use) ---
            app.appbuilder.add_api(CommentApi)
            app.appbuilder.add_api(ReviewRequestApi)
            # --- native menu-accessible CRUD surface (replaces the widget) ---
            app.appbuilder.add_view(
                AiscCommentView, "Comments", category="Assessment", icon="fa-comments")
            app.appbuilder.add_view(
                AiscReviewRequestView, "Review Requests", category="Assessment",
                icon="fa-clipboard-check")
            AiscComment.__table__.create(bind=db.engine, checkfirst=True)
            AiscReviewRequest.__table__.create(bind=db.engine, checkfirst=True)

            # --- grant API perms so editors+viewers can use them ---
            grants = {
                "CommentApi": ("can_list", "can_post", "can_delete"),
                "ReviewRequestApi": ("can_list", "can_post", "can_patch", "can_assignees"),
            }
            for view, perms in grants.items():
                for perm in perms:
                    pvm = sm.add_permission_view_menu(perm, view)
                    for role_name in ("Admin", "Alpha", "Gamma"):
                        role = sm.find_role(role_name)
                        if role and pvm and pvm not in role.permissions:
                            role.permissions.append(pvm)

            # --- stakeholder-group roles for review-request assignment ---
            for g in STAKEHOLDER_GROUPS:
                sm.add_role(g)
            sm.get_session.commit()
        except Exception as exc:  # don't block startup on this
            app.logger.warning("AISC extension init skipped: %s", exc)
