"""The dashboard is opened from the project's AI Assessment Sandbox (step 4 on the launcher), so its "← Back" goes
one level up, there. Superset does not know the project of a page (the list shows every tile of the person), so
the platform's link names it (?aisc_project=<pid>) and the session keeps it."""
import ast
import importlib
from pathlib import Path

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
LAUNCHER = "http://launcher.test/"


def back():
    return importlib.import_module("aisc_ext.back")


def test_the_project_named_by_the_link_is_kept_for_the_session():
    session = {}
    back().remember({"aisc_project": PID}, session)
    assert session == {"aisc_project": PID}
    back().remember({}, session)                       # a later page without it keeps the project
    assert session == {"aisc_project": PID}


def test_only_a_project_id_is_kept():
    session = {}
    back().remember({"aisc_project": "javascript:alert(1)"}, session)
    assert session == {}


def test_back_goes_to_the_projects_sandbox_or_else_to_the_launcher():
    assert back().target({"aisc_project": PID}, LAUNCHER) == f"http://launcher.test/evidence.html?project={PID}"
    assert back().target({}, LAUNCHER) == LAUNCHER


def test_the_menu_has_a_back_link_every_role_may_see():
    src = (Path(__file__).resolve().parents[1] / "superset_config.py").read_text()
    tree = ast.parse(src)
    grants = next(n.value for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))
                  and getattr(getattr(n, "target", None) or n.targets[0], "id", None) == "_EXTENSION_GRANTS")
    assert ast.literal_eval(grants)["Back"] == ("menu_access",)
    assert 'add_link("Back", label="← Back", href="/aisc/back/"' in src
    assert "remember(request.args, session)" in src
