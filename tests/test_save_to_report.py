"""The Save to report button: added through Superset's own hook, so Superset's code stays as it is."""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
HOOK = HERE / "templates_override" / "tail_js_custom_extra.html"
BUTTON = HERE / "branding" / "save-to-report" / "save-to-report.js"
LIBRARY = HERE / "branding" / "save-to-report" / "echarts.min.js"


def test_the_hook_loads_the_button_with_the_pages_nonce():
    text = HOOK.read_text()
    assert "save-to-report/save-to-report.js" in text and "nonce=" in text


def test_the_button_shows_only_on_a_dashboard_and_names_what_it_does():
    text = BUTTON.read_text()
    # which dashboard is open comes from dashboard-pages.js (tests/test_dashboard_pages.py runs it)
    assert "aiscDashboardPages.watch" in text and "Save to report" in text


def test_the_button_makes_a_vector_file_per_plot_with_the_filters_as_tags():
    text = BUTTON.read_text()
    assert "_echarts_instance_" in text and "renderToSVGString" in text and "renderer: 'svg'" in text
    assert "tags" in text and "html-to-image" not in text and "toPng" not in text


def test_the_library_is_the_published_echarts_5_5_1():
    digest = hashlib.sha256(LIBRARY.read_bytes()).hexdigest()
    assert digest == (HERE / "branding" / "save-to-report" / "echarts.min.js.sha256").read_text().split()[0]


def test_the_hook_renders_with_nothing_but_what_an_including_page_gives_it():
    """An included template sees no macros a page imported for itself: a name it lacks fails every Superset page."""
    jinja2 = __import__("pytest").importorskip("jinja2")
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    html = env.from_string(HOOK.read_text()).render(csp_nonce=lambda: "the-nonce", assets_prefix="")
    assert 'nonce="the-nonce"' in html
    assert env.from_string(HOOK.read_text()).render(assets_prefix="").count("<script") == 4      # no Talisman: no nonce


def test_the_button_sends_the_picture_with_the_csrf_token_to_the_export_route():
    text = BUTTON.read_text()
    assert "/api/v1/aisc_report_export/" in text and "X-CSRFToken" in text and "same-origin" in text


def test_the_save_route_is_granted_to_the_roles_that_open_dashboards():
    """A new API has no permission until a role is given one: without this every save answers Forbidden. The route
    itself then admits only a project's editors and admins."""
    source = (HERE / "superset_config.py").read_text()
    assert '"ReportExportApi": ("can_post",)' in source


def test_plots_are_saved_for_print_with_the_legend_below_and_dark_axis_names():
    text = BUTTON.read_text()
    assert "PRINT_WIDTH" in text and "PRINT_HEIGHT" in text
    assert "l.bottom = 0" in text and "axisName" in text and "DARK" in text


def test_the_tags_name_every_chosen_value_from_the_stored_filter_state_not_the_shortened_boxes():
    text = BUTTON.read_text()
    assert "native_filters_key" in text and "/filter_state/" in text and "native_filter_configuration" in text
    assert "ant-select-selection-item" not in text


def test_the_charts_on_screen_get_the_same_style_as_the_saved_plots():
    text = BUTTON.read_text()
    assert "styleOnScreen" in text and "function looks(" in text
    assert "looks(" in text[text.index("function forPrint"):text.index("function vector")]


def test_the_hook_names_the_scripts_version_so_a_browser_never_keeps_an_old_one():
    """Superset serves static files to be kept for a year: a changed script is only fetched under a new address."""
    import re
    html = HOOK.read_text()
    version = re.search(r"save-to-report\.js\?v=([0-9a-f]{12})", html)
    assert version and version.group(1) == hashlib.sha256(BUTTON.read_bytes()).hexdigest()[:12]


ASSISTANT = HERE / "branding" / "save-to-report" / "chart-assistant.js"


def test_the_hook_loads_the_chart_assistant_panel_with_its_version():
    import re
    version = re.search(r"chart-assistant\.js\?v=([0-9a-f]{12})", HOOK.read_text())
    assert version and version.group(1) == hashlib.sha256(ASSISTANT.read_bytes()).hexdigest()[:12]


