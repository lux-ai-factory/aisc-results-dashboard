# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
#
# The stock Superset image plus three Python packages it lacks. No Superset
# source and no customisation is copied in: the config, the extension and the
# branding are bind-mounted at runtime (see docker-compose.yml). Upgrade
# Superset by changing the tag on the next line.
FROM apache/superset:4.1.1

USER root
RUN pip install --no-cache-dir immudb-py Authlib psycopg2-binary
# superset_config.py and aisc_ext are mounted here at runtime
ENV PYTHONPATH=/app/pythonpath
USER superset
