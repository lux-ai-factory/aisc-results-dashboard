# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""/aisc/back/: where the top menu's "← Back" leads (aisc_ext/back.py says where that is)."""
import os

from flask import redirect, session
from flask_appbuilder import BaseView, expose

from aisc_ext.back import target


class AiscBackView(BaseView):
    route_base = "/aisc/back"
    default_view = "back"

    @expose("/")
    def back(self):
        # Only a redirect to the launcher, which asks for sign-in itself: nothing here to protect.
        return redirect(target(session, os.environ.get("LAUNCHER_URL", "http://localhost:8100/")))
