# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""Extra charts from a Superset export ZIP, into one plugin's tile, as the person's own. The view is
aisc_ext/import_view.py; this is the rewrite it applies, pure Python:

- every chart reads this project's results dataset, through this project's connection: the ZIP's own
  connection and dataset are dropped, never imported (they could name another database and its password);
- every chart gets an id of its own in this project: Superset imports charts by id, so the same file imported in
  two projects would otherwise make one project's chart the other's;
- any AISC mark goes: an imported chart is the person's, and AISC never changes it."""
from __future__ import annotations

import io
import json
import uuid
import zipfile

import yaml

from aisc_ext import charts as aisc_charts

_NAMESPACE = uuid.UUID("0d9a6c2e-5f1b-4a3c-8e7d-6b5a4c3d2e1f")
_AISC_KEYS = ("aisc_chart_id", "aisc_plugin", "aisc_project", "aisc_starter")


#: What a chart export may unpack to, and how many files it may hold. An export of a few charts is a few
#: kilobytes; the upload cap bounds the ZIP only, and deflated zeros unpack about 1000:1.
MAX_UNPACKED_BYTES = 5 * 1024 * 1024
MAX_MEMBERS = 500


def _read(data: bytes) -> dict[str, str]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("this is not a ZIP: export a chart from Superset (its menu, Download, Export to YAML)") from None
    members = [i for i in z.infolist() if not i.filename.endswith("/")]
    if len(members) > MAX_MEMBERS:
        raise ValueError(f"the file holds more files than a chart export does ({MAX_MEMBERS} at most)")
    if sum(i.file_size for i in members) > MAX_UNPACKED_BYTES:
        raise ValueError("the file unpacks to more than a chart export can be (5 MB)")
    out = {}
    left = MAX_UNPACKED_BYTES
    for info in members:
        name = info.filename
        with z.open(info) as member:                   # read no more than is left, whatever the header says
            raw = member.read(left + 1)
        left -= len(raw)
        if left < 0:
            raise ValueError("the file unpacks to more than a chart export can be (5 MB)")
        parts = name.split("/", 1)                     # Superset's export puts everything in one folder
        out[parts[1] if len(parts) == 2 and not parts[0].endswith(".yaml") else name] = raw.decode("utf-8")
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


def import_into_tile(dashboard, pid: str, files: dict, charts: list[dict], *, store, session, run_import,
                     slices_by_uuid) -> None:
    """Import the rewritten charts and place them under "Your charts" on the tile `dashboard`.

    `run_import(files)` is Superset's import; `slices_by_uuid(uuids)` returns the imported charts as
    {uuid text: Slice}; `session` is Superset's. Holds the project's lock, as a tile sync does, and places
    the charts on the layout as it is once the lock is held (`session.refresh`), not as it was when the page
    was posted: otherwise a sync and an import on one tile write over each other's layout."""
    with store.project_lock(pid):
        run_import(files)
        session.refresh(dashboard)
        pieces = slices_by_uuid([c["uuid"] for c in charts])
        placed = [{"id": pieces[c["uuid"]].id, "uuid": c["uuid"], "name": c["name"]}
                  for c in charts if c["uuid"] in pieces]
        position = place_under_your_charts(json.loads(dashboard.position_json or "{}"), placed)
        dashboard.position_json = json.dumps(position)
        have = {s.id for s in dashboard.slices}
        dashboard.slices = list(dashboard.slices) + [pieces[c["uuid"]] for c in charts
                                                     if c["uuid"] in pieces and pieces[c["uuid"]].id not in have]
        session.commit()
