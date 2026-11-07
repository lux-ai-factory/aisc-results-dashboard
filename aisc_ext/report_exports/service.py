# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""What a Save to report request may hold: one plot as an SVG, its name, tab, filter tags and a comment.

The SVG goes into reports, so it is checked: well formed, nothing that could run, nothing that could fetch. Pure: no
Superset import."""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ElementTree

MAX_BYTES = 2 * 1024 * 1024
MAX_COMMENT = 4000
MAX_NAME = 255
MAX_TAGS = 30
MAX_TAG = 500
#: elements that run, embed or fetch, and SVG animation (SMIL), which can set a link to javascript:
FORBIDDEN_ELEMENTS = {"script", "foreignobject", "iframe", "object", "embed", "link",
                      "animate", "set", "animatemotion", "animatetransform"}
_FETCHES = re.compile(r"url\(\s*['\"]?(?!#)", re.IGNORECASE)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _check_svg(text) -> None:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("the plot must be an SVG")
    if "<!doctype" in text.lower() or "<!entity" in text.lower():
        raise ValueError("the SVG must not declare a document type")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise ValueError("the plot must be an SVG") from None
    if _local(root.tag) != "svg":
        raise ValueError("the plot must be an SVG")
    for element in root.iter():
        if _local(element.tag) in FORBIDDEN_ELEMENTS:
            raise ValueError(f"the SVG must not hold a {_local(element.tag)} element")
        # ECharts writes its own style rules; one that could fetch something (an import, an outside url) is refused,
        # and so is any CSS escape (a backslash), which can spell url( so that the check above cannot see it
        style = element.text or ""
        if _local(element.tag) == "style" and ("@import" in style.lower() or _FETCHES.search(style) or "\\" in style):
            raise ValueError("the SVG's style must not point outside itself")
        for name, value in element.attrib.items():
            attribute = _local(name)
            if attribute == "style" and "\\" in value:
                raise ValueError("the SVG's style must not hold a CSS escape")
            if attribute.startswith("on"):
                raise ValueError("the SVG must not hold an event handler")
            if attribute in ("href", "src") and not value.startswith("#"):
                raise ValueError("the SVG must not point outside itself")
            if _FETCHES.search(value):
                raise ValueError("the SVG must not point outside itself")


def placed_chart_names(position: dict, slice_names: dict) -> set[str]:
    """The names a saved plot may take on a dashboard: each chart placed in its layout, by its own name (slice_names:
    chart id -> name) and by the name the dashboard gives it there."""
    names = set()
    for node in position.values():
        if isinstance(node, dict) and node.get("type") == "CHART":
            meta = node.get("meta") or {}
            if meta.get("chartId") in slice_names:
                names.add(slice_names[meta["chartId"]])
                if meta.get("sliceNameOverride"):
                    names.add(meta["sliceNameOverride"])
    return {n.strip() for n in names if n and n.strip()}


def _tags(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_TAGS or not all(isinstance(t, str) for t in value):
        raise ValueError("the tags must be a short list of text")
    return [t.strip()[:MAX_TAG] for t in value if t.strip()]


def read_plot(body: dict) -> dict:
    """{svg (bytes), sha256, size, chart, tab, tags, comment}; ValueError when it cannot be kept."""
    chart = str(body.get("chart") or "").strip()
    if not chart:
        raise ValueError("the plot needs a name")
    text = body.get("svg")
    if isinstance(text, str) and len(text.encode()) > MAX_BYTES:
        raise ValueError(f"the plot is too large: at most {MAX_BYTES // (1024 * 1024)} MB")
    _check_svg(text)
    comment = str(body.get("comment") or "").strip()
    if len(comment) > MAX_COMMENT:
        raise ValueError(f"the comment is too long: at most {MAX_COMMENT} characters")
    data = text.encode()
    return {"svg": data, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "chart": chart[:MAX_NAME],
            "tab": str(body.get("tab") or "").strip()[:MAX_NAME], "tags": _tags(body.get("tags")), "comment": comment}
