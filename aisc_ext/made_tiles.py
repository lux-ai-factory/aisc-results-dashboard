# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The plugin tiles made so far, by slug, and the default charts removed from them, stored in Superset's metadata
database.

A tile that was made and is no longer there was deleted by someone, so a sync does not make it again
(plugin_tiles.py). Removing a project forgets its tiles (projects._unregister).

Imported only inside Superset (it uses Superset's Model base)."""
from sqlalchemy import Column, DateTime, String, Text, func

from superset import db  # type: ignore

Model = db.Model


class AiscMadeTile(Model):
    __tablename__ = "aisc_made_tile"

    slug = Column(String(255), primary_key=True)
    made_at = Column(DateTime, server_default=func.now())


class AiscRemovedChart(Model):
    """A default chart someone removed from a plugin tile (with the chart assistant): a sync does not put it back."""
    __tablename__ = "aisc_removed_chart"

    slug = Column(String(255), primary_key=True)
    chart_uuid = Column(String(36), primary_key=True)
    removed_at = Column(DateTime, server_default=func.now())


class AiscChangedChart(Model):
    """A default chart someone changed with the chart assistant (scale, kind, title), as JSON: a sync keeps it."""
    __tablename__ = "aisc_changed_chart"

    slug = Column(String(255), primary_key=True)
    chart_uuid = Column(String(36), primary_key=True)
    changes = Column(Text, nullable=False)
    changed_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
