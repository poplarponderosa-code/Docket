"""Item links: a web address, a folder or a file."""
from __future__ import annotations

import re
from pathlib import Path

WEB_RE = re.compile(r"^(?:https?://|www\.|mailto:)", re.I)


def normalize(link: str) -> str:
    link = link.strip().strip('"')
    if link.lower().startswith("www."):
        return "https://" + link
    return link


def is_web(link: str) -> bool:
    return bool(WEB_RE.match(link.strip()))


def kind(link: str) -> str:
    """'web', 'folder', 'file', 'missing' (a path that isn't there now) or '' for no link."""
    link = normalize(link)
    if not link:
        return ""
    if is_web(link):
        return "web"
    path = Path(link.removeprefix("file:///"))
    try:
        if path.is_dir():
            return "folder"
        if path.exists():
            return "file"
    except OSError:
        pass
    return "missing"


def icon_name(link: str) -> str:
    k = kind(link)
    return {"web": "globe", "folder": "folder", "file": "file"}.get(k, "folder" if k == "missing" else "")