def test_the_panel_talks_only_to_the_dashboards_own_door_with_the_csrf_token():
    text = ASSISTANT.read_text()
    assert "/api/v1/aisc_assistant/conversations" in text and "X-CSRFToken" in text and "same-origin" in text
    assert "chart-assistant:" not in text and ":8096" not in text


def test_a_proposal_is_marked_mock_data_and_shows_what_it_computes_and_its_query():
    text = ASSISTANT.read_text()
    assert "MOCK DATA" in text and "proposal.description" in text and "proposal.sql" in text


def test_the_models_words_are_shown_as_text_never_as_markup():
    text = ASSISTANT.read_text()
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text


def test_validate_sends_the_fingerprint_of_the_proposal_shown():
    text = ASSISTANT.read_text()
    assert "/validate" in text and "fingerprint: proposal.fingerprint" in text


def test_closing_the_panel_hides_it_and_keeps_the_conversation():
    # the panel's inline display:flex beats the hidden attribute: only its own display style hides it
    text = ASSISTANT.read_text()
    assert "box.style.display = 'none'" in text and "box.remove()" not in text
    assert ".hidden" not in text


def test_the_button_opens_a_closed_panel_again():
    text = ASSISTANT.read_text()
    assert "open.style.display = open.style.display === 'none' ? 'flex' : 'none'" in text


def test_the_conversation_survives_a_reload_of_the_page_in_the_same_tab():
    text = ASSISTANT.read_text()
    assert "sessionStorage" in text and "STORE_KEY" in text and "restore" in text


def test_the_panel_is_narrow():
    text = ASSISTANT.read_text()
    assert "width:420px" in text and "width:720px" not in text


def test_a_removed_plot_is_said_and_the_dashboard_reloads_to_show_it_gone():
    text = ASSISTANT.read_text()
    assert "d.removed" in text and "Removed" in text and "location.reload()" in text


def test_a_change_to_a_plot_says_which_plot_it_replaces_before_validating():
    text = ASSISTANT.read_text()
    assert "proposal.replaces" in text and "Validate: replace" in text


def test_a_conversation_the_assistant_no_longer_holds_is_started_again_once():
    text = ASSISTANT.read_text()
    assert "status === 404" in text and "conversation = null" in text


def test_validate_names_the_proposal_clicked_not_only_its_query():
    assert "proposal: proposal.id" in ASSISTANT.read_text()


def test_a_plot_changed_in_place_is_said_and_the_dashboard_reloads():
    text = ASSISTANT.read_text()
    assert "d.changed" in text and "Changed" in text


def test_every_write_of_the_button_and_the_panel_names_the_dashboards_slug_for_the_ledger():
    """The gateway's witness files a dashboard write under the project its slug names, read from ?dashboard= (as
    the Review page sends it); without it the relay rejects the event. The page's address may hold the dashboard's
    number, so the slug is read from Superset."""
    for script in (BUTTON, ASSISTANT):
        text = script.read_text()
        assert "'?dashboard=' + encodeURIComponent(" in text, script.name
        assert "result.slug" in text, script.name


ROW_COUNTS = HERE / "branding" / "save-to-report" / "row-counts.js"


def test_the_hook_loads_the_row_counts_with_their_version_before_the_button():
    """The counts are read from the answers the dashboard receives: the script that watches them comes first."""
    import re
    html = HOOK.read_text()
    version = re.search(r"row-counts\.js\?v=([0-9a-f]{12})", html)
    assert version and version.group(1) == hashlib.sha256(ROW_COUNTS.read_bytes()).hexdigest()[:12]
    assert html.index("row-counts.js") < html.index("save-to-report.js")


def test_each_saved_plot_sends_the_rows_its_chart_draws():
    """The count shown under the chart (row-counts.js), read for the chart the plot is drawn from."""
    text = BUTTON.read_text()
    assert "window.aiscRowCounts" in text and "data-test-chart-id" in text
    assert "rows: r.plot.rows" in text


def test_one_click_saves_all_its_plots_under_one_save_id():
    text = BUTTON.read_text()
    assert "save_id: saveId" in text
    # made once per panel, before any click: the plots are sent one after another under it, and a retry
    # after a refused plot finishes the same group
    assert text.index("var saveId =") < text.index("save.onclick") < text.index("chosen.reduce")
