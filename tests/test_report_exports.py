"""What Save to report stores: one plot as a vector file, its filter tags as text, and a comment."""
import hashlib

import pytest

from aisc_ext.report_exports.service import MAX_BYTES, MAX_COMMENT, placed_chart_names, read_plot

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><path d="M0 0L1 1"/><text x="1" y="1">Age</text></svg>'


def body(**over):
    return {"svg": SVG, "chart": "By category", "tab": "Against the baseline",
            "tags": ["Model: OpenAI back-end", "Language: EN"], "comment": " Looks right. ", **over}


def test_a_plot_is_taken_with_its_name_tab_tags_comment_and_fingerprint():
    e = read_plot(body())
    assert e["svg"] == SVG.encode() and e["chart"] == "By category" and e["tab"] == "Against the baseline"
    assert e["tags"] == ["Model: OpenAI back-end", "Language: EN"] and e["comment"] == "Looks right."
    assert e["sha256"] == hashlib.sha256(SVG.encode()).hexdigest() and e["size"] == len(SVG)


def test_tags_and_comment_may_be_left_out():
    e = read_plot({"svg": SVG, "chart": "x"})
    assert e["tags"] == [] and e["comment"] == "" and e["tab"] == ""


def test_a_plot_needs_a_name():
    with pytest.raises(ValueError, match="name"):
        read_plot(body(chart=" "))


@pytest.mark.parametrize("svg", [None, "", "not xml", "<html></html>", "<svg", "<svg><path></svg>"])
def test_anything_but_an_svg_is_refused(svg):
    with pytest.raises(ValueError, match="SVG"):
        read_plot(body(svg=svg))


@pytest.mark.parametrize("svg", [
    '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><p>x</p></foreignObject></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink"><image x:href="http://evil/a.png"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>',
    '<!DOCTYPE svg [<!ENTITY a "b">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><path style="fill:url(http://evil/x)"/></svg>',
])
def test_an_svg_that_could_run_or_fetch_something_is_refused(svg):
    with pytest.raises(ValueError, match="SVG"):
        read_plot(body(svg=svg))


@pytest.mark.parametrize("svg", [
    '<svg xmlns="http://www.w3.org/2000/svg"><a><set attributeName="href" to="javascript:alert(1)"/>'
    '<text>x</text></a></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><a><animate attributeName="href" values="javascript:alert(1)"/>'
    '<text>x</text></a></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"><animateMotion dur="1s" path="M0 0L1 1"/></path></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"><animateTransform attributeName="transform"/></path></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><path style="fill:\\75 rl(http://evil/x)"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg"><style>path{fill:\\75 rl(http://evil/x)}</style></svg>',
])
def test_an_svg_animation_or_a_css_escape_is_refused(svg):
    """An animation can set a link to javascript:, and a CSS escape spells url( so the url check cannot see it."""
    with pytest.raises(ValueError, match="SVG"):
        read_plot(body(svg=svg))


def test_the_style_echarts_writes_is_taken():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg"><style>@keyframes zr-key {0%{opacity:1}}'
           ' path{stroke-linejoin:round}</style><path d="M0 0"/></svg>')
    assert read_plot(body(svg=svg))["svg"] == svg.encode()


@pytest.mark.parametrize("style", ["@import url(http://evil/x.css);", "path{fill:url(http://evil/x)}",
                                   "path{background:url('//evil/x')}", "@import 'x.css';"])
def test_a_style_that_could_fetch_something_is_refused(style):
    with pytest.raises(ValueError, match="SVG"):
        read_plot(body(svg=f'<svg xmlns="http://www.w3.org/2000/svg"><style>{style}</style></svg>'))


def test_too_large_a_plot_is_refused():
    with pytest.raises(ValueError, match="too large"):
        read_plot(body(svg='<svg xmlns="http://www.w3.org/2000/svg">' + " " * MAX_BYTES + "</svg>"))


def test_too_long_a_comment_is_refused():
    with pytest.raises(ValueError, match="comment"):
        read_plot(body(comment="x" * (MAX_COMMENT + 1)))


def test_tags_must_be_a_short_list_of_text():
    with pytest.raises(ValueError, match="tags"):
        read_plot(body(tags="Model: x"))
    with pytest.raises(ValueError, match="tags"):
        read_plot(body(tags=[{"a": 1}]))
    assert len(read_plot(body(tags=["  a  ", "", "b"]))["tags"]) == 2


def test_the_names_a_saved_plot_may_take_are_those_of_the_charts_placed_on_the_dashboard():
    """The chart's own name, or the name the dashboard gives it; a chart linked but not placed does not count."""
    position = {"ROOT_ID": {"type": "ROOT", "children": ["GRID_ID"]},
                "CHART-1": {"type": "CHART", "meta": {"chartId": 1}},
                "CHART-2": {"type": "CHART", "meta": {"chartId": 2, "sliceNameOverride": "Drift, renamed here"}}}
    names = placed_chart_names(position, {1: "Pass rate by model", 2: "Drift by feature", 3: "Not placed"})
    assert names == {"Pass rate by model", "Drift, renamed here", "Drift by feature"}


def test_the_rows_the_plot_draws_are_kept_when_sent():
    """The number of rows the chart's query gave when the plot was saved; older pages send none."""
    assert read_plot(body())["rows"] is None
    assert read_plot(body(rows=None))["rows"] is None
    assert read_plot(body(rows=0))["rows"] == 0
    assert read_plot(body(rows=2))["rows"] == 2


@pytest.mark.parametrize("rows", [-1, 1.5, "3", True, [2], {"n": 2}])
def test_rows_must_be_a_non_negative_whole_number(rows):
    with pytest.raises(ValueError, match="rows"):
        read_plot(body(rows=rows))


def test_the_rows_column_is_added_to_a_table_made_before_it_existed():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert "rows = Column(Integer, nullable=True)" in (root / "aisc_ext/report_exports/model.py").read_text()
    assert "ALTER TABLE aisc_report_plot ADD COLUMN IF NOT EXISTS rows INTEGER" in (root / "superset_config.py").read_text()
