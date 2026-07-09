# Open-Sourcing the AISC Collaborative Assessment Dashboard — Licensing & Governance

> Companion to [`README.md`](./README.md). The README explains **what** the
> customization is and **how to run** it; this document explains what has to be
> true before the project can be released publicly: **licensing, trademark, and
> governance**.
>
> ⚠️ **Not legal advice.** The analysis below is an engineering-informed starting
> point. Anything with legal or institutional consequences (license choice,
> product name, redistribution of built images) should get sign-off from LIST /
> the AI Factory legal or open-source office before release.

---

## 1. What is being open-sourced (and what is not)

This repository is **not a fork of Apache Superset**. It is a thin customization
layer *on top of* the unmodified upstream image (see README §1–2):

| We ship (our original work) | We do **not** ship |
|---|---|
| `Dockerfile`, `docker-compose.yml` | Superset's source code |
| `superset_config.py` (config only) | any patched Superset file |
| `aisc_ext/` (our Python extension) | Superset's Python/JS internals |
| `proxy/nginx.conf`, `aisc/*.js`, `aisc/*.css` | vendored copies of dependencies |
| `branding/laif_logo.png`, docs, `tests/` | the results / metadata databases |

The `Dockerfile` pulls `apache/superset:4.1.1` from Docker Hub **at build time**.
So publishing *this repository* mostly publishes **our own code**. Publishing a
**pre-built image** (that layers on top of `apache/superset`) is a different act
with heavier obligations — see §3.2.

---

## 2. How it differs & how it's used (summary → README)

Full detail lives in the README; the one-paragraph version for newcomers:

- **Differs:** stock Superset + (a) config-only branding, theme, feature-flag
  lockdown, and gated Keycloak SSO; (b) a small Python extension package
  (`aisc_ext/`) adding native comments, review-request/task assignment, and a
  tamper-evident immudb audit trail; (c) an nginx sidecar that injects the
  comments widget + CSS and rewrites CSP — **no Superset source is patched**.
  See README §2 (divergence table) and §3 (each customization).
- **Used as:** the **Collaborative Assessment Dashboard** of the AI Assessment
  Sandbox — multi-disciplinary reviewers explore the shared read-only Testing
  DB, comment per-chart and overall, and assign review tasks to stakeholder
  groups; every action is audited. See README §3.4–3.5 and §7 (scope boundary).

---

## 3. Licensing

### 3.1 Upstream: Apache Superset = Apache License 2.0

Apache-2.0 is **permissive** (not copyleft). It lets you use, modify, extend,
redistribute, and sublicense, **including in closed or differently-licensed
work**, provided you honor its attribution terms. Crucially:

- Building on top of / configuring / extending Superset imposes **no obligation**
  to open-source `aisc_ext/`, and does **not** "infect" our code with a license.
- The only obligations are **attribution-style** and they trigger on
  **distribution** (§3.2).

### 3.2 What triggers obligations — source repo vs. built image

| You distribute… | Apache-2.0 §4 obligations |
|---|---|
| **This source repo** (references upstream image, no Superset code inside) | Minimal. Good practice: credit Apache Superset in `README`/`NOTICE`. No Superset `LICENSE` copy is strictly required because no Superset code is included. |
| **A built Docker image** (`FROM apache/superset` + our layers), or any bundle containing Superset code | Full §4: (a) include a copy of the Apache-2.0 **License**; (b) retain all copyright/patent/trademark/attribution notices; (c) **carry forward Superset's `NOTICE`** file; (d) **state that you changed files** (a short "Modifications" note). The upstream image already carries its own `LICENSE`/`NOTICE`; don't strip them. |

**Recommendation:** even for the source-only release, add a top-level `NOTICE`
that credits Apache Superset and the added dependencies (§3.4). It's cheap and
removes ambiguity if someone later builds and redistributes an image.

### 3.3 License for **our** code — recommend Apache-2.0

