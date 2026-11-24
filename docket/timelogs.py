"""Finding and clearing Docket's own time log files. Nothing else in the folder is touched."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

NAME_RE = re.compile(r" (\d{4}-\d{2}-\d{2}) \d{4}\.(txt|csv)$", re.I)
UNITS = {"days": 1, "weeks": 7, "months": 30}


def _is_docket_log(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            first = f.readline().strip()
    except OSError:
        return False
    return first == "# Docket time log" or first.startswith("Checklist,Step,")


def log_files(folder: Path) -> list[tuple[Path, dt.date]]:
    """Every Docket time log (.txt and .csv) in the folder, with the date in its name."""
    if not folder.is_dir():
        return []
    found = []
    for p in folder.iterdir():
        m = NAME_RE.search(p.name)
        if not m or not p.is_file():
            continue
        try:
            day = dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if _is_docket_log(p):
            found.append((p, day))
    return sorted(found, key=lambda pair: (pair[1], pair[0].name))


def to_clear(folder: Path, older_than_days: int | None, today: dt.date | None = None) -> list[Path]:
    """Logs that "Clear all" (None) or "Clear logs older than N days" would delete."""
    today = today or dt.date.today()
    if older_than_days is None:
        return [p for p, _ in log_files(folder)]
    cutoff = today - dt.timedelta(days=max(0, older_than_days))
    return [p for p, day in log_files(folder) if day < cutoff]


def clear(paths: list[Path]) -> int:
    gone = 0
    for p in paths:
        try:
            p.unlink()
            gone += 1
        except OSError:
            pass
    return gone
