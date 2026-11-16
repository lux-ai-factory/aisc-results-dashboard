"""A person's rights in the dashboards follow their project memberships as they are now, not as they were at sign-in.
Removed from a project, or changed from editor to viewer, the person must lose the dashboards or the edit rights
without signing out of Superset. Either the platform tells the dashboard of a membership change (a bridge route that
sets that person's roles again), or each request checks the memberships (a before_request hook with a short cache).
Read from the sources: aisc_ext.sso and superset_config import Superset."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _bridge_has_a_membership_route():
    text = (ROOT / "aisc_ext" / "project_bridge_api.py").read_text()
    return any("member" in route for route in re.findall(r'@expose\("([^"]+)"', text))


def _each_request_reads_memberships():
    text = (ROOT / "superset_config.py").read_text()
    # the body of each before_request hook: its def and the lines indented under it
    bodies, lines = [], text.splitlines()
    for n, line in enumerate(lines):
        if line.strip() != "@app.before_request":
            continue
        head = lines[n + 1]
        indent = len(head) - len(head.lstrip())
        body = []
        for later in lines[n + 2:]:
            if later.strip() and len(later) - len(later.lstrip()) <= indent:
                break
            body.append(later)
        bodies.append("\n".join(body))
    return any(re.search(r"\bmemberships?\b|_member_projects|apply_sign_in|roles_for_login", b) for b in bodies)


def test_a_membership_change_reaches_the_dashboards_before_the_next_sign_in():
    assert _bridge_has_a_membership_route() or _each_request_reads_memberships(), (
        "memberships are read at sign-in only (aisc_ext/sso.py auth_user_oauth): a removed member keeps the "
        "dashboards until they sign out of Superset")


# What the request hook does, on stand-ins: aisc_ext.security imports nothing from Superset.
from tests.test_project_bridge import HEX, PID, _FakeSM, _load  # noqa: E402

OTHER = "2f833fb3-5df0-48a8-92c0-22b7c364e78a"


class _RolesSM(_FakeSM):
    """Superset's find_role: one role object per name, as the metadata database gives."""
    def __init__(self):
        super().__init__()
        self.roles = {}

    def find_role(self, name):
        return self.roles.setdefault(name, type("Role", (), {"name": name})())


def _names(user):
    return [r.name for r in user.roles]


def _signed_in(security, memberships, now=1000.0):
    sm, user, session = _RolesSM(), type("U", (), {"roles": [], "username": "u"})(), {}
    security.apply_sign_in(sm, user, ["primary-user"], memberships)
    security.remember_sign_in(session, "sub-1", ["primary-user"], now)
    sm.updated.clear()
    return sm, user, session


def test_a_member_removed_loses_the_projects_roles_on_a_request_after_the_wait():
    security = _load("aisc_ext.security")
    sm, user, session = _signed_in(security, [(PID, "editor"), (OTHER, "viewer")])
    asked = []

    def read(subject):
        asked.append(subject)
        return [(OTHER, "viewer")]
    changed = security.follow_memberships(sm, user, session, 1000.0 + security.MEMBERSHIPS_READ_EVERY_S, read)
    assert changed and asked == ["sub-1"]
    assert f"AiscProject_{HEX}" not in _names(user) and f"AiscProjectEditor_{HEX}" not in _names(user)
    assert f"AiscProject_{OTHER.replace('-', '')}" in _names(user) and sm.updated == [user]


def test_an_editor_made_viewer_loses_the_edit_role_and_the_tiles():
    security = _load("aisc_ext.security")
    sm, user, session = _signed_in(security, [(PID, "editor")])
    owned = []
    security.follow_memberships(sm, user, session, 5000.0, lambda s: [(PID, "viewer")],
                                sync_ownership=lambda u, m: owned.append(m))
    assert f"AiscProjectEditor_{HEX}" not in _names(user) and f"AiscProject_{HEX}" in _names(user)
    assert owned == [[(PID, "viewer")]]


def test_memberships_are_read_at_most_once_in_the_wait():
    security = _load("aisc_ext.security")
    sm, user, session = _signed_in(security, [(PID, "editor")])
    asked = []
    security.follow_memberships(sm, user, session, 1001.0, lambda s: asked.append(s) or [])
    assert asked == [] and f"AiscProject_{HEX}" in _names(user)


def test_unchanged_memberships_write_nothing():
    security = _load("aisc_ext.security")
    sm, user, session = _signed_in(security, [(PID, "editor")])
    assert not security.follow_memberships(sm, user, session, 9000.0, lambda s: [(PID, "editor")])
    assert sm.updated == []
    # and the next read waits again
    asked = []
    security.follow_memberships(sm, user, session, 9001.0, lambda s: asked.append(s) or [])
    assert asked == []


def test_memberships_that_cannot_be_read_keep_the_roles():
    security = _load("aisc_ext.security")
    sm, user, session = _signed_in(security, [(PID, "editor")])
    before = list(user.roles)
    assert not security.follow_memberships(sm, user, session, 9000.0, lambda s: None)
    assert user.roles == before and sm.updated == []


def test_a_session_signed_in_without_a_subject_reads_nothing():
    security = _load("aisc_ext.security")
    sm, user = _FakeSM(), type("U", (), {"roles": ["role:Admin"], "username": "admin"})()
    asked = []
    assert not security.follow_memberships(sm, user, {}, 9000.0, lambda s: asked.append(s) or [])
    assert asked == [] and user.roles == ["role:Admin"]


def test_both_sign_in_paths_remember_who_signed_in():
    sso = (ROOT / "aisc_ext" / "sso.py").read_text()
    assert "remember_sign_in(" in sso and "self._remember(" in sso
    gateway = ROOT.parent.parent / "dashboard-gateway" / "superset_gateway_config.py"
    if gateway.exists():                                # in the aisc checkout
        assert "self._remember(" in gateway.read_text()
