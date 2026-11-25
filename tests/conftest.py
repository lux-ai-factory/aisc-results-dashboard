"""What every test module may take as a parameter. Helpers that are not fixtures (FakeStore, PID, ...)
stay in the module that defines them and are imported from it."""
import importlib
import os
import sys
from pathlib import Path

import pytest

# aisc_identity (the ledger's shared delivery loop): mounted beside aisc_ext in the stack, read here from the
# AISC checkout this repository sits in, or from AISC_IDENTITY_DIR when the tests run somewhere else (CI mounts
# this repository alone, at /w, in the dashboard's image: there is no checkout above it)
_HERE = Path(__file__).resolve()
_IDENTITY = (Path(os.environ["AISC_IDENTITY_DIR"]) if os.environ.get("AISC_IDENTITY_DIR")
             else _HERE.parents[3] / "shared/identity" if len(_HERE.parents) > 3 else None)
if _IDENTITY is not None and _IDENTITY.is_dir() and str(_IDENTITY) not in sys.path:
    sys.path.insert(0, str(_IDENTITY))


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
