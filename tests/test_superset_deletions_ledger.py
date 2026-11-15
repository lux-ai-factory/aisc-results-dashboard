# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""A dashboard, chart or dataset of a project deleted through Superset itself is queued in the extension's ledger
outbox, in the delete's own transaction, as the overlay's own writes are. No Superset import: the models are
stand-ins mapped on SQLite, with the columns the extension reads."""
from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, create_engine, select
from sqlalchemy.orm import Session, declarative_base

from aisc_ext import ledger

PID = "0f8fad5b-d9cb-469f-a165-70867728950e"
SLUG = "aisc-" + PID.replace("-", "")

Base = declarative_base()


class Dashboard(Base):
    __tablename__ = "dashboards"
    id = Column(Integer, primary_key=True)
    slug = Column(String(255))
    dashboard_title = Column(String(500))


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")


@pytest.fixture
def engine():
    e = create_engine("sqlite://")
    ledger.OUTBOX.metadata.create_all(e)
    Base.metadata.create_all(e)
    return e


@pytest.mark.parametrize("action", ["dashboard.dashboard.deleted", "dashboard.chart.deleted",
                                    "dashboard.dataset.deleted"])
def test_the_extension_knows_the_superset_deletions(action):
    assert action in ledger.ACTIONS, f"{action} is not an action the extension can queue"


def test_deleting_a_projects_dashboard_in_superset_queues_its_deletion(engine):
    watch = getattr(ledger, "watch_superset_deletions", None)
    assert watch is not None, "the extension does not watch Superset's own deletions"
    watch(dashboard=Dashboard)
    with Session(engine) as session:
        session.add(Dashboard(id=4, slug=SLUG + "-aisc-plugin-langbite-langbiteevaluationplugin",
                              dashboard_title="LangBiTe (Mijke)"))
        session.commit()
        session.delete(session.get(Dashboard, 4))
        session.commit()
    with engine.connect() as conn:
        rows = conn.execute(select(ledger.OUTBOX)).all()
    assert [(r.project_pid, r.event["action"], r.event["item_id"]) for r in rows] == [
        (PID, "dashboard.dashboard.deleted", "4")]


class Dataset(Base):
    __tablename__ = "tables"
    id = Column(Integer, primary_key=True)
    table_name = Column(String(250))
    extra = Column(String(1000))


def test_deleting_a_projects_dataset_queues_its_deletion_and_another_dataset_nothing(engine):
    ledger.watch_superset_deletions(dataset=Dataset)
    with Session(engine) as session:
        session.add_all([Dataset(id=10, table_name="engine_results_x", extra='{"aisc_project": "%s"}' % PID),
                         Dataset(id=11, table_name="examples", extra=None)])
        session.commit()
        session.delete(session.get(Dataset, 10))
        session.delete(session.get(Dataset, 11))
        session.commit()
    with engine.connect() as conn:
        rows = conn.execute(select(ledger.OUTBOX)).all()
    assert [(r.project_pid, r.event["action"], r.event["item_id"], r.event["before"]) for r in rows] == [
        (PID, "dashboard.dataset.deleted", "10", {"name": "engine_results_x"})]


def test_after_a_commit_that_queued_a_deletion_the_queue_is_sent(engine):
    sent = []
    ledger.watch_superset_deletions(dashboard=Dashboard, after_commit=lambda: sent.append(1))
    with Session(engine) as session:
        session.add(Dashboard(id=6, slug=SLUG, dashboard_title="Runs compared"))
        session.commit()
        assert sent == []
        session.delete(session.get(Dashboard, 6))
        session.commit()
    assert sent == [1]
