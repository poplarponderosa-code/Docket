"""Plain-text backups that any editor can open, and that Docket can restore.

Format (one file holds every list):

    # Docket backup
    # Saved: 2026-11-20 13:15

    ## Work
    - [ ] Submit quarterly report | due: 2026-11-20 | priority: High | remind 15:00
        Pull figures from the shared drive.
    - [x] Plan offsite | due: 2026-11-24 to 2026-11-28 | priority: Low

Notes sit under their item, indented four spaces.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .store import PRIORITIES, Store, Tab
from .themes import LIST_COLORS

PREFIX = "Docket backup "
ITEM_RE = re.compile(r"^- \[( |x|X)\] (.*)$")
HEADER_RE = re.compile(r"^##\s+(.*?)\s*(?:\[([^\]]*)\])?\s*$")


def format_header(tab: Tab) -> str:
    """'## Map making [checklist, teal]': the list's name, type and colour."""
    attrs = []
    if tab.kind == "checklist":
        attrs.append("checklist")
    if tab.color in LIST_COLORS:
        attrs.append(tab.color)
    return f"## {tab.name}" + (f" [{', '.join(attrs)}]" if attrs else "")


def parse_header(line: str) -> dict | None:
    m = HEADER_RE.match(line.rstrip())
    if not m:
        return None
    name, kind, color = m.group(1).strip(), "list", ""
    for word in (m.group(2) or "").split(","):
        w = word.strip().lower()
        if w in ("checklist", "check list"):
            kind = "checklist"
        elif w in LIST_COLORS:
            color = w
    if m.group(2) is not None and not name:
        name = m.group(2)
    return {"name": name or "List", "kind": kind, "color": color, "items": []}


def render(store: Store, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    lines = ["# Docket backup",
             f"# Saved: {now:%Y-%m-%d %H:%M}",
             "# Restore in Docket: Settings > Restore from backup.",
             ""]
    for tab, items in store.snapshot():
        lines.append(format_header(tab))
        for it in items:
            fields = [f"- [{'x' if it.done else ' '}] {it.name}"]
            if it.due:
                fields.append(f"due: {it.due}" + (f" to {it.end}" if it.end else ""))
            fields.append(f"priority: {PRIORITIES[it.priority]}")
            if it.reminder:
                fields.append("remind" + (f" {it.remind_time}" if it.remind_time else ""))
            lines.append(" | ".join(fields))
            for note_line in it.notes.splitlines():
                lines.append("    " + note_line)
        lines.append("")
    return "\n".join(lines)


def _iso_ok(value: str) -> str:
    try:
        dt.date.fromisoformat(value)
        return value
    except ValueError:
        return ""


def parse(text: str) -> list[dict]:
    tabs: list[dict] = []
    current: dict | None = None
    last: dict | None = None
    for raw in text.splitlines():
        if raw.startswith("## "):
            current = parse_header(raw)
            tabs.append(current)
            last = None
            continue
        m = ITEM_RE.match(raw)
        if m and current is not None:
            parts = m.group(2).split(" | ")
            item = {"name": "", "due": "", "end": "", "priority": 1, "notes": "",
                    "reminder": False, "remind_time": "", "done": m.group(1).lower() == "x"}
            while len(parts) > 1:
                p = parts[-1].strip()
                low = p.lower()
                if low.startswith("due:"):
                    span = p[4:].strip().split(" to ")
                    item["due"] = _iso_ok(span[0].strip())
                    if len(span) > 1:
                        item["end"] = _iso_ok(span[1].strip())
                elif low.startswith("priority:"):
                    word = p[9:].strip().capitalize()
                    item["priority"] = PRIORITIES.index(word) if word in PRIORITIES else 1
                elif low == "remind" or low.startswith("remind "):
                    item["reminder"] = True
                    t = p[6:].strip()
                    if re.fullmatch(r"\d{2}:\d{2}", t):
                        item["remind_time"] = t
                else:
                    break
                parts.pop()
            item["name"] = " | ".join(parts).strip()
            current["items"].append(item)
            last = item
            continue
        if raw.startswith("    ") and last is not None:
            last["notes"] = (last["notes"] + "\n" if last["notes"] else "") + raw[4:]
            continue
        if not raw.strip():
            last = None
    return tabs


def filename(now: dt.datetime) -> str:
    return f"{PREFIX}{now:%Y-%m-%d %H%M%S}.txt"


def list_backups(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob(f"{PREFIX}*.txt") if p.is_file())


def prune(folder: Path, keep: int) -> None:
    files = list_backups(folder)
    for old in files[:max(0, len(files) - max(1, keep))]:
        try:
            old.unlink()
        except OSError:
            pass


def write_backup(store: Store, folder: Path, keep: int = 10,
                 now: dt.datetime | None = None) -> Path:
    now = now or dt.datetime.now()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename(now)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(render(store, now), encoding="utf-8")
    tmp.replace(path)
    prune(folder, keep)
    return path
