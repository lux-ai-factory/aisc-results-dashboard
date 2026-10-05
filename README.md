# AISC results dashboard

The results dashboard is step 5 of the AI Assessment Sandbox Configurator (AISC), where
the results of an assessment are analysed. AISC is a platform for assessing AI systems
in six steps: 1 qualification, 2 control objectives, 3 install plugins and tools, 4
execute tests and address controls, 5 analyse results on this dashboard, 6 compose the
report. This repository is the dashboard: stock Apache Superset 4.1.4, customised only
through Superset's configuration file and a small Python package (`aisc_ext`). For
every AISC project it builds one dashboard of that project's results: the execution
engine's scores by AI card version and by assessment target, and the answers to the
controls. People in the project can read those charts, comment on them and ask each
other for reviews. Every action is written to an immudb audit log and, when the ledger
is on, to the project's ledger.

## How it works

```
 browser ── Caddy + oauth2-proxy (AISC gateway, :8188) ── Superset (this repo)
                                                             │
     platform service ── bridge API: POST/DELETE ───────────►│
       /api/v1/aisc_project/<pid>                            │
                                                             ├─ Superset metadata DB (`superset`):
                                                             │    dashboards, comments, review
                                                             │    requests, ledger outbox
                                                             ├─ project_<pid hex> (one per project),
                                                             │    read as dashboard_ro
                                                             ├─ platform DB, core.project_member
                                                             │    only, at sign-in
                                                             ├─ Redis (cache)
                                                             └─ immudb (audit log)
```

- **No fork of Superset.** The image is `apache/superset:4.1.4` plus three Python packages (pinned)
  (`Dockerfile`). `superset_config.py`, `aisc_ext/` and `branding/` are bind-mounted at
  runtime, and every customisation uses a documented Superset hook:

  | What | Superset hook | Where |
  |---|---|---|
  | Branding (name, logo, colours) | `APP_NAME`, `APP_ICON`, `THEME_OVERRIDES` | `aisc_ext/branding.py` |
  | Audit log | `EVENT_LOGGER` | `aisc_ext/event_logger.py`, `aisc_ext/audit.py` |
  | Keycloak sign-in (standalone only) | `CUSTOM_SECURITY_MANAGER` | `aisc_ext/sso.py`, `aisc_ext/security.py` |
  | Bridge, comments, review requests, Review page | `FLASK_APP_MUTATOR` | `aisc_ext/` |
  | Embedding in other pages | `FEATURE_FLAGS`, Talisman `frame-ancestors` | `superset_config.py` |
  | Feature and chart lockdown | `FEATURE_FLAGS`, `VIZ_TYPE_DENYLIST` | `superset_config.py` |

  Before moving to another Superset tag, run the aisc repo's `scripts/check-superset-upgrade.sh
  <image>`: it runs that image with this overlay in throwaway containers and opens every plugin
  tile in a browser.
- **One dashboard per project.** When the platform creates a project it calls the bridge
  (`POST /api/v1/aisc_project/<pid>`, header `X-AISC-Bridge-Token`). `aisc_ext/projects.py`
  then creates, for that project: a connection `AISC Controls <slug>` to the project's own
  database `project_<pid hex>` as the read-only role `dashboard_ro`; the datasets
  `engine_results_<hex>` and `controls_answers_<hex>`; a role `AiscProject_<hex>` that may
  read only those; and the dashboard `aisc-<hex>`, visible only to that role
  (`DASHBOARD_RBAC`). `DELETE` on the same route removes them all. There is no Superset
  connection to the shared `platform` database.
- **Roles at sign-in.** Each user gets a role mapped from their Keycloak realm roles
  (`admin` gives Admin, `primary-user` gives the read-only `AiscViewer`), plus one
  `AiscProject_<hex>` role per project they are a member of. Memberships are read from
  `core.project_member` in the `platform` database over `AISC_MEMBERSHIP_DB_URI`, a plain
  connection that is opened and closed for each sign-in. `AiscViewer` is Gamma without any
  write permission and without SQL Lab, so a viewer can look and comment, nothing else.
- **Review page and comments.** Menu *Assessment > Review dashboards* (`/aisc/review/`)
  shows a dashboard in an iframe with its comment threads beside it. Comments can be about
  the whole dashboard or one chart; review requests go to a person or to a stakeholder
  group (legal, compliance, ethics, technical, business, domain). The REST APIs are
  `/api/v1/aisc_comment` and `/api/v1/aisc_review_request`. Both work only on dashboards the
  caller can open, and neither is exempt from CSRF. Both live in Superset's metadata database.
  A deleted comment is hidden, not removed. The raw *Comments* and *Review Requests* tables in
  the menu list every project's rows, so they are the Admin's only.
- **Ledger.** With `LEDGER_MODE` set to `record` or `enforce`, each comment and review
  change also queues an event in the table `aisc_ledger_outbox`, in the same transaction.
  The events are then posted, in order and off the request path (one pass at a time across
  Superset's workers, an advisory lock on Postgres), to the platform's internal route
  (`POST /internal/projects/<pid>/ledger/events`), which adds them to the project's ledger.
  When the platform cannot be reached (or the token or address is wrong) the events stay
  queued for the next pass; an event the platform refuses (409, 413, 422) is kept with
  that status and not sent again.

## Install and run

### Inside the AISC stack (the usual way)

The dashboard is a submodule of the [aisc](https://github.com/lux-ai-factory/aisc) repo at
`apps/results-dashboard` and is started with the rest of the stack. The image is built from
this repository. Two compose services in the aisc repo's `docker-compose.development.yml`
use it:

- `dashboard-migrate` runs `superset db upgrade && superset init` once and exits;
- `dashboard` is the server. It uses host networking and listens on
  `DASHBOARD_BIND_ADDRESS:DASHBOARD_INTERNAL_PORT` (default `172.17.0.1:8189`). Caddy
  publishes it at **http://localhost:8188** behind the AISC gateway. The aisc repo's
  `dashboard-gateway/superset_gateway_config.py` loads this repo's `superset_config.py`
  and signs the user in from the gateway's verified token, so `AISC_OAUTH` is `0` there and
  there is no local admin account.

From the aisc repo root, make the secrets once (this sets `SUPERSET_SECRET_KEY`,
`DASHBOARD_BRIDGE_TOKEN` and `PLATFORM_LEDGER_DASHBOARD_TOKEN`, among others), then start
the stack:

```bash
./scripts/secrets.sh
docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml \
  -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build
