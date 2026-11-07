"""The chart assistant knows every plot on the dashboard by its definition (never its values) and changes one in place:
title, kind between bar and line, the axis's minimum and maximum, percentages."""
import pytest

from aisc_ext.assistant.service import changed_params, plot_definition

FILTERS = [{"expressionType": "SIMPLE", "subject": "tool", "operator": "==", "comparator": "StrongREJECT (Mijke)",
            "clause": "WHERE"},
           {"expressionType": "SIMPLE", "subject": "metric", "operator": "IN", "comparator": ["Jailbreak success"],
            "clause": "WHERE"}]
RADAR = {"viz_type": "radar", "groupby": ["run"], "number_format": ".0%", "adhoc_filters": FILTERS,
         "metrics": [{"expressionType": "SQL", "label": lang,
                      "sqlExpression": f"AVG(CASE WHEN language = '{lang}' THEN score END)"} for lang in ("en", "nl")],
         "column_config": {"en": {"radarMetricMaxValue": 1}, "nl": {"radarMetricMaxValue": 1}}}
BAR = {"viz_type": "echarts_timeseries_bar", "x_axis": "language", "groupby": ["metric", "run"],
       "y_axis_format": ".0%", "adhoc_filters": FILTERS,
       "metrics": [{"expressionType": "SIMPLE", "aggregate": "AVG", "label": "score",
                    "column": {"column_name": "score"}}]}


def test_a_radar_is_described_by_its_axes_series_value_filters_and_scale():
    d = plot_definition("radar", RADAR)
    assert d == {"kind": "radar", "axes": ["en", "nl"], "series": ["run"],
                 "value": "AVG(CASE WHEN language = 'en' THEN score END), one such per axis",
                 "filters": ["tool == StrongREJECT (Mijke)", "metric IN Jailbreak success"],
                 "axis_max": 1, "percent": True}


def test_a_bar_chart_is_described_by_its_x_axis_series_value_filters_and_scale():
    d = plot_definition("echarts_timeseries_bar", {**BAR, "y_axis_bounds": [None, 0.5]})
    assert d == {"kind": "bar", "x": "language", "series": ["metric", "run"], "value": "AVG(score)",
                 "filters": ["tool == StrongREJECT (Mijke)", "metric IN Jailbreak success"],
                 "axis_min": None, "axis_max": 0.5, "percent": True}


def test_a_radars_scale_changes_on_every_axis_and_nothing_else():
    viz, params = changed_params("radar", RADAR, {"axis_max": 0.4})
    assert viz == "radar"
    assert params["column_config"] == {"en": {"radarMetricMaxValue": 0.4}, "nl": {"radarMetricMaxValue": 0.4}}
    assert {k: v for k, v in params.items() if k != "column_config"} == {k: v for k, v in RADAR.items()
                                                                          if k != "column_config"}


def test_a_bar_charts_axis_bounds_change():
    _, params = changed_params("echarts_timeseries_bar", BAR, {"axis_max": 0.4})
    assert params["y_axis_bounds"] == [None, 0.4]
    _, params = changed_params("echarts_timeseries_bar", params, {"axis_min": 0.1})
    assert params["y_axis_bounds"] == [0.1, 0.4]


def test_a_bar_chart_becomes_a_line_chart_with_the_same_settings():
    viz, params = changed_params("echarts_timeseries_bar", BAR, {"kind": "line"})
    assert viz == "echarts_timeseries_line" and params["viz_type"] == viz
    assert params["x_axis"] == "language" and params["adhoc_filters"] == FILTERS


def test_percent_can_be_switched_off():
    _, params = changed_params("radar", RADAR, {"percent": False})
    assert params["number_format"] == "SMART_NUMBER"
    _, params = changed_params("echarts_timeseries_bar", BAR, {"percent": False})
    assert params["y_axis_format"] == "SMART_NUMBER"


@pytest.mark.parametrize("viz, params, changes", [
    ("radar", RADAR, {"kind": "bar"}),                        # a radar's axes are its query: a new chart instead
    ("radar", RADAR, {"axis_min": 0.1}),                      # a radar starts at its centre
    ("echarts_timeseries_bar", BAR, {"colour": "red"}),       # not a change it can make
    ("echarts_timeseries_bar", BAR, {"axis_max": "40%"}),     # a number, not text
    ("table", {"viz_type": "table"}, {"axis_max": 1}),        # a table has no axis
])
def test_a_change_the_plot_cannot_take_is_refused(viz, params, changes):
    with pytest.raises(ValueError):
        changed_params(viz, params, changes)


def test_the_original_settings_are_never_changed_in_place():
    before = {**RADAR, "column_config": {k: dict(v) for k, v in RADAR["column_config"].items()}}
    changed_params("radar", RADAR, {"axis_max": 0.4})
    assert RADAR == before


def test_a_change_is_a_ledger_event_with_the_settings_before_and_after():
    from aisc_ext import ledger
    assert "dashboard.assistant.changed" in ledger.ACTIONS
    fields = ledger.assistant_changed(126, slug="aisc-x", request="r1", changes={"axis_max": 0.4},
                                      before={"viz_type": "radar", "title": "A"}, after={"viz_type": "radar", "title": "A"})
    assert fields["item_type"] == "chart" and fields["item_id"] == "126"
    assert fields["details"] == {"dashboard": "aisc-x"} and fields["content"] == {"axis_max": 0.4}
    assert fields["before"]["title"] == "A" and fields["after"]["viz_type"] == "radar"


def test_a_change_from_the_assistant_is_taken_only_for_a_plot_on_the_dashboard():
    from aisc_ext.assistant.service import to_change
    plots = [{"id": 126, "title": "Jailbreak success by language"}]
    assert to_change({"chart": 126, "changes": {"axis_max": 0.4}}, plots) == (126, {"axis_max": 0.4})
    assert to_change({"chart": 5, "changes": {"axis_max": 0.4}}, plots) is None
    assert to_change({"chart": 126, "changes": {}}, plots) is None
    assert to_change("126", plots) is None


