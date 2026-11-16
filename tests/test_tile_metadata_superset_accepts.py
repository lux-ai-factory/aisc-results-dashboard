"""Superset saves a dashboard's metadata back by itself (for one, the label colours when a person leaves the
dashboard): PUT /api/v1/dashboard/<id> with the stored json_metadata. Superset 4.1.4 checks that metadata against its
DashboardJSONMetadataSchema, which refuses any key it does not know with a 400. So the metadata a plugin's tile is
imported with must hold only keys Superset accepts back, or every one of those background saves is refused and
nobody is told."""
import importlib
import json

import pytest

from tests.test_plugin_tiles import PID, PLUGIN, V1

# The fields of DashboardJSONMetadataSchema in apache/superset 4.1.4 (superset/dashboards/schemas.py), the image the
# results dashboard is built from. Its Meta keeps marshmallow's default: an unknown key is an error.
SUPERSET_METADATA_FIELDS = {
    "native_filter_configuration", "chart_configuration", "global_chart_configuration",
    "timed_refresh_immune_slices", "filter_scopes", "expanded_slices", "refresh_frequency", "default_filters",
    "stagger_refresh", "stagger_time", "color_scheme", "color_namespace", "positions", "label_colors",
    "shared_label_colors", "map_label_colors", "color_scheme_domain", "cross_filters_enabled", "import_time",
    "remote_id", "filter_bar_orientation", "native_filter_migration",
    "show_native_filters",                 # removed by the schema's pre_load before it checks
}


@pytest.fixture
def charts():
    return importlib.import_module("aisc_ext.charts")


def test_superset_takes_back_the_metadata_a_plugins_tile_is_made_with(charts):
    import yaml
    files = charts.bundle(pid=PID, plugin=PLUGIN, label="Data Drift", version="0.4.1", visualizations=V1,
                          dataset_uuid="aaaaaaaa-0000-4000-8000-000000000001", dataset_name="engine_results_x",
                          database_uuid="bbbbbbbb-0000-4000-8000-000000000001", database_name="AISC mcas",
                          sqlalchemy_uri="postgresql+psycopg2://dashboard_ro:XXXXXXXXXX@postgres:5432/project_x",
                          columns=["score", "metric", "tool", "run", "run_order"], starter_chart_id=42,
                          default_version=1, default_runs=("Run 1",))
    (dashboard,) = [yaml.safe_load(t) for p, t in files.items() if p.startswith("dashboards/")]
    refused = sorted(set(dashboard["metadata"]) - SUPERSET_METADATA_FIELDS)
    assert not refused, ("Superset answers 400 to its own save of this dashboard's metadata, unknown fields: "
                         + json.dumps(refused))


# The markers' other home: the bridge records which project and plugin each tile it makes is, by the dashboard's
# uuid (which no one can change through Superset), and a tile is recognised by that record.

def test_a_sync_records_which_project_and_plugin_its_tile_is(charts):
    from aisc_ext import plugin_tiles
    from tests.test_plugin_tiles import Superset

    s = Superset()
    plugin_tiles.sync_plugin(PID, "mcas", PLUGIN, "Data Drift", "0.4.1", V1, store=s, importer=s)
    assert s.bindings == {charts.dashboard_uuid(PID, PLUGIN): (PID, PLUGIN)}


def test_a_tile_is_known_by_the_bridges_record_not_by_its_metadata():
    from types import SimpleNamespace as NS

    from aisc_ext import security
    from aisc_ext.projects import project_role_name

    tile_uuid = "cccccccc-0000-4000-8000-000000000001"
    tile = NS(uuid=tile_uuid, json_metadata="{}", created_by_fk=1, roles=[NS(name=project_role_name(PID))])
    other = NS(uuid="cccccccc-0000-4000-8000-000000000002", json_metadata="{}", created_by_fk=1,
               roles=[NS(name=project_role_name(PID))])
    found = security.plugin_tiles([tile, other], bridge_user_id=1, bindings={tile_uuid: (PID, PLUGIN)})
    assert found == [(tile, PID.lower())]
