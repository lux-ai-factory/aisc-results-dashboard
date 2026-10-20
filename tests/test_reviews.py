# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Review request rules, without storage: a request is assigned to one person
or to a stakeholder group."""
import pytest

from aisc_ext.reviews.service import (
    STAKEHOLDER_GROUPS, can_resolve, is_for_user, make_request,
)


def test_make_request_to_user():
    r = make_request(dashboard_id="mcas", requested_by_sub="u1",
                     requested_by_name="alice", message="please review drift",
                     assignee_type="user", assignee_user_sub="u2", chart_id=5)
    assert r["assignee_type"] == "user" and r["assignee_user_sub"] == "u2"
    assert r["status"] == "open" and r["chart_id"] == 5


def test_make_request_to_category():
    r = make_request(dashboard_id="mcas", requested_by_sub="u1",
                     requested_by_name="alice", message="legal check",
                     assignee_type="category", assignee_category="legal")
    assert r["assignee_category"] == "legal" and r["chart_id"] is None


def test_invalid_category_rejected():
    with pytest.raises(ValueError):
        make_request(dashboard_id="d", requested_by_sub="u1",
                     requested_by_name="a", message="x",
                     assignee_type="category", assignee_category="marketing")


def test_user_assignment_requires_sub():
    with pytest.raises(ValueError):
        make_request(dashboard_id="d", requested_by_sub="u1",
                     requested_by_name="a", message="x", assignee_type="user")


def test_message_required():
    with pytest.raises(ValueError):
        make_request(dashboard_id="d", requested_by_sub="u1",
                     requested_by_name="a", message="  ",
                     assignee_type="category", assignee_category="ethics")


def test_is_for_user_specific():
    r = make_request(dashboard_id="d", requested_by_sub="u1", requested_by_name="a",
                     message="x", assignee_type="user", assignee_user_sub="u2")
    assert is_for_user(r, user_sub="u2", user_groups=[])
    assert not is_for_user(r, user_sub="u3", user_groups=["legal"])


def test_is_for_user_category_membership():
    r = make_request(dashboard_id="d", requested_by_sub="u1", requested_by_name="a",
                     message="x", assignee_type="category", assignee_category="legal")
    assert is_for_user(r, user_sub="u9", user_groups=["legal", "ethics"])
    assert not is_for_user(r, user_sub="u9", user_groups=["technical"])


def test_can_resolve_rules():
    r = make_request(dashboard_id="d", requested_by_sub="u1", requested_by_name="a",
                     message="x", assignee_type="category", assignee_category="legal")
    assert can_resolve(r, user_sub="u1", user_groups=[], is_admin=False)        # requester
    assert can_resolve(r, user_sub="u5", user_groups=["legal"], is_admin=False) # in category
    assert can_resolve(r, user_sub="x", user_groups=[], is_admin=True)          # admin
    assert not can_resolve(r, user_sub="x", user_groups=["technical"], is_admin=False)


def test_groups_taxonomy():
    assert {"legal", "compliance", "ethics", "technical", "business", "domain"} \
        <= set(STAKEHOLDER_GROUPS)


# ── access ─────────────────────────────────────────────────────────────────
# ReviewRequestApi lists, creates and resolves only the review requests on dashboards the caller can open,
# and does not inherit Flask-AppBuilder's CSRF exemption, like CommentApi.

def test_only_requests_on_dashboards_the_caller_can_open_are_listed():
    from aisc_ext.reviews.service import visible

    rows = [{"id": 1, "dashboard_id": "aisc-a"}, {"id": 2, "dashboard_id": "aisc-b"},
            {"id": 3, "dashboard_id": "aisc-a"}]
    asked = []

    def can_open(d):
        asked.append(d)
        return d == "aisc-a"

    assert [r["id"] for r in visible(rows, can_open)] == [1, 3]
    assert asked == ["aisc-a", "aisc-b"]                  # each dashboard asked once


def test_the_api_checks_the_dashboard_on_every_route_and_keeps_csrf():
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "aisc_ext/reviews/api.py").read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "ReviewRequestApi")
    assigned = {t.id: ast.literal_eval(n.value) for n in cls.body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
    assert assigned.get("csrf_exempt") is False
    for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in ("assignees", "list", "post", "patch")):
        text = ast.get_source_segment(src, fn)
        assert "open_dashboard(" in text or "self._dashboard(" in text or "visible(" in text, fn.name


# ── Requests are stored under the dashboard's id, whether the client sent the id or the slug ──────────────
# Comments are keyed by the dashboard's id (str(dashboard.id)); a request stored under the slug would be
# missing from a list by id, and one dashboard's requests would have two keys.

class _Dashboard:
    id, slug = 12, "aisc-" + "ab" * 16 + "-langbite"


def test_a_request_posted_with_the_slug_is_stored_under_the_dashboards_id():
    from aisc_ext.reviews.service import new_request

    body = {"dashboard_id": _Dashboard.slug, "message": "please check", "assignee_type": "category",
            "assignee_category": "legal"}
    data = new_request(body, _Dashboard(), requested_by_sub="u1", requested_by_name="Ada")
    assert data["dashboard_id"] == "12"
    assert new_request({**body, "dashboard_id": "12"}, _Dashboard(), requested_by_sub="u1",
                       requested_by_name="Ada")["dashboard_id"] == "12"


def test_a_list_by_slug_or_by_id_looks_under_the_id():
    from aisc_ext.reviews.service import list_key

    def resolve(key):
        return _Dashboard() if key in ("12", _Dashboard.slug) else None
    assert list_key(_Dashboard.slug, resolve) == "12"
    assert list_key("12", resolve) == "12"
    assert list_key("nowhere", resolve) == "nowhere"                    # no such dashboard: nothing matches


def _meta(tmp_path):
    from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine

    md = MetaData()
    dashboards = Table("dashboards", md, Column("id", Integer, primary_key=True), Column("slug", String(255)))
    requests = Table("aisc_review_request", md, Column("id", Integer, primary_key=True),
                     Column("dashboard_id", String(128)))
    engine = create_engine(f"sqlite:///{tmp_path / 'meta.db'}")
    md.create_all(engine)
    with engine.begin() as conn:
        conn.execute(dashboards.insert(), [{"id": 12, "slug": _Dashboard.slug}, {"id": 13, "slug": "7"},
                                           {"id": 14, "slug": None}])
        conn.execute(requests.insert(), [{"id": 1, "dashboard_id": _Dashboard.slug}, {"id": 2, "dashboard_id": "12"},
                                         {"id": 3, "dashboard_id": "gone-slug"}, {"id": 4, "dashboard_id": "7"}])
    return engine, requests


def test_requests_stored_under_a_slug_are_moved_to_the_id_once(tmp_path):
    from sqlalchemy import select

    from aisc_ext.reviews.service import rekey_by_id

    engine, requests = _meta(tmp_path)
    with engine.begin() as conn:
        assert rekey_by_id(conn) == 1
    with engine.begin() as conn:
        assert rekey_by_id(conn) == 0                                   # idempotent: run at every start
        keys = dict(conn.execute(select(requests.c.id, requests.c.dashboard_id)).all())
    # a digit key is already an id (even if a slug reads "7"); a slug of no dashboard is left as it is
    assert keys == {1: "12", 2: "12", 3: "gone-slug", 4: "7"}


def test_the_rekeying_runs_at_start_up():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "superset_config.py").read_text()
    assert "rekey_by_id(" in src


# ── A request already done or dismissed could be resolved again ─────────────────────────────────────────────
# Each PATCH set a new status, resolved_by and resolved_at and queued another dashboard.review.resolved, so a
# dismissed request could be turned into a done one by someone else, and the ledger said it was resolved twice.

def test_an_open_request_is_resolved_as_asked():
    from aisc_ext.reviews.service import resolution

    assert resolution("open", "done") == "done"
    assert resolution(None, "dismiss") == "dismissed"


@pytest.mark.parametrize("status", ["done", "dismissed"])
def test_a_request_that_is_not_open_cannot_be_resolved_again(status):
    from aisc_ext.reviews.service import NotOpen, resolution

    with pytest.raises(NotOpen):
        resolution(status, "done")


def test_the_route_answers_409_before_it_changes_anything():
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "aisc_ext/reviews/api.py").read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "ReviewRequestApi")
    text = ast.get_source_segment(src, next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "patch"))
    assert "except NotOpen" in text and "self.response(409" in text
    assert text.index("resolution(") < text.index("row.status =") < text.index("ledger.emit(")


# ── The requester could never resolve or dismiss their own request ──────────────────────────────────────────
# The route passed row.to_dict() to can_resolve, and to_dict leaves out requested_by_sub, so the requester's
# rule never matched: only an admin or an assignee could close it.

def _row(**over):
    from types import SimpleNamespace as NS

    fields = dict(requested_by_sub="u1", requested_by_name="Ada", assignee_type="category",
                  assignee_category="legal", assignee_user_sub=None, status="open")
    fields.update(over)
    row = NS(**fields)
    row.to_dict = lambda: {k: v for k, v in fields.items() if k != "requested_by_sub"}   # as the model's
    return row


def test_the_requester_may_resolve_their_own_request():
    from aisc_ext.reviews.service import may_resolve

    assert may_resolve(_row(), user_sub="u1", user_groups=[], is_admin=False)
    assert may_resolve(_row(), user_sub="u2", user_groups=["legal"], is_admin=False)        # the assignee
    assert not may_resolve(_row(), user_sub="u2", user_groups=["ethics"], is_admin=False)
    assert may_resolve(_row(), user_sub="u2", user_groups=[], is_admin=True)


def test_the_route_decides_on_the_row_not_on_its_api_output():
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "aisc_ext/reviews/api.py").read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "ReviewRequestApi")
    text = ast.get_source_segment(src, next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "patch"))
    assert "may_resolve(row," in text and "can_resolve(row.to_dict()" not in text


# ── Review requests could be added, edited and deleted through FAB's form ───────────────────────────────────

def _view_attrs(path, cls_name):
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / path).read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    return {t.id: n.value for n in cls.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}


def test_the_review_requests_table_is_read_only():
    """Assessment > Review Requests had FAB's default permissions (add, edit, delete): an admin (or a role
    superset init gives can_edit) could set a request to done or rewrite it with no resolver, no time and no
    ledger event, or add one under any dashboard_id. Requests are written through the API only, as comments."""
    import ast

    attrs = _view_attrs("aisc_ext/reviews/views.py", "AiscReviewRequestView")
    assert ast.literal_eval(attrs["base_permissions"]) == ["can_list", "can_show"]
    assert "add_columns" not in attrs and "edit_columns" not in attrs


# ── Bad input answered 500 "Fatal error", or was silently accepted ─────────────────────────────────────────

class _Dash:
    id, slug = 12, "aisc-" + "ab" * 16 + "-langbite"


BODY = {"dashboard_id": "12", "message": "please check", "assignee_type": "category", "assignee_category": "legal"}


@pytest.mark.parametrize("over", [{"message": ""}, {"message": 5}, {"assignee_type": "team"},
                                  {"assignee_category": ["legal"]}, {"chart_id": 99}, {"chart_id": "x"}])
def test_a_review_request_it_cannot_take_is_a_value_error(over):
    """Each of these reached the route as an uncaught ValueError or AttributeError (500), or was stored: a
    chart of another dashboard, a chart id that is not a number."""
    from aisc_ext.reviews.service import new_request

    with pytest.raises(ValueError):
        new_request({**BODY, **over}, _Dash(), requested_by_sub="u1", requested_by_name="Ada",
                    charts=[(3, "Bias per feature")])


def test_a_chart_of_the_dashboard_is_taken():
    from aisc_ext.reviews.service import new_request

    data = new_request({**BODY, "chart_id": 3}, _Dash(), requested_by_sub="u1", requested_by_name="Ada",
                       charts=[(3, "Bias per feature")])
    assert data["chart_id"] == 3


def test_an_unknown_action_resolves_nothing():
    """PATCH {"action": "reopen"} marked the request done and queued a resolved event."""
    from aisc_ext.reviews.service import resolution

    with pytest.raises(ValueError):
        resolution("open", "reopen")
    assert resolution("open", "done") == "done" and resolution("open", "dismiss") == "dismissed"


def test_a_comment_body_that_is_not_text_is_a_value_error():
    from aisc_ext.comments.service import make_comment

    for body in (5, None, ["x"], {"x": 1}):
        with pytest.raises(ValueError):
            make_comment(dashboard_id="12", author_sub="u1", author_name="Ada", body=body)


def test_a_chart_filter_that_is_not_a_number_is_a_value_error():
    from aisc_ext.comments.service import chart_filter

    assert chart_filter("7") == 7
    for bad in ("abc", "1.5", ""):
        with pytest.raises(ValueError):
            chart_filter(bad)


def _api_fn(path, cls_name, fn):
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / path).read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == cls_name)
    return ast.get_source_segment(src, next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == fn))


def test_the_routes_answer_400_for_what_they_cannot_take():
    post = _api_fn("aisc_ext/reviews/api.py", "ReviewRequestApi", "post")
    assert "charts=" in post and "except (ValueError, TypeError)" in post
    assert post.index("except (ValueError, TypeError)") < post.index("db.session.add(")
    patch = _api_fn("aisc_ext/reviews/api.py", "ReviewRequestApi", "patch")
    assert "except ValueError" in patch and patch.index("except ValueError") < patch.index("row.status =")
    listing = _api_fn("aisc_ext/comments/api.py", "CommentApi", "list")
    assert "chart_filter(" in listing and "int(request.args" not in listing
