"""Quick capture, the parts that don't need Qt: which list an item goes to, and what a paste holds."""
from __future__ import annotations

import re

INBOX = "Inbox"


def route(text: str, list_names: list[str]) -> tuple[str, str | None]:
    """'#home buy milk' or 'buy milk #home' -> ('buy milk', 'Home').

    The longest list name that follows a # (any case, spaces allowed) wins, so #map making
    beats #map. An unknown #word is left in the text as written."""
    best: tuple[int, int, str] | None = None
    lowered = text.casefold()
    for name in list_names:
        tag = "#" + name.casefold()
        for m in re.finditer(re.escape(tag), lowered):
            before_ok = m.start() == 0 or lowered[m.start() - 1].isspace()
            after = m.end()
            after_ok = after == len(lowered) or lowered[after].isspace()
            if before_ok and after_ok and (best is None or len(tag) > best[1] - best[0]):
                best = (m.start(), m.end(), name)
    if best is None:
        return text.strip(), None
    start, end, name = best
    return " ".join((text[:start] + " " + text[end:]).split()), name


def paste_kind(text: str) -> str:
    """'list' (a ready-made list: first line '## Name'), 'lines' (several items) or 'one'."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and lines[0].lstrip().startswith("## "):
        return "list"
    return "lines" if len(lines) > 1 else "one"


def paste_lines(text: str) -> list[str]:
    """Each non-empty line of a paste, with list bullets and checkboxes taken off."""
    out = []
    for ln in text.splitlines():
        s = re.sub(r"^\s*(?:[-*•]|\d+[.)]|\[[ xX]\])\s+", "", ln).strip()
        if s:
            out.append(s)
    return out
