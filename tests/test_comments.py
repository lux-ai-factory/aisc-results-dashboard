# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Comment rules, without storage.

A comment with a chart_id is about that chart; with chart_id None it is about
the whole dashboard ("overall"). The author always comes from the signed-in
identity, never from the request body.
"""
import pytest

from aisc_ext.comments.service import make_comment, can_delete


def _row(i, dash, chart, author, body):
    return {"id": i, "dashboard_id": dash, "chart_id": chart,
            "author_sub": author, "body": body}


def test_make_comment_uses_identity_not_body():
    c = make_comment(dashboard_id="d1", author_sub="u1", author_name="alice",
                     body="hi", chart_id=5)
    assert c["author_sub"] == "u1" and c["author_name"] == "alice"
    assert c["chart_id"] == 5 and c["dashboard_id"] == "d1"


def test_make_comment_overall_when_no_chart():
    c = make_comment(dashboard_id="d1", author_sub="u1", author_name="a", body="x")
    assert c["chart_id"] is None


def test_empty_body_rejected():
    with pytest.raises(ValueError):
        make_comment(dashboard_id="d1", author_sub="u1", author_name="a", body="  ")


def test_can_delete_author_or_admin():
    row = _row(1, "d1", 5, "u1", "x")
    assert can_delete(row, user_sub="u1", is_admin=False)      # author
    assert can_delete(row, user_sub="other", is_admin=True)    # moderator
    assert not can_delete(row, user_sub="other", is_admin=False)


# ── A comment deleted twice at once got two ledger events ─────────────────────────────────────────────────

def _comment_db(tmp_path):
    from sqlalchemy import Column, DateTime, Integer, Text, create_engine
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()

    class Comment(Base):                                                # the columns hide_once touches
        __tablename__ = "aisc_comment"
        id = Column(Integer, primary_key=True)
        body = Column(Text)
        deleted_at = Column(DateTime, nullable=True)

    engine = create_engine(f"sqlite:///{tmp_path / 'meta.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(Comment.__table__.insert().values(id=7, body="The bar looks off"))
    return engine, Comment


def test_two_deletes_of_one_comment_hide_it_once(tmp_path):
    """The author and an admin delete the same comment at once (or a double-click sends two DELETEs). Both
    requests read the row first (for the dashboard and author checks) and saw it not hidden, so both hid
    it and both queued dashboard.comment.deleted. Only the delete that actually hides it may say so."""
    from datetime import datetime

    from sqlalchemy.orm import Session

    from aisc_ext.comments.service import hide_once

    engine, Comment = _comment_db(tmp_path)
    with Session(engine) as first, Session(engine) as second:
        # both requests read the row and hold it, as the route does for its checks
        seen = [first.get(Comment, 7), second.get(Comment, 7)]
        assert [row.deleted_at for row in seen] == [None, None]
        assert hide_once(first, Comment, 7, datetime(2026, 10, 13, 10, 0)) is True
        first.commit()
        assert hide_once(second, Comment, 7, datetime(2026, 10, 13, 10, 0, 1)) is False
        second.commit()
    with Session(engine) as check:
        assert check.get(Comment, 7).deleted_at == datetime(2026, 10, 13, 10, 0)   # the first delete's time


def test_a_missing_comment_is_not_hidden(tmp_path):
    from datetime import datetime

    from sqlalchemy.orm import Session

    from aisc_ext.comments.service import hide_once

    engine, Comment = _comment_db(tmp_path)
    with Session(engine) as s:
        assert hide_once(s, Comment, 99, datetime(2026, 10, 13)) is False


def test_the_delete_route_queues_its_event_only_when_it_hid_the_comment():
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "aisc_ext/comments/api.py").read_text()
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "CommentApi")
    text = ast.get_source_segment(src, next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "delete"))
    assert "if not hide_once(" in text and "row.deleted_at =" not in text
    assert text.index("if not hide_once(") < text.index("ledger.emit(")
