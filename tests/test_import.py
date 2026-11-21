import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docket import backup, importer                       # noqa: E402
from docket.parser import parse_quick_add, parse_time     # noqa: E402
from docket.store import Store                            # noqa: E402

FRI = dt.date(2026, 11, 20)


def test_times():
    assert parse_time("3pm") == "15:00"
    assert parse_time("3:30 PM") == "15:30"
    assert parse_time("at 9am") == "09:00"
    assert parse_time("12am") == "00:00"
    assert parse_time("12pm") == "12:00"
    assert parse_time("15:00") == "15:00"
    assert parse_time("2:30") == "14:30"          # afternoon guess
    assert parse_time("9:15") == "09:15"
    assert parse_time("25:00") is None
    q = parse_quick_add("Dentist fri 3pm !high", FRI)
    assert (q.name, q.due, q.remind_time, q.priority) == ("Dentist", FRI, "15:00", "High")
    q = parse_quick_add("Call bank at 10:30am", FRI)
    assert (q.name, q.due, q.remind_time) == ("Call bank", FRI, "10:30")
    q = parse_quick_add("Standup @9am mon", FRI)
    assert (q.name, q.due, q.remind_time) == ("Standup", dt.date(2026, 11, 23), "09:00")
    q = parse_quick_add("Read 1:1 notes", FRI)
    assert q.remind_time is None and q.name == "Read 1:1 notes"


def test_template_txt():
    tabs = importer.parse_text(importer.TEMPLATE_TXT, "file", FRI)
    assert [t["name"] for t in tabs] == ["Work", "Home", "Map making process"]
    assert [t["kind"] for t in tabs] == ["list", "list", "checklist"]
    assert tabs[1]["color"] == "sage" and tabs[2]["color"] == "teal"
    steps = tabs[2]["items"]
    assert steps[0]["name"] == "Gather heightmap and reference imagery" and steps[0]["due"] == ""
    assert steps[1]["notes"] == "Check the sea level against the reference."
    work = {i["name"]: i for i in tabs[0]["items"]}
    assert work["Submit quarterly report"]["priority"] == 0 and work["Submit quarterly report"]["due"] == "2026-11-20"
    off = work["Plan team offsite"]
    assert (off["due"], off["end"], off["priority"]) == ("2026-11-24", "2026-11-28", 2)
    assert off["notes"] == "Shortlist two venues.\nCheck the budget with finance."
    d = work["Dentist"]
    assert (d["due"], d["priority"], d["reminder"], d["remind_time"]) == ("2026-12-03", 1, True, "15:00")
    assert work["Update project tracker"]["notes"] == "Add the new milestones"
    assert work["Send kickoff email"]["done"]
    assert work["Book training course"]["due"] == ""
    home = {i["name"]: i for i in tabs[1]["items"]}
    assert home["Weekend groceries"]["due"] == "2026-11-21"
    assert home["Renew car insurance"]["end"] == "2026-11-27"


def test_plain_list_without_headers():
    text = "- Milk\n- [x] Eggs\n1. Bread tomorrow\n\n* Butter !h\n"
    tabs = importer.parse_text(text, "Groceries", FRI)
    assert len(tabs) == 1 and tabs[0]["name"] == "Groceries"
    names = [(i["name"], i["done"], i["due"], i["priority"]) for i in tabs[0]["items"]]
    assert names == [("Milk", False, "", 1), ("Eggs", True, "", 1), ("Bread", False, "2026-11-21", 1),
                     ("Butter", False, "", 0)]


def test_backup_file_imports_too():
    s = Store()
    t = s.add_tab("Work")
    s.add_item(t.id, "Report", due="2026-11-20", end="2026-11-22", priority=0, reminder=True,
               remind_time="15:00", notes="n1")
    text = backup.render(s)
    tabs = importer.parse_text(text, "x", FRI)
    it = tabs[0]["items"][0]
    assert (it["name"], it["due"], it["end"], it["priority"], it["remind_time"], it["notes"]) == \
        ("Report", "2026-11-20", "2026-11-22", 0, "15:00", "n1")


def test_template_csv():
    tabs = importer.parse_csv(importer.TEMPLATE_CSV, "file", FRI)
    assert [t["name"] for t in tabs] == ["Work", "Home"]
    first = tabs[0]["items"][0]
    assert (first["name"], first["due"], first["priority"], first["remind_time"]) == \
        ("Submit quarterly report", "2026-11-20", 0, "09:00")
    assert tabs[0]["items"][1]["end"] == "2026-11-28"
    assert tabs[0]["items"][2]["done"]
    assert tabs[1]["items"][1]["notes"] == "Oats, coffee, apples"


