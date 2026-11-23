import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docket.store import Store                                        # noqa: E402
from docket.timer import TimerEngine, fmt_duration, fmt_limit, parse_duration   # noqa: E402


class Clock:
    def __init__(self):
        self.t = dt.datetime(2026, 11, 21, 14, 0, 0)

    def __call__(self):
        return self.t

    def add(self, **kw):
        self.t += dt.timedelta(**kw)


def setup():
    s = Store()
    clock = Clock()
    eng = TimerEngine(s, clock)
    t = s.add_tab("Map making", kind="checklist")
    s.update_tab(t.id, timer_on=True, description="Winter map\nfor the contest")
    a = s.add_item(t.id, "Heightmap")
    b = s.add_item(t.id, "Water")
    c = s.add_item(t.id, "Roads")
    return s, clock, eng, t, a, b, c


def test_durations():
    assert parse_duration("15") == 900 and parse_duration("15m") == 900
    assert parse_duration("1h30") == 5400 and parse_duration("1h 30m") == 5400
    assert parse_duration("1:30") == 5400 and parse_duration("0:45:30") == 2730
    assert parse_duration("90s") == 90 and parse_duration("1.5h") == 5400
    assert parse_duration("") == 0 and parse_duration("abc") is None and parse_duration("1:75") is None
    assert fmt_duration(3725) == "1:02:05" and fmt_duration(125) == "2:05"
    assert fmt_limit(5400) == "1h 30m" and fmt_limit(900) == "15m"


def test_run_tick_advance_finish():
    s, clock, eng, t, a, b, c = setup()
    assert eng.start(t.id)
    clock.add(minutes=10)
    assert round(eng.live_elapsed(s.item(a.id))) == 600
    assert eng.set_done(a.id, True) is False              # next step starts straight away
    assert s.item(a.id).elapsed == 600 and s.item(a.id).finished == "2026-11-21T14:10:00"
    assert s.item(b.id).run_from == "2026-11-21T14:10:00"
    clock.add(minutes=5)
    eng.pause(t.id)
    clock.add(minutes=30)                                 # paused: not counted
    eng.start(t.id)
    clock.add(minutes=2)
    eng.set_done(b.id, True)
    assert round(s.item(b.id).elapsed) == 420
    clock.add(minutes=3)
    assert eng.set_done(c.id, True) is True               # last step finishes the checklist
    tab = s.tab(t.id)
    assert not tab.timer_running and tab.timer_finished == "2026-11-21T14:50:00"
    assert round(eng.total_elapsed(t.id)) == 600 + 420 + 180
    text = eng.log_text(t.id)
    assert "Checklist: Map making" in text and "Description: Winter map" in text and "for the contest" in text
    assert "Started: 2026-11-21 14:00:00" in text and "Finished: 2026-11-21 14:50:00" in text
    assert "Heightmap | 2026-11-21 14:00:00 | 2026-11-21 14:10:00 | 10:00 | -" in text
    assert "Total time: 20:00" in text
    csv_text = eng.log_csv(t.id)
    assert csv_text.splitlines()[0] == "Checklist,Step,Category,Start,End,Duration,Minutes,Limit,Done"
    assert "Map making,Roads,,2026-11-21 14:47:00,2026-11-21 14:50:00,3:00,3.0,,yes" in csv_text
    assert "By category" not in text                      # only when steps have categories


def test_make_current_one_running_and_alerts():
    s, clock, eng, t, a, b, c = setup()
    other = s.add_tab("Other", kind="checklist")
    s.update_tab(other.id, timer_on=True)
    s.add_item(other.id, "x")
    eng.set_item_limit(c.id, 120)
    eng.set_tab_limit(t.id, 300)
    eng.start(other.id)
    eng.start(t.id)                                        # starting one pauses the other
    assert not s.tab(other.id).timer_running and s.tab(t.id).timer_running
    clock.add(minutes=1)
    eng.make_current(t.id, c.id)                           # jump to Roads with its ▶
    assert s.item(a.id).run_from == "" and round(s.item(a.id).elapsed) == 60
    assert s.item(c.id).run_from
    clock.add(minutes=1, seconds=59)
    assert eng.due_alerts() == []
    clock.add(seconds=2)
    alerts = eng.due_alerts()
    assert [(x.id, y.id if y else None) for x, y in alerts] == [(t.id, c.id)]
    assert eng.due_alerts() == []                          # only once
    clock.add(minutes=2)
    alerts = eng.due_alerts()
    assert [(x.id, y) for x, y in alerts] == [(t.id, None)]   # whole-checklist limit
    eng.set_done(c.id, True)                               # ticked: back to the top unticked step
    assert s.item(a.id).run_from and s.tab(t.id).current_item == a.id


def test_lock_recover_reset():
    s, clock, eng, t, a, b, c = setup()
    eng.start(t.id)
    clock.add(minutes=5)
    locked_at = clock()
    clock.add(minutes=60)                                  # away while locked
    paused = eng.pause_all(at=locked_at)
    assert [p.id for p in paused] == [t.id] and round(s.item(a.id).elapsed) == 300
    eng.start(t.id)
    clock.add(minutes=1)
    eng.heartbeat()
    clock.add(hours=5)                                     # app closed / PC off
    assert [p.id for p in eng.recover()] == [t.id]
    assert round(s.item(a.id).elapsed) == 360 and not s.tab(t.id).timer_running
    eng.reset(t.id)
    assert s.item(a.id).elapsed == 0 and s.tab(t.id).timer_started == ""


def test_finish_while_paused():
    s, clock, eng, t, a, b, c = setup()
    eng.start(t.id)
    clock.add(minutes=1)
    eng.pause(t.id)
    eng.set_done(a.id, True)
    eng.set_done(b.id, True)
    assert eng.set_done(c.id, True) is True and s.tab(t.id).timer_finished


def test_timer_off_just_ticks():
    s = Store()
    eng = TimerEngine(s, Clock())
    t = s.add_tab("Plain", kind="checklist")
    a = s.add_item(t.id, "one")
    assert eng.set_done(a.id, True) is False and s.item(a.id).done
    assert eng.start(t.id) is False


def test_categories_in_time_log():
    s, clock, eng, t, a, b, c = setup()
    s.set_categories(t.id, ["Terrain", "Roads"])
    s.update_item(a.id, category="Terrain")
    s.update_item(b.id, category="Terrain")
    s.update_item(c.id, category="Roads")
    eng.start(t.id)
    clock.add(minutes=10)
    eng.set_done(a.id, True)
    clock.add(minutes=5)
    eng.set_done(b.id, True)
    clock.add(minutes=20)
    eng.set_done(c.id, True)
    text = eng.log_text(t.id)
    assert "Step | Category | Start | End | Duration | Limit" in text
    assert "Heightmap | Terrain | 2026-11-21 14:00:00" in text
    assert "By category | Duration" in text and "Terrain | 15:00" in text and "Roads | 20:00" in text
    assert "Map making,Roads,Roads,2026-11-21 14:15:00" in eng.log_csv(t.id)
