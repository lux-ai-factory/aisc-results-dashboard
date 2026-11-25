"""The dashboard's side of the chart assistant: what it tells the assistant about a project (D2: labels yes, free text
never, no counts), and how a validated proposal becomes a Superset chart on the project's own connection."""
import hashlib

import pytest

from aisc_ext.assistant.service import (MAX_LABELS, chart_params, confirmation, description_from, distinct_sql,
                                        read_signed, result_sentence, sign, validated_result,
                                        to_remove, validated_files)
from aisc_ext.charts import kind_of

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


def test_the_validated_bundle_is_written_in_the_one_superset_format_of_charts_py(monkeypatch):
    """A format change made in charts.py (here its file version) reaches the assistant's bundle too."""
    import yaml

    from aisc_ext import charts
    monkeypatch.setattr(charts, "_VERSION", "9.9.9")
    source = {"database_uuid": "db-uuid", "database_name": "project db", "sqlalchemy_uri": "postgresql://x"}
    files = validated_files(source, pid="0b5446b0-3bcf-4747-9a47-996747111b86", sql=SQL,
                            fingerprint=hashlib.sha256(SQL.encode()).hexdigest(),
                            chart={"kind": "bar", "title": "Mean by category", "category": "category", "value": "value"},
                            columns=["category", "series", "value"], axes=[], description="the mean", author="admin")
    assert {yaml.safe_load(v)["version"] for v in files.values()} == {"9.9.9"}
    dataset = yaml.safe_load(next(v for k, v in files.items() if k.startswith("datasets/")))
    assert dataset["metrics"] == [] and "the mean" in dataset["description"]


def test_a_query_changed_after_validation_is_refused():
    with pytest.raises(ValueError, match="fingerprint"):
        validated_files({"database_uuid": "d", "database_name": "n", "sqlalchemy_uri": "u"}, pid="p", sql=SQL + " ",
                        fingerprint=hashlib.sha256(SQL.encode()).hexdigest(),
                        chart={"kind": "table", "title": "t", "category": "category", "value": "value"},
                        columns=["category"], axes=[], description="", author="a")


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
    allowed = {"json", "os", "urllib", "flask", "flask_appbuilder", "aisc_ext", "superset", "hashlib", "hmac", "base64",
               "decimal", "math", "re", "time", "uuid", "yaml"}
    for name in ("api.py", "service.py"):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "aisc_ext" / "assistant" / name).read_text())
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for mod in mods:
                assert mod.split(".")[0] in allowed | {"__future__"}, f"{name} imports {mod}"


# ── the assistant's own plots: changed in place, removed ──


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


MADE = [{"id": 77, "title": "First"}, {"id": 78, "title": "Second"}]


def test_every_plot_the_assistant_asks_to_remove_is_taken_with_its_own_title():
    asked = [{"chart": 77, "title": "whatever the model said"}, {"chart": 78, "title": "x"}]
    assert to_remove(asked, MADE) == [(77, "First"), (78, "Second")]


def test_one_plot_not_on_the_dashboard_refuses_the_whole_removal():
    assert to_remove([{"chart": 77}, {"chart": 5}], MADE) is None
    assert to_remove([], MADE) is None and to_remove("77", MADE) is None


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


def test_the_service_keeps_only_the_assistants_own_rules_and_reexports_no_superset_format():
    """Superset's formats have one home, charts.py: callers import them from there."""
    from aisc_ext.assistant import service
    for name in ("changed_params", "kind_of", "plot_definition", "place_chart", "plots_on", "without_chart"):
        assert not hasattr(service, name), name


def test_a_signed_token_reads_back_as_what_was_signed():
    token = sign({"kind": "remove", "charts": [7]}, "key", now=1000.0)
    assert read_signed(token, "key", now=1100.0) == {"kind": "remove", "charts": [7]}


def test_a_token_changed_or_signed_with_another_key_reads_as_nothing():
    token = sign({"kind": "remove", "charts": [7]}, "key", now=1000.0)
    assert read_signed(token[:-2] + "xx", "key", now=1000.0) is None
    assert read_signed(token, "other", now=1000.0) is None
    assert read_signed("not a token", "key", now=1000.0) is None


def test_a_token_older_than_fifteen_minutes_reads_as_nothing():
    token = sign({"kind": "remove"}, "key", now=1000.0)
    assert read_signed(token, "key", now=1000.0 + 901) is None


PLOTS = [{"id": 7, "title": "Jailbreaks by language"}, {"id": 9, "title": "By category"}]


def test_a_change_is_confirmed_by_naming_the_plot_and_what_changes():
    c = confirmation({"change": {"chart": 7, "changes": {"axis_max": 0.4, "kind": "line"}}}, PLOTS)
    assert c == {"kind": "change", "chart": 7, "changes": {"axis_max": 0.4, "kind": "line"},
                 "text": 'Change "Jailbreaks by language": axis maximum to 0.4, kind to line?'}


