/* Which dashboard is open, for the scripts the hook adds (Save to report, the chart assistant, the row counts).
   Superset is a single-page app: opening a dashboard from its list or a link changes the address with
   history.pushState, without loading a page, and the hook's scripts run only at the first load. So they do not read
   the address once: they register here, are told the dashboard open now (its id or slug from the address, or null
   when no dashboard is open), and are told again at every change of the address. */
(function (window) {
  if (window.aiscDashboardPages) return;
  var DASHBOARD = /^\/superset\/dashboard\/([^/]+)/;
  var listeners = [];

  function now() {
    var m = ((window.location || {}).pathname || '').match(DASHBOARD);
    return m ? decodeURIComponent(m[1]) : null;
  }
  var current = now();

  function check() {
    var open = now();
    if (open === current) return;
    current = open;
    listeners.forEach(function (tell) {
      try { tell(open); } catch (e) { window.console && window.console.error('[dashboard-pages]', e); }
    });
  }

  var history = window.history;
  ['pushState', 'replaceState'].forEach(function (name) {
    var original = history && history[name];
    if (typeof original !== 'function') return;
    history[name] = function () {
      var result = original.apply(this, arguments);
      check();
      return result;
    };
  });
  if (typeof window.addEventListener === 'function') window.addEventListener('popstate', check);

  window.aiscDashboardPages = {
    current: function () { return current; },
    /* tell(dashboard) now, and again each time the open dashboard changes (null: none is open) */
    watch: function (tell) { listeners.push(tell); tell(current); },
  };
})(window);
