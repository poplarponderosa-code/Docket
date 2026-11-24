"""Plain-text backups that any editor can open, and that Docket can restore.

Format (one file holds every list):

    # Docket backup
    # Saved: 2026-11-20 13:15

    ## Work
    - [ ] Submit quarterly report | due: 2026-11-20 | priority: High | remind 15:00
        Pull figures from the shared drive.
    - [x] Plan offsite | due: 2026-11-24 to 2026-11-28 | priority: Low | link: https://example.com

    ## Map release [checklist, client: Acme, template: Map release]

Notes sit under their item, indented four spaces.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .store import PRIORITIES, Store, Tab
from .themes import LIST_COLORS
from .timer import fmt_limit, parse_duration

PREFIX = "Docket backup "
ITEM_RE = re.compile(r"^- \[( |x|X)\] (.*)$")
HEADER_RE = re.compile(r"^##\s+(.*?)\s*(?:\[([^\]]*)\])?\s*$")


def _attr_value(text: str) -> str:
    """Header values can't hold the characters that separate them."""
    return " ".join(text.replace(",", " ").replace("[", "(").replace("]", ")").split())


def format_header(tab: Tab, include_client: bool = True) -> str:
    """'## Map making [checklist, teal, client: Acme]': the list's name, type, colour and fields."""
    attrs = []
    if tab.kind == "checklist":
        attrs.append("checklist")
    if tab.color in LIST_COLORS:
        attrs.append(tab.color)
    if tab.timer_on:
        attrs.append("timer")
    if tab.time_limit:
        attrs.append(f"limit {fmt_limit(tab.time_limit)}")
    if include_client and tab.client.strip():
        attrs.append(f"client: {_attr_value(tab.client)}")
    if tab.template.strip():
        attrs.append(f"template: {_attr_value(tab.template)}")
    return f"## {tab.name}" + (f" [{', '.join(attrs)}]" if attrs else "")


def description_lines(tab: Tab) -> list[str]:
    """Under a list's name line: its categories ('@categories: A; B') and description ('> ' lines)."""
    lines = []
    if tab.category_list:
        lines.append("@categories: " + "; ".join(c.replace(";", ",") for c in tab.category_list))
    if tab.description.strip():
        lines += [f"> {line}" for line in tab.description.splitlines()]
    return lines


def parse_categories(line: str) -> list[str] | None:
    """'@categories: Terrain; Roads' -> ['Terrain', 'Roads'] (None if the line isn't one)."""
    if not line.lower().startswith("@categories"):
        return None
    body = line.split(":", 1)[1] if ":" in line else line[len("@categories"):]
    return [c.strip() for c in body.split(";") if c.strip()]


def parse_header(line: str) -> dict | None:
    m = HEADER_RE.match(line.rstrip())
    if not m:
        return None
    name, kind, color, timer_on, limit = m.group(1).strip(), "list", "", False, 0
    client = template = ""
    for word in (m.group(2) or "").split(","):
        w = word.strip().lower()
        if w.startswith("client:"):
            client = word.split(":", 1)[1].strip()
        elif w.startswith("template:"):
            template = word.split(":", 1)[1].strip()
        elif w in ("checklist", "check list"):
            kind = "checklist"
        elif w in LIST_COLORS:
            color = w
        elif w == "timer":
            timer_on = True
        elif w.startswith("limit"):
            limit = parse_duration(w[5:]) or 0
    if m.group(2) is not None and not name:
        name = m.group(2)
    return {"name": name or "List", "kind": kind, "color": color, "description": "",
            "timer_on": timer_on or bool(limit), "time_limit": limit, "categories": [], "items": [],
            "client": client, "template": template}


def render(store: Store, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    lines = ["# Docket backup",
             f"# Saved: {now:%Y-%m-%d %H:%M}",
             "# Restore in Docket: Settings > Restore from backup.",
             ""]
    for tab, items in store.snapshot():
        lines.append(format_header(tab))
        lines += description_lines(tab)
        for it in items:
            fields = [f"- [{'x' if it.done else ' '}] {it.name}"]
            if it.due:
                fields.append(f"due: {it.due}" + (f" to {it.end}" if it.end else ""))
            fields.append(f"priority: {PRIORITIES[it.priority]}")
            if it.reminder:
                fields.append("remind" + (f" {it.remind_time}" if it.remind_time else ""))
            if it.time_limit:
                fields.append(f"limit: {fmt_limit(it.time_limit)}")
            if it.category:
                fields.append(f"category: {it.category.replace('|', '/')}")
            if it.link:
                fields.append(f"link: {it.link.replace(' | ', ' / ')}")
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
                elif low.startswith("limit:"):
                    item["time_limit"] = parse_duration(p[6:]) or 0
                elif low.startswith("category:"):
                    item["category"] = p[9:].strip()
                elif low.startswith("link:"):
                    item["link"] = p[5:].strip()
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
        cats = parse_categories(raw)
        if cats is not None:
            if current is not None:
                current["categories"] = cats
            continue
        if raw.startswith("> ") or raw == ">":
            if current is not None and not current["items"]:
                current["description"] = (current["description"] + "\n" if current["description"] else "") + raw[2:]
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
