"""Date helpers shared by the parser, the list rows and the date picker."""
from __future__ import annotations

import datetime as dt

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

ONE_DAY = dt.timedelta(days=1)


def from_iso(value: str) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def fmt(d: dt.date) -> str:
    return f"{MONTH_ABBR[d.month - 1]} {d.day}"


def fmt_time(hhmm: str) -> str:
    """'15:00' -> '3:00 PM'."""
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return hhmm
    return f"{h % 12 or 12}:{m:02d} {'PM' if h >= 12 else 'AM'}"


def range_label(start: dt.date, end: dt.date | None) -> str:
    if end and end != start:
        if end.year == start.year and end.month == start.month:
            return f"{fmt(start)}–{end.day}"
        return f"{fmt(start)}–{fmt(end)}"
    return fmt(start)


def due_label(due: dt.date | None, end: dt.date | None, today: dt.date) -> str:
    """Short label for the Due column: Today, Tomorrow, Nov 24, Nov 24–28."""
    if not due:
        return "—"
    if end and end != due:
        return range_label(due, end)
    if due == today:
        return "Today"
    if due == today + ONE_DAY:
        return "Tomorrow"
    if due < today:
        return f"{fmt(due)} · late"
    return fmt(due)


def status(due: dt.date | None, end: dt.date | None, done: bool, today: dt.date) -> str:
    """'overdue', 'today', 'later' or 'none'."""
    if done or not due:
        return "none"
    last = end or due
    if last < today:
        return "overdue"
    if due <= today:
        return "today"
    return "later"


# ---- named days and ranges -------------------------------------------------

def next_weekday(base: dt.date, weekday: int) -> dt.date:
    """The next date on or after base that falls on weekday (Mon=0)."""
    return base + dt.timedelta(days=(weekday - base.weekday()) % 7)


def next_monday(today: dt.date) -> dt.date:
    return today + dt.timedelta(days=7 - today.weekday())


def friday(today: dt.date) -> dt.date:
    return next_weekday(today, 4)


def weekend(today: dt.date) -> tuple[dt.date, dt.date | None]:
    if today.weekday() == 6:          # it's Sunday: just today
        return today, None
    sat = next_weekday(today, 5)
    return sat, sat + ONE_DAY


def next_week(today: dt.date) -> tuple[dt.date, dt.date]:
    mon = next_monday(today)
    return mon, mon + dt.timedelta(days=4)


def this_week(today: dt.date) -> tuple[dt.date, dt.date | None]:
    if today.weekday() < 4:
        return today, friday(today)
    if today.weekday() == 4:
        return today, None
    end = next_weekday(today, 6)
    return today, (end if end != today else None)


def quick_picks(today: dt.date) -> list[tuple[str, dt.date, dt.date | None]]:
    """The six one-click choices in the date picker."""
    sat, sun = weekend(today)
    mon, fri = next_week(today)
    return [
        ("Today", today, None),
        ("Tomorrow", today + ONE_DAY, None),
        ("Friday", friday(today), None),
        ("In a week", today + dt.timedelta(days=7), None),
        ("Weekend", sat, sun),
        ("Next week", mon, fri),
    ]
