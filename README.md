# superset-overlay

A **configuration-only overlay** on top of Apache Superset, used as the AI
Assessment Sandbox's dashboard. There is **no Superset source code in this
repo**. The Superset instance is downloaded automatically as a pinned Docker
image, and everything here is layered on top of it through Superset's own
official configuration seams.

> **The one rule this project holds:** we never modify, patch, or inject into
> Superset. Not its source, not its Docker image contents, not its rendered
> HTML/DOM. If a new Superset release ships, upgrading is a one-line image-tag
> bump and nothing in this repo can silently break, because nothing here depends
> on Superset's internals.
>
> Successor to the older `superset-aisc` build, which baked branding into a
> custom image and injected a UI widget into Superset's DOM via an nginx
> sidecar. Both of those coupling points are gone.

---

## 1. How it works

The stack is stock Superset plus three sidecar services, with all customization
**bind-mounted** into the Superset container at runtime:

```
                     http://localhost:8188
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │ superset  (stock apache/superset:4.1.1)       │
        │   + /app/pythonpath/superset_config.py  (mnt) │  ← the overlay
        │   + /app/pythonpath/aisc_ext/           (mnt) │  ← extension pkg
        │   + static/assets/branding/             (mnt) │  ← tenant logos
        └───────┬───────────────┬───────────────┬───────┘
                ▼               ▼               ▼
          superset-db       superset-redis     immudb
          (Postgres:        (cache)            (tamper-evident
           metadata +                           audit ledger)
           comments/reviews)
```

- **No nginx sidecar** — Superset serves directly on `:8188`.
- **No celery worker** — every async feature (alerts, thumbnails, async queries)
  is off, so there are no background tasks.
- **The only custom-built image** is a 4-line `Dockerfile` that adds three pip
  dependencies the stock image lacks. It copies no Superset source and no
  customization; config/extension/branding are all mounts.

### Every customization rides a documented Superset seam

| Customization | Superset seam | Where |
|---|---|---|
| Branding (logo, name, theme colors) | `APP_NAME` / `APP_ICON` / `THEME_OVERRIDES` (env-driven) | `superset_config.py`, `aisc_ext/branding.py` |
| Tamper-evident audit trail | `EVENT_LOGGER` | `aisc_ext/event_logger.py`, `aisc_ext/audit.py` |
| Keycloak SSO (optional) | `CUSTOM_SECURITY_MANAGER` | `aisc_ext/sso.py`, `aisc_ext/security.py` |
| Comments & review requests | `FLASK_APP_MUTATOR` (REST API + native FAB views) | `aisc_ext/comments/`, `aisc_ext/reviews/` |
| Interactive embedding | `FEATURE_FLAGS` + Talisman `frame-ancestors` | `superset_config.py` |
| Feature / chart lockdown | `FEATURE_FLAGS`, `VIZ_TYPE_DENYLIST`, roles | `superset_config.py` |

Nothing above touches Superset's source or DOM.

---

## 2. Quick start

```bash
cd ~/superset-overlay
./scripts/bootstrap.sh
```

`bootstrap.sh` is the "automated download": it creates `.env` from the example,
pulls `apache/superset:4.1.1` (+ Postgres/Redis/immudb), builds the 3-dependency
layer, starts the stack, and initializes the metadata DB and an admin user.

Then open **http://localhost:8188** and log in with **admin / admin**.

Everyday commands:

```bash
docker compose logs -f superset   # watch logs
docker compose down               # stop (data is kept in the volume)
docker compose up -d              # start again (picks up .env + mount changes)
```

---

## 3. Configuration (`.env`)

Copy `.env.example` to `.env` and edit. Every value has a safe default, so a bare
run works out of the box with the default AISC identity. `.env` is git-ignored.

| Variable | Purpose |
|---|---|
| `SUPERSET_SECRET_KEY` | Flask secret. **Set a long random value for anything real.** |
| `SUPERSET_DB_PASSWORD` | Password for the bundled metadata Postgres. |
| `AISC_RESULTS_DB_URI` | Your results database. Register it as a connection in the UI after init. |
| `BRANDING_APP_NAME` / `BRANDING_LOGO` / `BRANDING_PRIMARY` / `BRANDING_SECONDARY` | White-label branding (see §4). Blank = default AISC identity. |
| `EMBED_ALLOWED_ORIGINS` | Comma-separated origins allowed to embed charts in an iframe (see §5). |
| `AISC_OAUTH` / `OIDC_*` | Keycloak SSO (see §7). Blank = local username/password login. |
| `IMMUDB_USER` / `IMMUDB_PASSWORD` | Credentials for the audit ledger. |

---

## 4. White-label for a company (no rebuild)

Branding is resolved from env at startup by `aisc_ext/branding.py`, with AISC as
the built-in default tenant. To brand for a company:

1. Drop the logo into a tenant folder:
   ```
   branding/acme/logo.png
   ```
   The whole `branding/` directory is mounted at `/static/assets/branding/`, so
   that file is served at `/static/assets/branding/acme/logo.png`.
2. Set the vars in `.env`:
   ```env
   BRANDING_APP_NAME=Acme Assurance
   BRANDING_LOGO=/static/assets/branding/acme/logo.png
   BRANDING_PRIMARY=#0a7d32
   BRANDING_SECONDARY=#ff6600
   ```
   Only `BRANDING_PRIMARY` is required for colors — the darker/lighter shades are
   derived automatically.
3. Apply:
   ```bash
   docker compose up -d
   ```

No image rebuild. See also [`branding/README.md`](branding/README.md).

