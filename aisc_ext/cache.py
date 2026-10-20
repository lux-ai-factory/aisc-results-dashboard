# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Superset's cache (CACHE_CONFIG): a Redis of the dashboard's own, with a password.

Flask-Caching's RedisCache stores values with cachelib, which unpickles whatever it reads back. A Redis that
anyone else can write to is therefore code execution in the dashboard: the stack's shared ``redis`` has no
password and the eval worker, where third-party plugin code runs, reaches it.
So the cache never reads REDIS_HOST, the shared one, only DASHBOARD_REDIS_HOST, DASHBOARD_REDIS_PORT and
DASHBOARD_REDIS_PASSWORD, and the dashboard refuses to start without a password. No Superset import,
so it unit-tests on its own."""
from __future__ import annotations

from typing import Mapping

#: Superset's keys in that Redis, so they are recognisable as the dashboard's.
KEY_PREFIX = "aisc_dashboard_"


def cache_config(env: Mapping[str, str]) -> dict:
    """CACHE_CONFIG from the environment; RuntimeError when the cache's Redis has no password."""
    password = (env.get("DASHBOARD_REDIS_PASSWORD") or "").strip()
    if not password:
        raise RuntimeError(
            "DASHBOARD_REDIS_PASSWORD is not set. The dashboard's cache is a Redis of its own with a password "
            "(DASHBOARD_REDIS_HOST, DASHBOARD_REDIS_PORT, DASHBOARD_REDIS_PASSWORD): Superset unpickles what "
            "it reads there, so a Redis others can write to is code execution in the dashboard."
        )
    return {
        "CACHE_TYPE": "RedisCache",
        "CACHE_REDIS_HOST": (env.get("DASHBOARD_REDIS_HOST") or "").strip() or "dashboard-redis",
        "CACHE_REDIS_PORT": int((env.get("DASHBOARD_REDIS_PORT") or "").strip() or "6379"),
        "CACHE_REDIS_PASSWORD": password,
        "CACHE_KEY_PREFIX": KEY_PREFIX,
        "CACHE_DEFAULT_TIMEOUT": 300,
    }
