# Security Policy

This application handles authentication (optionally via Keycloak SSO), role-based
access control, and a tamper-evident audit trail — security reports are taken
seriously.

## Reporting a vulnerability

Please do **not** open a public issue for security vulnerabilities. Instead,
report privately to the maintainers (see `MAINTAINERS.md`) or via the project's
private vulnerability reporting on the repository hosting platform. We aim to
acknowledge reports within 5 working days.

Please include: affected version/commit, reproduction steps, and impact
assessment if known.

## Scope

In scope: everything in this repository — `aisc_ext/` (comments, reviews, audit,
SSO/role mapping), `superset_config.py` (lockdown posture), the nginx sidecar
(CSP rewrite, asset injection) and the injected `aisc/comments.js` widget.

Out of scope: vulnerabilities in Apache Superset itself (report upstream via
https://superset.apache.org/docs/security/), in Keycloak, or in immudb.

## Deployment hardening checklist

- Regenerate `SUPERSET_SECRET_KEY`, `SUPERSET_DB_PASSWORD`, and the immudb
  credentials (`.env`) — never deploy the dev defaults.
- Replace the bootstrap `admin` account password immediately.
- Connect the results database with a **read-only** DB user.
- `PREVENT_UNSAFE_DB_CONNECTIONS` is on — keep it on (rejects unsafe DB URIs).
- Enable Keycloak SSO (`AISC_OAUTH=1`) only after registering the confidential
  client, and keep a break-glass admin DB account.
