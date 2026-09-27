"""The membership DSN the dashboard reads at sign-in (isolation I10.2).

The dashboard learns which projects a person is in from core.project_member in
the platform's `platform` database, and reads nothing else there. It does so
over a plain DSN, AISC_MEMBERSHIP_DB_URI, that is never registered as a Superset
connection, so SQL Lab cannot reach `platform`. The results of a project are
read over that project's own connection instead (projects.py).

The DSN comes from the variable the deployment sets rather than from a
connection someone registers by hand: on a machine running several stacks, a
hand-typed address can point at another stack's Postgres and appear to work.
These are the rules that decide what the sign-in may use.

Changed by the isolation (S-D13): these tests pinned AISC_RESULTS_DB_URI and the
registration of the "AISC Results" connection; they now pin membership_uri and
AISC_MEMBERSHIP_DB_URI with the same intent. The old fourth test (the connection
name is stable so re-registering replaces it) is gone with the registration; its
counterpart is test_isolation_dashboard.py::test_i10_2_results_db_registers_nothing_named_aisc_results.
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
    """The dashboard reads. A DSN that could write is a mistake worth failing on
    rather than carrying into production."""
    with pytest.raises(ValueError, match="read-only"):
        membership_uri({"AISC_MEMBERSHIP_DB_URI": "postgresql+psycopg2://platform_rw:x@postgres:5432/platform"})
