"""SupersetStore's imports run Superset's own import command as the bridge's service account. Superset is not
installed here: stand-ins for its import commands record what ran and as whom."""
import sys
import types

import pytest

from aisc_ext import projects


class Recorder:
    ran: list = []

    def __init__(self, files, overwrite=False):
        self.files, self.overwrite = files, overwrite

    def run(self):
        from flask import g
        Recorder.ran.append((type(self).__name__, self.files, self.overwrite, getattr(g.user, "username", None)))


class ImportDashboardsCommand(Recorder):
    pass


class ImportChartsCommand(Recorder):
    pass


@pytest.fixture
def store(monkeypatch):
    for name, cls in (("superset.commands.dashboard.importers.dispatcher", ImportDashboardsCommand),
                      ("superset.commands.chart.importers.dispatcher", ImportChartsCommand)):
        parts = name.split(".")
        for i in range(1, len(parts)):
            monkeypatch.setitem(sys.modules, ".".join(parts[:i]), sys.modules.get(".".join(parts[:i])) or types.ModuleType(".".join(parts[:i])))
        module = types.ModuleType(name)
        setattr(module, cls.__name__, cls)
        monkeypatch.setitem(sys.modules, name, module)
    bridge = types.SimpleNamespace(username=projects.BRIDGE_USER)
    s = projects.SupersetStore.__new__(projects.SupersetStore)
    monkeypatch.setattr(s, "_sm", lambda: types.SimpleNamespace(find_user=lambda username: bridge), raising=False)
    Recorder.ran = []
    return s


def test_a_dashboard_import_runs_supersets_command_as_the_bridge(store):
    from flask import Flask
    with Flask(__name__).app_context():
        store.import_dashboard({"metadata.yaml": "x"})
    assert Recorder.ran == [("ImportDashboardsCommand", {"metadata.yaml": "x"}, True, projects.BRIDGE_USER)]


def test_a_chart_import_runs_supersets_command_as_the_bridge(store):
    from flask import Flask
    with Flask(__name__).app_context():
        store.import_charts({"metadata.yaml": "y"})
    assert Recorder.ran == [("ImportChartsCommand", {"metadata.yaml": "y"}, True, projects.BRIDGE_USER)]
