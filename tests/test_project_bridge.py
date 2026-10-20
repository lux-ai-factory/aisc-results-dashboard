# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The bridge and the login role sync: who may make a project's dashboard, and
who may see it.

The platform calls POST / DELETE /api/v1/aisc_project/<pid> after it provisions
or before it drops a project. The call carries X-AISC-Bridge-Token, compared
in constant time with DASHBOARD_BRIDGE_TOKEN. The FAB BaseApi that serves it
needs Superset; the decision it applies is `authorize_bridge`, tested here.

On login, a member of project P gets AiscProject_<hex> on top of the role the
realm maps to; the admin keeps Admin.
"""
import hmac
import importlib
from pathlib import Path

import pytest

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")
OTHER = "0b7f5c3e-2d7a-4c1e-9f64-3a1b2c3d4e5f"


def _load(name):
    return importlib.import_module(name)


# ---- bridge authentication -------------------------------------------------

ENV = {"DASHBOARD_BRIDGE_TOKEN": "s3cret-bridge"}


def test_no_token_is_401(projects):
    assert projects.authorize_bridge({}, ENV) == 401


def test_wrong_token_is_401(projects):
    assert projects.authorize_bridge({"X-AISC-Bridge-Token": "nope"}, ENV) == 401


def test_right_token_passes(projects):
    assert projects.authorize_bridge({"X-AISC-Bridge-Token": "s3cret-bridge"}, ENV) is None


def test_an_unconfigured_bridge_refuses_everyone(projects):
    """No DASHBOARD_BRIDGE_TOKEN means no bridge, not an open one."""
    assert projects.authorize_bridge({"X-AISC-Bridge-Token": ""}, {}) == 401
    assert projects.authorize_bridge({}, {"DASHBOARD_BRIDGE_TOKEN": ""}) == 401


def test_the_comparison_is_constant_time(projects, monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    projects.authorize_bridge({"X-AISC-Bridge-Token": "s3cret-bridge"}, ENV)
    assert calls, "authorize_bridge must use hmac.compare_digest"


# ---- login role sync -------------------------------------------------------

def test_a_member_gets_the_project_role_on_top_of_the_realm_role():
    security = _load("aisc_ext.security")
    roles = security.roles_for_login(["primary-user"], [PID])
    assert set(roles) == {security.VIEWER_ROLE, f"AiscProject_{HEX}"}


def test_a_non_member_gets_no_project_role():
    security = _load("aisc_ext.security")
    roles = security.roles_for_login(["primary-user"], [])
    assert roles == [security.VIEWER_ROLE]
    assert not any(r.startswith("AiscProject_") for r in roles)


def test_one_role_per_project_membership():
    security = _load("aisc_ext.security")
    roles = security.roles_for_login(["primary-user"], [PID, OTHER])
    assert f"AiscProject_{HEX}" in roles
    assert f"AiscProject_{OTHER.replace('-', '')}" in roles


def test_the_admin_keeps_admin():
    security = _load("aisc_ext.security")
    roles = security.roles_for_login(["admin"], [PID])
    assert "Admin" in roles
    assert security.VIEWER_ROLE not in roles


def test_membership_is_read_from_core_project_member(projects):
    """The subject's projects, read over the dashboard_ro connection."""
    sql = " ".join(projects.MEMBER_PROJECTS_SQL.split()).lower()
    assert "from core.project_member" in sql
    assert "subject" in sql


# ---- Owners and editors build charts -------------------------------------------

def test_membership_is_read_with_the_members_rank(projects):
    sql = " ".join(projects.MEMBER_PROJECTS_SQL.split()).lower()
    assert sql.startswith("select project_id, role from core.project_member")


def test_an_owner_or_editor_also_gets_the_projects_editor_role():
    security = _load("aisc_ext.security")
    for rank in ("owner", "editor"):
        roles = security.roles_for_login(["primary-user"], [(PID, rank)])
        assert set(roles) == {security.VIEWER_ROLE, f"AiscProject_{HEX}", f"AiscProjectEditor_{HEX}"}, rank


def test_a_viewer_gets_the_project_role_only():
    security = _load("aisc_ext.security")
    assert set(security.roles_for_login(["primary-user"], [(PID, "viewer")])) == {
        security.VIEWER_ROLE, f"AiscProject_{HEX}"}


