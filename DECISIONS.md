# Design decisions

Short record of the choices that shaped this project, so they don't get
re-litigated. The through-line is a single constraint the user set:

> If a new version of Superset drops, it must be **impossible for us to break
> it.**

Everything below follows from that.

## 1. Overlay, not a fork — and stock image, not a source clone

**Decision:** Consume the published `apache/superset` Docker image, pinned by
tag. Do not `git clone` Superset's source, and do not modify it.

**Why:** Cloning source re-exposes us to build breakage, dependency drift, and
the temptation to patch — the fork maintenance burden we are trying to escape. A
pinned image is a sealed release artifact; upgrading is one tag change.

## 2. Dependencies via a 4-line Dockerfile, not "image-less"

**Decision:** A tiny `Dockerfile` does `FROM apache/superset:<tag>` plus
`pip install immudb-py Authlib psycopg2-binary`. Nothing else. Config, extension,
and branding are bind-mounted at runtime.

**Why:** The three deps can't be bind-mounted. The alternative — installing them
at container start via `PIP_ADDITIONAL_REQUIREMENTS` — only works on the published
image if you also override the start command, and it reinstalls on every boot
(slow, network-dependent, can fail offline). A build-once layer that adds
libraries touches no Superset source and is trivially upgrade-safe.

## 3. No nginx sidecar, no DOM injection

**Decision:** Removed the reverse-proxy sidecar that the prior build used to
inject JS/CSS into Superset's pages and rewrite its CSP.

**Why:** That injection coupled us to Superset's HTML/DOM selectors, which change
between versions — the single most upgrade-fragile thing in the old design.
Deleting it is the biggest step toward "can't break on upgrade."

## 4. Comments & reviews via native FAB views, not an injected widget

**Decision:** Keep the comments/reviews backend (models + REST API), and surface
them through Flask-AppBuilder `ModelView` pages under an "Assessment" menu.

**Why:** FAB views are rendered by Superset's own machinery through a public seam
(`FLASK_APP_MUTATOR` + `appbuilder.add_view`), so there is zero DOM coupling. The
old in-page widget was the only reason the sidecar existed; replacing it lets the
sidecar go. Trade-off accepted: the UX is a standard CRUD page, not a floating
in-context drawer.

## 5. Branding is env-driven and multi-tenant, applied at runtime

**Decision:** `APP_NAME`, `APP_ICON` and theme colors are read from `BRANDING_*`
env vars (`aisc_ext/branding.py`), defaulting to AISC. A company sets a few env
vars and mounts a logo; no rebuild.

**Why:** The goal is white-labeling for multiple companies off one image.
Runtime env + a mounted logo means the same image serves every tenant, and
rebranding is a restart, not a build. Only the primary color is required; shades
are derived.

## 6. Interactive embedding via native flags + shared SSO session

**Decision:** Enable `EMBEDDED_SUPERSET` / `EMBEDDABLE_CHARTS` and allow host
origins to frame the app via Talisman `frame-ancestors` (from
`EMBED_ALLOWED_ORIGINS`). Auth for the embedding host is the viewer's shared
Keycloak SSO session.

**Why:** To keep charts interactive (legend toggle, cross-filters) in another
dashboard, Superset must render them — so the embed is an iframe back to Superset,
configured entirely through native flags. Shared-SSO was chosen over guest tokens
for simplicity; the cost is `SameSite=None; Secure` cookies (needs HTTPS) and a
possible fallback to guest tokens under strict third-party-cookie policies.

## 7. The top-bar background color stays white

**Decision:** Do **not** recolor Superset's top navigation bar.

**Why:** Superset 4.1.1 has no configuration knob for the nav-bar background. The
prior build only colored it by injecting CSS through the sidecar. Recoloring it
by any means (CSS injection, nginx rewrite, source patch) is precisely the
customization decision #1–#3 forbid. Faced with "colored bar" vs "never breaks on
upgrade," the user chose the latter. Branding therefore comes from the logo, app
name, and theme accent colors; the bar itself is Superset's default white.

**Do not re-add nav CSS injection** without revisiting this decision.
