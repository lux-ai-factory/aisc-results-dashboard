# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Superset EVENT_LOGGER that mirrors actions into the immudb audit ledger.
Runtime-only (imports Superset's AbstractEventLogger)."""
from superset.utils.log import AbstractEventLogger  # type: ignore

from aisc_ext.audit import ImmudbClerk, clerk_kwargs_from_env

_clerk = ImmudbClerk(**clerk_kwargs_from_env())


class ImmudbEventLogger(AbstractEventLogger):
    def log(self, user_id, action, dashboard_id=None, duration_ms=None,
            slice_id=None, referrer=None, **kwargs):
        actor = str(user_id) if user_id is not None else "anonymous"
        target = str(dashboard_id or slice_id or "")
        _clerk.record(actor=actor, action=action, target=target,
                      extra={"slice_id": slice_id, "duration_ms": duration_ms})
