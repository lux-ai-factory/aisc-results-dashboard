# Copyright (c) 2025-2026 University of Luxembourg (SnT) and Luxembourg Institute of Science and Technology (LIST)
# SPDX-License-Identifier: Apache-2.0
"""A tile per plugin per project (plugin dashboards 2026-10-04, T4).

sync_plugin makes or updates one plugin's dashboard from its default charts, through Superset's import, and
keeps what people put under "Your charts". The fake importer behaves as Superset 4.1.1's does (read in its
code, 2026-10-05): the bundle's layout replaces the dashboard's, its charts are written, a person's chart
node keeps the chart id it has, and charts are linked to the dashboard only until the first one of the layout
that is not in the bundle (it walks a set, so which ones get linked is luck). The sync must not depend on it."""
import copy
import importlib
import uuid

import pytest
import yaml

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")
PLUGIN = "data-monitor::DataDriftPlugin"
COLUMNS = ["score", "metric", "tool", "run", "run_order", "feature", "target_label"]
V1 = [{"chart_type": "bars", "metrics": ["Drift Score"], "title": "Drift Score"},
      {"chart_type": "bars", "metrics": ["psi"], "title": "PSI per feature", "group_by_dimensions": ["feature"]}]
V2 = [{"chart_type": "bars", "metrics": ["Drift Score"], "title": "Drift Score"},
      {"chart_type": "table", "metrics": ["psi", "smd"], "title": "Drift tests per feature",
       "group_by_dimensions": ["feature"]}]


@pytest.fixture
def tiles():
    return importlib.import_module("aisc_ext.plugin_tiles")


@pytest.fixture
def charts():
    return importlib.import_module("aisc_ext.charts")