def test_csv_loose_headers_and_no_header(tmp_path):
    p = tmp_path / "Chores.csv"
    p.write_text("Task,Date,Importance,Completed\nVacuum,11/24/2026,low,\nDishes,,HIGH,yes\n", encoding="utf-8-sig")
    tabs = importer.load(p, FRI)
    assert tabs[0]["name"] == "Chores"
    v, d = tabs[0]["items"]
    assert (v["due"], v["priority"], v["done"]) == ("2026-11-24", 2, False)
    assert (d["priority"], d["done"]) == (0, True)
    q = tmp_path / "Plain.csv"
    q.write_text("Vacuum\nDishes\n", encoding="utf-8")
    assert [i["name"] for i in importer.load(q, FRI)[0]["items"]] == ["Vacuum", "Dishes"]


def test_add_lists_and_migration(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE tabs (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        position INTEGER NOT NULL DEFAULT 0, popped INTEGER NOT NULL DEFAULT 0, geometry TEXT NOT NULL DEFAULT '');
        CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT, tab_id INTEGER NOT NULL, name TEXT NOT NULL,
        due TEXT NOT NULL DEFAULT '', end_date TEXT NOT NULL DEFAULT '', priority INTEGER NOT NULL DEFAULT 1,
        notes TEXT NOT NULL DEFAULT '', reminder INTEGER NOT NULL DEFAULT 0, reminded INTEGER NOT NULL DEFAULT 0,
        done INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL DEFAULT '');
        INSERT INTO tabs (name) VALUES ('Old'); INSERT INTO items (tab_id, name) VALUES (1, 'kept');""")
    con.commit()
    con.close()
    s = Store(db)                                   # v1 database upgrades in place
    assert s.items(1)[0].name == "kept" and s.items(1)[0].remind_time == ""
    made = s.add_lists(importer.parse_text(importer.TEMPLATE_TXT, "x", FRI))
    assert [t.name for t in s.tabs()] == ["Old", "Work", "Home", "Map making process"] and len(made) == 3
    assert s.tabs()[3].kind == "checklist" and s.tabs()[3].color == "teal" and s.tabs()[0].kind == "list"
    s.update_item(s.items(1)[0].id, reminded=True)
    s.update_item(s.items(1)[0].id, remind_time="08:00")
    assert not s.items(1)[0].reminded


def test_checklist_order_reset_export_template(tmp_path):
    s = Store()
    t = s.add_tab("Map making", kind="checklist", color="teal")
    a = s.add_item(t.id, "Heightmap")
    b = s.add_item(t.id, "Water level", notes="check sea level")
    c = s.add_item(t.id, "Roads")
    s.move_item(c.id, a.id)                      # Roads to the top
    assert [i.name for i in s.items(t.id)] == ["Roads", "Heightmap", "Water level"]
    s.move_item(c.id, None)                      # back to the end
    assert [i.name for i in s.items(t.id)] == ["Heightmap", "Water level", "Roads"]
    s.update_item(a.id, done=True)
    s.update_item(b.id, done=True)
    assert s.reset_checklist(t.id) == 2 and not any(i.done for i in s.items(t.id))
    s.update_item(a.id, done=True)

    exported = importer.export_list(s.tab(t.id), s.items(t.id))
    back = importer.parse_text(exported, "x", FRI)[0]
    assert (back["name"], back["kind"], back["color"]) == ("Map making", "checklist", "teal")
    assert [(i["name"], i["done"], i["notes"]) for i in back["items"]] == \
        [("Heightmap", True, ""), ("Water level", False, "check sea level"), ("Roads", False, "")]

    tpl = tmp_path / (importer.safe_filename("Map: making?") + ".txt")
    tpl.write_text(importer.template_text(s.tab(t.id), s.items(t.id)), encoding="utf-8")
    assert tpl.name == "Map making.txt"
    loaded = importer.load_template(tpl)
    assert loaded["kind"] == "checklist" and not any(i["done"] for i in loaded["items"])
    assert [p.name for p in importer.list_templates(tmp_path)] == ["Map making.txt"]


def test_priority_list_export_roundtrip():
    s = Store()
    t = s.add_tab("Work", color="amber")
    s.add_item(t.id, "Offsite | planning", due="2026-11-24", end="2026-11-28", priority=2,
               reminder=True, remind_time="15:00", notes="venue")
    s.add_item(t.id, "Report", done=True, priority=0)
    back = importer.parse_text(importer.export_list(s.tab(t.id), s.items(t.id)), "x", FRI)[0]
    assert back["color"] == "amber" and back["kind"] == "list"
    a, b = back["items"]
    assert (a["name"], a["due"], a["end"], a["priority"], a["remind_time"], a["notes"]) == \
        ("Offsite / planning", "2026-11-24", "2026-11-28", 2, "15:00", "venue")
    assert (b["name"], b["done"], b["priority"]) == ("Report", True, 0)


def test_backup_keeps_kind_and_colour():
    s = Store()
    s.add_tab("Steps", kind="checklist", color="plum")
    s.add_tab("Plain")
    data = backup.parse(backup.render(s))
    assert [(d["name"], d["kind"], d["color"]) for d in data] == [("Steps", "checklist", "plum"), ("Plain", "list", "")]
    s2 = Store()
    s2.replace_all(data)
    assert [(t.kind, t.color) for t in s2.tabs()] == [("checklist", "plum"), ("list", "")]
