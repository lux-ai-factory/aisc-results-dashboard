"""The number of rows each chart draws, read from Superset's own chart-data answers (branding/save-to-report/row-counts.js).

A dashboard asks POST /api/v1/chart/data?form_data={"slice_id": N} for each chart, and the answer's result[].rowcount is
the number of rows the chart's query gave after aggregation. The script watches those answers without changing them and
keeps the latest count per chart, so a new filter value gives a new count. The script is run here in node, as the
browser would."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "branding" / "save-to-report" / "row-counts.js"

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [file, scenario] = process.argv.slice(2);
const s = JSON.parse(scenario);
function answer(a) {
  const text = typeof a.body === 'string' ? a.body : JSON.stringify(a.body);
  const make = () => ({ok: a.status >= 200 && a.status < 300, status: a.status, marker: a.marker,
                       json: () => Promise.resolve().then(() => JSON.parse(text)), clone: make});
  return make();
}
let i = 0;
const window = {location: {pathname: s.pathname || '/superset/dashboard/x/', search: ''},
                fetch: () => Promise.resolve(answer(s.calls[i++].answer))};
const ctx = {window, URLSearchParams, JSON, Promise, setTimeout, console, decodeURIComponent};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(file, 'utf8'), ctx);
const api = window.aiscRowCounts;
const markers = [];
s.calls.reduce((done, c) => done.then(() => window.fetch(c.url, c.init).then((r) => { markers.push(r.marker); })),
               Promise.resolve())
  .then(() => new Promise((r) => setTimeout(r, 10)))
  .then(() => {
    const out = {markers, counts: {}, labels: (s.labels || []).map((n) => api.label(n))};
    (s.ask || []).forEach((id) => { out.counts[id] = api.of(id) === undefined ? 'none' : api.of(id); });
    console.log(JSON.stringify(out));
  });
"""


def run(tmp_path, **scenario):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    assert SCRIPT.is_file(), "missing feature: branding/save-to-report/row-counts.js"
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    r = subprocess.run(["node", str(harness), str(SCRIPT), json.dumps({"calls": [], **scenario})],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def chart_data(slice_id, rowcounts, status=200, in_url=True, marker="m"):
    url = "/api/v1/chart/data"
    if in_url:
        url += "?form_data=" + json.dumps({"slice_id": slice_id}).replace('"', "%22").replace(" ", "") + "&dashboard_id=5"
    body = {"datasource": {"id": 7, "type": "table"}, "queries": [{}], "form_data": {"slice_id": slice_id}}
    return {"url": url, "init": {"method": "POST", "body": json.dumps(body)},
            "answer": {"status": status, "marker": marker, "body": {"result": [{"rowcount": n} for n in rowcounts]}}}


def test_the_count_of_a_chart_is_the_rowcount_of_its_answer(tmp_path):
    out = run(tmp_path, calls=[chart_data(50, [2]), chart_data(49, [7])], ask=[50, 49, 48])
    assert out["counts"] == {"50": 2, "49": 7, "48": "none"}


def test_the_page_receives_the_very_answer_superset_gave(tmp_path):
    out = run(tmp_path, calls=[chart_data(50, [2], marker="first"), chart_data(49, [3], marker="second")])
    assert out["markers"] == ["first", "second"]


def test_a_new_answer_for_the_same_chart_replaces_its_count(tmp_path):
    """A filter changed: the chart asks again and its count follows."""
    out = run(tmp_path, calls=[chart_data(50, [2]), chart_data(50, [1])], ask=[50])
    assert out["counts"] == {"50": 1}


def test_the_chart_is_read_from_the_body_when_the_address_does_not_name_it(tmp_path):
    out = run(tmp_path, calls=[chart_data(12, [4], in_url=False)], ask=[12])
    assert out["counts"] == {"12": 4}


def test_a_chart_with_several_queries_counts_the_rows_of_all(tmp_path):
    out = run(tmp_path, calls=[chart_data(8, [3, 5])], ask=[8])
    assert out["counts"] == {"8": 8}


def test_a_filters_own_query_and_a_refused_answer_give_no_count(tmp_path):
    native_filter = {"url": "/api/v1/chart/data", "init": {"method": "POST", "body": json.dumps({"queries": [{}],
                     "form_data": {"groupby": ["model"]}})}, "answer": {"status": 200, "body": {"result": [{"rowcount": 2}]}}}
    out = run(tmp_path, calls=[native_filter, chart_data(9, [3], status=400)], ask=[9])
    assert out["counts"] == {"9": "none"}


def test_an_answer_that_is_not_json_or_another_address_is_left_alone(tmp_path):
    other = {"url": "/api/v1/dashboard/5", "init": {}, "answer": {"status": 200, "marker": "dash", "body": {"result": {}}}}
    broken = chart_data(3, [1], marker="broken")
    broken["answer"]["body"] = "<html>not json</html>"
    out = run(tmp_path, calls=[other, broken], ask=[3])
    assert out["markers"] == ["dash", "broken"] and out["counts"] == {"3": "none"}


def test_the_count_reads_n_rows_and_1_row_for_one(tmp_path):
    assert run(tmp_path, labels=[0, 1, 2, 1234])["labels"] == ["0 rows", "1 row", "2 rows", "1234 rows"]


def test_the_count_is_shown_under_each_chart_as_a_muted_line():
    text = SCRIPT.read_text()
    assert "data-test-chart-id" in text and ".chart-slice" in text
    assert "innerHTML" not in text                         # the count is set as text


def test_outside_a_dashboard_nothing_is_wrapped(tmp_path):
    out = run(tmp_path, pathname="/superset/welcome/", calls=[chart_data(50, [2])], ask=[50])
    assert out["counts"] == {"50": "none"}
