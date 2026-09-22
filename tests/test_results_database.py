"""The results database the dashboard reads.

It reads the platform's one database as a read-only role, or it is reading
something else. That is not hypothetical: on a machine running several stacks,
a connection registered by hand once pointed at another stack's Postgres, and
worked, so nothing ever complained.

So the connection is not registered by hand any more. It comes from
AISC_RESULTS_DB_URI, the variable the deployment already sets, and these are the
rules that decide what gets registered.
"""
import pytest

from aisc_ext.results_db import RESULTS_DB_NAME, registration_for


def test_the_configured_database_is_what_gets_registered():
    found = registration_for({"AISC_RESULTS_DB_URI": "postgresql+psycopg2://dashboard_ro:x@postgres:5432/platform"})
    assert found == {
        "database_name": RESULTS_DB_NAME,
        "sqlalchemy_uri": "postgresql+psycopg2://dashboard_ro:x@postgres:5432/platform",
    }


def test_nothing_is_registered_when_nothing_is_configured():
    # An install that has not said where its results are gets no connection,
    # rather than a guess that silently points somewhere.
    assert registration_for({}) is None
    assert registration_for({"AISC_RESULTS_DB_URI": "   "}) is None


def test_a_read_write_role_is_refused():
    """The dashboard reads. A connection that could write is a mistake worth
    failing on rather than carrying into production."""
    with pytest.raises(ValueError, match="read-only"):
        registration_for({"AISC_RESULTS_DB_URI": "postgresql+psycopg2://platform_rw:x@postgres:5432/platform"})


def test_the_name_is_stable_so_re_registering_replaces_rather_than_adds():
    first = registration_for({"AISC_RESULTS_DB_URI": "postgresql+psycopg2://dashboard_ro:x@postgres:5432/platform"})
    second = registration_for({"AISC_RESULTS_DB_URI": "postgresql+psycopg2://dashboard_ro:y@postgres:5432/platform"})
    assert first["database_name"] == second["database_name"]
