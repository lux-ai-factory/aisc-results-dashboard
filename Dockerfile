# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
#
# The stock Superset image plus two Python packages it lacks. No Superset
# source and no customisation is copied in: the config, the extension and the
# branding are bind-mounted at runtime (see docker-compose.yml). Upgrade
# Superset by changing the tag on the next line.
FROM apache/superset:4.1.4@sha256:92e6bf4111b2192b2ff3b1b74252ae957f7237989662065c403afb3623da7e51

USER root
RUN pip install --no-cache-dir Authlib==1.8.0 psycopg2-binary==2.9.13
# superset_config.py and aisc_ext are mounted here at runtime
ENV PYTHONPATH=/app/pythonpath
USER superset
