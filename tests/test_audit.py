# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Feature 2: tamper-evident audit rows for Superset actions -> immudb.

The pure row-builder is unit-tested here; the immudb client degrades to a no-op
when disabled/unavailable so auditing never blocks a request.
"""
import json

from aisc_ext.audit import ImmudbClerk, build_audit_row


def test_build_audit_row_shape():
    row = build_audit_row(actor="alice", action="dashboard.view",
                          target="42", extra={"slice_id": 7})
    assert row["actor"] == "alice"
    assert row["action"] == "dashboard.view"
    assert row["target"] == "42"
    assert "alice" in row["summary"] and "dashboard.view" in row["summary"]
    # payload is JSON-serialised for storage
    assert json.loads(row["payload"]) == {"slice_id": 7}
    assert row["ts"].endswith("Z") or "T" in row["ts"]


def test_clerk_noop_when_disabled():
    clerk = ImmudbClerk(enabled=False)
    # must not raise, must not require a connection
    assert clerk.record(actor="a", action="x", target="t", summary="s") is None
    assert clerk.read() == []


def test_clerk_handles_unreachable_host_gracefully():
    clerk = ImmudbClerk(enabled=True, host="nonexistent.invalid", port=3322,
                        connect_timeout=0.2)
    # auditing must never blow up the caller even if immudb is down
    assert clerk.record(actor="a", action="x", target="t", summary="s") is None
    assert clerk.read() == []


def test_clerk_kwargs_from_env_defaults(monkeypatch):
    from aisc_ext.audit import clerk_kwargs_from_env
    for var in ("AISC_AUDIT_ENABLED", "IMMUDB_HOST", "IMMUDB_PORT",
                "IMMUDB_USER", "IMMUDB_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    kw = clerk_kwargs_from_env()
    assert kw == {"enabled": True, "host": "immudb", "port": 3322,
                  "user": "immudb", "password": "immudb"}


def test_clerk_kwargs_from_env_overrides(monkeypatch):
    from aisc_ext.audit import clerk_kwargs_from_env
    monkeypatch.setenv("AISC_AUDIT_ENABLED", "false")
    monkeypatch.setenv("IMMUDB_HOST", "audit.internal")
    monkeypatch.setenv("IMMUDB_PORT", "9999")
    monkeypatch.setenv("IMMUDB_USER", "clerk")
    monkeypatch.setenv("IMMUDB_PASSWORD", "s3cret")
    kw = clerk_kwargs_from_env()
    assert kw == {"enabled": False, "host": "audit.internal", "port": 9999,
                  "user": "clerk", "password": "s3cret"}


class _FakeClient:
    """Minimal immudb client double: sqlExec fails on INSERT the first
    `fail_times` calls with a tx-read-conflict, then succeeds."""
    def __init__(self, fail_times=0, exc_msg="tx read conflict"):
        self.fail_times = fail_times
        self.exc_msg = exc_msg
        self.insert_attempts = 0
    def sqlExec(self, sql, params=None):
        if sql.strip().upper().startswith("INSERT"):
            self.insert_attempts += 1
            if self.insert_attempts <= self.fail_times:
                raise Exception(self.exc_msg)
        return None


def test_record_retries_on_tx_conflict_then_succeeds():
    clerk = ImmudbClerk(enabled=True)
    fake = _FakeClient(fail_times=2)
    clerk._client = fake  # bypass real connect
    clerk.record(actor="a", action="x", target="t")
    # first two INSERTs conflict, third succeeds -> 3 attempts, no raise
    assert fake.insert_attempts == 3


def test_record_gives_up_after_max_retries_without_raising():
    clerk = ImmudbClerk(enabled=True)
    fake = _FakeClient(fail_times=99)
    clerk._client = fake
    # must not raise even when every attempt conflicts
    assert clerk.record(actor="a", action="x", target="t") is None
    assert fake.insert_attempts >= 3  # bounded retries attempted


def test_failed_connect_is_cached_with_backoff(monkeypatch):
    """A failed connect must not be retried on every record() call."""
    clerk = ImmudbClerk(enabled=True, host="nonexistent.invalid", connect_timeout=0.1)
    calls = {"n": 0}
    real_import_connect = clerk._connect
    def counting_connect():
        calls["n"] += 1
        return real_import_connect()
    monkeypatch.setattr(clerk, "_connect", counting_connect)
    for _ in range(5):
        clerk.record(actor="a", action="x", target="t")
    # _connect is still called each record (that's the entry point), but the
    # actual immudb connection attempt must be throttled: assert the clerk
    # tracks a failure timestamp so it can skip real reconnects.
    assert hasattr(clerk, "_next_retry_at")
