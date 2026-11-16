# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Which project a dashboard is, and who may act on it (aisc_ext.access). Pure: no Superset."""
from aisc_ext import access

PID = "0b5446b0-3bcf-4747-9a47-996747111b86"
SLUG = "aisc-" + PID.replace("-", "")


# ── The ledger project was read from the slug, which any owner writes ───────────────────────────────────────
# An editor of their own project made a dashboard with slug aisc-<victim hex>-notes and commented on it: the
# event went into the victim's ledger. The project is now the slug's only when the dashboard carries that
# project's role and the person writing is in the project (or an Admin); otherwise no event is queued.

OTHER = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"


def _named(*names):
    from types import SimpleNamespace as NS

    return [NS(name=n) for n in names]


def _dash(slug, *roles):
    from types import SimpleNamespace as NS

    return NS(slug=slug, roles=_named(*roles))


def _user(*roles):
    from types import SimpleNamespace as NS

    return NS(roles=_named(*roles))


def test_a_dashboard_of_the_project_written_by_a_member_names_its_project():
    from aisc_ext.projects import project_role_name

    role = project_role_name(PID)
    assert access.project_if(_user(role, "AiscViewer"), _dash(SLUG + "-langbite", role), "comment") == PID
    assert access.project_if(_user("Admin"), _dash(SLUG, role), "comment") == PID


def test_a_slug_alone_names_no_project():
    from aisc_ext.projects import project_role_name

    victim, mine = project_role_name(PID), project_role_name(OTHER)
    planted = SLUG + "-notes"
    assert access.project_if(_user(mine), _dash(planted), "comment") is None                  # no role on the dashboard
    assert access.project_if(_user(mine), _dash(planted, victim), "comment") is None          # role set, writer not in it
    assert access.project_if(_user(mine), _dash(planted, mine), "comment") is None            # another project's role
    assert access.project_if(_user("Admin"), _dash("sales"), "comment") is None




def test_a_dashboard_is_its_projects_only_when_it_carries_the_projects_role():
    from aisc_ext.projects import project_role_name

    assert access.project_of(_dash(SLUG + "-langbite", project_role_name(PID))) == PID
    assert access.project_of(_dash(SLUG + "-langbite")) is None
    assert access.project_of(_dash(SLUG, project_role_name(OTHER))) is None
    assert access.project_of(_dash("sales", project_role_name(PID))) is None


# ── who may do what: one table ──

import pytest  # noqa: E402

from aisc_ext.projects import editor_role_name, project_role_name  # noqa: E402

MEMBER = (project_role_name(PID), "AiscViewer")
EDITOR = (project_role_name(PID), editor_role_name(PID), "AiscViewer")
OTHER_EDITOR = (project_role_name(OTHER), editor_role_name(OTHER))


def _person(*roles, uid=1):
    from types import SimpleNamespace as NS

    return NS(id=uid, roles=_named(*roles))


def _board(*, owner=None, project=True):
    from types import SimpleNamespace as NS

    return NS(slug=SLUG + "-p" if project else "sales", roles=_named(project_role_name(PID)),
              owners=[NS(id=owner)] if owner else [])


#          who                 owns   read   comment export change_chart import
TABLE = [(MEMBER,              False, True,  True,   False, False,       False),
         (MEMBER,              True,  True,  True,   False, False,       False),
         (EDITOR,              False, True,  True,   True,  True,        False),   # import also needs ownership
         (EDITOR,              True,  True,  True,   True,  True,        True),
         (OTHER_EDITOR,        True,  False, False,  False, False,       False),   # another project's editor
         (("AiscViewer",),     True,  False, False,  False, False,       False),
         (("Admin",),          False, True,  True,   True,  True,        True)]


@pytest.mark.parametrize("roles, owns, read, comment, export, change_chart, import_", TABLE)
def test_who_may_do_what_on_a_projects_dashboard(roles, owns, read, comment, export, change_chart, import_):
    board = _board(owner=1 if owns else 2)
    allowed = [read, comment, export, change_chart, import_]
    got = [access.may(_person(*roles), board, act) for act in access.ACTS]
    assert got == allowed
    assert access.ACTS == ("read", "comment", "export", "change_chart", "import")


@pytest.mark.parametrize("roles", [EDITOR, ("Admin",)])
def test_on_a_dashboard_of_no_project_nobody_may_act(roles):
    assert not any(access.may(_person(*roles), _board(owner=1, project=False), act) for act in access.ACTS)
    assert access.project_if(_person(*roles), _board(project=False), "read") is None


def test_the_project_is_given_only_when_the_act_is_allowed():
    assert access.project_if(_person(*EDITOR), _board(), "change_chart") == PID
    assert access.project_if(_person(*MEMBER), _board(), "change_chart") is None


def test_an_act_with_no_rule_is_an_error():
    with pytest.raises(ValueError):
        access.may(_person("Admin"), _board(), "delete_everything")


def _body(path, cls, fn):
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / path).read_text()
    owner = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == cls)
    return ast.get_source_segment(src, next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == fn))


@pytest.mark.parametrize("path, cls, fn, named", [
    ("aisc_ext/assistant/api.py", "AssistantApi", "start", 'self._project((request.json or {}).get("dashboard_id"), "read")'),
    ("aisc_ext/assistant/api.py", "AssistantApi", "message", 'self._project(dashboard_id, "read")'),
    ("aisc_ext/assistant/api.py", "AssistantApi", "message", 'access.may(g.user, dashboard, "change_chart")'),
    ("aisc_ext/assistant/api.py", "AssistantApi", "validate", 'self._project(dashboard_id, "change_chart")'),
    ("aisc_ext/report_exports/api.py", "ReportExportApi", "post", 'access.project_if(user, dashboard, "export")'),
    ("aisc_ext/report_exports/api.py", "ReportExportApi", "get", 'access.project_if(g.user, dashboard, "export")'),
    ("aisc_ext/import_view.py", "AiscChartImportView", "_mine", 'access.may(g.user, d, "import")'),
])
def test_every_route_names_its_act(path, cls, fn, named):
    assert named in _body(path, cls, fn)


def test_the_chart_assistant_is_asked_only_after_the_act_is_checked():
    for fn, check in (("message", 'access.may(g.user, dashboard, "change_chart")'),
                      ("validate", 'self._project(dashboard_id, "change_chart")')):
        text = _body("aisc_ext/assistant/api.py", "AssistantApi", fn)
        assert text.index(check) < text.index("_assistant("), fn
