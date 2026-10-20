"""What every test module may take as a parameter. Helpers that are not fixtures (FakeStore, PID, ...)
stay in the module that defines them and are imported from it."""
import importlib

import pytest


@pytest.fixture
def projects():
    """aisc_ext.projects, the module most tests drive."""
    return importlib.import_module("aisc_ext.projects")
