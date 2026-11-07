"""The dashboard's side of the chart assistant: what it tells the assistant about a project (D2: labels yes, free text
never, no counts), and how a validated proposal becomes a Superset chart on the project's own connection."""
import hashlib

import pytest

from aisc_ext.assistant.service import (MAX_LABELS, chart_params, description_from, distinct_sql, kind_of,
                                        made_chart_ids, may_validate, to_remove,
                                        validated_files, without_chart,
                                        place_chart)

SQL = "SELECT dimensions->>'category' AS category, 'x' AS series, avg(score) AS value FROM engine.aisc_backend_measurement GROUP BY 1"


def test_the_description_holds_targets_metrics_keys_and_short_label_lists():
    rows = [("Conversation", "category", ["AGE", "BASELINE"], 2, False, 5.0),
            ("Conversation", "slot", ["0", "1"], 2, True, 1.0),
            ("Conversation", "organisations", ["Stichting A"] * 3, 218, False, 25.0)]
    d = description_from(["OpenAI back-end", "Local back-end"], rows)
    dims = d["metrics"][0]["dimensions"]
    assert d["targets"] == ["OpenAI back-end", "Local back-end"]
    assert dims["category"] == {"type": "text", "values": ["AGE", "BASELINE"]}
    assert dims["slot"] == {"type": "number", "values": [0, 1]}
    assert dims["organisations"] == {"type": "text", "values": None}          # too many: free text


def test_long_values_are_free_text_and_never_listed():
    d = description_from([], [("Failed cases", "prompt", ["a long prompt"], 3, False, 300.0)])
    assert d["metrics"][0]["dimensions"]["prompt"]["values"] is None


def test_no_count_reaches_the_description():
    d = description_from([], [("M", "k", ["a"], 1, False, 1.0)])
    assert "rows" not in d["metrics"][0] and str(MAX_LABELS) not in str(d)


@pytest.mark.parametrize("roles,ok", [(["Admin"], True), (["AiscProjectEditor_abc"], True),
                                      (["AiscProject_abc", "AiscViewer"], False), (["AiscProjectEditor_other"], False)])
def test_only_an_editor_of_the_project_or_an_admin_validates(roles, ok):
    assert may_validate(roles, "abc") is ok


def test_a_radar_has_one_axis_per_category_and_one_polygon_per_series():
    p = chart_params({"kind": "radar", "title": "t", "category": "category", "series": "series", "value": "value"},
                     axes=["Age", "Gender", "Status"])
    assert p["viz_type"] == "radar" and p["groupby"] == ["series"] and len(p["metrics"]) == 3
    assert "\"category\" = 'Age'" in p["metrics"][0]["sqlExpression"] and p["legendOrientation"] == "bottom"


def test_a_bar_and_a_line_put_the_category_on_the_axis():
    for kind, viz in (("bar", "echarts_timeseries_bar"), ("line", "echarts_timeseries_line")):
        p = chart_params({"kind": kind, "title": "t", "category": "category", "value": "value"}, axes=[])
        assert p["viz_type"] == viz and p["x_axis"] == "category" and p["groupby"] == []


def test_a_quote_in_an_axis_cannot_break_the_expression():
    p = chart_params({"kind": "radar", "title": "t", "category": "c", "value": "v"}, axes=["it's", "b", "c"])
    assert "\"c\" = 'it''s'" in p["metrics"][0]["sqlExpression"]


def test_a_column_name_carrying_sql_stays_one_quoted_name_in_every_query():
    """The radar's category and the value are result columns the model named: a quoted alias can hold any text,
    which must stay a column name and never become SQL the assistant's table check did not see."""
    alias = 'label FROM project.secret_table --'
    assert distinct_sql(alias, "SELECT 1") == \
        'SELECT DISTINCT "label FROM project.secret_table --" FROM (SELECT 1) AS v ORDER BY 1'
    assert distinct_sql('a"b', "SELECT 1").startswith('SELECT DISTINCT "a""b" FROM')
    p = chart_params({"kind": "radar", "title": "t", "category": alias, "value": 'v" FROM x --'}, axes=["a"])
    assert p["metrics"][0]["sqlExpression"] == \
        'MAX(CASE WHEN "label FROM project.secret_table --" = \'a\' THEN "v"" FROM x --" END)'