```

The `superset` metadata database and the `dashboard_ro` role are created by the aisc
repo's `init/` scripts on a fresh Postgres volume. Project dashboards appear when the
platform creates projects; nothing is registered by hand.

Changes to `superset_config.py`, `aisc_ext/` or `branding/` are bind-mounted, so a restart
of the `dashboard` container picks them up. Only a change to the `Dockerfile` needs a
rebuild.

To check the Review page and the comments API inside the running container:

```bash
docker exec -i dashboard python - < scripts/verify_review.py
```

It creates its own test objects, removes them afterwards and exits 0 when every check holds.

### Standalone, for development

Prerequisites: Docker with Compose v2; Python 3.10 or newer and
[uv](https://docs.astral.sh/uv/) for the tests.

```bash
git clone --branch feat/unified-modules https://github.com/lux-ai-factory/aisc-results-dashboard.git
cd aisc-results-dashboard
./scripts/bootstrap.sh   # makes .env from .env.example, with every empty secret generated
```

`bootstrap.sh` makes `.env` on its first run (every secret `.env.example` leaves empty is
generated with `openssl rand`, kept on later runs and never printed; `--env-only` stops there),
builds the image, pulls Postgres 16, Redis 7 and immudb, starts `docker-compose.yml`, runs the
Superset migrations and creates a local admin user (`ADMIN_USER`, default `admin`; its password is
`ADMIN_PASSWORD` in `.env`). Superset is then on
**http://localhost:8188**. It is safe to re-run.

This stack has its own Postgres, Redis and immudb and no gateway, so sign-in is
Superset's own login form unless `AISC_OAUTH=1`. It sets no `DASHBOARD_BRIDGE_TOKEN`,
so the bridge refuses every call and no project dashboards are created. To read a local
aisc stack's databases, add the overlay `docker-compose.aisc.yml`, which joins the
`aisc_backend` network (set `AISC_NETWORK` if yours has another name):

```bash
docker compose -f docker-compose.yml -f docker-compose.aisc.yml up -d
```

Everyday commands: `docker compose logs -f superset`, `docker compose down` (the
metadata volume is kept), `docker compose up -d`.

## Configuration

Environment variables read by `superset_config.py` and `aisc_ext`. "Stack" is the value
the aisc repo's `docker-compose.development.yml` sets.

| Variable | Meaning | Default |
|---|---|---|
| `SUPERSET_SECRET_KEY` | Signs session cookies. Required: Superset refuses to start without it. | none |
| `SUPERSET_GUEST_TOKEN_SECRET` | Signs guest tokens (embedding is on). Required, like the one above. | none |
| `SUPERSET_DB_URI` | SQLAlchemy URI of Superset's metadata database. Required. | none (stack: `.../superset` on Postgres) |
| `REDIS_HOST`, `REDIS_PORT` | Redis cache. | `superset-redis`, `6379` |
| `LAUNCHER_URL` | Where the logo links to: the AISC launcher's project list. | `http://localhost:8100/` |
| `BRANDING_APP_NAME` | App name in the top bar. | `AI Assessment Sandbox` |
| `BRANDING_LOGO` | Logo path as the browser requests it. | `/static/assets/branding/aisc/laif_logo.png` |
| `BRANDING_PRIMARY`, `BRANDING_SECONDARY` | Theme colours (hex); darker and lighter shades are derived. | `#001075`, `#D7193B` |
| `EMBED_ALLOWED_ORIGINS` | Comma-separated origins allowed to frame the dashboard. When set, the session cookie becomes `SameSite=None; Secure`, so HTTPS is needed. | empty (no framing) |
| `AISC_MEMBERSHIP_DB_URI` | DSN of the `platform` database for memberships at sign-in. Must connect as `dashboard_ro`. Unset: nobody gets a project role. | unset (stack: `dashboard_ro` on `localhost:5432/platform`) |
| `AISC_PROJECT_DB_HOSTPORT` | Host and port of the project databases, used in each project connection. | `postgres:5432` (stack: `localhost:5432`) |
| `DASHBOARD_RO_PASSWORD` | Password of `dashboard_ro` in the project connections. Required: without it the bridge registers nothing (503). | none (stack: from `scripts/secrets.sh`) |
| `DASHBOARD_BRIDGE_TOKEN` | Shared secret the platform sends to the bridge. Unset: the bridge refuses every call. | unset (stack: from `scripts/secrets.sh`) |
| `AISC_AUDIT_ENABLED` | Write the audit log to immudb (`true` / `false`). | `true` |
| `IMMUDB_HOST`, `IMMUDB_PORT` | immudb server for the audit log. | `immudb`, `3322` |
| `IMMUDB_USER`, `IMMUDB_PASSWORD` | immudb credentials. Without a password no audit row is written, and a warning is logged. | `immudb`, none |
| `LEDGER_MODE` | `off`, `record` or `enforce`. `record` and `enforce` queue ledger events; any other value is off. | `off` |
| `PLATFORM_URL` | Base URL of the platform service, for ledger events. Unset: events stay queued. | unset (stack: `http://172.17.0.1:8000`) |
| `PLATFORM_LEDGER_DASHBOARD_TOKEN` | Token for the platform's internal ledger route. Unset: events stay queued. | unset (stack: from `scripts/secrets.sh`) |
| `AISC_OAUTH` | `1` turns on Superset's own Keycloak sign-in (standalone use). | off (stack: `0`) |
| `OIDC_ISSUER` | Keycloak realm URL, with `AISC_OAUTH=1`. | `http://keycloak.localhost:8080/realms/dashboard` |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Keycloak client, with `AISC_OAUTH=1`. The secret is required then. | `superset`, none |

