# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The dashboard bridge: POST and DELETE /api/v1/aisc_project/<pid>, PUT /api/v1/aisc_project/<pid>/plugins.

The platform calls POST after it creates a project and DELETE before it drops
one; they create or remove that project's dashboard objects (aisc_ext.projects).
PUT .../plugins makes or updates one plugin's tile from its default charts
(aisc_ext.plugin_tiles; plugin dashboards 2026-10-04).
The call is authenticated by the X-AISC-Bridge-Token header, not by a session
cookie, so it is exempt from CSRF. Imported only inside Superset."""
import os

from flask import request
from flask_appbuilder.api import BaseApi, expose

from aisc_ext.plugin_tiles import plugin_request, sync_plugin
from aisc_ext.projects import (
    SupersetStore, authorize_bridge, dashboard_ro_password, register_project, unregister_project,
)


class ProjectBridgeApi(BaseApi):
    resource_name = "aisc_project"
    openapi_spec_tag = "AISC Project bridge"
    # Authenticated by token, never by cookie, so CSRF does not apply.
    csrf_exempt = True

    def _refused(self):
        status = authorize_bridge(request.headers, os.environ)
        return None if status is None else self.response(status, message="bridge token required")

    @expose("/<pid>", methods=["POST"])
    def register(self, pid):
        if (refused := self._refused()) is not None:
            return refused
        body = request.get_json(silent=True) or {}
        slug = str(body.get("slug") or pid)
        name = str(body.get("name") or slug)
        try:
            password = dashboard_ro_password(os.environ)
        except LookupError as exc:
            return self.response(503, message=str(exc))
        try:
            register_project(pid, slug, name, store=SupersetStore(), controls_password=password)
        except ValueError as exc:
            return self.response_400(message=str(exc))
        return self.response(200, message="registered")

    @expose("/<pid>", methods=["DELETE"])
    def unregister(self, pid):
        if (refused := self._refused()) is not None:
            return refused
        try:
            unregister_project(pid, store=SupersetStore())
        except ValueError as exc:
            return self.response_400(message=str(exc))
        return self.response(200, message="unregistered")

    @expose("/<pid>/plugins", methods=["PUT"])
    def sync_plugin_tile(self, pid):
        """Body: {plugin, label, version, project_name, visualizations}. 200 {slug, charts}; 400 what is wrong;
        404 a project the dashboard does not know."""
        if (refused := self._refused()) is not None:
            return refused
        try:
            req = plugin_request(request.get_json(silent=True) or {})
            store = SupersetStore()
            out = sync_plugin(pid, req["project_name"], req["plugin"], req["label"], req["version"],
                              req["visualizations"], store=store, importer=store)
        except LookupError as exc:
            return self.response_404(message=str(exc))
        except ValueError as exc:
            return self.response_400(message=str(exc))
        return self.response(200, **out)