def test_a_new_title_and_percentages_are_named_in_plain_words():
    c = confirmation({"change": {"chart": 9, "changes": {"axis_min": 0, "percent": True, "title": "Categories"}}}, PLOTS)
    assert c["text"] == 'Change "By category": title to "Categories", percentages on, axis minimum to 0?'


def test_a_removal_names_every_plot_and_says_the_charts_stay():
    c = confirmation({"remove": [{"chart": 7}, {"chart": 9}]}, PLOTS)
    assert c == {"kind": "remove", "charts": [7, 9],
                 "text": 'Remove "Jailbreaks by language", "By category" from this dashboard? '
                         'The charts stay in Superset.'}


def test_a_plot_that_is_not_on_the_dashboard_gives_no_confirmation():
    assert confirmation({"remove": [{"chart": 7}, {"chart": 99}]}, PLOTS) is None
    assert confirmation({"change": {"chart": 99, "changes": {"title": "x"}}}, PLOTS) is None


def test_the_assistant_is_told_only_the_targets_that_have_results():
    """A target with no result (a chat page, an organisation list) would become a series of invented values in every
    preview; the query that lists them reaches measurements through the run's target input."""
    from aisc_ext.assistant.service import TARGETS_SQL
    sql = " ".join(TARGETS_SQL.split())
    assert "ti.name = 'target'" in sql and "engine.aisc_backend_measurement" in sql


SENTENCE_CHART = {"kind": "bar", "title": "t", "category": "category", "series": "series", "value": "value"}
SENTENCE_COLS = ["category", "series", "value"]


def test_the_sentence_names_the_highest_and_the_lowest_value_with_their_place():
    rows = [("instructions", "Mistral", 0.872), ("out_of_scope", "Local", 0.0133), ("cv", "OpenAI", 0.207)]
    assert result_sentence(SENTENCE_CHART, SENTENCE_COLS, rows) == ("Highest: instructions, Mistral (0.872). "
                                                                    "Lowest: out_of_scope, Local (0.0133).")


def test_without_series_only_the_category_is_named():
    chart = {k: v for k, v in SENTENCE_CHART.items() if k != "series"}
    assert result_sentence(chart, ["category", "value"], [("a", 3), ("b", 12)]) == "Highest: b (12). Lowest: a (3)."


def test_empty_values_are_left_out_and_a_single_value_is_said_once():
    assert result_sentence(SENTENCE_CHART, SENTENCE_COLS, [("a", "x", None), ("b", "y", 0.5)]) == "One value: b, y (0.5)."


def test_no_rows_and_no_values_are_said_plainly():
    assert result_sentence(SENTENCE_CHART, SENTENCE_COLS, []) == "The query returns no rows on your data."
    assert result_sentence(SENTENCE_CHART, SENTENCE_COLS, [("a", "x", None)]) == "No value to compare."


def test_the_database_decimals_count_as_numbers_and_text_or_true_does_not():
    from decimal import Decimal
    rows = [("a", "x", Decimal("0.25")), ("b", "y", "high"), ("c", "z", True), ("d", "w", Decimal("2"))]
    assert result_sentence(SENTENCE_CHART, SENTENCE_COLS, rows) == "Highest: d, w (2). Lowest: a, x (0.25)."


def test_large_numbers_are_written_whole_not_in_exponent_form():
    rows = [("a", "x", 12345.6), ("b", "y", 40.0)]
    assert result_sentence(SENTENCE_CHART, SENTENCE_COLS, rows) == "Highest: a, x (12346). Lowest: b, y (40)."


def test_after_validation_the_answer_carries_the_first_fifty_rows_and_says_there_are_more():
    asked = []

    def read(sql):
        asked.append(sql)
        return ["category", "value"], [(f"c{i}", i) for i in range(51)]
    answer = validated_result(read, "SELECT 1", {"category": "category", "value": "value"})
    assert asked == ["SELECT * FROM (SELECT 1) AS validated LIMIT 51"]
    assert answer["result"]["columns"] == ["category", "value"] and len(answer["result"]["rows"]) == 50
    assert answer["result"]["more"] is True and answer["sentence"] == "Highest: c49 (49). Lowest: c0 (0)."


def test_the_rows_are_sent_as_json_values():
    from datetime import date
    from decimal import Decimal
    answer = validated_result(lambda sql: (["d", "v"], [(date(2026, 11, 2), Decimal("0.5"))]), "S",
                              {"category": "d", "value": "v"})
    assert answer["result"] == {"columns": ["d", "v"], "rows": [["2026-11-02", 0.5]], "more": False}


def test_rows_that_cannot_be_read_leave_the_chart_made_and_say_so():
    def read(sql):
        raise RuntimeError("timeout")
    assert validated_result(read, "S", {"category": "c", "value": "v"}) == {
        "sentence": "The chart was made; its values could not be read here."}
