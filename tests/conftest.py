"""What every test module may take as a parameter. Helpers that are not fixtures (FakeStore, PID, ...)
stay in the module that defines them and are imported from it."""
import importlib
import os

import pytest


@pytest.fixture
def projects():
    """aisc_ext.projects, the module most tests drive."""
    return importlib.import_module("aisc_ext.projects")


@pytest.fixture(autouse=True)
def _ledger_off_unless_a_test_says_otherwise(monkeypatch):
    """An absent LEDGER_MODE means record, so every test starts with the ledger off unless the environment
    already names a mode; a test that wants events sets it."""
    if "LEDGER_MODE" not in os.environ:
        monkeypatch.setenv("LEDGER_MODE", "off")
