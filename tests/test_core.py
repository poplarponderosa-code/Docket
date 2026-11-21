import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docket import backup                       # noqa: E402
from docket.parser import parse_quick_add      # noqa: E402
from docket.store import Store                 # noqa: E402

FRI = dt.date(2026, 11, 20)   # a Friday
D = dt.date


def q(text, today=FRI):
    r = parse_quick_add(text, today)
    return r.name, r.due, r.end, r.priority


def test_plain_text():
    assert q("Buy milk") == ("Buy milk", None, None, None)


def test_priority_anywhere():
    assert q("!high Fix bug") == ("Fix bug", None, None, "High")
    assert q("Fix bug !l") == ("Fix bug", None, None, "Low")
    assert q("Fix bug !2") == ("Fix bug", None, None, "Med")


def test_relative_words():
    assert q("Call mom tomorrow") == ("Call mom", D(2026, 11, 21), None, None)
    assert q("Report today !h") == ("Report", FRI, None, "High")
    assert q("Dentist fri") == ("Dentist", FRI, None, None)          # today is Friday
    assert q("Dentist mon")[1] == D(2026, 11, 23)
    assert q("Dentist next tue")[1] == D(2026, 11, 24)
    assert q("Send invoice in 3 days")[1] == D(2026, 11, 23)
    assert q("Renew passport in 2 weeks")[1] == D(2026, 12, 4)


def test_named_dates():
    assert q("Plan offsite nov 24")[1] == D(2026, 11, 24)
    assert q("Plan offsite 24 nov")[1] == D(2026, 11, 24)
    assert q("Pay invoice 12/15")[1] == D(2026, 12, 15)
    assert q("Taxes 2027-04-30")[1] == D(2027, 4, 30)
    assert q("Book flights jan 5")[1] == D(2027, 1, 5)        # Jan is past -> next year
    assert q("Due on dec 1")[0] == "Due"                       # connector stripped


def test_ranges():
    assert q("Plan offsite nov 24-28 !high") == ("Plan offsite", D(2026, 11, 24), D(2026, 11, 28), "High")
    assert q("Trip nov 30 - dec 2")[1:3] == (D(2026, 11, 30), D(2026, 12, 2))
    assert q("Trip nov 30-3")[1:3] == (D(2026, 11, 30), D(2026, 12, 3))
    assert q("Workshop mon to wed")[1:3] == (D(2026, 11, 23), D(2026, 11, 25))
    assert q("Sprint 11/24 to 11/28")[1:3] == (D(2026, 11, 24), D(2026, 11, 28))
    assert q("Sprint 2026-11-24 - 2026-11-28")[1:3] == (D(2026, 11, 24), D(2026, 11, 28))
    assert q("Clean garage weekend")[1:3] == (D(2026, 11, 21), D(2026, 11, 22))
    assert q("Review next week")[1:3] == (D(2026, 11, 23), D(2026, 11, 27))
    assert q("Range dec 20-jan 3")[1:3] == (D(2026, 12, 20), D(2027, 1, 3))


def test_not_dates():
    assert q("Read chapter 5") == ("Read chapter 5", None, None, None)
    assert q("Watch Friday Night Lights")[1] is None   # dates only count at the end
    assert q("tomorrow") == ("tomorrow", None, None, None)     # need a name left over
    assert q("Fix may bug")[1] is None
    assert q("Order 2 pizzas")[1] is None


def test_store_and_backup_roundtrip(tmp_path):
    s = Store()
    t = s.add_tab("Work | stuff")
    s.add_item(t.id, "Report | Q4", due="2026-11-20", priority=0, notes="line 1\n\n  indented", reminder=True)
    s.add_item(t.id, "Offsite", due="2026-11-24", end="2026-11-28", priority=2, done=True)
    s.add_item(t.id, "Bad range", due="2026-11-24", end="2026-11-20")
    s.add_tab("Empty")
    path = backup.write_backup(s, tmp_path, keep=2, now=dt.datetime(2026, 11, 20, 13, 15))
    data = backup.parse(path.read_text(encoding="utf-8"))
    assert [d["name"] for d in data] == ["Work | stuff", "Empty"]
    a, b, c = data[0]["items"]
    assert a == {"name": "Report | Q4", "due": "2026-11-20", "end": "", "priority": 0,
                 "notes": "line 1\n\n  indented", "reminder": True, "remind_time": "", "done": False}
    assert (b["due"], b["end"], b["priority"], b["done"]) == ("2026-11-24", "2026-11-28", 2, True)
    assert c["end"] == ""
    s2 = Store()
    s2.replace_all(data)
    assert backup.render(s2, dt.datetime(2026, 11, 20, 13, 15)) == backup.render(s, dt.datetime(2026, 11, 20, 13, 15))


def test_prune(tmp_path):
    s = Store()
    s.add_tab("A")
    for minute in range(5):
        backup.write_backup(s, tmp_path, keep=3, now=dt.datetime(2026, 11, 20, 13, minute))
    names = [p.name for p in backup.list_backups(tmp_path)]
    assert names == ["Docket backup 2026-11-20 130200.txt", "Docket backup 2026-11-20 130300.txt",
                     "Docket backup 2026-11-20 130400.txt"]


def test_update_resets_reminded_and_events():
    s = Store()
    events, dirty = [], []
    s.subscribe(events.append)
    s.subscribe_dirty(lambda: dirty.append(1))
    t = s.add_tab("A")
    it = s.add_item(t.id, "x", due="2026-11-20", reminder=True)
    s.update_item(it.id, reminded=True)
    assert s.item(it.id).reminded
    s.update_item(it.id, quiet=True, due="2026-11-21")
    assert not s.item(it.id).reminded
    assert events == [None, t.id, t.id]     # quiet update skipped
    assert len(dirty) == 4
