#!/usr/bin/env bash
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
#
# One-shot: download the stock Superset instance + supporting images, start the
# overlay, and initialise the metadata DB + admin user. Idempotent-ish: safe to
# re-run; DB init is skipped by Superset if already applied.
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
docker compose build --pull        # pulls apache/superset:<tag> and layers the 3 deps
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
  - register your results DB (Settings -> Database Connections) using AISC_RESULTS_DB_URI
  - to white-label: see branding/README.md
  - to upgrade Superset: bump the tag in Dockerfile, then re-run this script
EOF