Pick a license for `aisc_ext/`, config, and the sidecar assets. Recommended:
**Apache-2.0**, because it (a) matches upstream (least cognitive overhead for
contributors), (b) is permissive and widely trusted, and (c) includes an explicit
**patent grant** (MIT/BSD do not). MIT is a fine lighter-weight alternative if the
institution prefers it; avoid GPL/copyleft here — it would add friction for an
integration/deployment project and is unnecessary.

**To do:**
- Add a root **`LICENSE`** file (Apache-2.0 text).
- Add a short per-file header to source files (matches the header already used
  across `aisc_ext/`):
  ```
  # Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
  # SPDX-License-Identifier: Apache-2.0
  ```
- Record the copyright holder — confirm with LIST whether it's LIST, the AI
  Factory, or named authors (matters if the work was funded, e.g. Horizon
  Europe / national funding often carries open-source and IP-ownership terms).

### 3.4 Dependencies we add (verify versions before release)

The `Dockerfile` `pip install`s three packages beyond the base image. These are
pulled at build time (not vendored), so the **source repo** doesn't redistribute
them — but a **published image** does, so list them in `NOTICE`:

| Package | License (verify) | Note |
|---|---|---|
| `Authlib` | BSD-3-Clause | permissive |
| `immudb-py` | Apache-2.0 | permissive |
| `psycopg2-binary` | **LGPL-3.0 (with exceptions)** | ⚠️ weak-copyleft — fine when used unmodified/dynamically, but **flag it**: if you ship an image, note LGPL and don't statically modify it. Consider `psycopg[binary]` (LGPL too) or document the dependency clearly. |

Superset itself bundles many transitive deps under their own licenses; those are
covered by the **upstream image's** `NOTICE`, which you inherit — another reason
not to strip it from any image you publish.

---

## 4. Trademark — the actual sharp edge ⚠️

Copyright is the easy part; **trademark is where projects like this get into
trouble.** "**Apache Superset**", "**Superset**", and the Apache feather logo are
**trademarks of the Apache Software Foundation (ASF)**. Apache-2.0 grants
copyright and patent rights but **explicitly does *not* grant trademark rights**
(§6 of the license). ASF trademark policy: <https://www.apache.org/foundation/marks/>.

Practical rules:

- ✅ **Nominative/descriptive use is allowed:** "based on Apache Superset",
  "powered by Apache Superset", "an Apache Superset deployment". Always use the
  **full** "Apache Superset" on first mention and acknowledge the mark.
- ❌ **Don't use "Superset" as (part of) your product/repo name** in a way that
  implies ASF endorsement or that this *is* Superset. The current internal title
  **"AISC Superset"** is the kind of name ASF asks projects **not** to use.
- ❌ Don't use the Apache feather logo as if it were your product's logo.

**Recommendation:** name the released product for what it is in the sandbox — e.g.
**"AISC Collaborative Assessment Dashboard"**, with the tagline *"built on Apache
Superset."* Keep the AISC/AI-Factory branding (logo/theme) as the product
identity; reference Superset descriptively. This also matches what the UI already
does (it rebrands `APP_NAME`/`APP_ICON`), which Apache-2.0 permits.