def test_a_bare_pid_still_reads_as_a_viewer():
    """What _member_projects returned before ranks: no editor role from it."""
    security = _load("aisc_ext.security")
    assert f"AiscProjectEditor_{HEX}" not in security.roles_for_login(["primary-user"], [PID])


def test_the_editor_role_writes_charts_and_dashboards_and_nothing_else(projects):
    import tests.test_projects as tp
    store = tp.FakeStore()
    tp._register(projects, store)
    role = store.items("role")[f"AiscProjectEditor_{HEX}"]
    assert sorted(map(tuple, role["permissions"])) == [("can_write", "Chart"), ("can_write", "Dashboard")]
    assert role["aisc_project"] == PID


def test_owners_and_editors_own_their_plugin_dashboards_and_a_former_editor_is_removed():
    security = _load("aisc_ext.security")
    dashboards = [("aisc-p-drift", PID, False), ("aisc-p-langbite", PID, True), ("aisc-o-drift", OTHER, True),
                  ("aisc-x-drift", "c0ffee00-0000-4000-8000-000000000000", False)]
    add, remove = security.ownership_changes([(PID, "editor"), (OTHER, "viewer")], dashboards)
    assert add == ["aisc-p-drift"] and remove == ["aisc-o-drift"]
    add, remove = security.ownership_changes([], dashboards)
    assert add == [] and remove == ["aisc-o-drift", "aisc-p-langbite"]


# ---- one sign-in for both paths (the gateway's and OAuth's) -------------------
# The stack signs people in through the gateway (dashboard-gateway/superset_gateway_config.py), not OAuth: an
# ownership step on the OAuth path only would leave editors never owning their tiles.

class _FakeSM:
    def __init__(self):
        self.updated = []

    def find_role(self, name):
        return f"role:{name}"

    def update_user(self, user):
        self.updated.append(user)


def test_sign_in_sets_the_roles_then_the_ownership():
    security = _load("aisc_ext.security")
    sm, user, owned = _FakeSM(), type("U", (), {"roles": []})(), []
    security.apply_sign_in(sm, user, ["primary-user"], [(PID, "editor")],
                           sync_ownership=lambda u, m: owned.append((u, m)))
    assert user.roles == [f"role:{security.VIEWER_ROLE}", f"role:AiscProject_{HEX}", f"role:AiscProjectEditor_{HEX}"]
    assert sm.updated == [user] and owned == [(user, [(PID, "editor")])]


def test_an_ownership_failure_never_blocks_a_sign_in():
    security = _load("aisc_ext.security")

    def broken(u, m):
        raise RuntimeError("the metadata database is down")
    user = type("U", (), {"roles": [], "username": "u"})()
    security.apply_sign_in(_FakeSM(), user, ["primary-user"], [(PID, "editor")], sync_ownership=broken)
    assert user.roles                                   # signed in, with the roles


def test_both_sign_in_paths_use_it():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    assert "apply_sign_in(self, user" in (root / "aisc_ext" / "sso.py").read_text()
    # .parent, not .parents[1]: a checkout mounted near "/" (a test image's /repo) has no parents[1]
    gateway = root.parent.parent / "dashboard-gateway" / "superset_gateway_config.py"
    if gateway.exists():                                # in the aisc checkout
        text = gateway.read_text()
        assert "apply_sign_in(" in text and "sync_ownership=self._sync_dashboard_ownership" in text


def test_the_project_connections_take_dashboard_ro_s_password_from_the_environment_only(projects):
    """No fallback to `dashboard_ro`, the role's own name, which would run every project connection on
    a password anyone who read the repository has. It is DASHBOARD_RO_PASSWORD, and without it the bridge registers nothing."""
    assert projects.dashboard_ro_password({"DASHBOARD_RO_PASSWORD": "from-secrets"}) == "from-secrets"
    with pytest.raises(LookupError):
        projects.dashboard_ro_password({})
    with pytest.raises(LookupError):
        projects.dashboard_ro_password({"DASHBOARD_RO_PASSWORD": ""})
    src = (Path(__file__).resolve().parents[1] / "aisc_ext/project_bridge_api.py").read_text()
    assert '"dashboard_ro")' not in src and "dashboard_ro_password(os.environ)" in src
