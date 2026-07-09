# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""immudb-backed audit ledger for Superset actions.

`build_audit_row` is a pure helper (unit-tested). `ImmudbClerk` wraps the
immudb SQL client and degrades to a no-op if disabled or unreachable, so
auditing never blocks or breaks a Superset request. The FAB EVENT_LOGGER that
feeds this lives in aisc_ext.event_logger (runtime-only)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

_TABLE = "superset_audit"
_MAX_WRITE_RETRIES = 3       # immudb MVCC aborts concurrent txns ("tx read conflict")
_RETRY_BACKOFF_S = 0.05      # brief backoff between INSERT retries
_CONNECT_RETRY_COOLDOWN_S = 30.0  # after a failed connect, don't hammer immudb


def clerk_kwargs_from_env() -> dict:
    """ImmudbClerk constructor kwargs from the environment (dev defaults)."""
    return {
        "enabled": os.environ.get("AISC_AUDIT_ENABLED", "true").lower() == "true",
        "host": os.environ.get("IMMUDB_HOST", "immudb"),
        "port": int(os.environ.get("IMMUDB_PORT", "3322")),
        "user": os.environ.get("IMMUDB_USER", "immudb"),
        "password": os.environ.get("IMMUDB_PASSWORD", "immudb"),
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
                 user: str = "immudb", password: str = "immudb",
                 connect_timeout: float = 2.0):
        self.enabled = enabled
        self.host, self.port = host, port
        self.user, self.password = user, password
        self.connect_timeout = connect_timeout
        self._client = None
        self._next_retry_at = 0.0  # epoch after which a failed connect may retry

    def _connect(self):
        if not self.enabled:
            return None
        if self._client is not None:
            return self._client
        # A prior connect failed recently: skip the (slow) attempt so a down
        # immudb doesn't add multi-second latency to every logged request.
        if time.monotonic() < self._next_retry_at:
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
            print(f"[aisc-audit] immudb unavailable, auditing disabled: {exc}")
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
        # immudb serialises SQL txns with MVCC: concurrent workers writing audit
        # rows abort with "tx read conflict". Retry a few times so ordinary
        # concurrent load doesn't silently drop tamper-evidence records.
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