class Superset:
    """What the tile code reads and writes, and an importer that behaves as Superset's."""

    def __init__(self, with_project=True):
        self.charts = {}            # uuid -> {"id", "uuid", "name", "params"}
        self.dashboards = {}        # slug -> {"position", "slices": set(chart ids), "roles", "metadata"}
        self.next_id = 100
        self.imports = []
        self.latest = "Run 2 · 04 Oct 2026, 20:39"
        self.with_project = with_project
        from aisc_ext.projects import ENGINE_RESULTS_COLUMNS, engine_results_sql
        self.dataset = {"sql": engine_results_sql(), "columns": [c[0] for c in ENGINE_RESULTS_COLUMNS]}
        self.upserts = []
        self.events = []            # "lock", "unlock" and each import, in order

    # -- what the tile code reads and writes --
    def source(self, pid):
        if not self.with_project:
            return None
        return {"dataset_uuid": "aaaaaaaa-0000-4000-8000-000000000001", "dataset_name": f"engine_results_{HEX}",
                "database_uuid": "bbbbbbbb-0000-4000-8000-000000000001", "database_name": "AISC Controls mcas",
                "sqlalchemy_uri": "postgresql+psycopg2://dashboard_ro:XXXXXXXXXX@postgres:5432/x",
                "columns": list(self.dataset["columns"])}

    def dataset_sql(self, pid):
        return self.dataset["sql"] if self.with_project else None

    def upsert(self, kind, key, spec):
        self.upserts.append((kind, key, spec))
        if kind == "dataset":
            self.dataset = {"sql": spec["sql"], "columns": [c[0] for c in spec["columns"]]}

    def project_lock(self, pid):
        import contextlib

        @contextlib.contextmanager
        def held():
            self.events.append("lock")
            try:
                yield
            finally:
                self.events.append("unlock")
        return held()

    def latest_run(self, pid, label):
        return self.latest

    def chart_id(self, chart_uuid):
        c = self.charts.get(chart_uuid)
        return c["id"] if c else None

    def dashboard_state(self, slug):
        d = self.dashboards.get(slug)
        if d is None:
            return None
        by_id = {c["id"]: c for c in self.charts.values()}
        return {"position": copy.deepcopy(d["position"]),
                "charts": [{"id": i, "uuid": by_id[i]["uuid"], "aisc": "aisc_chart_id" in by_id[i]["params"]}
                           for i in sorted(d["slices"]) if i in by_id]}

    def link_charts(self, slug, chart_uuids):
        self.dashboards[slug]["slices"] |= {self.charts[u]["id"] for u in chart_uuids if u in self.charts}

    def delete_charts(self, chart_uuids):
        for u in chart_uuids:
            c = self.charts.pop(u, None)
            if c:
                for d in self.dashboards.values():
                    d["slices"].discard(c["id"])

    def set_dashboard_roles(self, slug, roles):
        self.dashboards[slug]["roles"] = list(roles)

    # -- Superset's import --
    def _write_charts(self, files):
        written = {}
        for path, text in files.items():
            if path.startswith("charts/"):
                c = yaml.safe_load(text)
                if c["uuid"] not in self.charts:
                    self.charts[c["uuid"]] = {"id": self.next_id, "uuid": c["uuid"]}
                    self.next_id += 1
                self.charts[c["uuid"]].update(name=c["slice_name"], params=c["params"])
                written[c["uuid"]] = self.charts[c["uuid"]]["id"]
        return written

    def import_charts(self, files):
        self.imports.append(("charts", files))
        self.events.append("charts")
        self._write_charts(files)

    def import_dashboard(self, files):
        self.imports.append(("dashboard", files))
        self.events.append("dashboard")
        written = self._write_charts(files)
        (dash,) = [yaml.safe_load(t) for p, t in files.items() if p.startswith("dashboards/")]
        pos = dash["position"]
        for node in pos.values():
            if isinstance(node, dict) and node.get("type") == "CHART" and node["meta"]["uuid"] in written:
                node["meta"]["chartId"] = written[node["meta"]["uuid"]]
        d = self.dashboards.setdefault(dash["slug"], {"slices": set(), "roles": []})
        d.update(position=pos, metadata=dash["metadata"], title=dash["dashboard_title"])
        uuids = [n["meta"]["uuid"] for n in pos.values() if isinstance(n, dict) and n.get("type") == "CHART"]
        for u in reversed(uuids):              # stops at the first chart not in the bundle, as Superset does
            if u not in written:
                break
            d["slices"].add(written[u])

    # -- a person's own chart, saved and added to the dashboard --
    def add_user_chart(self, slug, name="Levene per feature (mine)"):
        u = str(uuid.uuid4())
        self.charts[u] = {"id": self.next_id, "uuid": u, "name": name, "params": {"viz_type": "table"}}
        self.next_id += 1
        d = self.dashboards[slug]
        d["slices"].add(self.charts[u]["id"])
        node_id = f"CHART-{u[:6]}"
        d["position"][node_id] = {"type": "CHART", "id": node_id, "children": [], "parents": ["ROOT_ID", "GRID_ID"],
                                  "meta": {"chartId": self.charts[u]["id"], "uuid": u, "width": 4, "height": 50}}
        d["position"]["GRID_ID"]["children"].append(node_id)
        return u


def sync(tiles, s, visualizations=V1, version="0.4.1"):
    return tiles.sync_plugin(PID, "mcas", PLUGIN, "Data Drift", version, visualizations, store=s, importer=s)


def on_dashboard(s, slug):
    d = s.dashboards[slug]
    placed = {n["meta"]["uuid"] for n in d["position"].values() if isinstance(n, dict) and n.get("type") == "CHART"}
    linked = {c["uuid"] for c in s.charts.values() if c["id"] in d["slices"]}
    return placed, linked


# ── T4.1 to T4.3 ─────────────────────────────────────────────────────────────

def test_t4_1_a_sync_makes_the_plugins_dashboard_its_starter_and_its_defaults(tiles, charts):
    s = Superset()
    out = sync(tiles, s)
    slug = charts.plugin_slug(PID, PLUGIN)
    assert out == {"slug": slug, "charts": 2}
    assert [k for k, _ in s.imports] == ["charts", "dashboard"]
    assert charts.starter_uuid(PID, PLUGIN) in s.charts
    placed, linked = on_dashboard(s, slug)
    assert len(placed) == 2 and placed == linked
    assert charts.starter_uuid(PID, PLUGIN) not in placed                 # the starter stays off the dashboard
    assert s.dashboards[slug]["roles"] == [f"AiscProject_{HEX}"]
    assert s.dashboards[slug]["title"] == "mcas · Data Drift"
    run = next(f for f in s.dashboards[slug]["metadata"]["native_filter_configuration"] if f["name"] == "Run")
    assert run["defaultDataMask"]["filterState"]["value"] == [s.latest]


