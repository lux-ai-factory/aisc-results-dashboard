/* The Save to report button on a Superset dashboard. Each plot on the open tab becomes one vector file: Superset draws
   its charts with ECharts on a canvas, so the live chart's own settings are drawn again as an SVG, by ECharts. Its
   filters are read from the filter bar as text, and the rows the chart draws from row-counts.js. The person picks what to
   keep and can add a comment per plot. */
(function () {
  var m = location.pathname.match(/^\/superset\/dashboard\/([^/]+)/);
  if (!m) return;
  var dashboard = decodeURIComponent(m[1]);
  var ID = 'aisc-save-to-report';
  var folder = document.currentScript.src.replace(/[^/]*$/, '');

  function library() {
    return new Promise(function (resolve, reject) {
      if (window.aiscEcharts) return resolve(window.aiscEcharts);
      var taken = window.echarts;
      var s = document.createElement('script');
      s.src = folder + 'echarts.min.js';
      s.onload = function () { window.aiscEcharts = window.echarts; window.echarts = taken; resolve(window.aiscEcharts); };
      s.onerror = function () { reject(new Error('the drawing library did not load')); };
      document.head.appendChild(s);
    });
  }

  /* The chart object behind a chart's element: React keeps it in the component that made it. */
  function chartOf(dom) {
    var key = Object.keys(dom).filter(function (k) {
      return k.indexOf('__reactFiber$') === 0 || k.indexOf('__reactInternalInstance$') === 0;
    })[0];
    var fiber = key && dom[key];
    for (var up = 0; fiber && up < 12; up++, fiber = fiber.return) {
      for (var state = fiber.memoizedState, n = 0; state && n < 40; state = state.next, n++) {
        var held = state.memoizedState && state.memoizedState.current;
        if (held && typeof held.getOption === 'function') return held;
      }
    }
    return null;
  }

  function nameOf(dom) {
    var slice = dom.closest('.chart-slice');
    var title = slice && slice.querySelector('[data-test="editable-title"], .editable-title, .header-title');
    return title ? title.textContent.trim() : 'Chart';
  }

  function json(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) throw new Error('Error ' + r.status + ' reading the filters');
      return r.json();
    });
  }

  /* The filters in force, as text, every chosen value written out: "Model: Local back-end, OpenAI back-end". They are
     read where Superset keeps them (the dashboard's filters and the state the address names), not from the boxes on
     screen, which shorten long lists. A filter with nothing chosen is no tag. */
  function tags() {
    var key = new URLSearchParams(location.search).get('native_filters_key');
    return json('/api/v1/dashboard/' + encodeURIComponent(dashboard)).then(function (d) {
      var meta = JSON.parse(d.result.json_metadata || '{}');
      var filters = meta.native_filter_configuration || [];
      var state = key
        ? json('/api/v1/dashboard/' + d.result.id + '/filter_state/' + encodeURIComponent(key)).then(function (f) {
            return JSON.parse(f.value || '{}');
          })
        : Promise.resolve({});
      return state.then(function (mask) {
        var out = [];
        filters.forEach(function (f) {
          var chosen = (mask[f.id] || f.defaultDataMask || {}).filterState || {};
          var values = [].concat(chosen.value == null ? [] : chosen.value);
          if (values.length) out.push(f.name + ': ' + values.join(', '));
        });
        return out;
      });
    });
  }

  function activeTab() {
    var tab = document.querySelector('.dashboard .ant-tabs-tab-active') || document.querySelector('.ant-tabs-tab-active');
    return tab ? tab.textContent.trim() : '';
  }

  /* Plots are saved for print: one size for all, so a wide plot is not shrunk to the page; the legend below, so the
     plot takes the width; the axis names as dark as the values. */
  var PRINT_WIDTH = 760, PRINT_HEIGHT = 660, DARK = '#333';

  /* The look shared by the chart on screen and the saved plot: legend below, axis names and legend as dark as the
     values. */
  function looks(option) {
    (option.legend || []).forEach(function (l) {
      l.orient = 'horizontal'; l.left = 'center'; l.top = null; l.bottom = 0;
      l.textStyle = Object.assign({}, l.textStyle, { color: DARK });
    });
    (option.radar || []).forEach(function (r) {
      r.axisName = Object.assign({}, r.axisName, { color: DARK });
    });
    ['xAxis', 'yAxis'].forEach(function (key) {
      (option[key] || []).forEach(function (a) {
        a.axisLabel = Object.assign({}, a.axisLabel, { color: DARK });
        a.nameTextStyle = Object.assign({}, a.nameTextStyle, { color: DARK });
      });
    });
    return option;
  }

  function forPrint(option) {
    looks(option);
    option.animation = false;
    delete option.toolbox;
    (option.legend || []).forEach(function (l) {
      l.selector = false;
      l.textStyle = Object.assign({}, l.textStyle, { fontSize: 13 });
    });
    (option.radar || []).forEach(function (r) {
      r.center = ['50%', '46%']; r.radius = '66%';
      r.axisName = Object.assign({}, r.axisName, { fontSize: 13 });
    });
    (option.grid || []).forEach(function (g) { g.bottom = Math.max(parseInt(g.bottom, 10) || 0, 60); });
    return option;
  }

  /* The charts on screen take the same look. Superset replaces a chart's settings each time it draws it, so every
     second each chart is checked and only what it lacks is set again (a chart already looking right is left alone). */
  function styleOnScreen() {
    document.querySelectorAll('[_echarts_instance_]').forEach(function (dom) {
      var chart = chartOf(dom);
      if (!chart) return;
      var option = chart.getOption() || {};
      var patch = {};
      if ((option.radar || []).some(function (r) { return (r.axisName || {}).color !== DARK; })) {
        patch.radar = option.radar.map(function () { return { axisName: { color: DARK } }; });
      }
      if ((option.legend || []).some(function (l) { return (l.textStyle || {}).color !== DARK; })) {
        patch.legend = option.legend.map(function () { return { textStyle: { color: DARK } }; });
      }
      ['xAxis', 'yAxis'].forEach(function (key) {
        if ((option[key] || []).some(function (x) { return (x.axisLabel || {}).color !== DARK; })) {
          patch[key] = option[key].map(function () { return { axisLabel: { color: DARK }, nameTextStyle: { color: DARK } }; });
        }
      });
      if (Object.keys(patch).length) chart.setOption(patch);
    });
  }

  function vector(lib, chart) {
    var copy = lib.init(null, null, { renderer: 'svg', ssr: true, width: PRINT_WIDTH, height: PRINT_HEIGHT });
    copy.setOption(forPrint(chart.getOption()));
    var svg = copy.renderToSVGString();
    copy.dispose();
    return svg;
  }

  /* The rows the chart draws, as shown under it (row-counts.js), or null when no count is known. */
  function rowsOf(dom) {
    var slice = dom.closest('[data-test-chart-id]');
    var n = slice && window.aiscRowCounts ? window.aiscRowCounts.of(slice.getAttribute('data-test-chart-id')) : undefined;
    return typeof n === 'number' ? n : null;
  }

  function plotsOnTheTab(lib) {
    var out = [];
    document.querySelectorAll('[_echarts_instance_]').forEach(function (dom) {
      if (!dom.offsetParent) return;
      var chart = chartOf(dom);
      if (chart) out.push({ chart: nameOf(dom), svg: vector(lib, chart), rows: rowsOf(dom) });
    });
    return out;
  }

  function csrf() {
    return fetch('/api/v1/security/csrf_token/', { credentials: 'same-origin' })
      .then(function (r) { return r.json(); }).then(function (d) { return d.result; });
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

  function send(token, body) {
    return witnessed('/api/v1/aisc_report_export/').then(function (url) {
      return fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
        body: JSON.stringify(body),
      });
    }).then(function (r) {
      if (r.ok) return r;
      return r.json().catch(function () { return {}; }).then(function (d) {
        throw new Error(d.message || ('Error ' + r.status));
      });
    });
  }

  function panel(plots, filterTags, tab) {
    var box = document.createElement('div');
    box.id = ID + '-panel';
    box.style.cssText = 'position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,.6);overflow:auto;padding:24px';
    var card = document.createElement('div');
    card.style.cssText = 'background:#fff;padding:16px;border-radius:4px;max-width:1000px;margin:0 auto';
    var tagLine = document.createElement('p');
    tagLine.className = ID + '-tags';
    tagLine.textContent = filterTags.length ? 'Filters: ' + filterTags.join(' | ') : 'No filters: all the data';
    card.append(tagLine);
    var rows = plots.map(function (plot) {
      var row = document.createElement('div');
      row.className = ID + '-plot';
      row.style.cssText = 'border-top:1px solid #ddd;padding:12px 0';
      var label = document.createElement('label');
      label.style.cssText = 'display:block;font-weight:600;margin-bottom:6px';
      var keep = document.createElement('input');
      keep.type = 'checkbox'; keep.checked = true; keep.style.marginRight = '8px';
      label.append(keep, plot.chart);
      if (plot.rows !== null && window.aiscRowCounts) {
        var count = document.createElement('span');
        count.style.cssText = 'font-weight:400;color:#8a8a8a;margin-left:8px;font-size:12px';
        count.textContent = window.aiscRowCounts.label(plot.rows);
        label.append(count);
      }
      var img = document.createElement('img');
      img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(plot.svg)));
      img.style.cssText = 'display:block;max-width:100%';
      var note = document.createElement('textarea');
      note.rows = 2; note.placeholder = 'Comment for the report (optional)';
      note.style.cssText = 'display:block;width:100%;margin-top:6px;padding:6px';
      row.append(label, img, note);
      card.append(row);
      return { plot: plot, keep: keep, note: note };
    });
    var save = document.createElement('button');
    save.id = ID + '-save'; save.textContent = 'Save to report';
    var close = document.createElement('button');
    close.textContent = 'Cancel'; close.style.marginLeft = '8px';
    close.onclick = function () { box.remove(); };
    var said = document.createElement('span');
    said.id = ID + '-said'; said.style.marginLeft = '12px';
    save.onclick = function () {
      var chosen = rows.filter(function (r) { return r.keep.checked; });
      if (!chosen.length) { said.textContent = 'Tick at least one plot.'; return; }
      save.disabled = true; said.textContent = 'Saving…';
      csrf().then(function (token) {
        return chosen.reduce(function (done, r) {
          return done.then(function () {
            return send(token, { dashboard_id: dashboard, chart: r.plot.chart, tab: tab, tags: filterTags,
                                 svg: r.plot.svg, comment: r.note.value, rows: r.plot.rows });
          });
        }, Promise.resolve());
      }).then(function () {
        said.textContent = 'Saved ' + chosen.length + ' plot(s). They are now in the report.'; close.textContent = 'Close';
      }).catch(function (e) {
        said.textContent = 'Not saved: ' + e.message; save.disabled = false;
      });
    };
    card.append(save, close, said); box.append(card); document.body.append(box);
  }

  function open(button) {
    button.disabled = true; button.textContent = 'Preparing…';
    return library().then(function (lib) {
      var plots = plotsOnTheTab(lib);
      if (!plots.length) throw new Error('no plot on this tab');
      return tags().then(function (filterTags) {
        panel(plots, filterTags, activeTab());
        button.textContent = 'Save to report';
      });
    }).catch(function (e) {
      console.error('[save-to-report]', e);
      button.textContent = 'Could not make the plots: ' + (e && e.message || e);
    }).finally(function () { button.disabled = false; });
  }

  function add() {
    if (document.getElementById(ID)) return;
    var b = document.createElement('button');
    b.id = ID; b.type = 'button'; b.textContent = 'Save to report';
    b.style.cssText = 'position:fixed;right:24px;bottom:24px;z-index:99999;padding:8px 14px;background:#000FDF;'
      + 'color:#fff;border:0;border-radius:4px;cursor:pointer;font-size:14px';
    b.onclick = function () { open(b); };
    document.body.append(b);
  }
  function start() {
    add();
    styleOnScreen();
    setInterval(styleOnScreen, 1000);
  }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
