#!/usr/bin/env bash
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
#
# Standalone setup: build the image, pull Postgres, Redis and immudb, start the
# stack of docker-compose.yml, and initialise the metadata database and a local
# admin user. Safe to re-run: applied migrations are skipped and an existing
# admin is kept. Not used inside the AISC stack.
#
#   scripts/bootstrap.sh              # .env (its secrets made if empty), then the stack
#   scripts/bootstrap.sh --env-only   # .env only
set -euo pipefail
cd "$(dirname "$0")/.."

# The secrets .env.example leaves empty on purpose (compose refuses to start without them), and the
# local admin's password. An empty one is made here, once; one already set is kept. Never printed.
SECRETS=(SUPERSET_SECRET_KEY SUPERSET_GUEST_TOKEN_SECRET SUPERSET_DB_PASSWORD IMMUDB_PASSWORD ADMIN_PASSWORD)

value_in() { awk -v n="$1" 'index($0, n "=") == 1 { print substr($0, length(n) + 2); exit }' .env; }

if [[ ! -f .env ]]; then
  echo "==> creating .env from .env.example"
  cp .env.example .env
fi
for name in "${SECRETS[@]}"; do
  if [[ -z "$(value_in "$name")" ]]; then
    fresh=$(openssl rand -hex 32)
    if grep -q "^$name=" .env; then
      NAME=$name VALUE=$fresh awk 'index($0, ENVIRON["NAME"] "=") == 1 { print ENVIRON["NAME"] "=" ENVIRON["VALUE"]; next } { print }' .env > .env.tmp
      mv .env.tmp .env
    else
      echo "$name=$fresh" >> .env
    fi
    echo "==> made $name in .env"
  fi
done
chmod 600 .env
[[ "${1:-}" == "--env-only" ]] && exit 0

ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(value_in ADMIN_PASSWORD)}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"

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

==> done. Dashboard: http://localhost:8188  (login: ${ADMIN_USER}; the password is ADMIN_PASSWORD in .env)

Next:
  - set AISC_MEMBERSHIP_DB_URI (dashboard_ro on the platform database) for sign-in memberships
  - project connections are registered by the platform's bridge, one per project database,
    on AISC_PROJECT_DB_HOSTPORT; nothing to register by hand
  - to white-label: see branding/README.md
  - to upgrade Superset: bump the tag in Dockerfile, then re-run this script
EOF