def test_t4_2_before_any_run_the_tile_says_to_run_the_test(tiles, charts):
    s = Superset()
    s.latest = None
    out = sync(tiles, s, visualizations=[])
    slug = charts.plugin_slug(PID, PLUGIN)
    assert out == {"slug": slug, "charts": 0} and [k for k, _ in s.imports] == ["dashboard"]
    codes = [n["meta"]["code"] for n in s.dashboards[slug]["position"].values()
             if isinstance(n, dict) and n.get("type") == "MARKDOWN"]
    assert any("No results yet" in c for c in codes) and not any("slice_id" in c for c in codes)


def markdown(s, slug):
    return [n["meta"]["code"] for n in s.dashboards[slug]["position"].values()
            if isinstance(n, dict) and n.get("type") == "MARKDOWN"]


def test_t4_2_a_run_of_a_version_with_no_default_charts_says_so_and_offers_the_starter(tiles, charts):
    """The plugin ran, but its version declares no default charts (LangBiTe 0.2.4): the tile says that, not
    "No results yet", and the starter is there to build charts of one's own."""
    s = Superset()
    out = sync(tiles, s, visualizations=[], version="0.2.4")
    slug = charts.plugin_slug(PID, PLUGIN)
    assert out == {"slug": slug, "charts": 0}
    codes = markdown(s, slug)
    assert not any("No results yet" in c for c in codes)
    assert any("Data Drift 0.2.4 declares no default charts" in c for c in codes)
    starter = s.charts[charts.starter_uuid(PID, PLUGIN)]
    assert any(f"slice_id={starter['id']}" in c for c in codes)


def test_t4_9_a_stale_results_dataset_is_brought_up_to_date_before_the_tile(tiles, charts):
    """A project registered by older dashboard code has the dataset without the run columns (the stack's
    restart order, 2026-10-05): the sync rewrites it first, and the bundle names the current columns."""
    from aisc_ext.projects import ENGINE_RESULTS_COLUMNS, engine_results_sql
    s = Superset()
    s.dataset = {"sql": "SELECT 1 AS score", "columns": ["score", "metric", "tool", "target_label"]}
    sync(tiles, s)
    (kind, key, spec), = s.upserts
    assert (kind, key) == ("dataset", f"engine_results_{HEX}")
    assert spec["sql"] == engine_results_sql() and spec["database"] == "AISC Controls mcas"
    assert spec["aisc_project"] == PID and spec["metrics"]
    assert spec["columns"] == [list(c) for c in ENGINE_RESULTS_COLUMNS]
    dataset_file = next(yaml.safe_load(t) for p, t in s.imports[-1][1].items() if p.startswith("datasets/"))
    assert "run" in [c["column_name"] for c in dataset_file["columns"]]


def test_t4_9_a_current_results_dataset_is_left_alone(tiles):
    s = Superset()
    sync(tiles, s)
    assert s.upserts == []


def test_t4_10_a_sync_holds_the_projects_lock_around_everything_it_writes(tiles):
    """Two syncs of a project at once both made its new dashboard, and one failed on the slug (2026-10-05):
    a sync holds the project's lock from reading the dataset to setting the dashboard's roles."""
    s = Superset()
    s.dataset = {"sql": "SELECT 1 AS score", "columns": ["score"]}
    real_upsert = s.upsert

    def upsert(kind, key, spec):
        s.events.append("refresh")
        real_upsert(kind, key, spec)
    s.upsert = upsert
    sync(tiles, s)
    assert s.events == ["lock", "refresh", "charts", "dashboard", "unlock"]


