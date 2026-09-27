"""What the dashboard reads in the platform's shared database, and nothing more.

Each project's results live in that project's own database (isolation, 01-specs.md
section 10), read over that project's own Superset connection, which the bridge
makes (projects.py). The only thing the dashboard still reads in the shared
`platform` database is who is in which project (core.project_member), at sign-in.
It reads that over a plain DSN, AISC_MEMBERSHIP_DB_URI, as the read-only role, and
never registers it as a Superset connection, so SQL Lab cannot reach `platform`.

The DSN comes from the variable the deployment sets rather than from a connection
someone registers by hand: on a machine running several stacks, a hand-typed
address can point at another stack's Postgres and appear to work.

`remove_results_connection` deletes the connection the dashboard used to register
for the shared database ("AISC Results"); the cutover runs it once every dataset
has moved to its project's connection.
"""
from __future__ import annotations

import os

#: The retired connection onto the shared `platform` database. Nothing registers
#: it any more; the cutover deletes it (remove_results_connection) once no dataset
#: sits on it.
RESULTS_DB_NAME = "AISC Results"

#: The role the dashboard connects as. Anything else can write, and a dashboard
#: that can write is a dashboard that can be made to.
READ_ONLY_ROLE = "dashboard_ro"

#: The DSN memberships are read over at sign-in (dashboard_ro on `platform`).
MEMBERSHIP_ENV = "AISC_MEMBERSHIP_DB_URI"

#: Superset's table of connections, and its table of datasets with the column
#: that names a dataset's connection.
_DBS = "dbs"
_DATASETS = ("tables", "database_id")


def membership_uri(env=None) -> str | None:
    """The DSN to read memberships over, or None when this install has not said
    where they are. ValueError unless it connects as the read-only role."""
    uri = ((env if env is not None else os.environ).get(MEMBERSHIP_ENV) or "").strip()
    if not uri:
        return None
    if f"//{READ_ONLY_ROLE}:" not in uri and f"//{READ_ONLY_ROLE}@" not in uri:
        raise ValueError(
            f"{MEMBERSHIP_ENV} must connect as the read-only role {READ_ONLY_ROLE!r}: "
            "the dashboard reads the platform's memberships and writes none of it."
        )
    return uri


def remove_results_connection(*, store=None) -> int:
    """Delete the retired "AISC Results" connection from Superset's metadata.

    Refuses (RuntimeError) while any dataset still sits on it. Otherwise deletes the
    rows of every table with a foreign key to `dbs` that name it (a table that
    references another of those tables first), then its `dbs` row, and returns how
    many rows went. 0 when it is already gone. At runtime (no store) it runs on
    Superset's own metadata database, in one transaction.
    """
    if store is not None:
        return _remove(store)
    from superset import db  # type: ignore

    with db.engine.begin() as connection:
        return _remove(_SqlMetadata(connection))


def _remove(store) -> int:
    db_id = store.database_id(RESULTS_DB_NAME)
    if db_id is None:
        return 0
    on_it = store.count(*_DATASETS, db_id)
    if on_it:
        raise RuntimeError(
            f"{RESULTS_DB_NAME!r} still has {on_it} dataset(s) on it: re-register every "
            "project first, so each dataset moves to its project's connection.")
    fks = store.foreign_keys()
    referencing = {}
    for table, cols, ref, ref_cols in fks:
        if ref == _DBS and tuple(ref_cols) == ("id",) and len(cols) == 1:
            referencing.setdefault(table, []).append(cols[0])
    removed = 0
    for table in _delete_order(referencing, fks):
        for column in referencing[table]:
            removed += store.delete(table, column, db_id)
    return removed + store.delete(_DBS, "id", db_id)


def _delete_order(tables, fks) -> list[str]:
    """The tables in an order where one that references another of them comes first."""
    refers = {t: {ref for src, _c, ref, _r in fks if src == t and ref in tables and ref != t} for t in tables}
    order, left = [], set(tables)
    while left:
        # a table nobody left refers to may go now
        ready = sorted(t for t in left if not any(t in refers[o] for o in left if o != t))
        if not ready:
            raise RuntimeError(f"cannot order the delete: foreign keys form a cycle among {sorted(left)}")
        order.extend(ready)
        left -= set(ready)
    return order


class _SqlMetadata:
    """The four calls `_remove` makes, on Superset's metadata database. Runtime only
    (it needs SQLAlchemy); the logic above is tested on a fake."""

    def __init__(self, connection):
        from sqlalchemy import inspect, text

        self._connection, self._text = connection, text
        self._inspector = inspect(connection)
        self._quote = connection.dialect.identifier_preparer.quote

    def database_id(self, name):
        row = self._connection.execute(
            self._text("SELECT id FROM dbs WHERE database_name = :name"), {"name": name}).fetchone()
        return None if row is None else row[0]

    def foreign_keys(self):
        out = []
        for table in self._inspector.get_table_names():
            for fk in self._inspector.get_foreign_keys(table):
                out.append((table, tuple(fk["constrained_columns"]), fk["referred_table"],
                            tuple(fk["referred_columns"])))
        return out

    def count(self, table, column, value):
        sql = f"SELECT count(*) FROM {self._quote(table)} WHERE {self._quote(column)} = :value"
        return self._connection.execute(self._text(sql), {"value": value}).scalar()

    def delete(self, table, column, value):
        sql = f"DELETE FROM {self._quote(table)} WHERE {self._quote(column)} = :value"
        return self._connection.execute(self._text(sql), {"value": value}).rowcount
