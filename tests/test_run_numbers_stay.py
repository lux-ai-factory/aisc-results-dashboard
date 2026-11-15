# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""A run keeps its number: runs are numbered over all of the project's evaluations, and only then are the runs
that did not finish Done hidden. So with runs 1 Done, 2 Failed (with measures) and 3 Done the dashboard shows
Run 1 and Run 3, and a Failed run never moves the number of another run (titles, saved filters and reports cite
these numbers).

Same throwaway Postgres as test_project_datasets_db.py (AISC_DASHBOARD_TEST_PG_CONTAINER), in a project
database of its own, so it runs before, after or without that module's seed."""
import uuid

import pytest

from tests.test_project_datasets_db import CONTAINER, _run_sql, _seed_platform, _seed_project, psql

pytestmark = pytest.mark.skipif(
    not CONTAINER, reason="AISC_DASHBOARD_TEST_PG_CONTAINER not set (throwaway Postgres)")

PROJECT = "7e1f2a3b-4c5d-4e6f-8a7b-8c9d0e1f2a3b"
VERSION = "77777777-7777-4777-8777-777777777777"
E_FAILED, M_FAILED = "eeeeeeee-0000-4000-8000-0000000000f2", "dddddddd-0000-4000-8000-0000000000f2"
E_THIRD, M_THIRD = "eeeeeeee-0000-4000-8000-0000000000d3", "dddddddd-0000-4000-8000-0000000000d3"
E_LATER_FAILED, M_LATER_FAILED = "eeeeeeee-0000-4000-8000-0000000000f4", "dddddddd-0000-4000-8000-0000000000f4"


def _run_ending(evaluation, plugin, measurement, status, created_at):
    """A run as _run_sql makes it, ending with `status` and made at `created_at`."""
    return _run_sql(evaluation, plugin, [], measurement, 0.5, system=VERSION).replace(
        f"SELECT '{evaluation}', 'Done',", f"SELECT '{evaluation}', '{status}',") + (
        f"UPDATE aisc_backend_evaluation SET created_at = '{created_at}' WHERE pid = '{evaluation}';\n")


@pytest.fixture(scope="module")
def project_db():
    """Run 1 is the seed's own Done evaluation (made now, so it moves to 2001 to come first), run 2 Failed
    after one of its tests posted a measure, run 3 Done."""
    try:
        _seed_platform()
    except AssertionError:
        pass                                    # another module's seed got there first
    db = f"project_{uuid.UUID(PROJECT).hex}"
    psql(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE);')    # a reused throwaway may hold a former run's
    _seed_project(db, [(VERSION, 1)], VERSION)
    psql("SET ROLE engine_rw;\nSET search_path = engine;\n"
         "UPDATE aisc_backend_evaluation SET created_at = '2001-10-04 10:00+00';\n"
         + _run_ending(E_FAILED, "failed-two", M_FAILED, "Failed", "2001-10-04 11:00+00")
         + _run_ending(E_THIRD, "done-three", M_THIRD, "Done", "2001-10-04 12:00+00"), db=db)
    return db


def _shown_runs(db, projects):
    """(run_order, the run's 'Run N' prefix) of each run the engine results dataset shows, in order."""
    out = psql(f"SELECT DISTINCT run_order, split_part(run, ' · ', 1) FROM ({projects.engine_results_sql()}) t "
               "ORDER BY 1;", db=db, user="dashboard_ro")
    return [(int(order), run) for order, run in (line.split("|") for line in out.stdout.splitlines())]


def test_a_failed_run_between_two_done_runs_leaves_their_numbers(project_db, projects):
    assert _shown_runs(project_db, projects) == [(1, "Run 1"), (3, "Run 3")]


def test_a_later_failed_run_changes_no_shown_number(project_db, projects):
    before = _shown_runs(project_db, projects)
    psql("SET ROLE engine_rw;\nSET search_path = engine;\n"
         + _run_ending(E_LATER_FAILED, "failed-four", M_LATER_FAILED, "Failed", "2001-10-04 13:00+00"),
         db=project_db)
    assert _shown_runs(project_db, projects) == before


def test_a_run_ending_failed_keeps_the_numbers_it_had_while_running(project_db, projects):
    """Run 2 was still Running when run 3 finished: run 3 was Run 3 then and stays Run 3 when run 2 fails."""
    def shown_while(status):
        psql(f"SET ROLE engine_rw;\nUPDATE engine.aisc_backend_evaluation SET status = '{status}' "
             f"WHERE pid = '{E_FAILED}';", db=project_db)
        return _shown_runs(project_db, projects)

    running, failed = shown_while("Running"), shown_while("Failed")
    assert running == failed == [(1, "Run 1"), (3, "Run 3")]
