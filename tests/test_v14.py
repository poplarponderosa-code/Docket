import datetime as dt

from docket import aiprompt, capture, importer, modes, tour


def test_instructions_use_the_phrase_and_version():
    text = aiprompt.instructions("send to Docket")
    assert '"send to Docket"' in text and f"(v{aiprompt.VERSION})" in text
    assert "{" not in text.split("EXAMPLE")[0]          # every placeholder filled


def test_phrase_choice_and_custom():
    assert aiprompt.phrase_from({}) == aiprompt.DEFAULT_PHRASE
    assert aiprompt.phrase_from({"ai_phrase": "add to Docket"}) == "add to Docket"
    assert aiprompt.phrase_from({"ai_phrase": "custom", "ai_phrase_custom": "  “docket   this” "}) == "docket this"
    assert aiprompt.phrase_from({"ai_phrase": "custom", "ai_phrase_custom": ""}) == aiprompt.DEFAULT_PHRASE


def test_update_available():
    assert not aiprompt.update_available(0)               # never copied: nothing to update
    assert not aiprompt.update_available(aiprompt.VERSION)


def test_instruction_example_imports():
    example = aiprompt.instructions().split("EXAMPLE\n")[1]
    lists = importer.parse_text(example, "x", dt.date(2026, 11, 24))
    assert [t["name"] for t in lists] == ["Website launch", "Launch day"]
    assert lists[1]["kind"] == "checklist" and lists[1]["timer_on"]
    assert lists[1]["categories"] == ["Writing", "Admin"]
    assert lists[0]["items"][2]["link"] == "https://example.com"


def test_code_fences_ignored():
    pasted = "```text\n## A\nb\n```"
    assert capture.strip_fences(pasted) == "## A\nb"
    assert [i["name"] for i in importer.parse_text(pasted, "x")[0]["items"]] == ["b"]


def test_tour_steps_by_mode():
    basic = [s.key for s in tour.steps_for("basic")]
    pro = [s.key for s in tour.steps_for("pro")]
    assert basic[0] == "welcome" and basic[-1] == "done"
    assert "capture" not in basic and "timer" not in basic
    assert {"capture", "templates", "timer", "timelogs"} <= set(pro)
    for s in tour.STEPS:
        assert s.feature == "basic" or s.feature in modes.FEATURES


def test_tour_fills_keys():
    steps = tour.steps_for("advanced", {"capture_key": "F16", "show_key": "F13", "tick_key": "F14"})
    capture_step = next(s for s in steps if s.key == "capture")
    assert "F16" in capture_step.text and "{" not in capture_step.text


def test_mode_tour_only_new_steps():
    keys = [s.key for s in tour.steps_new_in("advanced", "pro")]
    assert keys[0] == "intro" and set(keys[1:]) == {"timer", "categories", "timelogs"}
    assert tour.steps_new_in("pro", "basic") == []


def test_offer_and_tips():
    assert tour.should_offer_tour({"setup_done": True, "tour_done": False})
    assert not tour.should_offer_tour({"setup_done": True, "tour_done": True})
    assert tour.tip_due({"tips_on": True, "tips_seen": []}, "panel")
    assert not tour.tip_due({"tips_on": True, "tips_seen": ["panel"]}, "panel")
    assert not tour.tip_due({"tips_on": False, "tips_seen": []}, "panel")


def test_diagnostics_log_and_crash_detection(tmp_path):
    from docket import diagnostics
    assert not diagnostics.previous_session_crashed(tmp_path)
    diagnostics.start(tmp_path, "9.9.9")
    try:
        diagnostics.note("pop out list 3")
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            diagnostics._excepthook(*sys.exc_info())
        assert diagnostics.previous_session_crashed(tmp_path)      # an error and no clean exit
        diagnostics.clean_exit()
        assert not diagnostics.previous_session_crashed(tmp_path)
        (tmp_path / "docket-crash.txt").open("a").write("Fatal Python error: Segmentation fault\n")
        assert diagnostics.previous_session_crashed(tmp_path)
        text = diagnostics.report(tmp_path)
        assert "pop out list 3" in text and "ValueError: boom" in text and "Segmentation fault" in text
    finally:
        import faulthandler
        faulthandler.disable()
        import sys
        sys.excepthook = sys.__excepthook__
        diagnostics._log_path = None
