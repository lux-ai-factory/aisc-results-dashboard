"""What the Save to report button says and offers (branding/save-to-report/save-to-report.js).

A click sends the ticked plots one after another, and each one the route accepts is kept: when a later plot is
refused, the panel must not say "Not saved" for plots that are already in the report.

The scripts run here in node, against a stand-in for the browser: two plots on the tab, a drawing library that
returns a fixed SVG, and a fetch that answers as the dashboard's routes do."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "branding" / "save-to-report"

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [folder, scenario] = process.argv.slice(2);
const s = JSON.parse(scenario);
const nodes = {}, posts = [], gets = [];
function element(tag) {
  const e = {tagName: tag, style: {}, children: [], dataset: {}, disabled: false, textContent: '', value: '',
             set id(v) { this._id = v; nodes[v] = this; }, get id() { return this._id; },
             append(...c) { this.children.push(...c); }, appendChild(c) { this.children.push(c); return c; },
             remove() { delete nodes[this._id]; }, setAttribute() {}, getAttribute() { return null; },
             addEventListener() {}, querySelector: () => null, querySelectorAll: () => [], focus() {}};
  return e;
}
function plotElement(name, chartId) {
  const slice = {querySelector: () => ({textContent: name}), getAttribute: () => String(chartId)};
  const chart = {getOption: () => ({}), setOption() {}};
  const dom = {offsetParent: {}, closest: () => slice};
  dom['__reactFiber$x'] = {memoizedState: {memoizedState: {current: chart}, next: null}, return: null};
  return dom;
}
const plots = s.plots.map((name, i) => plotElement(name, i + 1));
const document = {body: element('body'), head: element('head'), createElement: element,
                  getElementById: (id) => nodes[id] || null, querySelector: () => null,
                  querySelectorAll: (sel) => sel === '[_echarts_instance_]' ? plots : [],
                  addEventListener() {}, currentScript: {src: 'http://dash/static/assets/branding/save-to-report/x.js'}};
const location = {pathname: s.start, search: ''};
const history = {pushState(st, t, url) { location.pathname = url; }, replaceState(st, t, url) { location.pathname = url; }};
const answer = (status, body) => Promise.resolve({ok: status < 400, status, json: () => Promise.resolve(body)});
function fetch(url, init) {
  const method = (init && init.method) || 'GET';
  if (url.startsWith('/api/v1/aisc_report_export/')) {
    if (method === 'POST') {
      const body = JSON.parse(init.body);
      posts.push(body.chart);
      const refusal = (s.refuse || {})[body.chart];
      return refusal ? answer(refusal.status, {message: refusal.message}) : answer(201, {result: {id: posts.length}});
    }
    gets.push(url);
    return s.viewer ? answer(200, {result: {may_export: false}}) : answer(200, {result: {may_export: true}});
  }
  if (url === '/api/v1/security/csrf_token/') return answer(200, {result: 'fake-csrf'});
  if (url.startsWith('/api/v1/me')) {
    return answer(200, {result: {username: 'someone', roles: s.viewer ? {Viewer: []} : {Editor: []}}});
  }
  if (url.startsWith('/api/v1/dashboard/')) {
    return answer(200, {result: {id: 1, slug: 'a-slug', json_metadata: '{}', may_export: !s.viewer}});
  }
  return answer(404, {});
}
const lib = {init: () => ({setOption() {}, renderToSVGString: () => '<svg xmlns="http://www.w3.org/2000/svg"/>',
                           dispose() {}})};
const window = {location, history, document, console, fetch, aiscEcharts: lib,
                addEventListener() {}, setInterval() {}, setTimeout,
                sessionStorage: {getItem() { return null; }, setItem() {}, removeItem() {}}};
window.window = window;
const ctx = Object.assign({}, window, {window, URLSearchParams, JSON, Promise, setTimeout, decodeURIComponent,
                                       encodeURIComponent, Object, Array, Math, Error, Date, btoa, unescape});
vm.createContext(ctx);
for (const f of ['dashboard-pages.js', 'save-to-report.js']) {
  document.currentScript = {src: 'http://dash/static/assets/branding/save-to-report/' + f};
  vm.runInContext(fs.readFileSync(folder + '/' + f, 'utf8'), ctx);
}
const wait = () => new Promise((r) => setTimeout(r, 80));
(async () => {
  await wait();
  const button = nodes['aisc-save-to-report'];
  const out = {button: button ? {disabled: !!button.disabled, text: button.textContent, title: button.title || ''} : null};
  if (s.click && button) {
    button.onclick();
    await wait();
    const save = nodes['aisc-save-to-report-save'];
    if (save) { save.onclick(); await wait(); await wait(); }
    out.said = nodes['aisc-save-to-report-said'] ? nodes['aisc-save-to-report-said'].textContent : null;
  }
  out.posts = posts;
  console.log(JSON.stringify(out));
})();
"""


def run(tmp_path, scenario):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    scenario = {"start": "/superset/dashboard/a-slug/", **scenario}
    r = subprocess.run(["node", str(harness), str(FOLDER), json.dumps(scenario)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def test_a_refused_later_plot_does_not_hide_that_the_earlier_ones_were_saved(tmp_path):
    seen = run(tmp_path, {"plots": ["Pass rate", "Calls per day"], "click": True,
                          "refuse": {"Calls per day": {"status": 400, "message": "the plot is too large"}}})
    assert seen["posts"] == ["Pass rate", "Calls per day"], seen
    said = seen["said"] or ""
    # one plot is in the report now: the panel says so, and names the plot that was refused and why
    assert not said.startswith("Not saved"), f"the panel says nothing was saved although one plot was: {said!r}"
    assert "1 of 2" in said and "Calls per day" in said and "too large" in said, said


def test_every_plot_saved_says_how_many(tmp_path):
    seen = run(tmp_path, {"plots": ["Pass rate", "Calls per day"], "click": True})
    assert seen["said"].startswith("Saved 2 plot(s)"), seen
