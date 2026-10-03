"""The membership DSN the dashboard reads at sign-in.

The dashboard learns which projects a person is in from core.project_member in
the platform's `platform` database, and reads nothing else there. It does so
over a plain DSN, AISC_MEMBERSHIP_DB_URI, that is never registered as a Superset
connection, so SQL Lab cannot reach `platform`. The results of a project are
read over that project's own connection instead (projects.py).

The DSN comes from the variable the deployment sets rather than from a
connection someone registers by hand: on a machine running several stacks, a
hand-typed address can point at another stack's Postgres and appear to work.
These are the rules that decide what the sign-in may use.
"""
import pytest

from aisc_ext.results_db import MEMBERSHIP_ENV, membership_uri


def test_the_configured_dsn_is_what_gets_used():
    uri = "postgresql+psycopg2://dashboard_ro:x@postgres:5432/platform"
    assert MEMBERSHIP_ENV == "AISC_MEMBERSHIP_DB_URI"
    assert membership_uri({"AISC_MEMBERSHIP_DB_URI": uri}) == uri


def test_nothing_is_used_when_nothing_is_configured():
    # An install that has not said where memberships are gets no project role,
    # rather than a guess that silently points somewhere.
    assert membership_uri({}) is None
    assert membership_uri({"AISC_MEMBERSHIP_DB_URI": "   "}) is None


def test_a_read_write_role_is_refused():
    """The dashboard only reads, so a DSN that could write is refused."""
    with pytest.raises(ValueError, match="read-only"):
        membership_uri({"AISC_MEMBERSHIP_DB_URI": "postgresql+psycopg2://platform_rw:x@postgres:5432/platform"})
