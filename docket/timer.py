"""The checklist timer: records time on each step, with optional time limits.

How it behaves:
* Time always runs on the "current" step: the top unticked step, unless a step
  was picked with its ▶.
* Ticking the running step saves its time and starts the next step straight away.
  Ticking the last step stops the timer and the checklist is finished.
* A time limit (on a step or the whole checklist) only changes what's shown
  (time left, then overtime) and raises one alert when it's reached.
* Only one checklist's timer runs at a time.

No Qt in here; the app calls these and refreshes the screen.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from typing import Callable

from .store import Item, Store, Tab

ISO = "%Y-%m-%dT%H:%M:%S"


def to_iso(t: dt.datetime) -> str:
    return t.strftime(ISO)


def from_iso(s: str) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.strptime(s[:19], ISO)
    except ValueError:
        return None


# ---- durations ----------------------------------------------------------------------
def fmt_duration(seconds: float, short: bool = False) -> str:
    """3725 -> '1:02:05'; 125 -> '2:05'."""
    total = int(round(abs(seconds)))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    text = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    if short and h:
        text = f"{h}:{m:02d}:{s:02d}"
    return text


def fmt_limit(seconds: int) -> str:
    """For typing back into a box: 900 -> '15m', 5400 -> '1h 30m'."""
    if not seconds:
        return ""
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s:
        parts.append(f"{s}s")
    return " ".join(parts)


def parse_duration(text: str) -> int | None:
    """'15' or '15m' -> 900; '1h30', '1h 30m', '1:30' -> 5400; '1:30:00' -> 5400; '90s' -> 90.
    A plain number is minutes; h:mm is hours and minutes. '' or '0' -> 0 (no limit)."""
    s = text.strip().lower().replace(" ", "")
    if not s or s in ("0", "none", "-"):
        return 0
    m = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", s)
    if m:
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if mi > 59 or se > 59:
            return None
        return h * 3600 + mi * 60 + se
    m = re.fullmatch(r"(\d+)h(\d{1,2})", s)            # 1h30
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h(?:ours?|rs?)?)?(?:(\d+)m(?:in(?:ute)?s?)?)?(?:(\d+)s(?:ec(?:ond)?s?)?)?", s)
    if m and any(m.groups()):
        return int(float(m.group(1) or 0) * 3600) + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return int(float(s) * 60)
    return None


# ---- the engine -------------------------------------------------------------------------
class TimerEngine:
    def __init__(self, store: Store, now: Callable[[], dt.datetime] = dt.datetime.now):
        self.store = store
        self.now = now

    # -- reading ----------------------------------------------------------------------------
    def current_item(self, tab_id: int) -> Item | None:
        tab = self.store.tab(tab_id)
        items = self.store.items(tab_id)
        if tab and tab.current_item:
            for it in items:
                if it.id == tab.current_item and not it.done:
                    return it
        return next((it for it in items if not it.done), None)

    def running_tab(self) -> Tab | None:
        return next((t for t in self.store.tabs() if t.timer_running), None)

    def live_elapsed(self, item: Item, at: dt.datetime | None = None) -> float:
        start = from_iso(item.run_from)
        if start is None:
            return item.elapsed
        return item.elapsed + max(0.0, ((at or self.now()) - start).total_seconds())

    def total_elapsed(self, tab_id: int, at: dt.datetime | None = None) -> float:
        at = at or self.now()
        return sum(self.live_elapsed(i, at) for i in self.store.items(tab_id))

    # -- changing --------------------------------------------------------------------------
    def _begin(self, tab: Tab, item: Item, now: dt.datetime) -> None:
        stamp = to_iso(now)
        self.store.update_item(item.id, quiet=True, run_from=stamp, started=item.started or stamp)
        self.store.update_tab(tab.id, quiet=True, timer_running=True, timer_started=tab.timer_started or stamp,
                              timer_finished="", heartbeat=stamp, current_item=item.id)

    def _stop_segment(self, item: Item, at: dt.datetime) -> None:
        if item.run_from:
            self.store.update_item(item.id, quiet=True, elapsed=self.live_elapsed(item, at), run_from="")

    def start(self, tab_id: int) -> bool:
        tab = self.store.tab(tab_id)
        if tab is None or not tab.timer_on:
            return False
        for other in self.store.tabs():
            if other.timer_running and other.id != tab_id:
                self.pause(other.id)
        item = self.current_item(tab_id)
        if item is None:
            return False
        if not item.run_from:
            self._begin(self.store.tab(tab_id), item, self.now())
        self.store.update_tab(tab_id, timer_running=True)
        return True

    def pause(self, tab_id: int, at: dt.datetime | None = None) -> None:
        at = at or self.now()
        for item in self.store.items(tab_id):
            self._stop_segment(item, at)
        self.store.update_tab(tab_id, timer_running=False)

    def toggle(self, tab_id: int) -> bool:
        """Play/pause. Returns True if it's now running."""
        tab = self.store.tab(tab_id)
        if tab is None:
            return False
        if tab.timer_running:
            self.pause(tab_id)
            return False
        return self.start(tab_id)

    def make_current(self, tab_id: int, item_id: int) -> None:
        """A step's ▶: move the timer onto that step and run it."""
        tab = self.store.tab(tab_id)
        item = self.store.item(item_id)
        if tab is None or item is None or item.done:
            return
        now = self.now()
        for it in self.store.items(tab_id):
            if it.id != item_id:
                self._stop_segment(it, now)
        self.store.update_tab(tab_id, quiet=True, current_item=item_id)
        self.start(tab_id)

    def set_done(self, item_id: int, done: bool) -> bool:
        """Tick or untick a step. Returns True when this tick finished the whole checklist."""
        item = self.store.item(item_id)
        if item is None:
            return False
        tab = self.store.tab(item.tab_id)
        now = self.now()
        if not done:
            self.store.update_item(item_id, done=False, finished="")
            return False
        was_running = bool(item.run_from)
        self._stop_segment(item, now)
        self.store.update_item(item_id, quiet=True, done=True, finished=to_iso(now))
        if tab is None or not (tab.timer_on and tab.timer_running):
            self.store.update_item(item_id, done=True)            # tell the screen
            if (tab is not None and tab.timer_on and tab.timer_started
                    and all(i.done for i in self.store.items(tab.id))):
                self.store.update_tab(tab.id, timer_finished=to_iso(now), current_item=0)
                return True                                        # finished while paused
            return False
        if tab.current_item == item_id:
            self.store.update_tab(tab.id, quiet=True, current_item=0)
        nxt = self.current_item(tab.id)
        if nxt is not None:
            if was_running or not any(i.run_from for i in self.store.items(tab.id)):
                self._begin(self.store.tab(tab.id), nxt, now)
            self.store.update_tab(tab.id, timer_running=True)
            return False
        self.store.update_tab(tab.id, timer_running=False, timer_finished=to_iso(now), current_item=0)
        return True

    def reset(self, tab_id: int) -> None:
        for it in self.store.items(tab_id):
            self.store.update_item(it.id, quiet=True, elapsed=0.0, run_from="", started="", finished="",
                                   alerted=False)
        self.store.update_tab(tab_id, timer_running=False, timer_started="", timer_finished="",
                              current_item=0, alerted=False, heartbeat="")

    def set_item_limit(self, item_id: int, seconds: int) -> None:
        self.store.update_item(item_id, time_limit=int(seconds), alerted=False)

    def set_tab_limit(self, tab_id: int, seconds: int) -> None:
        self.store.update_tab(tab_id, time_limit=int(seconds), alerted=False)

    # -- the clock ---------------------------------------------------------------------------
    def due_alerts(self, at: dt.datetime | None = None) -> list[tuple[Tab, Item | None]]:
        """Limits just reached: (tab, step) for a step, (tab, None) for the whole checklist."""
        at = at or self.now()
        out: list[tuple[Tab, Item | None]] = []
        for tab in self.store.tabs():
            if not tab.timer_running:
                continue
            item = next((i for i in self.store.items(tab.id) if i.run_from), None)
            if item and item.time_limit and not item.alerted and self.live_elapsed(item, at) >= item.time_limit:
                self.store.update_item(item.id, quiet=True, alerted=True)
                out.append((tab, item))
            if tab.time_limit and not tab.alerted and self.total_elapsed(tab.id, at) >= tab.time_limit:
                self.store.update_tab(tab.id, quiet=True, dirty=False, alerted=True)
                out.append((tab, None))
        return out

    def heartbeat(self, at: dt.datetime | None = None) -> None:
        stamp = to_iso(at or self.now())
        for tab in self.store.tabs():
            if tab.timer_running:
                self.store.update_tab(tab.id, quiet=True, dirty=False, heartbeat=stamp)

    def pause_all(self, at: dt.datetime | None = None) -> list[Tab]:
        """PC locked or asleep: pause, counting time only up to `at`."""
        paused = []
        for tab in self.store.tabs():
            if tab.timer_running:
                self.pause(tab.id, at)
                paused.append(tab)
        return paused

    def recover(self) -> list[Tab]:
        """At start-up: a timer left running (PC shut down, app closed) is paused at its last heartbeat."""
        paused = []
        for tab in self.store.tabs():
            if tab.timer_running:
                self.pause(tab.id, from_iso(tab.heartbeat) or self.now())
                paused.append(tab)
        return paused

    # -- time log --------------------------------------------------------------------------------
    def log_rows(self, tab_id: int, at: dt.datetime | None = None) -> list[dict]:
        at = at or self.now()
        rows = []
        for it in self.store.items(tab_id):
            end = from_iso(it.finished)
            if it.run_from and not end:
                end_text = "running"
            else:
                end_text = end.strftime("%Y-%m-%d %H:%M:%S") if end else ""
            start = from_iso(it.started)
            rows.append({
                "step": it.name,
                "category": it.category,
                "start": start.strftime("%Y-%m-%d %H:%M:%S") if start else "",
                "end": end_text,
                "seconds": round(self.live_elapsed(it, at)),
                "limit": it.time_limit,
                "done": it.done,
            })
        return rows

    def log_text(self, tab_id: int, at: dt.datetime | None = None) -> str:
        at = at or self.now()
        tab = self.store.tab(tab_id)
        rows = self.log_rows(tab_id, at)
        total = sum(r["seconds"] for r in rows)
        started = from_iso(tab.timer_started)
        finished = from_iso(tab.timer_finished)
        lines = ["# Docket time log",
                 f"Checklist: {tab.name}"]
        if tab.description.strip():
            desc = tab.description.strip().splitlines()
            lines.append(f"Description: {desc[0]}")
            lines += [f"             {d}" for d in desc[1:]]
        lines.append(f"Started: {started:%Y-%m-%d %H:%M:%S}" if started else "Started: (not started)")
        lines.append(f"Finished: {finished:%Y-%m-%d %H:%M:%S}" if finished else "Finished: (not finished)")
        total_line = f"Total time: {fmt_duration(total)}"
        if tab.time_limit:
            diff = tab.time_limit - total
            total_line += (f" (limit {fmt_duration(tab.time_limit)}, "
                           + (f"{fmt_duration(diff)} under)" if diff >= 0 else f"{fmt_duration(-diff)} over)"))
        lines.append(total_line)
        lines.append("")
        has_cats = any(r["category"] for r in rows)
        lines.append("Step | Category | Start | End | Duration | Limit" if has_cats
                     else "Step | Start | End | Duration | Limit")
        for r in rows:
            cells = [r["step"].replace("|", "/")]
            if has_cats:
                cells.append(r["category"].replace("|", "/") or "-")
            cells += [r["start"] or "-", r["end"] or "-",
                      fmt_duration(r["seconds"]) if r["seconds"] or r["start"] else "-",
                      fmt_duration(r["limit"]) if r["limit"] else "-"]
            lines.append(" | ".join(cells))
        lines.append(("Total | | | | " if has_cats else "Total | | | ") + fmt_duration(total) + " | "
                     + (fmt_duration(tab.time_limit) if tab.time_limit else "-"))
        if has_cats:
            lines.append("")
            lines.append("By category | Duration")
            for name, seconds in self.category_totals(rows):
                lines.append(f"{name.replace('|', '/')} | {fmt_duration(seconds)}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def category_totals(rows: list[dict]) -> list[tuple[str, int]]:
        """Time per category, in the order categories first appear; steps without one last."""
        totals: dict[str, int] = {}
        for r in rows:
            key = r["category"] or "(no category)"
            totals[key] = totals.get(key, 0) + r["seconds"]
        ordered = [(k, v) for k, v in totals.items() if k != "(no category)"]
        if "(no category)" in totals:
            ordered.append(("(no category)", totals["(no category)"]))
        return ordered

    def log_csv(self, tab_id: int, at: dt.datetime | None = None) -> str:
        at = at or self.now()
        tab = self.store.tab(tab_id)
        rows = self.log_rows(tab_id, at)
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\r\n")
        w.writerow(["Checklist", "Step", "Category", "Start", "End", "Duration", "Minutes", "Limit", "Done"])
        for r in rows:
            w.writerow([tab.name, r["step"], r["category"], r["start"], r["end"],
                        fmt_duration(r["seconds"]) if r["seconds"] or r["start"] else "",
                        round(r["seconds"] / 60, 2) if r["seconds"] else "",
                        fmt_duration(r["limit"]) if r["limit"] else "", "yes" if r["done"] else "no"])
        total = sum(r["seconds"] for r in rows)
        w.writerow([tab.name, "Total", "", tab.timer_started.replace("T", " "), tab.timer_finished.replace("T", " "),
                    fmt_duration(total), round(total / 60, 2),
                    fmt_duration(tab.time_limit) if tab.time_limit else "", ""])
        return out.getvalue()
