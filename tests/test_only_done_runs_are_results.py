# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Only the measures of runs that finished Done are results: a run that failed after one of its tests posted
measures (the target went away mid-run, a person pressed Stop) shows none of them in the engine results dataset.

Same throwaway Postgres as test_project_datasets_db.py (AISC_DASHBOARD_TEST_PG_CONTAINER), in a project
database of its own, so it runs before, after or without that module's seed."""
import uuid

import pytest

from tests.test_project_datasets_db import (CONTAINER, _run_sql, _seed_platform, _seed_project, psql)

pytestmark = pytest.mark.skipif(
    not CONTAINER, reason="AISC_DASHBOARD_TEST_PG_CONTAINER not set (throwaway Postgres)")

PROJECT = "6d0e1f2a-3b4c-4d5e-8f6a-7b8c9d0e1f2a"
VERSION = "66666666-6666-4666-8666-666666666666"
E_DONE, M_DONE = "eeeeeeee-0000-4000-8000-0000000000d1", "dddddddd-0000-4000-8000-0000000000d1"
E_FAILED, M_FAILED = "eeeeeeee-0000-4000-8000-0000000000f1", "dddddddd-0000-4000-8000-0000000000f1"


def _failed_run_sql(evaluation, plugin, measurement, score):
    """A run as _run_sql makes it, but whose evaluation ended Failed."""
    return _run_sql(evaluation, plugin, [], measurement, score, system=VERSION).replace(
        f"SELECT '{evaluation}', 'Done',", f"SELECT '{evaluation}', 'Failed',")


@pytest.fixture(scope="module")
def project_db():
    try:
        _seed_platform()
    except AssertionError:
        pass                                    # the other module's seed got there first
    db = f"project_{uuid.UUID(PROJECT).hex}"
    _seed_project(db, [(VERSION, 1)], VERSION)
    psql("SET ROLE engine_rw;\nSET search_path = engine;\n"
         + _run_sql(E_DONE, "done-one", [], M_DONE, 0.4, system=VERSION)
         + _failed_run_sql(E_FAILED, "failed-one", M_FAILED, 0.5), db=db)
    return db


def _measures_of(db, projects, evaluation):
    out = psql(f"SELECT count(*) FROM ({projects.engine_results_sql()}) t WHERE evaluation_pid = '{evaluation}';",
               db=db, user="dashboard_ro")
    return int(out.stdout.split()[-1])


def test_the_seed_made_a_failed_run_with_a_measure(project_db):
    out = psql(f"SELECT e.status FROM engine.aisc_backend_evaluation e WHERE e.pid = '{E_FAILED}';", db=project_db)
    assert out.stdout.strip() == "Failed"


def test_a_done_runs_measures_are_results(project_db, projects):
    assert _measures_of(project_db, projects, E_DONE) == 1


def test_engine_results_show_only_done_runs(project_db, projects):
    """A run that failed after one of its tests posted measures shows none of them."""
    assert _measures_of(project_db, projects, E_FAILED) == 0
