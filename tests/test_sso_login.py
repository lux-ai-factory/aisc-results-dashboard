# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""With one OAuth provider, FAB's login page has a single button.
`skip_provider_picker` decides when to send a request straight to the provider
instead, so a visitor with a Keycloak session never sees a sign-in screen.

Importing aisc_ext.sso needs Superset, so this file runs only where Superset is
installed."""
from aisc_ext.sso import skip_provider_picker


def test_anonymous_get_on_the_login_page_goes_to_the_provider():
    assert skip_provider_picker("/login/", "GET", authenticated=False) == "keycloak"


def test_trailing_slash_does_not_matter():
    assert skip_provider_picker("/login", "GET", authenticated=False) == "keycloak"


def test_an_authenticated_visitor_is_left_alone():
    # FAB already redirects them to the index; do not start another OAuth round trip.
    assert skip_provider_picker("/login/", "GET", authenticated=True) is None


def test_the_provider_route_itself_is_not_redirected():
    assert skip_provider_picker("/login/keycloak", "GET", authenticated=False) is None


def test_other_paths_are_untouched():
    for path in ("/", "/health", "/superset/welcome/", "/logout/", "/api/v1/chart/"):
        assert skip_provider_picker(path, "GET", authenticated=False) is None


def test_only_get_is_redirected():
    assert skip_provider_picker("/login/", "POST", authenticated=False) is None


def test_a_different_provider_name_is_honoured():
    assert skip_provider_picker("/login/", "GET", authenticated=False, provider="azure") == "azure"
