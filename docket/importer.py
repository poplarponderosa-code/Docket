"""Import existing lists from a text file (.txt / .md) or a spreadsheet saved as .csv.

Imported lists are added as new tabs; nothing already in Docket is changed.
The two template files (TEMPLATE_TXT, TEMPLATE_CSV) show the formats.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from pathlib import Path

from .backup import description_lines, format_header, parse_categories, parse_header
from .timer import fmt_limit, parse_duration
from .parser import PRIORITY_WORDS, parse_date_expr, parse_quick_add, parse_single, parse_time
from .store import PRIORITIES, Item, Tab

CHECK_RE = re.compile(r"^(?:[-*•]\s*)?\[( |x|X|✓)\]\s*")
BULLET_RE = re.compile(r"^(?:[-*•]|\d+[.)])\s+")
TRUE_WORDS = {"x", "yes", "y", "true", "1", "done", "✓", "complete", "completed"}


def _new_item(name: str = "") -> dict:
    return {"name": name, "due": "", "end": "", "priority": 1, "notes": "",
            "reminder": False, "remind_time": "", "done": False, "time_limit": 0, "category": ""}


def _priority(word: str) -> int | None:
    w = word.strip().lower().lstrip("!")
    if w in PRIORITY_WORDS:
        return PRIORITIES.index(PRIORITY_WORDS[w])
    return None


def _set_dates(item: dict, text: str, today: dt.date) -> bool:
    found = parse_date_expr(text, today)
    if not found:
        return False
    item["due"] = found[0].isoformat()
    item["end"] = found[1].isoformat() if found[1] else ""
    return True


def parse_line(line: str, today: dt.date, checklist: bool = False) -> dict | None:
    s = line.strip()
    done = False
    m = CHECK_RE.match(s)
    if m:
        done = m.group(1) not in (" ",)
        s = s[m.end():]
    else:
        m = BULLET_RE.match(s)
        if m:
            s = s[m.end():]
    s = s.strip()
    if not s:
        return None

    if checklist and "|" not in s:
        item = _new_item(s)          # checklist steps are taken as written: no dates
        item["done"] = done
        return item
    if "|" in s:
        parts = [p.strip() for p in s.split("|")]
        item = _new_item(parts[0])
        for field in parts[1:]:
            low = field.lower()
            if not low:
                continue
            if low.startswith("due:"):
                _set_dates(item, field[4:], today)
            elif low.startswith("limit"):
                item["time_limit"] = parse_duration(field[5:].lstrip(":").strip()) or 0
            elif low.startswith("category"):
                item["category"] = field[8:].lstrip(":").strip()
            elif low.startswith("priority:"):
                pri = _priority(field[9:])
                if pri is not None:
                    item["priority"] = pri
            elif low.startswith("notes:"):
                item["notes"] = field[6:].strip()
            elif low == "remind" or low.startswith("remind "):
                item["reminder"] = True
                item["remind_time"] = parse_time(field[6:]) or ""
            elif low in ("done", "[x]", "x"):
                done = True
            elif _priority(low) is not None:
                item["priority"] = _priority(low)
            elif _set_dates(item, field, today):
                pass
            elif parse_time(field):
                item["reminder"] = True
                item["remind_time"] = parse_time(field)
            else:
                item["notes"] = (item["notes"] + "\n" if item["notes"] else "") + field
        if not item["name"]:
            return None
    else:
        q = parse_quick_add(s, today)
        item = _new_item(q.name or s)
        if q.due:
            item["due"] = q.due.isoformat()
            item["end"] = q.end.isoformat() if q.end else ""
        if q.priority:
            item["priority"] = PRIORITIES.index(q.priority)
        if q.remind_time:
            item["reminder"] = True
            item["remind_time"] = q.remind_time
    item["done"] = done
    return item


def parse_text(text: str, default_name: str, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    tabs: list[dict] = []
    current: dict | None = None
    last: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            last = None
            continue
        if line.startswith("## "):
            current = parse_header(line) or {"name": default_name, "kind": "list", "color": "", "items": []}
            tabs.append(current)
            last = None
            continue
        cats = parse_categories(line)
        if cats is not None:
            if current is not None:
                current["categories"] = cats
            continue
        if line.startswith("> ") or line == ">":
            if current is not None and not current["items"]:
                current["description"] = ((current.get("description") or "") + "\n" if current.get("description")
                                          else "") + line[2:]
            continue
        if line.lstrip().startswith("#"):
            continue
        if (raw.startswith("    ") or raw.startswith("\t")) and last is not None:
            note = raw[4:] if raw.startswith("    ") else raw[1:]
            last["notes"] = (last["notes"] + "\n" if last["notes"] else "") + note.rstrip()
            continue
        if current is None:
            current = {"name": default_name, "kind": "list", "color": "", "description": "", "items": []}
            tabs.append(current)
        item = parse_line(line, today, checklist=current.get("kind") == "checklist")
        if item is None:
            continue
        current["items"].append(item)
        last = item
    return [t for t in tabs if t["items"] or t.get("kind") == "checklist"]


HEADER_ALIASES = {
    "name": ("item", "name", "task", "title", "to do", "todo", "description"),
    "due": ("due", "due date", "date", "start", "start date", "when"),
    "end": ("end", "end date", "until", "finish"),
    "priority": ("priority", "pri", "importance"),
    "notes": ("notes", "note", "details", "comments", "comment"),
    "done": ("done", "completed", "complete", "status", "finished"),
    "remind": ("remind", "reminder", "remind at", "reminder time"),
    "list": ("list", "tab", "category", "project"),
}


def parse_csv(text: str, default_name: str, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []
    header = [h.strip().lower() for h in rows[0]]
    cols: dict[str, int] = {}
    for key, aliases in HEADER_ALIASES.items():
        for i, h in enumerate(header):
            if h in aliases and key not in cols:
                cols[key] = i
    if "name" not in cols:              # no recognisable header: first column is the item
        cols = {"name": 0}
        body = rows
    else:
        body = rows[1:]

    def cell(row: list[str], key: str) -> str:
        i = cols.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    tabs: dict[str, dict] = {}
    for row in body:
        name = cell(row, "name")
        if not name:
            continue
        item = _new_item(name)
        due = cell(row, "due")
        if due:
            _set_dates(item, due, today)
        end = cell(row, "end")
        if end and item["due"]:
            e = parse_single(end, today, ref=dt.date.fromisoformat(item["due"]))
            if e and e.isoformat() > item["due"]:
                item["end"] = e.isoformat()
        pri = _priority(cell(row, "priority"))
        if pri is not None:
            item["priority"] = pri
        item["notes"] = cell(row, "notes")
        status = cell(row, "done").lower()
        item["done"] = status in TRUE_WORDS
        remind = cell(row, "remind")
        if remind:
            t = parse_time(remind)
            if t or remind.lower() in TRUE_WORDS:
                item["reminder"] = True
                item["remind_time"] = t or ""
        list_name = cell(row, "list") or default_name
        tabs.setdefault(list_name, {"name": list_name, "kind": "list", "color": "",
                                    "items": []})["items"].append(item)
    return list(tabs.values())


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load(path: Path, today: dt.date | None = None) -> list[dict]:
    text = read_text_file(path)
    name = path.stem.strip() or "Imported"
    if path.suffix.lower() == ".csv":
        return parse_csv(text, name, today)
    return parse_text(text, name, today)


def export_list(tab: Tab, items: list[Item]) -> str:
    """One list in the import format, so it can be imported again (here or on another PC)."""
    lines = [f"# Docket list export: {tab.name}",
             f"# Saved {dt.datetime.now():%Y-%m-%d %H:%M}. Import it with Settings > Import a list…",
             "", format_header(tab)] + description_lines(tab)
    for it in items:
        parts = [("[x] " if it.done else "") + it.name.replace("|", "/")]
        if tab.kind != "checklist" or it.due:
            if it.due:
                parts.append(it.due + (f" to {it.end}" if it.end else ""))
            parts.append(PRIORITIES[it.priority])
            if it.reminder:
                parts.append("remind" + (f" {it.remind_time}" if it.remind_time else ""))
        if it.time_limit:
            parts.append(f"limit {fmt_limit(it.time_limit)}")
        if it.category:
            parts.append(f"category {it.category.replace('|', '/')}")
        lines.append(" | ".join(parts) if len(parts) > 1 else parts[0])
        for note in it.notes.splitlines():
            lines.append("    " + note)
    return "\n".join(lines) + "\n"


def template_text(tab: Tab, items: list[Item]) -> str:
    """A checklist saved as a reusable template: every step unticked, notes kept."""
    lines = [f"# Docket checklist template: {tab.name}",
             "# Start a new checklist from it with + > New from template,",
             "# or send this file to someone and they can do the same.",
             "", format_header(Tab(0, tab.name, kind="checklist", color=tab.color, timer_on=tab.timer_on,
                                   time_limit=tab.time_limit))]
    lines += description_lines(tab)
    for it in items:
        parts = [it.name.replace("|", "/")]
        if it.time_limit:
            parts.append(f"limit {fmt_limit(it.time_limit)}")
        if it.category:
            parts.append(f"category {it.category.replace('|', '/')}")
        lines.append(" | ".join(parts))
        for note in it.notes.splitlines():
            lines.append("    " + note)
    return "\n".join(lines) + "\n"


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().strip(".")
    return (cleaned or "List")[:80]


def list_templates(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.suffix.lower() in (".txt", ".md") and p.is_file()),
                  key=lambda p: p.stem.casefold())


def load_template(path: Path) -> dict | None:
    """A template file becomes one new checklist (the first list in the file)."""
    tabs = parse_text(read_text_file(path), path.stem)
    if not tabs:
        return None
    tab = tabs[0]
    tab["kind"] = "checklist"
    for it in tab["items"]:
        it["done"] = False
    return tab


TEMPLATE_TXT = """\
# Docket import example
# Import it in Docket: Settings > Import a list…  or right-click a tab > Import a list…
# Imported lists are added as new tabs. Nothing you already have is changed.
#
# Lines starting with # are ignored. Blank lines are fine.
# A line starting with "## " begins a list. Without one, the list is named after the file.
# Add [checklist] after the name for a checklist (steps only, no dates), and/or a colour:
#   ## Map making [checklist, teal]       colours: blue teal sage olive amber peach rose plum lavender slate
# For a checklist with its timer on, add "timer" and/or a total time: [checklist, teal, timer, limit 3h]
# Lines starting with "> " right under the name line are the list's description.
# A step's time limit goes after a " | ": Paint terrain | limit 45m
# Checklist categories: a line "@categories: Terrain; Roads; Assets" under the name line,
#   and a step's category after a " | ": Paint terrain | limit 45m | category Terrain
#
# SIMPLE STYLE: write items the same way you type them in the add box.
#   A date at the end           call mom tomorrow / plan offsite nov 24-28 / pay invoice 12/15
#   !high !med !low anywhere    fix bug !high
#   A time turns on a reminder  dentist fri 3pm
#
# COLUMN STYLE: name first, then any of these, separated by " | ", in any order:
#   a date or range   2026-12-03 / Dec 3 / Nov 24-28 / next week
#   a priority        High / Med / Low
#   a reminder        remind / remind 3:00 PM
#   notes             notes: any text
#
# Indent a line under an item (4 spaces or a tab) to add it to that item's notes.
# Start a line with [x] to bring it in already ticked off. "- " bullets and "1." numbers are ignored.