def test_a_column_name_with_capitals_or_spaces_is_read_as_that_column():
    p = chart_params({"kind": "bar", "title": "t", "category": "Model", "value": "Pass rate"}, axes=[])
    assert p["metrics"][0]["sqlExpression"] == 'MAX("Pass rate")' and p["metrics"][0]["label"] == "Pass rate"
    radar = chart_params({"kind": "radar", "title": "t", "category": "Model", "value": "Pass rate"}, axes=["m"])
    assert radar["metrics"][0]["sqlExpression"] == 'MAX(CASE WHEN "Model" = \'m\' THEN "Pass rate" END)'
    assert distinct_sql("Model", "SELECT 1").startswith('SELECT DISTINCT "Model" FROM')


def test_the_validated_chart_reads_exactly_the_validated_query_on_the_projects_connection():
    source = {"database_uuid": "db-uuid", "database_name": "project db", "sqlalchemy_uri": "postgresql://x"}
    files = validated_files(source, pid="0b5446b0-3bcf-4747-9a47-996747111b86", sql=SQL,
                            fingerprint=hashlib.sha256(SQL.encode()).hexdigest(),
                            chart={"kind": "bar", "title": "Mean by category", "category": "category", "value": "value"},
                            columns=["category", "series", "value"], axes=[], description="the mean", author="admin")
    dataset = next(v for k, v in files.items() if k.startswith("datasets/"))
    chart = next(v for k, v in files.items() if k.startswith("charts/"))
    import yaml
    assert yaml.safe_load(dataset)["sql"] == SQL and yaml.safe_load(dataset)["database_uuid"] == "db-uuid"
    assert "Mean by category" in chart and hashlib.sha256(SQL.encode()).hexdigest()[:12] in chart


def test_a_query_changed_after_validation_is_refused():
    with pytest.raises(ValueError, match="fingerprint"):
        validated_files({"database_uuid": "d", "database_name": "n", "sqlalchemy_uri": "u"}, pid="p", sql=SQL + " ",
                        fingerprint=hashlib.sha256(SQL.encode()).hexdigest(),
                        chart={"kind": "table", "title": "t", "category": "category", "value": "value"},
                        columns=["category"], axes=[], description="", author="a")


def test_the_chart_goes_under_assistant_charts_on_the_dashboard():
    position = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
                "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]}}
    out = place_chart(position, chart_id=77, chart_uuid="u-1", name="Mean by category")
    header = [n for n in out.values() if isinstance(n, dict) and n.get("type") == "HEADER"]
    assert header and header[0]["meta"]["text"] == "Assistant charts"
    charts = [n for n in out.values() if isinstance(n, dict) and n.get("type") == "CHART"]
    assert charts[0]["meta"]["chartId"] == 77 and charts[0]["meta"]["uuid"] == "u-1"
    again = place_chart(out, chart_id=78, chart_uuid="u-2", name="Second")
    assert sum(1 for n in again.values() if isinstance(n, dict) and n.get("type") == "HEADER") == 1


def test_each_metric_carries_the_range_of_its_first_run_and_numbers_without_a_list_their_range():
    rows = [("Jailbreak success", "category", ["cv", "health"], 2, False, 5.0),
            ("Jailbreak success", "turns", ["1", "2"] * 30, 60, True, 1.0)]
    ranges = {"Jailbreak success": {"score": (0.0, 1.0, True), "dimensions": {"turns": (1, 6)}}}
    d = description_from([], rows, ranges)
    m = d["metrics"][0]
    assert m["score"] == {"min": 0.0, "max": 1.0, "whole": True}
    assert m["dimensions"]["turns"] == {"type": "number", "values": None, "min": 1, "max": 6}
    assert m["dimensions"]["category"] == {"type": "text", "values": ["cv", "health"]}