def test_t4_10_the_lock_is_released_when_the_sync_fails(tiles):
    s = Superset()

    def boom(files):
        raise RuntimeError("import failed")
    s.import_dashboard = boom
    with pytest.raises(RuntimeError):
        sync(tiles, s)
    assert s.events[-1] == "unlock"


def test_t4_3_a_second_sync_changes_nothing(tiles, charts):
    s = Superset()
    sync(tiles, s)
    before = (sorted(s.charts), copy.deepcopy(s.dashboards))
    sync(tiles, s)
    assert sorted(s.charts) == before[0]
    slug = charts.plugin_slug(PID, PLUGIN)
    assert s.dashboards[slug]["slices"] == before[1][slug]["slices"]
    assert s.dashboards[slug]["position"]["GRID_ID"] == before[1][slug]["position"]["GRID_ID"]


# ── T4.4 a new plugin version ────────────────────────────────────────────────

def test_t4_4_a_new_version_replaces_its_defaults(tiles, charts):
    s = Superset()
    sync(tiles, s, V1, "0.4.1")
    dropped = charts.chart_uuid(PID, PLUGIN, 1, "PSI per feature")
    kept = charts.chart_uuid(PID, PLUGIN, 0, "Drift Score")
    kept_id = s.charts[kept]["id"]
    sync(tiles, s, V2, "0.4.2")
    added = charts.chart_uuid(PID, PLUGIN, 1, "Drift tests per feature")
    assert dropped not in s.charts and added in s.charts
    assert s.charts[kept]["id"] == kept_id                                  # updated in place, same chart
    placed, linked = on_dashboard(s, charts.plugin_slug(PID, PLUGIN))
    assert placed == linked == {kept, added}
    header = next(n for n in s.dashboards[charts.plugin_slug(PID, PLUGIN)]["position"].values()
                  if isinstance(n, dict) and n.get("id") == "HEADER-aisc-defaults")
    assert header["meta"]["text"] == "Default charts · Data Drift 0.4.2"


# ── T4.5 people's charts ─────────────────────────────────────────────────────

def test_t4_5_a_persons_chart_stays_in_its_place_through_a_new_version(tiles, charts):
    s = Superset()
    slug = charts.plugin_slug(PID, PLUGIN)
    sync(tiles, s, V1, "0.4.1")
    mine = s.add_user_chart(slug)
    sync(tiles, s, V2, "0.4.2")                    # the fake import links nothing past the person's chart
    placed, linked = on_dashboard(s, slug)
    assert mine in placed and mine in linked and mine in s.charts
    assert placed == linked                                                   # every default linked anyway
    grid = s.dashboards[slug]["position"]["GRID_ID"]["children"]
    yours = grid.index("HEADER-aisc-yours")
    mine_node = next(k for k, n in s.dashboards[slug]["position"].items()
                     if isinstance(n, dict) and n.get("meta", {}).get("uuid") == mine)
    assert grid.index(mine_node) > yours
    assert s.dashboards[slug]["position"][mine_node]["meta"]["chartId"] == s.charts[mine]["id"]


def test_t4_5_a_persons_chart_with_no_place_goes_under_your_charts(tiles, charts):
    s = Superset()
    slug = charts.plugin_slug(PID, PLUGIN)
    sync(tiles, s)
    mine = s.add_user_chart(slug)
    node = next(k for k, n in s.dashboards[slug]["position"].items()
                if isinstance(n, dict) and n.get("meta", {}).get("uuid") == mine)
    del s.dashboards[slug]["position"][node]                    # linked to the dashboard, placed nowhere
    s.dashboards[slug]["position"]["GRID_ID"]["children"].remove(node)
    sync(tiles, s)
    pos = s.dashboards[slug]["position"]
    grid = pos["GRID_ID"]["children"]
    placed = [k for k in grid if pos[k].get("type") == "CHART" and pos[k]["meta"]["uuid"] == mine]
    assert placed and grid.index(placed[0]) > grid.index("HEADER-aisc-yours")


def test_t4_5_the_aisc_blocks_are_not_copied_into_your_charts(tiles, charts):
    s = Superset()
    slug = charts.plugin_slug(PID, PLUGIN)
    sync(tiles, s)
    sync(tiles, s)
    grid = s.dashboards[slug]["position"]["GRID_ID"]["children"]
    assert grid.count("MARKDOWN-aisc-starter") == 1 and grid.count("HEADER-aisc-yours") == 1