## Work
Submit quarterly report today !high
Review meeting agenda draft fri
Plan team offsite nov 24-28 !low
    Shortlist two venues.
    Check the budget with finance.
Book training course
Dentist | Dec 3 | Med | remind 3:00 PM
Update project tracker | Nov 30 | High | notes: Add the new milestones
[x] Send kickoff email

## Home [sage]
Renew car insurance next week !h
Weekend groceries sat
    Oats, coffee, apples, rice.
Fix closet door !low

## Map making process [checklist, teal, timer]
@categories: Research; Terrain; Roads; Publishing
> Steps for a new map, start to finish.
Gather heightmap and reference imagery | limit 30m | category Research
Import heightmap and set water level | limit 20m | category Terrain
    Check the sea level against the reference.
Paint terrain textures | limit 1h | category Terrain
Place roads and rail connections | category Roads
Test play and fix issues
Write the listing and upload | category Publishing
"""

TEMPLATE_CSV = """\
List,Item,Due,End,Priority,Remind,Notes,Done
Work,Submit quarterly report,2026-11-20,,High,9:00 AM,Pull figures from the shared drive,
Work,Plan team offsite,2026-11-24,2026-11-28,Low,,Shortlist two venues,
Work,Send kickoff email,,,Med,,,x
Home,Renew car insurance,2026-11-23,,High,,,
Home,Weekend groceries,2026-11-21,,Med,,"Oats, coffee, apples",
Home,Fix closet door,,,Low,,,
"""

TEMPLATE_README = """\
Docket import examples
======================

Docket import example.txt   - type lists in Notepad (or copy them from another app).
Docket import example.csv   - for lists kept in Excel or Google Sheets
                              (File > Save as / Download > CSV).

CSV columns (the header row names them, any order, only "Item" is required):
  List      which tab it goes in (blank = named after the file)
  Item      the item name (also accepted: Name, Task, Title)
  Due       date: 2026-11-24, Nov 24, 11/24/2026 (month/day)
  End       end of a date range (optional)
  Priority  High, Med, Low
  Remind    a time like 3:00 PM, or "yes" for the default reminder time
  Notes     any text
  Done      x, yes or done to bring it in ticked off
"""
