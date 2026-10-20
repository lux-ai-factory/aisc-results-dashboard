# Changelog of the AISC results dashboard overlay (newest first).

## 2026-10-19: closed submissions as they were answered

- `controls_answers_<hex>` shows a closed submission's answers with their questions as they were when it was
  closed (text, article, category, place), answers to questions removed since included; a draft follows
  today's questions, as the controls app does (`apps/controls/src/lib/answerSheet.ts`). New columns
  `article`, `category`, `question_order` and `questions_version` (the template revision a closed submission
  answered). Needs the controls migrations of 2026-10-18 and every project registered again (the platform
  registers them all on its first pass after a start).

## 2026-10-16: review fixes

- The standalone `superset-redis` reads its password from a config file it writes at start, as the root
  compose's `dashboard-redis` does: `--requirepass` put it on the server's command line, which `ps` shows on
  the host (`tests/test_cache_config.py`).
- README: Superset's action log has Superset's own views only; comments, reviews and chart imports are
  recorded only as ledger events, with `LEDGER_MODE` on.
- `tests/test_routes_in_superset.py` (dashboard image only) boots Superset on SQLite and calls the comment,
  review request and import routes: CSRF kept, a second resolution 409, no event for a dashboard naming a
  project the writer is not in, no request id without the gateway's claims, only the person's tiles.

## 2026-10-15: one access model for immudb (aisc immudb-unify)

- Removed: the direct immudb path (`aisc_ext/event_logger.py` ImmudbEventLogger, `aisc_ext/audit.py`
  ImmudbClerk, immudb-py in the image, IMMUDB_* and AISC_AUDIT_ENABLED). Superset's own event logger records
  actions in its `logs` table; comments and reviews keep reaching the platform's ledger. The standalone stack
  has no immudb. Rows already written to immudb's `defaultdb.superset_audit` stay there (immudb deletes
  nothing). Needs the image rebuilt.

## 2026-10-14: review pass (branch pass/dashboard-2026-10-13)

Areas: cache config, plugin tiles and chart import, security (roles, tiles), comments and review requests,
ledger outbox, audit clerk, project bridge, standalone compose, tests.

Security
- Cache: Superset's cache is the dashboard's own Redis with a password (`DASHBOARD_REDIS_HOST`, default
  `dashboard-redis`; `DASHBOARD_REDIS_PORT`, default `6379`; `DASHBOARD_REDIS_PASSWORD`, required: no password,
  no start). `REDIS_HOST`/`REDIS_PORT` are no longer read. Needs the aisc compose's `dashboard-redis` first.
- Plugin tiles: a dashboard is a project's tile only when `aisc-bridge` made it and it carries the project's
  role; importing charts takes being Admin, or owner and the project's editor. Role lists
  (`/related/roles`) show a person their own roles only.
- Ledger: an event goes to a project's ledger only when the dashboard carries that project's role and the writer
  is in it (or Admin); `X-AISC-Request-Id` is cited only on a request the gateway verified.
- Chart import: a ZIP of more than 500 files or more than 5 MB unpacked is refused before it is read.
- Embedding: with `EMBED_ALLOWED_ORIGINS` the session cookie is really `SameSite=None; Secure` (Talisman reset
  it to Lax).
- Review Requests table (Assessment menu) is read-only: list and show.
- A project's connection is named `AISC Controls <hex>` by its pid, not its slug (a reused slug took over
  another project's connection); an old slug-named one is renamed in place at the next registration.

Behaviour
- Reviews: PATCH on a done or dismissed request answers 409; the requester may resolve their own request;
  bad input (non-text message or body, unknown assignee or action, chart not on the dashboard, bad
  `?chart_id=`) answers 400, not 500; requests are stored under the dashboard's id (slug rows moved at start).
- Comments: two deletes at once hide the comment once, with one ledger event; commenting on a dashboard whose
  slug names no project works again.
- Ledger outbox: a deleted project's events (platform 404 "no project") are refused, not retried forever; a
  waiting project holds back only its own events; a pass on Postgres no longer fails on `Connection.commit()`.
- Bridge: registration, unregistration and chart import hold the project's lock; unregister also deletes
  untagged charts on the project's datasets; the tile sync answers 404 only for an unregistered project.
- Tiles: a person's chart placed among the defaults goes under "Your charts" in the same sync.
- Audit: after every retry of a write fails, the immudb client is dropped and reconnects after the cooldown.
- Menu: "← Back" returns to the project's Sandbox (`LAUNCHER_URL/evidence.html?project=<pid>`).
- Standalone: `docker-compose.yml` loads again (YAML error in its refusal messages); its Redis runs with
  `--requirepass`; overlay and bootstrap no longer promise project registrations.
- Removed dead code: `extract_realm_roles`, comments `scope_filter`, `VIEWER_WRITABLE_VIEWS`, register's slug and
  name; tests deduplicated.

How to check
- Unit suite (README "Tests" command): 319 passed, 24 skipped on the host; in the dashboard image with pytest,
  328 passed, 22 skipped. Postgres file: `AISC_DASHBOARD_TEST_PG_CONTAINER=<throwaway> ... tests/test_project_datasets_db.py`
  (20 passed).
- Running stack: the dashboard refuses to start without `DASHBOARD_REDIS_PASSWORD`; `redis-cli -h dashboard-redis
  PING` without the password answers NOAUTH. Before deploying, every plugin tile should have `created_by_fk` =
  the `aisc-bridge` user (`SELECT d.slug, u.username FROM dashboards d LEFT JOIN ab_user u ON u.id =
  d.created_by_fk WHERE d.json_metadata LIKE '%aisc_plugin%';`), else it stops being a tile. Project connections
  read `AISC Controls <hex>` after the platform's next registration pass.
