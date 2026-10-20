"""Dead code and dead permissions that read as if they mattered.

- register_project took a slug and a name it no longer used (the connection is named by the pid now);
- VIEWER_WRITABLE_VIEWS and ensure_viewer_role(extra_writable_views=...) named view menus no view checks
  ("AiscComment", "AiscReview", "AiscReviewRequest"): each start made can_read/can_write on them for nothing,
  while a viewer's real comment and review grants are _EXTENSION_GRANTS in superset_config.py;
- the comments table had add and edit column lists that its read-only permissions never reach."""
import ast
import inspect
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_register_project_takes_no_slug_or_name():
    from aisc_ext import projects

    assert not {"slug", "name"} & set(inspect.signature(projects.register_project).parameters)
    bridge = (REPO / "aisc_ext/project_bridge_api.py").read_text()
    assert 'body.get("slug")' not in bridge and 'body.get("name")' not in bridge


def test_no_view_menu_of_no_view_is_granted():
    from aisc_ext import security, viewer_role

    assert not hasattr(security, "VIEWER_WRITABLE_VIEWS")
    assert "extra_writable_views" not in inspect.signature(viewer_role.ensure_viewer_role).parameters
    assert "extra_writable_views" not in (REPO / "superset_config.py").read_text()


def test_the_comments_table_has_no_form_columns():
    src = (REPO / "aisc_ext/comments/views.py").read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "AiscCommentView")
    names = {t.id for n in cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert not {"add_columns", "edit_columns"} & names


def test_a_viewer_comments_and_files_reviews_through_the_extension_grants():
    src = (REPO / "superset_config.py").read_text()
    tree = ast.parse(src)
    grants = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Assign, ast.AnnAssign))
                  and getattr(getattr(n, "target", None) or n.targets[0], "id", None) == "_EXTENSION_GRANTS")
    assert {"can_post", "can_delete"} <= set(grants["CommentApi"])
    assert {"can_post", "can_patch"} <= set(grants["ReviewRequestApi"])
    assert '_grant(sm, _EXTENSION_GRANTS, ("Admin", "Alpha", "Gamma", VIEWER_ROLE))' in src
