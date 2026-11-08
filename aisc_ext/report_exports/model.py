# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""A plot saved for the report: a vector file and its filters as text, in Superset's metadata database. Rows are only
added: the newest per dashboard, chart and filters is what a report shows. Imported only inside Superset."""
from sqlalchemy import JSON, Column, DateTime, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from superset import db  # type: ignore

Model = db.Model


class AiscReportPlot(Model):
    __tablename__ = "aisc_report_plot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dashboard_id = Column(Integer, index=True, nullable=False)
    chart = Column(String(255), nullable=False)
    tab = Column(String(255), nullable=False, default="")
    tags = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list)
    svg = Column(LargeBinary, nullable=False)
    sha256 = Column(String(64), nullable=False)
    comment = Column(Text, nullable=False, default="")
    #: the rows the chart's query gave when the plot was saved (None: saved by a page that did not send them)
    rows = Column(Integer, nullable=True)
    #: the id of the Save to report click that saved it (one click saves several plots; the report shows each
    #: dashboard's latest); None for plots saved before clicks had one
    save_id = Column(String(64), nullable=True)
    author_sub = Column(String(255), nullable=False)
    author_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
