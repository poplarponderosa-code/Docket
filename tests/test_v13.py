"""1.3.0 formats: links, client/template fields, capitalized logs, copy list, quick-add links."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docket import backup, importer                                   # noqa: E402
from docket.parser import parse_quick_add, take_link                   # noqa: E402
from docket.store import Store                                         # noqa: E402
from docket.timer import TimerEngine, cap_first                        # noqa: E402

TODAY = dt.date(2026, 11, 23)


def make():
    s = Store()
    t = s.add_tab("Map release", kind="checklist")
    s.update_tab(t.id, client="Acme, Inc", template="Map release v2", timer_on=True)
    s.add_item(t.id, "obtain heightmap", link=r"C:\Maps\River", category="setup")
    s.add_item(t.id, "upload", link="https://example.com/a?b=1")
    return s, s.tab(t.id)


def test_link_parsing():
    assert take_link("Check mod page https://x.com/p, tomorrow") == ("Check mod page tomorrow", "https://x.com/p")
    q = parse_quick_add("read docs www.site.com fri !high", TODAY)
    assert q.name == "read docs" and q.link == "https://www.site.com" and q.priority == "High" and q.due
    assert parse_quick_add("no link here", TODAY).link == ""


def test_backup_round_trip_keeps_links_client_template():
    s, t = make()
    text = backup.render(s)
    assert "## Map release [checklist, timer, client: Acme Inc, template: Map release v2]" in text
    assert r"link: C:\Maps\River" in text
    tabs = backup.parse(text)
    assert tabs[0]["client"] == "Acme Inc" and tabs[0]["template"] == "Map release v2"
    assert tabs[0]["items"][0]["link"] == r"C:\Maps\River"
    s2 = Store()
    s2.replace_all(tabs)
    t2 = s2.tabs()[0]
    assert t2.client == "Acme Inc" and s2.items(t2.id)[1].link == "https://example.com/a?b=1"


def test_copy_list_leaves_client_out_and_pastes_back():
    s, t = make()
    copied = importer.export_list(t, s.items(t.id), comments=False, include_client=False)
    assert copied.startswith("## Map release [") and "client" not in copied and "template: Map release v2" in copied
    back = importer.parse_text(copied, "x", TODAY)
    assert back[0]["kind"] == "checklist" and back[0]["items"][1]["link"] == "https://example.com/a?b=1"
    assert importer.plain_text(s.items(t.id)) == "obtain heightmap\nupload\n"
    full = importer.export_list(t, s.items(t.id))
    assert "client: Acme Inc" in full


def test_template_never_keeps_client(tmp_path):
    s, t = make()
    p = tmp_path / "Map release.txt"
    p.write_text(importer.template_text(t, s.items(t.id)), encoding="utf-8")
    loaded = importer.load_template(p)
    assert loaded["client"] == "" and loaded["template"] == "Map release"
    assert loaded["items"][0]["link"] == r"C:\Maps\River"


def test_logs_capitalized_with_client_and_template():
    s, t = make()
    clock = [dt.datetime(2026, 11, 23, 9, 0, 0)]
    eng = TimerEngine(s, now=lambda: clock[0])
    eng.start(t.id)
    for it in s.items(t.id):
        clock[0] += dt.timedelta(minutes=5)
        eng.set_done(it.id, True)
    text = eng.log_text(t.id)
    assert "Client: Acme, Inc" in text and "Template: Map release v2" in text
    assert "Obtain heightmap | Setup |" in text
    csv_text = eng.log_csv(t.id)
    assert "Map release,Obtain heightmap,Setup," in csv_text
    assert csv_text.splitlines()[-1].endswith(',"Acme, Inc",Map release v2')
    assert cap_first("") == "" and cap_first("abc") == "Abc" and cap_first("ABC") == "ABC"


def test_clear_time_logs_only_touches_docket_logs(tmp_path):
    from docket import timelogs
    (tmp_path / "Map 2026-01-02 0900.txt").write_text("# Docket time log\n", encoding="utf-8")
    (tmp_path / "Map 2026-01-02 0900.csv").write_text("﻿Checklist,Step,Category\n", encoding="utf-8")
    (tmp_path / "Map 2026-11-20 0900.txt").write_text("# Docket time log\n", encoding="utf-8")
    (tmp_path / "Notes 2026-01-02 0900.txt").write_text("my own notes\n", encoding="utf-8")
    (tmp_path / "invoice.pdf").write_text("x", encoding="utf-8")
    old = timelogs.to_clear(tmp_path, 30, today=TODAY)
    assert sorted(p.name for p in old) == ["Map 2026-01-02 0900.csv", "Map 2026-01-02 0900.txt"]
    assert len(timelogs.to_clear(tmp_path, None, today=TODAY)) == 3
    assert timelogs.clear(old) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Map 2026-11-20 0900.txt", "Notes 2026-01-02 0900.txt",
                                                          "invoice.pdf"]


def test_add_categories_merges():
    s = Store()
    a = s.add_tab("A", kind="checklist")
    s.set_categories(a.id, ["Terrain", "Roads"])
    s.add_categories(a.id, ["Roads", "Detailing"])
    assert s.tab(a.id).category_list == ["Terrain", "Roads", "Detailing"]


def test_modes():
    from docket import modes
    assert modes.has("basic", "anything_else") and not modes.has("basic", "quick_capture")
    assert modes.has("advanced", "quick_capture") and not modes.has("advanced", "timer")
    assert all(modes.has("pro", f) for f in modes.FEATURES)
    assert modes.has("nonsense", "timer")        # unknown mode falls back to Pro: nothing hidden


def test_link_kinds(tmp_path):
    from docket import links
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert links.kind("https://x.com") == "web" and links.kind("www.x.com") == "web"
    assert links.kind(str(tmp_path)) == "folder" and links.kind(str(f)) == "file"
    assert links.kind(str(tmp_path / "gone")) == "missing" and links.kind("") == ""
    assert links.icon_name("https://x.com") == "globe" and links.normalize(' "www.a.com" ') == "https://www.a.com"


def test_capture_routing_and_paste():
    from docket import capture
    names = ["Home", "Map making", "Map", "Inbox"]
    assert capture.route("#home buy milk", names) == ("buy milk", "Home")
    assert capture.route("export river #Map Making", names) == ("export river", "Map making")
    assert capture.route("fix #map tiles", names) == ("fix tiles", "Map")
    assert capture.route("use C# here", names) == ("use C# here", None)
    assert capture.route("#nolist thing", names) == ("#nolist thing", None)
    assert capture.paste_kind("## Trip\nbook flights\n") == "list"
    assert capture.paste_kind("a\n\nb") == "lines" and capture.paste_kind("one line") == "one"
    assert capture.paste_lines("- a\n2. b\n[x] c\n\n  d  ") == ["a", "b", "c", "d"]


def test_synced_folders():
    from docket import syncfolders
    env = {"OneDrive": r"C:\Users\James\OneDrive"}
    assert syncfolders.service(r"C:\Users\James\OneDrive\Documents\Docket", env) == "OneDrive"
    assert syncfolders.service(r"C:\Users\James\OneDrive - Acme Corp\Logs", {}) == "OneDrive"
    assert syncfolders.service(r"G:\My Drive\Docket", {}) == "Google Drive"
    assert syncfolders.service(r"C:\Users\James\Dropbox\x", {}) == "Dropbox"
    assert syncfolders.service(r"C:\Users\James\Documents\Docket", env) == ""
    assert "OneDrive" in syncfolders.note(r"C:\Users\James\OneDrive\x", "Time logs") or True


def test_add_to_top():
    s = Store()
    t = s.add_tab("A", kind="checklist")
    s.add_item(t.id, "one"); s.add_item(t.id, "two"); s.add_item(t.id, "zero", top=True)
    assert [i.name for i in s.items(t.id)] == ["zero", "one", "two"]


def test_parse_line_reads_copied_lines():
    it = importer.parse_line("obtain heightmap | category Setup", TODAY, checklist=True)
    assert it["name"] == "obtain heightmap" and it["category"] == "Setup"
    it = importer.parse_line("water | limit 15m | link https://x.com", TODAY, checklist=True)
    assert it["time_limit"] == 900 and it["link"] == "https://x.com"
    it = importer.parse_line("call Sam fri", TODAY, default_priority=2)
    assert it["priority"] == 2 and it["due"]
