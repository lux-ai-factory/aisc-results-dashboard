# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
#
# The ONLY reason this image exists: add three Python libraries the stock image
# lacks. It copies no Superset source and no customization -- config, extension
# and branding are all bind-mounted at runtime (see docker-compose.yml). Upgrade
# Superset by bumping the tag on the next line; nothing else changes.
FROM apache/superset:4.1.1

USER root
RUN pip install --no-cache-dir immudb-py Authlib psycopg2-binary
# config + extension are mounted here at runtime; make sure it's importable
ENV PYTHONPATH=/app/pythonpath
USER superset
