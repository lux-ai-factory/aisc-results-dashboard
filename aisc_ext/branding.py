# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Branding (name, logo, colours) from environment variables, AISC by default.

A company rebrands the dashboard by mounting its logo and setting the BRANDING_*
variables (see .env.example), without rebuilding the image. The module imports
nothing from Superset, so it can be unit-tested and imported from
superset_config.py at startup.
"""
from __future__ import annotations

import os
from typing import Mapping

# AISC defaults
DEFAULT_APP_NAME = "AI Assessment Sandbox"
DEFAULT_LOGO = "/static/assets/branding/aisc/laif_logo.png"
DEFAULT_PRIMARY = "#001075"
DEFAULT_SECONDARY = "#D7193B"
# accent colours that fill the categorical colour scheme after the brand colours
_ACCENTS = ["#1976d2", "#2dd4bf", "#fbbf24", "#7c3aed", "#0ea5e9", "#10b981"]


def _get(env: Mapping[str, str] | None, name: str, default: str) -> str:
    """Read an env var; unset or blank means the default.

    Blank counts as unset because compose passes "" for a variable missing from .env."""
    val = (env if env is not None else os.environ).get(name)
    return val.strip() if (val and val.strip()) else default


def shade_hex(hex_color: str, factor: float) -> str:
    """Darken (factor < 0) or lighten (factor > 0) a #rrggbb color.

    factor in [-1, 1]: -1 -> black, +1 -> white, 0 -> unchanged.
    """
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))

    def adj(c: int) -> int:
        c = c * (1 + factor) if factor < 0 else c + (255 - c) * factor
        return max(0, min(255, round(c)))

    return "#{:02x}{:02x}{:02x}".format(adj(r), adj(g), adj(b))


def app_name(env: Mapping[str, str] | None = None) -> str:
    return _get(env, "BRANDING_APP_NAME", DEFAULT_APP_NAME)


def app_icon(env: Mapping[str, str] | None = None) -> str:
    return _get(env, "BRANDING_LOGO", DEFAULT_LOGO)


def _primary(env: Mapping[str, str] | None) -> str:
    return _get(env, "BRANDING_PRIMARY", DEFAULT_PRIMARY)


def _secondary(env: Mapping[str, str] | None) -> str:
    return _get(env, "BRANDING_SECONDARY", DEFAULT_SECONDARY)


def theme_overrides(env: Mapping[str, str] | None = None) -> dict:
    """Superset THEME_OVERRIDES. The dark1 and light1 shades are derived from the
    primary colour, so a company supplies only one hex value."""
    primary = _primary(env)
    return {
        "colors": {
            "primary": {
                "base": primary,
                "dark1": shade_hex(primary, -0.35),
                "light1": shade_hex(primary, 0.4),
            },
            "secondary": {"base": _secondary(env)},
        },
    }


def categorical_schemes(env: Mapping[str, str] | None = None) -> list[dict]:
    """One default categorical colour scheme that starts with the brand colours."""
    return [{
        "id": "brand",
        "label": app_name(env),
        "isDefault": True,
        "colors": [_primary(env), _ACCENTS[0], _secondary(env), *_ACCENTS[1:]],
    }]


def favicons(env: Mapping[str, str] | None = None) -> list[dict]:
    return [{"href": app_icon(env)}]