### What branding can and cannot change

- **Can (config-only):** the bar **logo**, the app **name**, the **favicon**, and
  **theme accent colors** (buttons, links, the active-nav underline, focus rings,
  chart color accents).
- **Cannot:** the **top-bar background color**. Superset 4.1.1 exposes no config
  for it, and the bar stays Superset's default white. Recoloring it would require
  injecting CSS into Superset's pages, which is exactly the customization this
  project refuses to do. This is a deliberate trade-off — see
  [`DECISIONS.md`](DECISIONS.md).

---

## 5. Embed an interactive figure in another dashboard

Legend select/deselect, cross-filters and drill all survive, because **Superset
itself renders the chart inside the host page's `<iframe>`** — this is native
embedding, not a static image export.

1. Set the host page origin(s) in `.env`:
   ```env
   EMBED_ALLOWED_ORIGINS=https://portal.example.com
   ```
2. `docker compose up -d`.
3. Put the chart/dashboard's standalone URL in an `<iframe>` on the host page.

**Auth model: shared Keycloak SSO session** — the iframe rides the viewer's
existing login. Because the session cookie is then sent in a third-party context,
the overlay automatically sets `SameSite=None; Secure` when `EMBED_ALLOWED_ORIGINS`
is present, which **requires serving over HTTPS**. If a browser's strict
third-party-cookie policy still blocks it, switch to guest tokens (native
`/api/v1/security/guest_token/`).

> Not yet verified end-to-end — see §9.

---

## 6. Comments & review requests

Reviewers can comment on results and raise review requests (assigned to a person
or to a stakeholder group: legal / compliance / ethics / technical / business /
domain). This is exposed two ways, both native:

- **REST API** (`/api/v1/aisc_comment`, `/api/v1/aisc_review_request`) — for the
  embedding host or programmatic use.
- **Menu views** under an **"Assessment"** category — standard Flask-AppBuilder
  CRUD pages rendered by Superset itself, with **zero coupling to Superset's
  React/DOM**. These replace the old DOM-injected widget.

Every action is written to the immudb audit ledger.

---

## 7. Audit trail & SSO (carried over from the prior build)

- **Audit:** `EVENT_LOGGER` mirrors actions into immudb (`aisc_ext/audit.py`). If
  immudb is unreachable it fails soft (a warning, no crash).
- **Keycloak SSO:** set `AISC_OAUTH=1` and the `OIDC_*` vars. This swaps login for
  OAuth, so register the `superset` client in your realm first. Realm roles map to
  Superset's Admin / Alpha (editor) / Gamma (viewer) via `aisc_ext/security.py`.

---

## 8. Upgrading Superset

1. Bump the tag in `Dockerfile` (`FROM apache/superset:<new-tag>`).
2. Re-run `./scripts/bootstrap.sh`.

Because every customization rides a public config seam, an upgrade does not touch
our code. The one thing worth re-checking is the interactive-embedding CSP (§5).

---

## 9. Known limitations / not yet verified

- **`bootstrap.sh` has not been run end-to-end here** (it pulls several GB and
  starts four containers). First run should be watched.
- **Interactive-embedding CSP** (`frame-ancestors`) extends Superset's shipped
  Talisman default; confirm framing actually works against the running image
  before relying on it.
- **Top-bar background stays white** by design (§4) — not a bug.

---

## 10. Development & tests

The extension is pure-logic where it matters, so the unit tests run without
Docker or a Superset install:

```bash
PYTHONPATH=. python -m pytest -q     # 33 tests
```

New logic is added test-first. `aisc_ext/branding.py` (the branding resolution)
was built this way; the comments/reviews/security/audit tests carry over from the
prior build.

---

## 11. Repository layout

```
superset-overlay/
├── Dockerfile              # 4 lines: stock image + 3 pip deps. No source, no branding.
├── docker-compose.yml      # stock image + bind-mounts. Serves :8188. No sidecar/worker.
├── superset_config.py      # the config overlay (mounted on PYTHONPATH)
├── aisc_ext/               # extension package (mounted; never copied into Superset)
│   ├── branding.py         # env → branding resolution (unit-tested)
│   ├── comments/           # model, service, REST api, FAB view
│   ├── reviews/            # model, service, REST api, FAB view
│   ├── event_logger.py     # EVENT_LOGGER → immudb
│   ├── audit.py            # immudb clerk
│   ├── security.py, sso.py # Keycloak SecurityManager
├── branding/
│   ├── aisc/laif_logo.png  # default tenant logo (Luxembourg AI Factory)
│   └── README.md           # how to add a company
├── scripts/bootstrap.sh    # automated download + first-run init
├── tests/                  # unit tests (no Docker needed)
├── .env.example            # copy to .env
├── DECISIONS.md            # why the architecture is the way it is
└── README.md               # this file
```

---

## License & governance

Apache-2.0 — see [`LICENSE.md`](LICENSE.md) and [`NOTICE.md`](NOTICE.md). This
project contains no Apache Superset source; it runs the stock `apache/superset`
image unmodified. "Apache Superset" is a trademark of the Apache Software
Foundation; the Luxembourg AI Factory logo is not covered by the Apache license
(see NOTICE).

Contribution and governance docs: [`CONTRIBUTING.md`](CONTRIBUTING.md),
[`GOVERNANCE.md`](GOVERNANCE.md), [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md),
[`SECURITY.md`](SECURITY.md), and the CLA text files. Background on the public
release is in [`OPEN_SOURCING.md`](OPEN_SOURCING.md).
