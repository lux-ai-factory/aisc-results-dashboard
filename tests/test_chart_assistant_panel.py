"""The chart assistant panel (branding/save-to-report/chart-assistant.js), run in node against a stand-in for the
page: the person writes, the panel shows what the assistant answers, and the buttons it shows post what they should.
A change or a removal is only asked; Confirm makes it and offers Undo; the reload keeps the tab and the scroll."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "branding" / "save-to-report" / "chart-assistant.js"

_HARNESS = r"""
const fs = require('fs');
const [scriptPath, planJson] = process.argv.slice(2);
const plan = JSON.parse(planJson);
const posts = [], said = [];
let reloads = 0;
const store = Object.assign({}, plan.storage || {});
const byId = {};
function node(tag) {
  const e = {tagName: tag.toUpperCase(), style: {}, children: [], value: '', disabled: false, _text: '', rows: 0,
    set id(v) { this._id = v; byId[v] = this; }, get id() { return this._id; },
    set textContent(v) { this._text = String(v); this.children = []; }, get textContent() {
      return this._text + this.children.map((c) => c.textContent).join(''); },
    append(...kids) { kids.forEach((k) => { k.parent = this; this.children.push(k); }); },
    appendChild(k) { this.append(k); return k; },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); if (this._id) delete byId[this._id]; },
    focus() {}, setAttribute() {}, addEventListener() {},
    get scrollHeight() { return 0; }, set scrollTop(v) {},
  };
  return e;
}
const tabs = (plan.tabs || []).map((t) => ({textContent: t, selected: false, clicked: 0,
  getAttribute(name) { return name === 'aria-selected' ? String(this.selected) : null; },
  click() { this.clicked++; this.selected = true; }}));
if (tabs.length) tabs[plan.selectedTab || 0].selected = true;
const body = node('body');
global.document = {
  body, head: node('head'), currentScript: {src: 'http://x/static/assets/branding/save-to-report/chart-assistant.js'},
  createElement: node, createTextNode: (t) => ({textContent: String(t), children: []}),
  getElementById: (id) => byId[id] || null,
  querySelectorAll: (sel) => sel.indexOf('role="tab"') >= 0 ? tabs : [],
  addEventListener() {},
};
global.window = {scrollY: plan.scrollY || 0, scrolled: null, scrollTo(x, y) { this.scrolled = y; },
                 aiscDashboardPages: {watch: (f) => f('5')}};
global.location = {pathname: '/superset/dashboard/5/', reload() { reloads++; }};
global.sessionStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }};
global.setTimeout = (f) => { f(); return 0; };
const answers = plan.answers;
global.fetch = (url, opts) => {
  const ok = (data) => Promise.resolve({ok: true, status: 200, json: () => Promise.resolve(data)});
  if (url.indexOf('/csrf_token/') >= 0) return ok({result: 'csrf'});
  if (url.indexOf('/api/v1/dashboard/') === 0) return ok({result: {slug: 'aisc-x-p'}});
  const path = url.replace(/\?.*$/, '').replace('/api/v1/aisc_assistant/conversations', '');
  posts.push({path, body: JSON.parse(opts.body)});
  const kind = path === '' ? 'start' : path.split('/').pop();
  const answer = (answers[kind] || []).shift() || {};
  return Promise.resolve({ok: !answer.status, status: answer.status || 200, json: () => Promise.resolve(answer.body || answer)});
};
const flush = () => new Promise((r) => setImmediate(r)).then(() => new Promise((r) => setImmediate(r)))
  .then(() => new Promise((r) => setImmediate(r)));
