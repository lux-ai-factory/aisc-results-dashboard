# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Branding is resolved from env with AISC as the built-in default tenant, so a
company rebrands by setting env + mounting a logo (no image rebuild). Pure logic,
no Superset import -> unit-testable standalone."""
from aisc_ext import branding


def test_shade_hex_darken_and_lighten():
    assert branding.shade_hex("#000000", 0.5) == "#808080"   # lighten black -> grey
    assert branding.shade_hex("#ffffff", -0.5) == "#808080"  # darken white -> grey
    assert branding.shade_hex("#001075", 0.0) == "#001075"   # no-op
    # clamps, stays valid 7-char hex
    out = branding.shade_hex("#001075", -0.9)
    assert out.startswith("#") and len(out) == 7


def test_defaults_are_aisc_when_env_empty():
    env: dict[str, str] = {}
    assert branding.app_name(env) == "AI Assessment Sandbox"
    assert branding.app_icon(env) == "/static/assets/branding/aisc/laif_logo.png"
    theme = branding.theme_overrides(env)
    assert theme["colors"]["primary"]["base"] == "#001075"
    assert theme["colors"]["secondary"]["base"] == "#D7193B"


def test_empty_or_blank_env_falls_back_to_default():
    # docker-compose forwards unset .env vars as "" -> must fall back, not blank out
    env = {"BRANDING_APP_NAME": "", "BRANDING_PRIMARY": "   ", "BRANDING_LOGO": ""}
    assert branding.app_name(env) == "AI Assessment Sandbox"
    assert branding.app_icon(env) == "/static/assets/branding/aisc/laif_logo.png"
    assert branding.theme_overrides(env)["colors"]["primary"]["base"] == "#001075"


def test_company_override_produces_its_own_branding():
    env = {
        "BRANDING_APP_NAME": "Acme Assurance",
        "BRANDING_LOGO": "/static/assets/branding/acme/logo.png",
        "BRANDING_PRIMARY": "#0a7d32",
        "BRANDING_SECONDARY": "#ff6600",
    }
    assert branding.app_name(env) == "Acme Assurance"
    assert branding.app_icon(env) == "/static/assets/branding/acme/logo.png"
    theme = branding.theme_overrides(env)
    primary = theme["colors"]["primary"]
    assert primary["base"] == "#0a7d32"
    # derived shades are valid hex and differ from base
    for key in ("dark1", "light1"):
        assert primary[key].startswith("#") and len(primary[key]) == 7
    assert primary["dark1"] != primary["base"] != primary["light1"]
    assert theme["colors"]["secondary"]["base"] == "#ff6600"


def test_categorical_scheme_leads_with_brand_colors():
    env = {"BRANDING_PRIMARY": "#0a7d32", "BRANDING_SECONDARY": "#ff6600"}
    schemes = branding.categorical_schemes(env)
    scheme = schemes[0]
    assert scheme["isDefault"] is True
    assert scheme["colors"][0] == "#0a7d32"   # primary leads
    assert scheme["colors"][2] == "#ff6600"   # secondary in slot 2 (as AISC default)
