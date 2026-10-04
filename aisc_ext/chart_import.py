# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Extra charts from a Superset export ZIP, into one plugin's tile, as the person's own (plugin dashboards
2026-10-04, T7). The view is aisc_ext/import_view.py; this is the rewrite it applies, pure Python:

- every chart reads this project's results dataset, through this project's connection: the ZIP's own
  connection and dataset are dropped, never imported (they could name another database and its password);
- every chart gets an id of its own in this project: Superset imports charts by id, so the same file imported in
  two projects would otherwise make one project's chart the other's;
- any AISC mark goes: an imported chart is the person's, and AISC never changes it."""
from __future__ import annotations

import io
import uuid
import zipfile

import yaml

from aisc_ext import charts as aisc_charts

_NAMESPACE = uuid.UUID("0d9a6c2e-5f1b-4a3c-8e7d-6b5a4c3d2e1f")
_AISC_KEYS = ("aisc_chart_id", "aisc_plugin", "aisc_project", "aisc_starter")


def _read(data: bytes) -> dict[str, str]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("this is not a ZIP: export a chart from Superset (its menu, Download, Export to YAML)") from None
    out = {}
    for name in z.namelist():
        if name.endswith("/"):
            continue
        parts = name.split("/", 1)                     # Superset's export puts everything in one folder
        out[parts[1] if len(parts) == 2 and not parts[0].endswith(".yaml") else name] = z.read(name).decode("utf-8")
    return out


def rewrite(data: bytes, *, pid: str, source: dict) -> tuple[dict[str, str], list[dict]]:
    """The bundle to import into this project, and its charts as [{"uuid", "name"}]."""
    files = _read(data)
    meta = yaml.safe_load(files.get("metadata.yaml") or "{}") or {}
    if meta.get("type") != "Slice":
        raise ValueError("this is not a chart export: export charts (one or several), not a dashboard or a dataset")
    out = {"metadata.yaml": files["metadata.yaml"]}
    out.update(aisc_charts._source_files(**source))
    imported = []
    for path, text in files.items():
        if not path.startswith("charts/"):
            continue
        chart = yaml.safe_load(text)
        own = str(uuid.uuid5(_NAMESPACE, f"{pid}:{chart['uuid']}"))
        params = {k: v for k, v in (chart.get("params") or {}).items() if k not in _AISC_KEYS}
        params.pop("datasource", None)
        chart.update(uuid=own, dataset_uuid=source["dataset_uuid"], params=params)
        out[f"charts/{own}.yaml"] = yaml.safe_dump(chart, sort_keys=False, allow_unicode=True)
        imported.append({"uuid": own, "name": chart.get("slice_name") or own})
    if not imported:
        raise ValueError("the file holds no chart")
    return out, imported


def place_under_your_charts(position: dict, placed: list[dict]) -> dict:
    """The dashboard's layout with these charts ([{"id", "uuid", "name"}]) under "Your charts"; one already
    there is not added twice."""
    pos = {k: (dict(v) if isinstance(v, dict) else v) for k, v in position.items()}
    pos["GRID_ID"] = dict(pos["GRID_ID"], children=list(pos["GRID_ID"]["children"]))
    have = {v["meta"].get("uuid") for v in pos.values()
            if isinstance(v, dict) and v.get("type") == "CHART" and isinstance(v.get("meta"), dict)}
    for chart in placed:
        if chart["uuid"] in have:
            continue
        node_id = f"CHART-user-{chart['uuid'][:8]}"
        pos[node_id] = {"type": "CHART", "id": node_id, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                        "meta": {"chartId": chart["id"], "uuid": chart["uuid"], "width": 6, "height": 50,
                                 "sliceName": chart["name"]}}
        pos["GRID_ID"]["children"].append(node_id)
    return pos
