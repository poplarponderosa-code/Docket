"""Quick-add parsing: pull a date (or range) and a priority out of typed text.

Rules, kept simple so they are predictable:

* Priority is a word starting with "!" anywhere in the text:
  !high !h !1   !med !m !2   !low !l !3
* A date is only picked up at the END of the text (after removing the
  priority word), optionally after "on", "by", "due", "from", "until":
    today, tomorrow, fri, next fri, this week, next week, weekend,
    in 3 days, in 2 weeks, nov 24, 24 nov, 11/24, 2026-11-24,
  and ranges joined by "-", "to", "until" or "through":
    nov 24-28, nov 30 - dec 2, fri-sun, 11/24 to 11/28
* A time anywhere (3pm, 3:30 pm, at 9am, @14:00) turns on a reminder at that
  time. With no date, the item is due today. Times with a colon and no am/pm
  are 24-hour, except 1:00-6:59, which are read as afternoon.
* Numeric dates are month/day (11/24 = Nov 24).
* A date without a year is this year, unless it is more than two months in
  the past, in which case it means next year.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from . import dates

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
WEEKDAYS = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3,
    "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}
PRIORITY_WORDS = {
    "high": "High", "hi": "High", "h": "High", "1": "High",
    "medium": "Med", "med": "Med", "m": "Med", "2": "Med",
    "low": "Low", "lo": "Low", "l": "Low", "3": "Low",
}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
                "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
CONNECTORS = {"on", "by", "due", "from", "until", "starting"}

PRI_RE = re.compile(r"(?<!\S)!(" + "|".join(sorted(PRIORITY_WORDS, key=len, reverse=True)) + r")(?!\S)", re.I)
TIME_RE = re.compile(
    r"(?<!\S)(?:(?:at|@)\s*)?(\d{1,2})(?::(\d{2}))?\s?(am|pm|a\.m\.|p\.m\.|a|p)(?!\S)"
    r"|(?<!\S)(?:(?:at|@)\s*)?(\d{1,2}):(\d{2})(?!\S)", re.I)
SEP_RE = re.compile(r"\s*(?:–|—|\.\.|-)\s*|\s+(?:to|until|till|thru|through)\s+")
ORD = r"(?:st|nd|rd|th)?"


@dataclass
class QuickAdd:
    name: str
    due: dt.date | None = None
    end: dt.date | None = None
    priority: str | None = None   # "High" | "Med" | "Low"
    remind_time: str | None = None  # "HH:MM"


def _time_from_match(m: re.Match) -> str | None:
    if m.group(1) is not None:
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm.startswith("p") else 0)
    else:
        hour, minute = int(m.group(4)), int(m.group(5))
        if 1 <= hour <= 6:
            hour += 12
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def parse_time(text: str) -> str | None:
    """'3pm', '3:30 PM', '15:00', 'at 9am' -> 'HH:MM'."""
    m = TIME_RE.fullmatch(" ".join(text.strip().split()))
    return _time_from_match(m) if m else None


def _make_date(year: int | None, month: int, day: int, today: dt.date,
               ref: dt.date | None) -> dt.date | None:
    try:
        if year is not None:
            if year < 100:
                year += 2000
            return dt.date(year, month, day)
        base = ref or today
        d = dt.date(base.year, month, day)
        if ref is not None:
            if d < ref:
                d = dt.date(base.year + 1, month, day)
        elif d < today - dt.timedelta(days=60):
            d = dt.date(base.year + 1, month, day)
        return d
    except ValueError:
        return None


def _add_months(d: dt.date, n: int) -> dt.date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    for day in (d.day, 30, 29, 28):
        try:
            return dt.date(y, m, day)
        except ValueError:
            continue
    return d


def parse_single(text: str, today: dt.date, ref: dt.date | None = None) -> dt.date | None:
    """One date. ref is the start of a range, used to read '28' in 'nov 24-28'."""
    s = " ".join(text.lower().strip().rstrip(",.").split())
    if not s:
        return None
    if s in ("today", "tod", "tdy"):
        return today
    if s in ("tomorrow", "tmr", "tmrw", "tomorow"):
        return today + dates.ONE_DAY
    if s in ("eow", "end of week", "end of the week"):
        return dates.friday(today)

    m = re.fullmatch(r"(next\s+|this\s+)?([a-z]+)", s)
    if m and m.group(2) in WEEKDAYS:
        wd = WEEKDAYS[m.group(2)]
        if m.group(1) and m.group(1).startswith("next"):
            return dates.next_monday(today) + dt.timedelta(days=wd)
        return dates.next_weekday(ref or today, wd)

    m = re.fullmatch(r"in\s+(\d+|[a-z]+)\s+(day|days|week|weeks|month|months)", s)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS.get(m.group(1))
        if n is None:
            return None
        unit = m.group(2)
        if unit.startswith("day"):
            return today + dt.timedelta(days=n)
        if unit.startswith("week"):
            return today + dt.timedelta(weeks=n)
        return _add_months(today, n)

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return _make_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), today, ref)

    m = re.fullmatch(r"([a-z]+)\.?\s*(\d{1,2})" + ORD + r"(?:,?\s*(\d{4}))?", s)
    if m and m.group(1) in MONTHS:
        year = int(m.group(3)) if m.group(3) else None
        return _make_date(year, MONTHS[m.group(1)], int(m.group(2)), today, ref)

    m = re.fullmatch(r"(\d{1,2})" + ORD + r"\s*([a-z]+)\.?(?:,?\s*(\d{4}))?", s)
    if m and m.group(2) in MONTHS:
        year = int(m.group(3)) if m.group(3) else None
        return _make_date(year, MONTHS[m.group(2)], int(m.group(1)), today, ref)

    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?", s)
    if m:
        year = int(m.group(3)) if m.group(3) else None
        return _make_date(year, int(m.group(1)), int(m.group(2)), today, ref)

    if ref is not None:
        m = re.fullmatch(r"(\d{1,2})" + ORD, s)
        if m:
            day = int(m.group(1))
            d = _make_date(ref.year, ref.month, day, today, None)
            if d is None or d < ref:
                nxt = _add_months(ref.replace(day=1), 1)
                d = _make_date(nxt.year, nxt.month, day, today, None)
            return d
    return None


def parse_date_expr(text: str, today: dt.date) -> tuple[dt.date, dt.date | None] | None:
    """A single date or a range. Returns (start, end-or-None)."""
    s = " ".join(text.lower().strip().rstrip(",.").split())
    if not s:
        return None
    if s in ("next week",):
        return dates.next_week(today)
    if s in ("this week",):
        return dates.this_week(today)
    if s in ("weekend", "this weekend", "the weekend"):
        return dates.weekend(today)
    if s == "next weekend":
        sat, sun = dates.weekend(today)
        if sun is None:                      # Sunday: next Sat-Sun
            sat = today + dt.timedelta(days=6)
            return sat, sat + dates.ONE_DAY
        week = dt.timedelta(days=7)
        return sat + week, sun + week

    single = parse_single(s, today)
    if single:
        return single, None

    for m in SEP_RE.finditer(s):
        left, right = s[:m.start()], s[m.end():]
        start = parse_single(left, today)
        if not start:
            continue
        end = parse_single(right, today, ref=start)
        if end and end >= start:
            return start, (end if end != start else None)
    return None


def parse_quick_add(text: str, today: dt.date | None = None) -> QuickAdd:
    today = today or dt.date.today()
    priority = None

    def take_priority(m: re.Match) -> str:
        nonlocal priority
        priority = PRIORITY_WORDS[m.group(1).lower()]
        return " "

    rest = PRI_RE.sub(take_priority, text)
    remind_time = None
    for m in TIME_RE.finditer(rest):
        t = _time_from_match(m)
        if t:
            remind_time, span = t, m.span()
    if remind_time:
        rest = rest[:span[0]] + " " + rest[span[1]:]
    words = rest.split()

    # Longest trailing phrase first; always leave at least one word for the name.
    for k in range(min(7, len(words) - 1), 0, -1):
        found = parse_date_expr(" ".join(words[-k:]), today)
        if found:
            name_words = words[:-k]
            while len(name_words) > 1 and name_words[-1].lower() in CONNECTORS:
                name_words.pop()
            return QuickAdd(" ".join(name_words), found[0], found[1], priority, remind_time)
    name_words = words
    while remind_time and len(name_words) > 1 and name_words[-1].lower() in CONNECTORS:
        name_words = name_words[:-1]
    return QuickAdd(" ".join(name_words), today if remind_time else None, None, priority, remind_time)
