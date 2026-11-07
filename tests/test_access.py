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
    assert access.project_for(_dash(SLUG + "-langbite", role), _user(role, "AiscViewer")) == PID
    assert access.project_for(_dash(SLUG, role), _user("Admin")) == PID


def test_a_slug_alone_names_no_project():
    from aisc_ext.projects import project_role_name

    victim, mine = project_role_name(PID), project_role_name(OTHER)
    planted = SLUG + "-notes"
    assert access.project_for(_dash(planted), _user(mine)) is None                  # no role on the dashboard
    assert access.project_for(_dash(planted, victim), _user(mine)) is None          # role set, writer not in it
    assert access.project_for(_dash(planted, mine), _user(mine)) is None            # another project's role
    assert access.project_for(_dash("sales"), _user("Admin")) is None




def test_a_dashboard_is_its_projects_only_when_it_carries_the_projects_role():
    from aisc_ext.projects import project_role_name

    assert access.project_of(_dash(SLUG + "-langbite", project_role_name(PID))) == PID
    assert access.project_of(_dash(SLUG + "-langbite")) is None
    assert access.project_of(_dash(SLUG, project_role_name(OTHER))) is None
    assert access.project_of(_dash("sales", project_role_name(PID))) is None
