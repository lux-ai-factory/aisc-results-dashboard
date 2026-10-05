# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Results navigation (docs/superpowers/results-nav-2026-10-03/01-specs.md, R1): the engine results
name each result's tool, and the project dashboard carries two native filters with fixed ids,
Target and Tool, so the launcher's buttons can open it with both set."""
import importlib
import sys
import types


TARGET, TOOL = "NATIVE_FILTER-target", "NATIVE_FILTER-tool"


# ── R1.1 the tool column ────────────────────────────────────────────────────


def _projects():
    return importlib.import_module("aisc_ext.projects")


def test_r1_1_engine_results_name_the_tool_never_null():
    sql = _projects().engine_results_sql()
    assert "COALESCE(p.display_name, p.name, 'unknown') AS tool" in " ".join(sql.split())


def test_r1_1_the_tool_column_is_declared_after_the_target_ones_as_a_string():
    """Last until 2026-10-04, when the run and the plugins' dimensions came after it (plugin dashboards T2.1)."""
    columns = _projects().ENGINE_RESULTS_COLUMNS
    names = [n for n, _ in columns]
    assert ("tool", "STRING") in columns and names.index("tool") == names.index("target_status") + 1


# ── R1.2 the two filters in the dashboard spec ──────────────────────────────

# ── R1.2, R1.3 the Superset store writes them, keeping the project tag ──────

class Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _superset(monkeypatch, rows, role):
    class Query:
        def __init__(self, items):
            self.items = items

        def filter_by(self, **kw):
            return Query([i for i in self.items if all(getattr(i, k, None) == v for k, v in kw.items())])

        def one_or_none(self):
            return self.items[0] if self.items else None

    class Session:
        def query(self, model):
            return Query(rows[model.__name__])

        def add(self, obj):
            name = type(obj).__name__
            if obj not in rows[name]:
                rows[name].append(obj)

        def flush(self):
            for obj in rows["Slice"]:
                if getattr(obj, "id", None) is None:
                    obj.id = 100 + rows["Slice"].index(obj)

        def commit(self):
            pass

    class SecurityManager:
        def find_role(self, name):
            return role if name == role.name else None

    Dashboard = type("Dashboard", (Row,), {})
    Slice = type("Slice", (Row,), {})
    SqlaTable = type("SqlaTable", (Row,), {})
    fake = {
        "superset": types.SimpleNamespace(db=types.SimpleNamespace(session=Session())),
        "superset.models": types.ModuleType("superset.models"),
        "superset.models.dashboard": types.SimpleNamespace(Dashboard=Dashboard),
        "superset.models.slice": types.SimpleNamespace(Slice=Slice),
        "superset.connectors": types.ModuleType("superset.connectors"),
        "superset.connectors.sqla": types.ModuleType("superset.connectors.sqla"),
        "superset.connectors.sqla.models": types.SimpleNamespace(SqlaTable=SqlaTable),
        "flask": types.SimpleNamespace(
            current_app=types.SimpleNamespace(appbuilder=types.SimpleNamespace(sm=SecurityManager()))),
    }
    for name, module in fake.items():
        monkeypatch.setitem(sys.modules, name, module)
    return SqlaTable

