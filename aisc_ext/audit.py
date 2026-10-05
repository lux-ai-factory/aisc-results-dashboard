# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Audit log of Superset actions in immudb (table superset_audit).

`ImmudbClerk` wraps the immudb SQL client and does nothing when auditing is
disabled or immudb is unreachable, so auditing never blocks or breaks a Superset
request. The EVENT_LOGGER that feeds it is aisc_ext.event_logger."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

_log = logging.getLogger(__name__)
_TABLE = "superset_audit"
_MAX_WRITE_RETRIES = 3       # immudb aborts concurrent transactions ("tx read conflict")
_RETRY_BACKOFF_S = 0.05
_CONNECT_RETRY_COOLDOWN_S = 30.0  # wait this long after a failed connect before trying again


def clerk_kwargs_from_env() -> dict:
    """ImmudbClerk keyword arguments from the environment (defaults suit a local stack; the
    password has none: immudb's own default is not one to run on)."""
    return {
        "enabled": os.environ.get("AISC_AUDIT_ENABLED", "true").lower() == "true",
        "host": os.environ.get("IMMUDB_HOST", "immudb"),
        "port": int(os.environ.get("IMMUDB_PORT", "3322")),
        "user": os.environ.get("IMMUDB_USER", "immudb"),
        "password": os.environ.get("IMMUDB_PASSWORD", ""),
    }


def build_audit_row(*, actor: str, action: str, target: str,
                    extra: dict | None = None) -> dict:
    extra = extra or {}
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "target": str(target),
        "summary": f"{actor} performed {action} on {target or 'n/a'}",
        "payload": json.dumps(extra, default=str),
    }


class ImmudbClerk:
    def __init__(self, enabled: bool = True, host: str = "immudb", port: int = 3322,
                 user: str = "immudb", password: str = "",
                 connect_timeout: float = 2.0):
        self.enabled = enabled
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.connect_timeout = connect_timeout
        self._client = None
        self._next_retry_at = 0.0  # time.monotonic() after which a failed connect may be retried

    def _connect(self):
        if not self.enabled:
            return None
        if self._client is not None:
            return self._client
        # A connect failed recently: skip the slow attempt, so an immudb that is
        # down does not add seconds to every logged request.
        if time.monotonic() < self._next_retry_at:
            return None
        if not self.password:
            # immudb's own default is no password to run on: say so, and wait like a failed connect
            _log.warning("audit: IMMUDB_PASSWORD is not set; no audit row is written")
            self._next_retry_at = time.monotonic() + _CONNECT_RETRY_COOLDOWN_S
            return None
        try:
            from immudb import ImmudbClient

            client = ImmudbClient(f"{self.host}:{self.port}",
                                  timeout=self.connect_timeout)
            client.login(self.user, self.password)
            client.sqlExec(
                f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
                    id INTEGER AUTO_INCREMENT, ts VARCHAR, actor VARCHAR,
                    action VARCHAR, target VARCHAR, summary VARCHAR,
                    payload VARCHAR, PRIMARY KEY id);"""
            )
            self._client = client
        except Exception as exc:  # never let auditing break the request path
            _log.warning("audit: immudb unavailable, no audit row is written: %s", exc)
            self._client = None
            self._next_retry_at = time.monotonic() + _CONNECT_RETRY_COOLDOWN_S
        return self._client

    def record(self, *, actor: str, action: str, target: str,
               summary: str | None = None, extra: dict | None = None) -> None:
        client = self._connect()
        if client is None:
            return None
        row = build_audit_row(actor=actor, action=action, target=target, extra=extra)
        stmt = (f"INSERT INTO {_TABLE} (ts, actor, action, target, summary, payload) "
                "VALUES (@ts,@actor,@action,@target,@summary,@payload);")
        # immudb serialises SQL transactions: concurrent workers writing audit
        # rows abort with "tx read conflict". Retry a few times so ordinary
        # concurrent load does not drop audit records.
        for attempt in range(_MAX_WRITE_RETRIES):
            try:
                client.sqlExec(stmt, params=row)
                return None
            except Exception as exc:
                if attempt + 1 >= _MAX_WRITE_RETRIES:
                    print(f"[aisc-audit] write failed after {_MAX_WRITE_RETRIES} "
                          f"attempts: {exc}")
                else:
                    time.sleep(_RETRY_BACKOFF_S * (attempt + 1))
        return None

    def read(self, limit: int = 100) -> list[dict]:
        client = self._connect()
        if client is None:
            return []
        try:
            rows = client.sqlQuery(
                f"SELECT id,ts,actor,action,target,summary,payload FROM {_TABLE} "
                f"ORDER BY id DESC LIMIT {int(limit)};"
            )
            cols = ["id", "ts", "actor", "action", "target", "summary", "payload"]
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            return []
