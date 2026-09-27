# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Isolation 2026-09-25 (01-specs.md I10.1, I10.3, I19.3): the engine dataset, run for real as
dashboard_ro inside a project database.

Same THROWAWAY container convention as test_project_datasets_db.py
(AISC_DASHBOARD_TEST_PG_CONTAINER=aisc-t-...; skipped when unset). The project database R is
made with every platform template file (0006_project_system.sql and 0009_engine.sql come from
WP P1; until they exist the tests FAIL naming the missing file). The engine tables are the
reduced frozen-engine DDL of test_project_datasets_db.py, created as engine_rw in R's `engine`
schema; the SELECT grant to dashboard_ro stands in for the engine's migrate_projects grants
(I7.6), whose exact matrix is tested by scripts/tests/test_project_grants.py (I2.6, I16.1).
"""
import os
import pathlib

import pytest

from tests.test_project_datasets_db import CONTAINER, ENGINE_DDL, ROOT, psql

R = "5d0c1a2b-3e4f-4a5b-8c6d-7e8f9a0b1c2d"
R_HEX = R.replace("-", "")
DB = f"project_{R_HEX}"
RV1 = "44444444-4444-4444-8444-444444444444"
# A second project database S, for the cross-project case (I16.5 on the dashboard).
S = "6e1d2b3c-4f5a-4b6c-9d7e-8f9a0b1c2d3e"
S_DB = f"project_{S.replace('-', '')}"
SV1 = "55555555-5555-4555-8555-555555555555"
# ISOLATION_TEMPLATE_DIR lets 02-tests.md's dry check point this at a scratch copy with
# stand-in 0006/0009, to prove the test bodies before WP P1 exists. Unset in every real run.
TEMPLATES = pathlib.Path(os.environ.get("ISOLATION_TEMPLATE_DIR") or ROOT / "platform" / "project-template")

pytestmark = pytest.mark.skipif(
    not CONTAINER, reason="AISC_DASHBOARD_TEST_PG_CONTAINER not set (throwaway Postgres)")


class Made:
    def __init__(self):
        self.missing = []

    def need(self):
        if self.missing:
            pytest.fail("I2.1 template missing: " + ", ".join(self.missing))


@pytest.fixture(scope="module")
def made():
    m = Made()
    for f in ("0006_project_system.sql", "0009_engine.sql"):
        if not (TEMPLATES / f).exists():
            m.missing.append(f)
    if m.missing:
        yield m
        return
    # The init files are not re-runnable over an initialised cluster (test_project_datasets_db
    # may have applied them already in this container), so only a bare container gets them.
    if psql("SELECT to_regnamespace('core') IS NULL;").stdout.strip() == "t":
        for f in ("init/platform-db.sql", "init/project-databases.sql"):
            psql((ROOT / f).read_text())
    for pid, db, version, score in ((R, DB, RV1, "0.8"), (S, S_DB, SV1, "0.3")):
        _make_project_database(pid, db, version, score)
    yield m
    for db in (DB, S_DB):
        psql(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE);')


def _make_project_database(pid, db, version, score):
    """One project database made with every template file, the reduced engine tables, one
    card version and one finished evaluation with one measurement, all of that project."""
    psql(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE);')
    psql(f'CREATE DATABASE "{db}" OWNER platform_rw;')
    for f in sorted(TEMPLATES.glob("*.sql")):
        psql("SET ROLE platform_rw;\n" + f.read_text(), db=db)
    psql(ENGINE_DDL + "\nSET ROLE engine_rw; GRANT SELECT ON ALL TABLES IN SCHEMA engine TO dashboard_ro; RESET ROLE;",
         db=db)
    psql(f"""
SET ROLE platform_rw;
INSERT INTO project.system (pid, number, name, version) VALUES ('{version}', 1, 'X', '1.0');
RESET ROLE;
SET ROLE engine_rw;
SET search_path = engine;
INSERT INTO project (pid, name, description, project_id) VALUES (gen_random_uuid(), 'X', '', '{pid}');
INSERT INTO metric (pid, name) VALUES (gen_random_uuid(), 'accuracy');
INSERT INTO evaluation (pid, status, project_id, system_id) SELECT gen_random_uuid(), 'Finished', id, '{version}' FROM project;
INSERT INTO observation (pid, evaluation_id) SELECT gen_random_uuid(), id FROM evaluation;
INSERT INTO measurement (pid, time, score, unit, metric_id, observation_id)
  SELECT gen_random_uuid(), now(), {score}, 'ratio', (SELECT id FROM metric), id FROM observation;
""", db=db)


def _engine_sql():
    from aisc_ext import projects

    try:
        return projects.engine_results_sql()
    except TypeError:
        return projects.engine_results_sql(R)


def _rows(out):
    return [line.split("|") for line in out.stdout.splitlines() if line]


def test_i10_3_dashboard_ro_reads_project_system_and_never_writes_it(made):
    made.need()
    out = psql("SELECT has_table_privilege('project.system', 'SELECT'), "
               "has_table_privilege('project.system', 'INSERT'), has_schema_privilege('llm', 'USAGE');",
               db=DB, user="dashboard_ro", check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "t|f|f"


def test_i10_1_i19_3_the_engine_dataset_runs_as_dashboard_ro_in_the_project_database(made):
    """The dataset SQL, on the project's own connection, returns that database's rows with
    the card version from project.system."""
    made.need()
    out = psql(f"SELECT system_version, system_version_pid FROM ({_engine_sql()}) t;",
               db=DB, user="dashboard_ro", check=False)
    assert out.returncode == 0, out.stderr[-400:]
    assert {tuple(r) for r in _rows(out)} == {("1", RV1)}


def test_i16_5_the_engine_dataset_of_one_project_database_never_shows_another_projects_rows(made):
    """Two project databases R and S: the same SQL (no pid filter) on R's connection returns
    only R's version, on S's only S's, because the database is the project."""
    made.need()
    for db, version in ((DB, RV1), (S_DB, SV1)):
        out = psql(f"SELECT system_version_pid FROM ({_engine_sql()}) t;", db=db, user="dashboard_ro", check=False)
        assert out.returncode == 0, out.stderr[-400:]
        assert {r[0] for r in _rows(out)} == {version}, db


def test_i10_3_dashboard_ro_cannot_write_the_engine_tables_of_a_project_database(made):
    made.need()
    out = psql("SELECT has_table_privilege('engine.evaluation', 'INSERT'), "
               "has_table_privilege('engine.evaluation', 'UPDATE'), has_table_privilege('engine.evaluation', 'SELECT');",
               db=DB, user="dashboard_ro", check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "f|f|t"