def test_the_dashboard_side_imports_only_what_the_dashboard_image_has():
    """A module the image lacks makes Superset skip every AISC extension at start (comments, reviews, exports)."""
    import ast
    from pathlib import Path
    allowed = {"json", "os", "urllib", "flask", "flask_appbuilder", "aisc_ext", "superset", "hashlib", "uuid", "yaml"}
    for name in ("api.py", "service.py"):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "aisc_ext" / "assistant" / name).read_text())
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for mod in mods:
                assert mod.split(".")[0] in allowed | {"__future__"}, f"{name} imports {mod}"


# ── the assistant's own plots: changed in place, removed ──

def _dashboard_with_two_made_plots():
    position = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
                "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-mine"], "parents": ["ROOT_ID"]},
                "ROW-mine": {"type": "ROW", "id": "ROW-mine", "children": ["CHART-mine"], "parents": ["ROOT_ID", "GRID_ID"]},
                "CHART-mine": {"type": "CHART", "id": "CHART-mine", "children": [],
                               "parents": ["ROOT_ID", "GRID_ID", "ROW-mine"], "meta": {"chartId": 5, "uuid": "u-0"}}}
    out = place_chart(position, chart_id=77, chart_uuid="u-1", name="First")
    return place_chart(out, chart_id=78, chart_uuid="u-2", name="Second")


def _charts(position):
    return [n["meta"]["chartId"] for n in position.values() if isinstance(n, dict) and n.get("type") == "CHART"]


def test_the_plots_it_made_are_only_those_under_assistant_charts():
    assert made_chart_ids(_dashboard_with_two_made_plots()) == [77, 78]


def test_removing_a_plot_takes_it_and_its_row_off_and_leaves_the_others_where_they_were():
    position = _dashboard_with_two_made_plots()
    out = without_chart(position, 77)
    assert sorted(_charts(out)) == [5, 78]
    grid = out["GRID_ID"]["children"]
    assert all(child in out for child in grid)
    assert grid == [c for c in position["GRID_ID"]["children"] if c in out]
    assert "HEADER-aisc-assistant" in out


def test_removing_the_last_plot_it_made_takes_the_header_off_too():
    out = without_chart(without_chart(_dashboard_with_two_made_plots(), 77), 78)
    assert _charts(out) == [5] and "HEADER-aisc-assistant" not in out
    assert "HEADER-aisc-assistant" not in out["GRID_ID"]["children"]


def test_a_plot_that_is_not_its_own_is_not_removed_unless_any_plot_may_be():
    position = _dashboard_with_two_made_plots()
    assert without_chart(position, 5) == position


def test_a_replacement_takes_the_old_plots_place():
    position = _dashboard_with_two_made_plots()
    out = place_chart(position, chart_id=79, chart_uuid="u-3", name="First, as bars", replaces=77)
    assert sorted(_charts(out)) == [5, 78, 79]
    order = [out[r]["children"][0] for r in out["GRID_ID"]["children"] if r.startswith("ROW-")]
    assert [out[n]["meta"]["chartId"] for n in order] == [5, 79, 78]


def test_a_replacement_of_a_plot_no_longer_there_is_added_at_the_end():
    out = place_chart(without_chart(_dashboard_with_two_made_plots(), 77), chart_id=79, chart_uuid="u-3",
                      name="x", replaces=77)
    assert made_chart_ids(out) == [78, 79]


@pytest.mark.parametrize("viz, kind", [("radar", "radar"), ("echarts_timeseries_bar", "bar"),
                                       ("echarts_timeseries_line", "line"), ("table", "table")])
def test_the_kind_of_a_made_plot_is_read_back_from_superset(viz, kind):
    assert kind_of(viz) == kind


def test_a_removal_is_a_ledger_event_saying_which_plot_left_which_dashboard():
    from aisc_ext import ledger
    assert "dashboard.assistant.removed" in ledger.ACTIONS
    fields = ledger.assistant_removed(77, "Mean by category", slug="aisc-x", request="r1")
    assert fields["item_type"] == "chart" and fields["item_id"] == "77"
    assert fields["details"] == {"dashboard": "aisc-x"} and fields["before"] == {"title": "Mean by category"}