function texts(n) { return n.children.map((c) => c.textContent); }
function find(n, pred) {
  if (pred(n)) return n;
  for (const c of n.children || []) { const f = find(c, pred); if (f) return f; }
  return null;
}
function button(label) { return find(body, (n) => n.tagName === 'BUTTON' && n.textContent === label); }
(async () => {
  eval(fs.readFileSync(scriptPath, 'utf8'));
  await flush();
  const out = {steps: []};
  for (const step of plan.steps) {
    if (step.open) byId['aisc-chart-assistant'].onclick();
    if (step.say != null) {
      const panel = byId['aisc-chart-assistant-panel'];
      const form = find(panel, (n) => n.tagName === 'FORM');
      find(form, (n) => n.tagName === 'TEXTAREA').value = step.say;
      form.onsubmit({preventDefault() {}});
    }
    if (step.click) { const b = button(step.click); if (!b) { out.steps.push({missing: step.click}); continue; } b.onclick(); }
    await flush();
    out.steps.push({buttons: (function all(n, acc) { if (n.tagName === 'BUTTON') acc.push(n.textContent);
      (n.children || []).forEach((c) => all(c, acc)); return acc; })(body, []),
      log: byId['aisc-chart-assistant-panel'] ? texts(find(byId['aisc-chart-assistant-panel'],
        (n) => n.style.cssText && n.style.cssText.indexOf('overflow:auto') >= 0)) : [],
      tables: (function count(n) { return (n.tagName === 'TABLE' ? 1 : 0)
        + (n.children || []).reduce((a, c) => a + count(c), 0); })(body)});
  }
  out.posts = posts; out.reloads = reloads; out.store = store;
  out.scrolled = window.scrolled; out.tabsClicked = tabs.map((t) => t.clicked);
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e.stack); process.exit(1); });
"""


def run(tmp_path, plan):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    harness = tmp_path / "harness.js"
    harness.write_text(_HARNESS)
    done = subprocess.run(["node", str(harness), str(SCRIPT), json.dumps(plan)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


CONFIRM = {"confirm": {"text": 'Change "Bars": title to "New"?', "token": "T1"}}


def test_a_change_is_asked_first_and_cancel_changes_nothing(tmp_path):
    out = run(tmp_path, {"answers": {"start": [{"conversation": "c1"}], "messages": [CONFIRM]},
                         "steps": [{"open": True, "say": "rename it"}, {"click": "Cancel"}]})
    assert {"Confirm", "Cancel"} <= set(out["steps"][0]["buttons"])
    assert any('Change "Bars": title to "New"?' in line for line in out["steps"][0]["log"])
    assert [p["path"] for p in out["posts"]] == ["", "/c1/messages"]
    assert "Nothing was changed." in " ".join(out["steps"][1]["log"]) and out["reloads"] == 0
    assert "Confirm" not in out["steps"][1]["buttons"]


def test_confirm_posts_the_token_then_offers_undo_which_posts_the_undo_token(tmp_path):
    out = run(tmp_path, {"answers": {"start": [{"conversation": "c1"}], "messages": [CONFIRM],
                                     "confirm": [{"changed": {"chart": 7, "title": "New"}, "undo": "U1"}],
                                     "undo": [{"undone": "change"}]},
                         "steps": [{"open": True, "say": "rename it"}, {"click": "Confirm"}, {"click": "Undo"}]})
    posts = [(p["path"], p["body"]) for p in out["posts"]]
    assert ("/c1/confirm", {"token": "T1"}) in posts and ("/c1/undo", {"token": "U1"}) in posts
    assert "Undo" in out["steps"][1]["buttons"] and "Undo" not in out["steps"][2]["buttons"]
    assert out["reloads"] == 2


def test_the_undo_button_is_still_there_after_the_reload(tmp_path):
    first = run(tmp_path, {"answers": {"start": [{"conversation": "c1"}], "messages": [CONFIRM],
                                       "confirm": [{"changed": {"chart": 7, "title": "New"}, "undo": "U1"}]},
                           "steps": [{"open": True, "say": "rename it"}, {"click": "Confirm"}]})
    after = run(tmp_path, {"storage": first["store"], "answers": {"undo": [{"undone": "change"}]},
                           "steps": [{"open": True}, {"click": "Undo"}]})
    assert "Undo" in after["steps"][0]["buttons"]
    assert ("/c1/undo", {"token": "U1"}) in [(p["path"], p["body"]) for p in after["posts"]]


def test_a_refused_confirmation_is_said_and_nothing_reloads(tmp_path):
    out = run(tmp_path, {"answers": {"start": [{"conversation": "c1"}], "messages": [CONFIRM],
                                     "confirm": [{"status": 409, "body": {"message": "This took too long; ask again."}}]},
                         "steps": [{"open": True, "say": "rename it"}, {"click": "Confirm"}]})
    assert "This took too long; ask again." in " ".join(out["steps"][1]["log"]) and out["reloads"] == 0


def test_the_reload_comes_back_on_the_same_tab_at_the_same_height(tmp_path):
    first = run(tmp_path, {"tabs": ["Overview", "Jailbreaks"], "selectedTab": 1, "scrollY": 640,
                           "answers": {"start": [{"conversation": "c1"}], "messages": [CONFIRM],
                                       "confirm": [{"changed": {"chart": 7, "title": "New"}, "undo": "U1"}]},
                           "steps": [{"open": True, "say": "rename it"}, {"click": "Confirm"}]})
    after = run(tmp_path, {"storage": first["store"], "tabs": ["Overview", "Jailbreaks"], "selectedTab": 0,
                           "answers": {}, "steps": [{"open": False}]})
    assert after["tabsClicked"] == [0, 1] and after["scrolled"] == 640


PROPOSAL = {"proposal": {"id": 1, "sql": "SELECT 1", "chart": {"kind": "bar", "title": "Share by category",
                                                               "category": "category", "value": "value"},
                         "description": "the share", "fingerprint": "F1", "mock": {"columns": [], "rows": []},
                         "mock_data": True}}
REAL = {"chart": 9, "fingerprint": "F1", "sentence": "Highest: instructions (0.87). Lowest: out_of_scope (0.013).",
        "result": {"columns": ["category", "value"], "rows": [["instructions", 0.87], ["out_of_scope", 0.013]],
                   "more": True}}


def validated(tmp_path, answer):
    return run(tmp_path, {"answers": {"start": [{"conversation": "c1"}], "messages": [PROPOSAL], "validate": [answer]},
                          "steps": [{"open": True, "say": "share by category"},
                                    {"click": "Validate: make it on the real data"}]})


def test_after_validation_the_card_shows_the_real_result_and_its_sentence_and_keeps_them_after_the_reload(tmp_path):
    first = validated(tmp_path, REAL)
    log = " ".join(first["steps"][1]["log"])
    assert "On your data" in log and REAL["sentence"] in log and "out_of_scope" in log and "and more" in log
    assert first["steps"][1]["tables"] == 1 and first["reloads"] == 1
    after = run(tmp_path, {"storage": first["store"], "answers": {}, "steps": [{"open": True}]})
    kept = " ".join(after["steps"][0]["log"])
    assert "On your data" in kept and REAL["sentence"] in kept and after["steps"][0]["tables"] == 1
    assert "Validate: make it on the real data" not in after["steps"][0]["buttons"]      # made once, not twice


def test_a_result_with_no_rows_says_so_and_shows_no_table(tmp_path):
    out = validated(tmp_path, {"chart": 9, "fingerprint": "F1", "sentence": "The query returns no rows on your data.",
                               "result": {"columns": ["category", "value"], "rows": [], "more": False}})
    assert "The query returns no rows on your data." in " ".join(out["steps"][1]["log"])
    assert out["steps"][1]["tables"] == 0


def test_values_that_could_not_be_read_are_said_without_a_table(tmp_path):
    out = validated(tmp_path, {"chart": 9, "fingerprint": "F1",
                               "sentence": "The chart was made; its values could not be read here."})
    assert "The chart was made; its values could not be read here." in " ".join(out["steps"][1]["log"])
    assert out["steps"][1]["tables"] == 0
