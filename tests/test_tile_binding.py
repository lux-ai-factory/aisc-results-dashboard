"""Any signed-in person could read another project's results.

They imported a dashboard of their own whose metadata said `{"aisc_plugin": "x", "aisc_project": <victim pid>}`
(Superset's dashboard import keeps free metadata and makes the importer its owner), then chose it on
Assessment > Import charts: the page took the tile's project from that metadata and checked only ownership,
so every imported chart pointed at the victim's results dataset. The victim's pid was listed by
/api/v1/dashboard/related/roles.

A plugin tile is now a dashboard the bridge made (created by BRIDGE_USER) that carries its project's role;
importing into it takes being that project's editor (or an Admin), not only owning the dashboard; and the
related-roles list shows a person their own roles only."""
import json
import uuid
from pathlib import Path
from types import SimpleNamespace as NS

from aisc_ext import security
from aisc_ext.projects import editor_role_name, project_role_name

REPO = Path(__file__).resolve().parents[1]
A = str(uuid.UUID(int=0xA))
B = str(uuid.UUID(int=0xB))
BRIDGE_ID, ATTACKER_ID = 1, 7


def _dashboard(pid, *, created_by, roles=None, plugin="pkg::P"):
    meta = {"aisc_plugin": plugin, "aisc_project": pid}
    return NS(json_metadata=json.dumps(meta), created_by_fk=created_by,
              roles=[NS(name=r) for r in (roles if roles is not None else [project_role_name(pid)])])


def test_a_dashboard_someone_imported_naming_another_project_is_no_tile():
    planted = _dashboard(B, created_by=ATTACKER_ID, roles=[])
    planted_with_role = _dashboard(B, created_by=ATTACKER_ID)            # an owner may set roles too
    real = _dashboard(B, created_by=BRIDGE_ID)
    tiles = security.plugin_tiles([planted, planted_with_role, real], bridge_user_id=BRIDGE_ID)
    assert tiles == [(real, B)]


def test_a_bridge_dashboard_without_its_projects_role_is_no_tile():
    moved = _dashboard(B, created_by=BRIDGE_ID, roles=[project_role_name(A)])
    assert security.plugin_tiles([moved], bridge_user_id=BRIDGE_ID) == []
    assert security.plugin_tiles([_dashboard(B, created_by=BRIDGE_ID)], bridge_user_id=None) == []


def test_bad_metadata_is_no_tile():
    for meta in ("not json", "{}", json.dumps({"aisc_plugin": "x"}), json.dumps({"aisc_project": B}),
                 json.dumps({"aisc_plugin": "x", "aisc_project": "not-a-pid"})):
        d = NS(json_metadata=meta, created_by_fk=BRIDGE_ID, roles=[NS(name=project_role_name(B))])
        assert security.plugin_tiles([d], bridge_user_id=BRIDGE_ID) == []


def test_importing_into_a_tile_takes_being_its_projects_editor():
    """Owning the dashboard is not enough: an editor of A who owns B's tile (or any dashboard naming B) may not
    import into it. An Admin may."""
    mine_a = [project_role_name(A), editor_role_name(A)]
    assert security.may_import_into(A, user_roles=mine_a, is_admin=False, owns=True)
    assert not security.may_import_into(B, user_roles=mine_a, is_admin=False, owns=True)
    assert not security.may_import_into(A, user_roles=mine_a, is_admin=False, owns=False)
    assert not security.may_import_into(A, user_roles=[project_role_name(A)], is_admin=False, owns=True)
    assert security.may_import_into(B, user_roles=[], is_admin=True, owns=False)


def _source(path, cls, fn):
    import ast

    src = (REPO / path).read_text()
    tree = ast.parse(src)
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls) if cls else tree
    return ast.get_source_segment(src, next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == fn))


def test_the_import_page_and_the_ownership_sync_use_the_binding():
    assert "security.plugin_tiles(" in _source("aisc_ext/import_view.py", None, "_plugin_tiles")
    assert "may_import_into(" in _source("aisc_ext/import_view.py", "AiscChartImportView", "_mine")
    sync = _source("aisc_ext/sso.py", "KeycloakSecurityManager", "_sync_dashboard_ownership")
    assert "plugin_tiles(" in sync and "json_metadata" not in sync


def _roles_db():
    from sqlalchemy import Column, Integer, String, create_engine
    from sqlalchemy.orm import Session, declarative_base

    Base = declarative_base()

    class Role(Base):
        __tablename__ = "ab_role"
        id = Column(Integer, primary_key=True)
        name = Column(String)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all([Role(id=1, name="Admin"), Role(id=2, name=project_role_name(A)),
                     Role(id=3, name=project_role_name(B)), Role(id=4, name="AiscViewer")])
    session.commit()
    return session, Role


def test_the_related_roles_list_shows_a_person_their_own_roles_only():
    session, Role = _roles_db()
    me = NS(roles=[NS(id=2, name=project_role_name(A)), NS(id=4, name="AiscViewer")])
    names = sorted(r.name for r in security.own_roles_only(session.query(Role), user=me))
    assert names == sorted([project_role_name(A), "AiscViewer"])
    admin = NS(roles=[NS(id=1, name="Admin")])
    assert len(security.own_roles_only(session.query(Role), user=admin).all()) == 4


def test_superset_config_filters_the_related_roles():
    text = (REPO / "superset_config.py").read_text()
    assert 'EXTRA_RELATED_QUERY_FILTERS = {"role": own_roles_only}' in text