Also confirm rights to **`branding/laif_logo.png`** (the AI Factory mark) — that's
LIST/AI-Factory's own trademark; make sure the open-source license on the *code*
does **not** implicitly license the *logo* (typical practice: "trademarks and
logos are excluded from the license; see `NOTICE`").

---

## 5. Governance

Two distinct governance questions — keep them separate:

### 5.1 Relationship to Apache / ASF governance

Apache Superset is governed by the **ASF** (a PMC, meritocratic committers, the
"Apache Way"). **We are downstream consumers, not part of that governance.** Our
deliberate no-fork design (README §5) means:

- We do **not** need to participate in ASF governance to ship this.
- If we ever want a change **in Superset itself**, that goes through the normal
  ASF contribution process upstream — but the architecture is specifically built
  to **avoid** needing that (extension seams + sidecar, not source patches).
- We track upstream by **version bump + re-test the 3 seams** (README §5), which
  is a maintenance policy, not a governance obligation.

### 5.2 Our own project governance (define before release)

Once public, the repo needs its own lightweight governance so external
contributions and security reports have a home:

| Concern | Recommended artifact |
|---|---|
| Who decides / merges | `MAINTAINERS.md` (named maintainers + areas) |
| How to contribute | `CONTRIBUTING.md` (build, test via §6 TDD, PR flow) |
| Contribution IP / provenance | **DCO** (`Signed-off-by`) — lightweight; or a CLA if the institution requires one. (ASF uses ICLAs; for our own repo, DCO is usually enough.) |
| Behavior | `CODE_OF_CONDUCT.md` (e.g. Contributor Covenant) |
| Vulnerability reporting | `SECURITY.md` (private disclosure contact + SLA) — important: this app does auth, RBAC, audit, and SSO |
| Releases / versioning | short policy: our version is independent of Superset's; note the tested `apache/superset` tag in each release |

### 5.3 Institutional sign-off

Because this is a LIST / AI Factory asset (and possibly grant-funded), before
release confirm: (a) IP ownership / right to release, (b) any funder open-source
mandate or required license, (c) approval to use the AI Factory branding in a
public repo, (d) that the audit/SSO security posture is acceptable to publish.

---

## 6. Pre-release checklist

- [x] **Scrub data:** no databases or sample data in the repo; demo seeds live in
      the **demo repo** (`seed/dashboard/`). `.gitignore` excludes `*.db`,
      `*.sqlite*`, `.env`, `.venv/`, `__pycache__/`.
- [x] **`LICENSE.md`** — Apache-2.0 (the AISC org's standard, copied from the org template).
- [x] **`NOTICE.md`** — credits Apache Superset (+ trademark disclaimer), added deps
      incl. the psycopg2 LGPL note, and excludes the AI Factory logo from the code license.
- [x] **Per-file SPDX headers** on all `aisc_ext/`, config, and test sources.
- [x] **Rename** done: "AISC Collaborative Assessment Dashboard — built on Apache
      Superset" (README/FEATURES/COLORS titles; `APP_NAME` was already "AI Assessment Sandbox").
- [x] Governance files: `CONTRIBUTING.md` (org template + repo notes, implicit CLA),
      `GOVERNANCE.md` (SnT+LIST model), `SECURITY.md`, `MAINTAINERS.md`, org CLA texts.
- [x] **Secrets sweep:** `SUPERSET_SECRET_KEY`, `SUPERSET_DB_PASSWORD`,
      `IMMUDB_USER`/`IMMUDB_PASSWORD` are env-driven via `.env` (dev defaults
      documented as dev-only; see `SECURITY.md` hardening checklist).
- [ ] Confirm dependency licenses at the pinned versions (§3.4) at release time.
- [ ] Institutional sign-off (§5.3) — LIST/AI Factory legal + maintainers.

---

## 7. TL;DR

- **Copyright:** Apache-2.0 upstream is permissive → **no contamination**, no
  obligation to open our code. License **our** code **Apache-2.0** (add `LICENSE`
  + `NOTICE` + SPDX headers).
- **Distribution:** source-only release = minimal duty (just attribute). Publishing
  a **built image** = full Apache-2.0 §4 (keep Superset's `LICENSE`/`NOTICE`, note
  changes) + carry the `psycopg2` **LGPL** note.
- **Trademark is the real constraint:** don't name it "…Superset"; use "built on
  Apache Superset." Exclude logos from the code license.
- **Governance:** we're **downstream** of ASF (no obligation there); we must stand
  up **our own** lightweight governance (CONTRIBUTING / CoC / SECURITY / DCO) and
  get **institutional sign-off**.
