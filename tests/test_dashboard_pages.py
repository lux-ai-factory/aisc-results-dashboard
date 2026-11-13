"""The dashboard buttons follow Superset's own navigation (branding/save-to-report/dashboard-pages.js).

Superset is a single-page app: opening a dashboard from its list or a link changes the address with history.pushState,
without loading a page. The scripts the hook adds run once, at the first page load, so each one learns from
dashboard-pages.js which dashboard is open now, and again at every change: the buttons appear on a dashboard opened
from inside Superset, disappear elsewhere, and act on the dashboard that is open, not on the first one. The scripts
run here in node, against a stand-in for the browser's window."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "branding" / "save-to-report"
HOOK = Path(__file__).resolve().parents[1] / "templates_override" / "tail_js_custom_extra.html"

_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [folder, scenario] = process.argv.slice(2);
const s = JSON.parse(scenario);
const nodes = {}, events = {}, reads = [];
function element(tag) {
  const e = {tagName: tag, style: {}, children: [], dataset: {}, set id(v) { this._id = v; nodes[v] = this; }, get id() { return this._id; },
             append(...c) { this.children.push(...c); }, appendChild(c) { this.children.push(c); return c; },
             remove() { delete nodes[this._id]; }, setAttribute() {}, addEventListener() {}, querySelector: () => null,
             querySelectorAll: () => [], textContent: '', focus() {}};
  return e;
}
const document = {body: element('body'), head: element('head'), createElement: element,
                  getElementById: (id) => nodes[id] || null, querySelector: () => null, querySelectorAll: () => [],
                  addEventListener() {}, currentScript: {src: 'http://dash/static/assets/branding/save-to-report/x.js'}};
const location = {pathname: s.start, search: ''};
const history = {pushState(st, t, url) { location.pathname = url; }, replaceState(st, t, url) { location.pathname = url; }};
const window = {location, history, document, console,
                addEventListener(n, f) { (events[n] = events[n] || []).push(f); },
                fetch: () => new Promise(() => {}), setInterval() {}, setTimeout,
                sessionStorage: {getItem(k) { reads.push(k); return null; }, setItem() {}, removeItem() {}}};
window.window = window;
const ctx = Object.assign({}, window, {window, URLSearchParams, JSON, Promise, setTimeout, decodeURIComponent,
                                       encodeURIComponent, Object, Array, Math, Error});
vm.createContext(ctx);
for (const f of s.scripts) {
  document.currentScript = {src: 'http://dash/static/assets/branding/save-to-report/' + f};
  vm.runInContext(fs.readFileSync(folder + '/' + f, 'utf8'), ctx);
}
const out = [];
const look = (label) => out.push({at: label, path: location.pathname, buttons: Object.keys(nodes).sort(),
                                  dashboard: window.aiscDashboardPages ? window.aiscDashboardPages.current() : 'no watcher',
                                  saveTo: window.aiscSaveToReport ? window.aiscSaveToReport.dashboard() : 'no seam',
                                  reads: reads.splice(0)});
look('loaded');
for (const step of s.steps) {
  if (step.push) window.history.pushState({}, '', step.push);
  if (step.back) { location.pathname = step.back; (events.popstate || []).forEach((f) => f({})); }
  look(step.push || step.back);
}
console.log(JSON.stringify(out));
"""

PAGES = "dashboard-pages.js"


def run(tmp_path, scripts, start, steps):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    r = subprocess.run(["node", str(harness), str(FOLDER), json.dumps({"scripts": scripts, "start": start, "steps": steps})],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def test_the_watcher_says_which_dashboard_is_open_after_each_navigation(tmp_path):
    seen = run(tmp_path, [PAGES], "/dashboard/list/",
               [{"push": "/superset/dashboard/a-slug/"}, {"push": "/dashboard/list/"},
                {"push": "/superset/dashboard/7/"}, {"back": "/superset/dashboard/a-slug/"}])
    assert [x["dashboard"] for x in seen] == [None, "a-slug", None, "7", "a-slug"]


def test_save_to_report_appears_on_a_dashboard_opened_from_the_list_and_leaves_with_it(tmp_path):
    seen = run(tmp_path, [PAGES, "save-to-report.js"], "/dashboard/list/",
               [{"push": "/superset/dashboard/a-slug/"}, {"push": "/dashboard/list/"}])
    assert ["aisc-save-to-report" in x["buttons"] for x in seen] == [False, True, False]


def test_save_to_report_acts_on_the_dashboard_open_now(tmp_path):
    seen = run(tmp_path, [PAGES, "save-to-report.js"], "/superset/dashboard/first/",
               [{"push": "/superset/dashboard/second/"}])
    assert [x["saveTo"] for x in seen] == ["first", "second"]
    assert seen[-1]["buttons"].count("aisc-save-to-report") == 1


def test_the_chart_assistant_follows_the_dashboard_and_its_own_conversation(tmp_path):
    seen = run(tmp_path, [PAGES, "chart-assistant.js"], "/superset/welcome/",
               [{"push": "/superset/dashboard/first/"}, {"push": "/superset/dashboard/second/"}, {"push": "/chart/list/"}])
    assert ["aisc-chart-assistant" in x["buttons"] for x in seen] == [False, True, True, False]
    assert "aisc-assistant-conversation@first" in seen[1]["reads"]
    assert "aisc-assistant-conversation@second" in seen[2]["reads"]


def test_the_hook_loads_the_watcher_first_with_its_version():
    import hashlib
    import re
    html = HOOK.read_text()
    scripts = re.findall(r"save-to-report/([a-z-]+\.js)\?v=([0-9a-f]{12})", html)
    assert scripts[0][0] == PAGES
    assert scripts[0][1] == hashlib.sha256((FOLDER / PAGES).read_bytes()).hexdigest()[:12]
