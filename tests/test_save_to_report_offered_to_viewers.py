"""A person who may not save (a viewer) must not be offered a Save to report button that only refuses after the
plots are drawn and the comments typed. Runs the scripts in node through the harness of
test_save_to_report_answers.py."""
from tests.test_save_to_report_answers import run


def test_a_viewer_is_not_offered_a_save_that_will_be_refused(tmp_path):
    seen = run(tmp_path, {"plots": ["Pass rate"], "viewer": True})
    button = seen["button"]
    # no button, or a disabled one that says why: never one that refuses only after the plots and comments
    assert button is None or (button["disabled"] and button["title"]), \
        f"a viewer is offered an active Save to report button: {button}"


def test_an_editor_is_offered_the_save(tmp_path):
    seen = run(tmp_path, {"plots": ["Pass rate"]})
    assert seen["button"] and not seen["button"]["disabled"], seen
