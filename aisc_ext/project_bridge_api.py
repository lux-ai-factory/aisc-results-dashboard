# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""The dashboard bridge: POST and DELETE /api/v1/aisc_project/<pid>.

The platform calls POST after it creates a project and DELETE before it drops
one; they create or remove that project's dashboard objects (aisc_ext.projects).
The call is authenticated by the X-AISC-Bridge-Token header, not by a session
cookie, so it is exempt from CSRF. Imported only inside Superset."""
import os

from flask import request
from flask_appbuilder.api import BaseApi, expose

from aisc_ext.projects import SupersetStore, authorize_bridge, register_project, unregister_project


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
            register_project(
                pid, slug, name,
                store=SupersetStore(),
                controls_password=os.environ.get("DASHBOARD_RO_PASSWORD", "dashboard_ro"),
            )
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
