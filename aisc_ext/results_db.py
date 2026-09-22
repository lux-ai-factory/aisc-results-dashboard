"""The results database this dashboard reads.

One database for the whole platform, read by a role that can read everything in
it and write nothing. Which database that is comes from AISC_RESULTS_DB_URI, the
variable the deployment already sets, rather than from a connection someone
registers by hand in the UI: on a machine running several stacks, a hand-typed
address can point at another stack's Postgres and work, which is exactly what
had happened here.

`registration_for` is the decision, kept apart from Superset so it can be read
and tested on its own; `register_results_database` applies it through Superset's
own model, replacing the connection of the same name rather than adding a
second.
"""
from __future__ import annotations

import os

#: One name, so re-registering replaces rather than accumulates.
RESULTS_DB_NAME = "AISC Results"

#: The role the dashboard connects as. Anything else can write, and a dashboard
#: that can write is a dashboard that can be made to.
READ_ONLY_ROLE = "dashboard_ro"


def registration_for(env: dict | None = None) -> dict | None:
    """What to register, or None when this install has not said where its
    results are."""
    uri = ((env if env is not None else os.environ).get("AISC_RESULTS_DB_URI") or "").strip()
    if not uri:
        return None
    if f"//{READ_ONLY_ROLE}:" not in uri and f"//{READ_ONLY_ROLE}@" not in uri:
        raise ValueError(
            f"AISC_RESULTS_DB_URI must connect as the read-only role {READ_ONLY_ROLE!r}: "
            "the dashboard reads the platform's data and writes none of it."
        )
    return {"database_name": RESULTS_DB_NAME, "sqlalchemy_uri": uri}


def register_results_database(app) -> None:
    """Put that connection in Superset, once, at start.

    Never fatal: a dashboard that cannot register its results database is still
    a dashboard someone can log into and fix.
    """
    try:
        wanted = registration_for()
    except ValueError as exc:
        app.logger.error("AISC results database not registered: %s", exc)
        return
    if wanted is None:
        app.logger.info("AISC_RESULTS_DB_URI is not set: no results database registered.")
        return

    try:
        from superset import db
        from superset.models.core import Database

        existing = (
            db.session.query(Database)
            .filter_by(database_name=wanted["database_name"])
            .one_or_none()
        )
        if existing is None:
            existing = Database(database_name=wanted["database_name"])
            db.session.add(existing)
        existing.sqlalchemy_uri = wanted["sqlalchemy_uri"]
        existing.expose_in_sqllab = True
        existing.allow_ctas = False
        existing.allow_cvas = False
        existing.allow_dml = False
        db.session.commit()
        app.logger.info("AISC results database registered: %s", wanted["database_name"])
    except Exception as exc:  # pragma: no cover - defensive; never block startup
        app.logger.warning("Could not register the AISC results database: %s", exc)
