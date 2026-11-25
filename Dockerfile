# syntax=docker/dockerfile:1.19
# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
#
# The stock Superset image plus two Python packages it lacks, and this deployment's own configuration, extension,
# branding and sign-in code, so that the image runs without a checkout. The development stack bind-mounts the same
# files over them (see docker-compose.yml). Upgrade Superset by changing the tag on the stock image line below.

# Stand-in for the `shared` build context. The baked stack (docker-compose.baked.yml) passes the aisc repository's
# shared/ folder under that name and its identity folder goes into the image; a build that passes none gets these
# stand-in packages, which raise ImportError, and the development stack mounts shared/identity over them.
FROM apache/superset:4.1.4@sha256:92e6bf4111b2192b2ff3b1b74252ae957f7237989662065c403afb3623da7e51 AS shared
USER root
RUN for p in aisc_identity aisc_redact aisc_service_client; do mkdir -p /identity/$p \
 && echo "raise ImportError('$p is a stand-in: build this image with docker-compose.baked.yml, which passes the aisc shared folder as the shared build context')" \
      > /identity/$p/__init__.py; done

# Stand-in for the `gateway` build context. The baked stack passes the aisc repository's dashboard-gateway/ folder under
# that name; a build that passes none gets these stand-in modules, which raise ImportError, and the development stack
# mounts the folder over them.
FROM apache/superset:4.1.4@sha256:92e6bf4111b2192b2ff3b1b74252ae957f7237989662065c403afb3623da7e51 AS gateway-stand-in
USER root
RUN mkdir /stand-in && for m in gateway_identity superset_gateway_config; do \
      echo "raise ImportError('$m is a stand-in: build this image with docker-compose.baked.yml, which passes the aisc dashboard-gateway folder as the gateway build context')" \
      > /stand-in/$m.py; done
FROM scratch AS gateway
COPY --from=gateway-stand-in /stand-in/ /

FROM apache/superset:4.1.4@sha256:92e6bf4111b2192b2ff3b1b74252ae957f7237989662065c403afb3623da7e51

USER root
RUN pip install --no-cache-dir Authlib==1.8.0 psycopg2-binary==2.9.13
ENV PYTHONPATH=/app/pythonpath
# the configuration and the extension
COPY --chmod=a=rX superset_config.py /app/pythonpath/superset_config.py
COPY --chmod=a=rX aisc_ext /app/pythonpath/aisc_ext
COPY --chmod=a=rX branding /app/superset/static/assets/branding
# Superset's hook for a deployment's own code: Save to report and the chart assistant panel
COPY --chmod=a=rX templates_override/tail_js_custom_extra.html /app/superset/templates/tail_js_custom_extra.html
# the shared identity rules (the ledger's delivery loop reads them) and the gateway's sign-in code, the folders the
# development stack mounts, without local environments and caches, read-only
COPY --chmod=a=rX --exclude=.venv --exclude=*.egg-info --exclude=**/__pycache__ --exclude=.pytest_cache \
     --exclude=.ruff_cache --from=shared /identity /app/pythonpath_identity
COPY --chmod=a=rX --exclude=**/__pycache__ --exclude=.ruff_cache --exclude=.pytest_cache --from=gateway . /app/pythonpath_gateway
USER superset
