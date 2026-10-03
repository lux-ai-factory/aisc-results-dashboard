#!/usr/bin/env bash
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
#
# Standalone setup: build the image, pull Postgres, Redis and immudb, start the
# stack of docker-compose.yml, and initialise the metadata database and a local
# admin user. Safe to re-run: applied migrations are skipped and an existing
# admin is kept. Not used inside the AISC stack.
set -euo pipefail
cd "$(dirname "$0")/.."

ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"

if [[ ! -f .env ]]; then
  echo "==> creating .env from .env.example (edit it, then re-run for prod)"
  cp .env.example .env
fi

echo "==> downloading Superset + supporting images (this is the 'automated download')"
docker compose build --pull        # pulls apache/superset:<tag> and adds three Python packages
docker compose pull superset-db superset-redis immudb

echo "==> starting the stack"
docker compose up -d

echo "==> waiting for the superset container to be running"
until [[ "$(docker compose ps -q superset)" ]]; do sleep 2; done

echo "==> initialising metadata DB + admin"
docker compose exec -T superset superset db upgrade
docker compose exec -T superset superset fab create-admin \
  --username "$ADMIN_USER" --firstname Admin --lastname User \
  --email "$ADMIN_EMAIL" --password "$ADMIN_PASSWORD" || true
docker compose exec -T superset superset init

cat <<EOF

==> done. Dashboard: http://localhost:8188  (login: ${ADMIN_USER} / ${ADMIN_PASSWORD})

Next:
  - set AISC_MEMBERSHIP_DB_URI (dashboard_ro on the platform database) for sign-in memberships
  - project connections are registered by the platform's bridge, one per project database,
    on AISC_PROJECT_DB_HOSTPORT; nothing to register by hand
  - to white-label: see branding/README.md
  - to upgrade Superset: bump the tag in Dockerfile, then re-run this script
EOF
