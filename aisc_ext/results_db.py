# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Access to the platform's shared database, limited to project memberships.

Each project's results live in that project's own database and are read over that
project's own Superset connection, which the bridge creates (projects.py). The only
thing the dashboard reads in the shared `platform` database is who is in which
project (core.project_member), at sign-in. It reads that over a plain DSN,
AISC_MEMBERSHIP_DB_URI, as the read-only role, and never registers it as a Superset
connection, so SQL Lab cannot reach `platform`.

The DSN comes from an env var the deployment sets, not from a connection someone
registers by hand: on a machine running several stacks, a hand-typed address can
point at another stack's Postgres and appear to work.
"""
from __future__ import annotations

import os

#: The Postgres role the dashboard must connect as. Every other role can write,
#: and the dashboard has no reason to.
READ_ONLY_ROLE = "dashboard_ro"

#: The DSN memberships are read over at sign-in (dashboard_ro on `platform`).
MEMBERSHIP_ENV = "AISC_MEMBERSHIP_DB_URI"


def membership_uri(env=None) -> str | None:
    """The DSN to read memberships over, or None when AISC_MEMBERSHIP_DB_URI is unset.

    Raises ValueError unless the DSN connects as the read-only role."""
    uri = ((env if env is not None else os.environ).get(MEMBERSHIP_ENV) or "").strip()
    if not uri:
        return None
    if f"//{READ_ONLY_ROLE}:" not in uri and f"//{READ_ONLY_ROLE}@" not in uri:
        raise ValueError(
            f"{MEMBERSHIP_ENV} must connect as the read-only role {READ_ONLY_ROLE!r}: "
            "the dashboard reads the platform's memberships and writes none of it."
        )
    return uri

