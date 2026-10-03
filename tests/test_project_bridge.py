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

import pytest

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")
OTHER = "0b7f5c3e-2d7a-4c1e-9f64-3a1b2c3d4e5f"


class _Missing:
    """The module under test, imported on first use, so a missing module fails
    the test that uses it (not its setup, not collection)."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        try:
            mod = importlib.import_module(self._name)
        except ModuleNotFoundError as exc:
            pytest.fail(f"WP11 not built yet: {exc}")
        return getattr(mod, attr)


def _load(name):
    return _Missing(name)


@pytest.fixture
def projects():
    return _Missing("aisc_ext.projects")


# ---- bridge authentication -------------------------------------------------

ENV = {"DASHBOARD_BRIDGE_TOKEN": "s3cret-bridge"}


def test_s11_6_no_token_is_401(projects):
    assert projects.authorize_bridge({}, ENV) == 401


def test_s11_6_wrong_token_is_401(projects):
    assert projects.authorize_bridge({"X-AISC-Bridge-Token": "nope"}, ENV) == 401


def test_s11_6_right_token_passes(projects):
    assert projects.authorize_bridge({"X-AISC-Bridge-Token": "s3cret-bridge"}, ENV) is None


def test_s11_6_an_unconfigured_bridge_refuses_everyone(projects):
    """No DASHBOARD_BRIDGE_TOKEN means no bridge, not an open one."""
    assert projects.authorize_bridge({"X-AISC-Bridge-Token": ""}, {}) == 401
    assert projects.authorize_bridge({}, {"DASHBOARD_BRIDGE_TOKEN": ""}) == 401


def test_s11_6_the_comparison_is_constant_time(projects, monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    projects.authorize_bridge({"X-AISC-Bridge-Token": "s3cret-bridge"}, ENV)
    assert calls, "authorize_bridge must use hmac.compare_digest"


def test_s11_6_bridge_api_resource_name():
    """The route is /api/v1/aisc_project/<pid>. FAB derives it from resource_name."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "aisc_ext"
    found = [p for p in root.rglob("*.py")
             if 'resource_name = "aisc_project"' in p.read_text()]
    assert found, "no FAB BaseApi with resource_name = \"aisc_project\" in aisc_ext"


# ---- login role sync -------------------------------------------------------

def test_s11_2_a_member_gets_the_project_role_on_top_of_the_realm_role():
    security = _load("aisc_ext.security")
    roles = security.roles_for_login(["primary-user"], [PID])
    assert set(roles) == {security.VIEWER_ROLE, f"AiscProject_{HEX}"}


def test_s11_3_a_non_member_gets_no_project_role():
    security = _load("aisc_ext.security")
    roles = security.roles_for_login(["primary-user"], [])
    assert roles == [security.VIEWER_ROLE]
    assert not any(r.startswith("AiscProject_") for r in roles)


def test_s11_2_one_role_per_project_membership():
    security = _load("aisc_ext.security")
    roles = security.roles_for_login(["primary-user"], [PID, OTHER])
    assert f"AiscProject_{HEX}" in roles
    assert f"AiscProject_{OTHER.replace('-', '')}" in roles


def test_s11_2_the_admin_keeps_admin():
    security = _load("aisc_ext.security")
    roles = security.roles_for_login(["admin"], [PID])
    assert "Admin" in roles
    assert security.VIEWER_ROLE not in roles


def test_s11_2_membership_is_read_from_core_project_member(projects):
    """The subject's projects, read over the dashboard_ro connection."""
    sql = " ".join(projects.MEMBER_PROJECTS_SQL.split()).lower()
    assert "from core.project_member" in sql
    assert "subject" in sql


def test_s11_2_the_sso_manager_uses_the_membership():
    """auth_user_oauth must call roles_for_login, not only map_keycloak_roles."""
    import pathlib
    text = (pathlib.Path(__file__).resolve().parents[1] / "aisc_ext" / "sso.py").read_text()
    assert "roles_for_login" in text