Used only by the standalone compose files: `SUPERSET_DB_PASSWORD` (metadata Postgres,
required), `AISC_NETWORK` (network of the aisc stack, default `aisc_backend`), and
`ADMIN_USER`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` for `bootstrap.sh`. In the stack, Superset's
own entrypoint also reads `SUPERSET_BIND_ADDRESS` and `SUPERSET_PORT`.

### Branding

To rebrand for a company, put its logo in `branding/<company>/` (served at
`/static/assets/branding/<company>/`), set the `BRANDING_*` variables and restart. No
rebuild is needed. The top-bar background stays Superset's white: Superset 4.1.1 has no
setting for it, and changing it would mean injecting CSS into Superset's pages. See
[`branding/README.md`](branding/README.md).

### Embedding

Set `EMBED_ALLOWED_ORIGINS` to the host page's origin and put the dashboard's or chart's
standalone URL in an `<iframe>`. The charts stay interactive because Superset itself renders
them. The iframe uses the viewer's existing session, which a browser sends cross-site only
over HTTPS; a browser that blocks third-party cookies needs Superset's guest tokens
(`/api/v1/security/guest_token/`). Check the resulting `Content-Security-Policy` header
against the running image before relying on it.

## Tests

The unit tests need no Docker, database or Superset install. From the repository root:

```bash
PYTHONPATH=. uv run --no-project --with pytest --with sqlalchemy --with psycopg2-binary \
  --with authlib --with flask --with requests --with pyyaml \
  python -m pytest -q -p no:cacheprovider tests --ignore tests/test_sso_login.py
