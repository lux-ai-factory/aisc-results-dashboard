/* The number of rows each chart on a dashboard draws, shown as "N rows" in a muted line under the chart.

   A dashboard asks Superset for each chart's data with POST /api/v1/chart/data, naming the chart in the address
   (?form_data={"slice_id": N}) and in the body's form_data; the answer's result[].rowcount is the number of rows the
   chart's query gave after aggregation (2 for a radar with one polygon per model). The page's fetch is wrapped to read
   a copy of those answers: what the page receives is the very answer Superset gave. The latest count per chart is
   kept, so a new filter value gives a new count. Save to report reads it through window.aiscRowCounts.of(id). */
(function (window) {
  var counts = {};
  var CLASS = 'aisc-row-count';

  function label(n) { return n === 1 ? '1 row' : n + ' rows'; }

  function idOf(value) {
    var n = typeof value === 'string' && /^\d+$/.test(value) ? parseInt(value, 10) : value;
    return typeof n === 'number' && isFinite(n) && n >= 0 && Math.floor(n) === n ? n : null;
  }

  /* The chart a chart-data request is for, or null (a native filter's own query names no chart). */
  function sliceOf(url, body) {
    var id = null;
    try {
      var query = String(url).split('?')[1] || '';
      var named = new URLSearchParams(query).get('form_data');
      if (named) id = idOf((JSON.parse(named) || {}).slice_id);
    } catch (e) { id = null; }
    if (id === null && typeof body === 'string') {
      try { id = idOf(((JSON.parse(body) || {}).form_data || {}).slice_id); } catch (e) { id = null; }
    }
    return id;
  }

  /* The rows a chart-data answer holds: the sum over its queries, or null when it holds no count. */
  function rowsOf(answer) {
    var results = answer && answer.result;
    if (!Array.isArray(results) || !results.length) return null;
    var total = 0;
    for (var i = 0; i < results.length; i++) {
      var n = results[i] && results[i].rowcount;
      if (typeof n !== 'number' || !isFinite(n) || n < 0) return null;
      total += n;
    }
    return total;
  }

  function isChartData(url) { return /\/api\/v1\/chart\/data(\?|$)/.test(String(url)); }

  function paint() {
    var document = window.document;
    if (!document) return;
    var slices = document.querySelectorAll('.chart-slice[data-test-chart-id]');
    for (var i = 0; i < slices.length; i++) {
      var slice = slices[i];
      /* the line sits in the chart card's bottom padding, so the chart keeps all its height */
      var card = slice.parentElement;
      if (!card) continue;
      var n = counts[idOf(slice.getAttribute('data-test-chart-id'))];
      var line = card.querySelector(':scope > .' + CLASS);
      if (n === undefined) { if (line) line.remove(); continue; }
      if (!line) {
        line = document.createElement('div');
        line.className = CLASS;
        line.style.cssText = 'position:absolute;right:16px;bottom:1px;font-size:11px;line-height:14px;color:#8a8a8a;'
          + 'pointer-events:none';
        if (window.getComputedStyle && window.getComputedStyle(card).position === 'static') card.style.position = 'relative';
        card.appendChild(line);
      }
      if (line.textContent !== label(n)) line.textContent = label(n);
    }
  }

  function note(url, body, response) {
    var id = isChartData(url) ? sliceOf(url, body) : null;
    if (id === null || !response || !response.ok || typeof response.clone !== 'function') return;
    response.clone().json().then(function (answer) {
      var n = rowsOf(answer);
      if (n !== null) { counts[id] = n; paint(); }
    }).catch(function () { /* not JSON: no count */ });
  }

  window.aiscRowCounts = {
    label: label, sliceOf: sliceOf, rowsOf: rowsOf,
    of: function (id) { return counts[idOf(id)]; },
  };

  if (!/^\/superset\/dashboard\//.test((window.location || {}).pathname || '')) return;
  var original = window.fetch;
  if (typeof original === 'function') {
    window.fetch = function (input, init) {
      var url = input && typeof input === 'object' && 'url' in input ? input.url : input;
      var body = init && init.body;
      var answer = original.apply(window, arguments);
      if (isChartData(url)) {
        answer.then(function (response) { note(url, body, response); }, function () {});
      }
      return answer;
    };
  }
  if (window.document && typeof window.setInterval === 'function') window.setInterval(paint, 1000);
})(window);
