/* The chart assistant panel on a Superset dashboard. The person asks for a chart in words; the assistant answers with
   a proposal computed on MOCK DATA (invented rows with the project's structure), what it computes and its query. A
   change is asked the same way. Validate makes the chart from exactly that query on the project's real data (a change
   to a plot it made replaces that plot in place); a plot it made is removed at once when the person clearly asks. The
   model's words are always shown as text. */
(function () {
  /* the dashboard open now (its id or slug), told by dashboard-pages.js at load and at every in-app navigation */
  var dashboard = null;
  var ID = 'aisc-chart-assistant';
  var folder = document.currentScript.src.replace(/[^/]*$/, '');
  var conversation = null;
  /* What the panel has shown, kept in this tab per dashboard, so closing the panel or reloading the page keeps the
     conversation: [{who, text}] and [{proposal}] in order. */
  var STORE_KEY = null;
  var shown = [];

  function save() {
    if (!STORE_KEY) return;
    try { sessionStorage.setItem(STORE_KEY, JSON.stringify({ conversation: conversation, shown: shown })); } catch (e) {}
  }

  function restore() {
    try {
      var kept = JSON.parse(sessionStorage.getItem(STORE_KEY) || 'null');
      if (kept) { conversation = kept.conversation; shown = kept.shown || []; }
    } catch (e) {}
  }

  function library() {
    return new Promise(function (resolve, reject) {
      if (window.aiscEcharts) return resolve(window.aiscEcharts);
      var taken = window.echarts, s = document.createElement('script');
      s.src = folder + 'echarts.min.js';
      s.onload = function () { window.aiscEcharts = window.echarts; window.echarts = taken; resolve(window.aiscEcharts); };
      s.onerror = function () { reject(new Error('the drawing library did not load')); };
      document.head.appendChild(s);
    });
  }

  /* The dashboard's slug, which every write names (?dashboard=): the gateway's witness reads the project from it, so the
     write's ledger event is filed in that project's log. The address may hold the dashboard's number instead. */
  var slugOnce = null;
  function slug() {
    if (!slugOnce) {
      slugOnce = fetch('/api/v1/dashboard/' + encodeURIComponent(dashboard), { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (d) { return (d.result && d.result.slug) || ''; })
        .catch(function () { return ''; });
    }
    return slugOnce;
  }

  function witnessed(url) {
    return slug().then(function (s) { return s ? url + '?dashboard=' + encodeURIComponent(s) : url; });
  }

  function post(path, body) {
    return Promise.all([
      fetch('/api/v1/security/csrf_token/', { credentials: 'same-origin' }).then(function (r) { return r.json(); }),
      witnessed('/api/v1/aisc_assistant/conversations' + path),
    ])
      .then(function (got) {
        return fetch(got[1], {
          method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': got[0].result },
          body: JSON.stringify(body),
        });
      })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (!r.ok) { var failed = new Error(data.message || data.detail || ('Error ' + r.status)); failed.status = r.status; throw failed; }
          return data;
        });
      });
  }

  function el(tag, text, css) {
    var e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (css) e.style.cssText = css;
    return e;
  }

  /* The proposal drawn from its mock rows: one series per value of chart.series. */
  function draw(lib, box, proposal) {
    var c = proposal.chart, cols = proposal.mock.columns, rows = proposal.mock.rows;
    var at = function (name) { return cols.indexOf(name); };
    var ci = at(c.category), vi = at(c.value), si = c.series ? at(c.series) : -1;
    var cats = [], series = {};
    rows.forEach(function (r) {
      var cat = String(r[ci]), s = si >= 0 ? String(r[si]) : c.value;
      if (cats.indexOf(cat) < 0) cats.push(cat);
      (series[s] = series[s] || {})[cat] = r[vi] == null ? null : Number(r[vi]);
    });
    if (c.kind === 'table') {
      var t = el('table', null, 'border-collapse:collapse;font-size:12px');
      [cols].concat(rows.slice(0, 50)).forEach(function (r, i) {
        var tr = el('tr');
        r.forEach(function (v) { tr.append(el(i ? 'td' : 'th', v == null ? '' : String(v), 'border:1px solid #ccc;padding:2px 6px')); });
        t.append(tr);
      });
      box.append(t);
      return;
    }
    var holder = el('div', null, 'width:100%;height:340px');
    box.append(holder);
    var chart = lib.init(holder, null, { renderer: 'svg' });
    var names = Object.keys(series);
    var option = { animation: false, legend: { bottom: 0, data: names, textStyle: { color: '#333' } }, tooltip: {} };
    if (c.kind === 'radar') {
      var max = 0;
      names.forEach(function (n) { cats.forEach(function (k) { max = Math.max(max, series[n][k] || 0); }); });
      option.radar = { indicator: cats.map(function (k) { return { name: k, max: max || 1 }; }), radius: '62%',
                       axisName: { color: '#333' } };
      option.series = [{ type: 'radar', data: names.map(function (n) {
        return { name: n, value: cats.map(function (k) { return series[n][k]; }) }; }) }];
    } else {
      option.xAxis = { type: 'category', data: cats, axisLabel: { color: '#333', rotate: 30 } };
      option.yAxis = { type: 'value', axisLabel: { color: '#333' } };
      option.grid = { bottom: 90 };
      option.series = names.map(function (n) {
        return { name: n, type: c.kind === 'line' ? 'line' : 'bar', data: cats.map(function (k) { return series[n][k]; }) };
      });
    }
    chart.setOption(option);
  }

  function panel() {
    var open = document.getElementById(ID + '-panel');
    if (open) { open.style.display = open.style.display === 'none' ? 'flex' : 'none'; return; }
    var box = el('div', null, 'position:fixed;top:56px;right:16px;bottom:72px;width:420px;max-width:calc(100% - 32px);'
      + 'z-index:100001;background:#fff;border:1px solid #ccc;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.2);'
      + 'display:flex;flex-direction:column;font-size:13px');
    box.id = ID + '-panel';
    var head = el('div', null, 'display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #ddd');
    head.append(el('strong', 'Chart assistant'));
    var close = el('button', 'Close'); close.onclick = function () { box.style.display = 'none'; };
    var fresh = el('button', 'New conversation', 'margin-right:8px');
    fresh.onclick = function () {
      conversation = null; shown = []; save();
      Array.prototype.slice.call(log.children, 1).forEach(function (n) { n.remove(); });
    };
    var actions = el('span'); actions.append(fresh, close);
    head.append(actions);
    var log = el('div', null, 'flex:1;overflow:auto;padding:12px 16px');
    log.append(el('p', 'Ask for a chart in words. It is first built on MOCK DATA: invented rows with the structure of '
      + 'this project. Validate it to make the same chart on the real data.', 'color:#555'));
    var form = el('form', null, 'display:flex;gap:8px;padding:12px 16px;border-top:1px solid #ddd');
    var input = el('textarea', null, 'flex:1;padding:6px;font-size:13px'); input.rows = 2;
    input.placeholder = 'e.g. radar of the share treated like the baseline by category, one polygon per model';
    var send = el('button', 'Send');
    form.append(input, send);
    box.append(head, log, form);
    document.body.append(box);

    function say(who, text, css, replay) {
      var p = el('p', null, 'margin:8px 0;' + (css || ''));
      p.append(el('strong', who + ': '), document.createTextNode(text));
      log.append(p); log.scrollTop = log.scrollHeight;
      if (!replay && !css) { shown.push({ who: who, text: text }); save(); }
      return p;
    }

    function show(proposal, replay) {
      if (!replay) { shown.push({ proposal: proposal }); save(); }
      var card = el('div', null, 'border:1px solid #ccc;border-radius:4px;padding:10px;margin:8px 0');
      card.append(el('div', 'MOCK DATA: not your results', 'display:inline-block;background:#fff3cd;color:#664d03;padding:2px 8px;border-radius:3px;font-weight:600'));
      card.append(el('h4', proposal.chart.title, 'margin:8px 0 4px'));
      card.append(el('p', proposal.description, 'margin:4px 0'));
      var sql = el('details'); sql.append(el('summary', 'Query')); sql.append(el('pre', proposal.sql, 'white-space:pre-wrap;font-size:12px;background:#f6f6f6;padding:6px'));
      var plot = el('div');
      card.append(plot, sql);
      if (proposal.replaces) card.append(el('p', 'Replaces the plot "' + proposal.replaces.title + '" once validated.', 'margin:4px 0;font-weight:600'));
      var validate = el('button', proposal.replaces ? 'Validate: replace it on the real data' : 'Validate: make it on the real data');
      var said = el('span', null, 'margin-left:10px');
      validate.onclick = function () {
        validate.disabled = true; said.textContent = 'Making the chart…';
        post('/' + conversation + '/validate', { fingerprint: proposal.fingerprint, proposal: proposal.id }).then(function () {
          said.textContent = proposal.replaces ? 'Replaced on the real data. Reloading…'
            : 'Made on the real data, under "Assistant charts". Reloading…';
          setTimeout(function () { location.reload(); }, 800);
        }).catch(function (e) { said.textContent = 'Not made: ' + e.message; validate.disabled = false; });
      };
      card.append(validate, said);
      log.append(card);
      library().then(function (lib) { draw(lib, plot, proposal); log.scrollTop = log.scrollHeight; })
        .catch(function (e) { plot.append(el('p', 'The preview could not be drawn: ' + e.message)); });
    }

    shown.forEach(function (item) {
      if (item.proposal) show(item.proposal, true); else say(item.who, item.text, '', true);
    });

    form.onsubmit = function (ev) {
      ev.preventDefault();
      var text = input.value.trim();
      if (!text) return;
      input.value = ''; send.disabled = true;
      say('You', text);
      var waiting = say('Assistant', 'thinking…', 'color:#777');
      function begin() {
        return post('', { dashboard_id: dashboard }).then(function (d) { conversation = d.conversation; save(); });
      }
      function ask() { return post('/' + conversation + '/messages', { text: text }); }
      var ready = conversation ? Promise.resolve() : begin();
      ready.then(ask)
        .catch(function (e) {
          // the assistant restarted and no longer holds this conversation: start it again, once
          if (e.status === 404) { conversation = null; return begin().then(ask); }
          throw e;
        })
        .then(function (d) {
          waiting.remove();
          if (d.changed) {
            say('Assistant', 'Changed "' + d.changed.title + '". Reloading…', 'color:#555');
            setTimeout(function () { location.reload(); }, 800);
          } else if (d.removed) {
            var names = [].concat(d.removed).map(function (r) { return '"' + r.title + '"'; }).join(', ');
            say('Assistant', 'Removed ' + names + ' from the dashboard. Reloading…', 'color:#555');
            setTimeout(function () { location.reload(); }, 800);
          } else if (d.proposal) show(d.proposal); else say('Assistant', d.question || '');
        })
        .catch(function (e) { waiting.remove(); say('Assistant', 'Could not answer: ' + e.message, 'color:#a00'); })
        .finally(function () { send.disabled = false; });
    };
    input.focus();
  }

  function add() {
    if (document.getElementById(ID)) return;
    var b = el('button', 'Chart assistant', 'position:fixed;right:170px;bottom:24px;z-index:99999;padding:8px 14px;'
      + 'background:#fff;color:#000FDF;border:1px solid #000FDF;border-radius:4px;cursor:pointer;font-size:14px');
    b.id = ID; b.type = 'button'; b.onclick = panel;
    document.body.append(b);
  }
  function remove() {
    [ID, ID + '-panel'].forEach(function (id) { var n = document.getElementById(id); if (n) n.remove(); });
  }
  /* the button and the panel belong to the dashboard open now: on another dashboard, its own conversation comes back */
  function follow(open) {
    if (open === dashboard) return;
    remove();
    dashboard = open;
    slugOnce = null;
    conversation = null; shown = [];
    STORE_KEY = open ? 'aisc-assistant-conversation@' + open : null;
    if (!open) return;
    restore();
    add();
  }
  function start() { window.aiscDashboardPages.watch(follow); }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