```

`tests/test_sso_login.py` imports `aisc_ext.sso`, which needs Superset, so it is left out
here.

Two files run the dataset SQL against a real Postgres: `tests/test_project_datasets_db.py`
and `tests/test_isolation_dashboard_db.py`. They are skipped unless
`AISC_DASHBOARD_TEST_PG_CONTAINER` names a **throwaway** Postgres container, and they read
the init files, platform migrations, project template and controls migrations from the aisc
repo, so they run only in a checkout at `apps/results-dashboard`. Start the container and
run them:

```bash
docker run --rm -d --name aisc-t-dash-$(openssl rand -hex 3) -p 127.0.0.1:<free port>:5432 \
  -e POSTGRES_USER=aisc-postgres-user -e POSTGRES_PASSWORD=<pw> \
  -e POSTGRES_DB=platform postgres:15-alpine
AISC_DASHBOARD_TEST_PG_CONTAINER=aisc-t-dash-<hex> PYTHONPATH=. uv run --no-project \
  --with pytest --with sqlalchemy --with psycopg2-binary --with authlib --with flask --with requests --with pyyaml \
  python -m pytest -q -p no:cacheprovider tests/test_project_datasets_db.py tests/test_isolation_dashboard_db.py
```

The tests send their SQL through `docker exec psql` into that container and create roles and
databases there. **Never point them at the running stack's Postgres** (the `postgres`
container, port 5432): they would change the live databases.

## Layout

```
superset_config.py      the Superset configuration (mounted on PYTHONPATH)
aisc_ext/               the extension package (mounted next to it)
  projects.py           what the bridge creates per project: connection, datasets, role, dashboard
  project_bridge_api.py the bridge route, /api/v1/aisc_project/<pid>
  security.py, sso.py,  role mapping, Keycloak sign-in, the AiscViewer role
  viewer_role.py
  results_db.py         the membership DSN; removal of the old shared "AISC Results" connection
  comments/, reviews/   models, rules, REST APIs and list pages for comments and review requests
  review/               the Review page (views, rules, Jinja templates)
  dashboards.py         the "may this user open this dashboard" check
  ledger.py             ledger events and their outbox
  audit.py, event_logger.py   the immudb audit log
  branding.py           branding from env vars
branding/               logos, served at /static/assets/branding/
scripts/                bootstrap.sh (standalone setup), verify_review.py (in-container check)
tests/                  unit tests and the two database tests
Dockerfile              stock Superset image plus immudb-py, Authlib, psycopg2-binary
docker-compose.yml      standalone stack; docker-compose.aisc.yml joins a local aisc stack
DECISIONS.md            why the design is the way it is
```

## Contributing

- `feat/unified-modules` is the only branch to work on; the aisc repo pins this submodule on
  it.
- There are no migrations of its own. The tables `aisc_comment`, `aisc_review_request` and
  `aisc_ledger_outbox` are created in Superset's metadata database at startup if missing
  (`_install_extension` in `superset_config.py`), and roles and permissions are refreshed at
  every start.
- Upgrading Superset: change the tag in the `Dockerfile`, rebuild, and run
  `superset db upgrade && superset init` (in the stack, `dashboard-migrate` does this).
  Then check the embedding CSP and run `scripts/verify_review.py`.
- Never change Superset's source, image contents or rendered pages: everything goes through
  its configuration hooks. See [`DECISIONS.md`](DECISIONS.md).
- See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contribution process and the CLA.

## License and governance

Apache-2.0: see [`LICENSE.md`](LICENSE.md) and [`NOTICE.md`](NOTICE.md). This project
contains no Apache Superset source; it runs the stock `apache/superset` image unmodified.
"Apache Superset" is a trademark of the Apache Software Foundation; the Luxembourg AI
Factory logo is not covered by the Apache license (see NOTICE).

Contribution and governance documents: [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`GOVERNANCE.md`](GOVERNANCE.md), [`MAINTAINERS.md`](MAINTAINERS.md),
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), [`SECURITY.md`](SECURITY.md) and the CLA text
files. Background on the public release is in [`OPEN_SOURCING.md`](OPEN_SOURCING.md).