def _tabbed_dashboard():
    return {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["TABS-x"]},
            "TABS-x": {"type": "TABS", "id": "TABS-x", "children": ["TAB-a"], "parents": ["ROOT_ID"], "meta": {}},
            "TAB-a": {"type": "TAB", "id": "TAB-a", "children": [], "parents": ["ROOT_ID", "TABS-x"],
                      "meta": {"text": "Against the baseline"}}}


def test_on_a_dashboard_with_tabs_its_plots_go_in_a_tab_of_their_own():
    out = place_chart(_tabbed_dashboard(), chart_id=77, chart_uuid="u-1", name="First")
    tabs = out["TABS-x"]["children"]
    assert tabs[0] == "TAB-a" and len(tabs) == 2
    tab = out[tabs[1]]
    assert tab["type"] == "TAB" and tab["meta"]["text"] == "Assistant charts"
    row = out[tab["children"][0]]
    node = out[row["children"][0]]
    assert node["meta"]["chartId"] == 77 and node["parents"] == ["ROOT_ID", "TABS-x", tabs[1], row["id"]]
    assert made_chart_ids(out) == [77]


def test_removing_its_last_plot_on_a_tabbed_dashboard_takes_its_tab_off():
    out = place_chart(_tabbed_dashboard(), chart_id=77, chart_uuid="u-1", name="First")
    assert without_chart(out, 77) == _tabbed_dashboard()


MADE = [{"id": 77, "title": "First"}, {"id": 78, "title": "Second"}]


def test_every_plot_the_assistant_asks_to_remove_is_taken_with_its_own_title():
    asked = [{"chart": 77, "title": "whatever the model said"}, {"chart": 78, "title": "x"}]
    assert to_remove(asked, MADE) == [(77, "First"), (78, "Second")]


def test_one_plot_not_on_the_dashboard_refuses_the_whole_removal():
    assert to_remove([{"chart": 77}, {"chart": 5}], MADE) is None
    assert to_remove([], MADE) is None and to_remove("77", MADE) is None



def test_any_plot_on_the_dashboard_can_be_removed_when_asked_for_any():
    position = _dashboard_with_two_made_plots()
    out = without_chart(position, 5, any_chart=True)
    assert sorted(_charts(out)) == [77, 78] and "ROW-mine" not in out
    assert "ROW-mine" not in out["GRID_ID"]["children"]


def test_every_plot_on_the_dashboard_is_listed_saying_which_the_assistant_made():
    from aisc_ext.assistant.service import plots_on
    assert plots_on(_dashboard_with_two_made_plots()) == [(5, False), (77, True), (78, True)]


def test_the_session_keeps_only_the_most_recent_conversations():
    """The conversations live in the signed session cookie: it must not grow past a browser's 4 KB limit."""
    from aisc_ext.assistant.service import MAX_CONVERSATIONS, with_conversation
    held = {}
    for n in range(200):
        held = with_conversation(held, f"conversation-{n}", n)
    assert len(held) == MAX_CONVERSATIONS <= 20
    assert list(held) == [f"conversation-{n}" for n in range(200 - MAX_CONVERSATIONS, 200)]
    assert held["conversation-199"] == 199


def test_a_numeric_labels_range_keeps_its_fractions_and_whole_ranges_stay_whole():
    from decimal import Decimal

    from aisc_ext.assistant.service import ranges_from
    out = ranges_from([("M", Decimal("0.1"), Decimal("0.75"), False)],
                      [("M", "threshold", Decimal("0.2"), Decimal("0.9")), ("M", "turns", Decimal("1"), Decimal("6"))])
    assert out["M"]["score"] == (0.1, 0.75, False)
    assert out["M"]["dimensions"]["threshold"] == (0.2, 0.9)
    assert out["M"]["dimensions"]["turns"] == (1, 6) and isinstance(out["M"]["dimensions"]["turns"][0], int)