def test_an_unknown_project_is_refused(tiles):
    with pytest.raises(LookupError):
        sync(tiles, Superset(with_project=False))


# ── T4.8 the bridge's request, validated before it reaches Superset ─────────

@pytest.mark.parametrize("body, message", [
    ({}, "plugin"),
    ({"plugin": "x::Y", "label": "", "version": "1"}, "label"),
    ({"plugin": "x::Y", "label": "Y", "version": "1", "visualizations": "nope"}, "visualizations"),
    ({"plugin": "x::Y", "label": "Y", "version": "1", "visualizations": [{"metrics": ["a"]}]}, "chart_type"),
])
def test_t4_8_a_malformed_request_is_refused_with_what_is_wrong(tiles, body, message):
    with pytest.raises(ValueError, match=message):
        tiles.plugin_request(body)


def test_t4_8_a_request_names_the_plugin_and_its_charts(tiles):
    req = tiles.plugin_request({"plugin": "x::Y", "label": "Y", "version": "1.0", "project_name": "mcas",
                                "visualizations": [{"chart_type": "bars", "metrics": ["a"], "title": "A"}]})
    assert req == {"plugin": "x::Y", "label": "Y", "version": "1.0", "project_name": "mcas",
                   "visualizations": [{"chart_type": "bars", "metrics": ["a"], "title": "A"}]}


def test_t4_10_the_lock_key_is_a_signed_64_bit_number_of_the_project():
    """pg_advisory_lock takes a bigint: one per project, the same in every worker."""
    from aisc_ext.projects import project_lock_key
    key = project_lock_key(PID)
    assert isinstance(key, int) and -2**63 <= key < 2**63
    assert key == project_lock_key(PID.upper())
    assert key != project_lock_key("0b7f5c3e-2d7a-4c1e-9f64-3a1b2c3d4e5f")


def test_a_save_as_copy_of_a_default_is_the_persons_chart():
    """A default carries aisc_chart_id, its own uuid; 'Save as' keeps the params under a new uuid.
    Such a copy counted as a default the plugin dropped, and the next sync deleted it (code review
    2026-10-05). Only a chart whose aisc_chart_id is its own uuid is the sync's."""
    from aisc_ext.charts import made_by_sync

    cid = "8f1c5d2e-0000-4000-8000-000000000001"
    assert made_by_sync({"aisc_chart_id": cid, "aisc_plugin": "p"}, cid)
    assert not made_by_sync({"aisc_chart_id": cid, "aisc_plugin": "p"}, "9a9a9a9a-0000-4000-8000-000000000002")
    assert not made_by_sync({}, cid)


def test_a_plugins_metadata_with_markup_is_refused():
    """The label, titles, descriptions and metric names come from the plugin, which is third-party
    code, and become chart labels, headers and markdown on every viewer's dashboard (security review
    2026-10-05; Superset 4.1.1 has a stored XSS through chart labels). A string with markup, a
    control character, or past its length is refused before anything reaches Superset."""
    from aisc_ext.plugin_tiles import plugin_request

    good = {"plugin": "pkg::P", "label": "LangBiTe", "version": "0.2.6",
            "visualizations": [{"chart_type": "bar", "metrics": ["ageism | AISCTarget | en_us"],
                                "title": "Pass rate per concern", "description": "Share of passed cases."}]}
    assert plugin_request(good)["label"] == "LangBiTe"
    for bad in ({"label": "<img src=x onerror=alert(1)>"},
                {"visualizations": [{"chart_type": "bar", "metrics": ["<script>x</script>"]}]},
                {"visualizations": [{"chart_type": "bar", "metrics": ["m"], "title": "a\x00b"}]},
                {"visualizations": [{"chart_type": "bar", "metrics": ["m"], "description": "x" * 5000}]},
                {"version": "1\n<b>"}):
        with pytest.raises(ValueError):
            plugin_request({**good, **bad})
