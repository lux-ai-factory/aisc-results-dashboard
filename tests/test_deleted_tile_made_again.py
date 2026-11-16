"""A plugin's tile that someone deleted stays deleted by design, but the person who opens Visualisation for that test
must learn why there is no tile and be able to have it made again. The sync says the tile was deleted (not a bare
slug None, which reads as "no tile due"), and asking for the tile again makes it on the next sync."""
import importlib

import pytest

from tests.test_plugin_tiles import PID, PLUGIN, V1, Superset


@pytest.fixture
def tiles():
    return importlib.import_module("aisc_ext.plugin_tiles")


@pytest.fixture
def charts():
    return importlib.import_module("aisc_ext.charts")


def _deleted(tiles, charts):
    s = Superset()
    tiles.sync_plugin(PID, "mcas", PLUGIN, "Data Drift", "0.4.1", V1, store=s, importer=s)
    del s.dashboards[charts.plugin_slug(PID, PLUGIN)]
    return s


def test_the_sync_says_a_tile_was_deleted(tiles, charts):
    s = _deleted(tiles, charts)
    answer = tiles.sync_plugin(PID, "mcas", PLUGIN, "Data Drift", "0.4.1", V1, store=s, importer=s)
    assert answer.get("deleted") is True, f"a deleted tile reads as no tile at all: {answer}"


def test_a_deleted_tile_can_be_asked_for_again_and_is_made(tiles, charts):
    s = _deleted(tiles, charts)
    assert hasattr(tiles, "make_tile_again"), "nothing makes a deleted tile again: it stays deleted for good"
    answer = tiles.make_tile_again(PID, "mcas", PLUGIN, "Data Drift", "0.4.1", V1, store=s, importer=s)
    slug = charts.plugin_slug(PID, PLUGIN)
    assert answer["slug"] == slug and slug in s.dashboards, answer


def test_the_bridge_request_carries_the_ask_to_make_a_tile_again(tiles):
    body = {"plugin": "x::Y", "label": "Y", "version": "1.0", "project_name": "mcas", "visualizations": []}
    assert tiles.plugin_request(body)["again"] is False
    assert tiles.plugin_request({**body, "again": True})["again"] is True
    with pytest.raises(ValueError):
        tiles.plugin_request({**body, "again": "yes"})
