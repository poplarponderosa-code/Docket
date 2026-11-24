"""Spotting folders that a cloud service syncs (OneDrive, Google Drive, Dropbox, iCloud), so Docket
can say so where lists and time logs (which can hold client labels) will be stored."""
from __future__ import annotations

import os
from pathlib import Path

ENV_ROOTS = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")
NAMES = (("onedrive", "OneDrive"), ("google drive", "Google Drive"), ("my drive", "Google Drive"),
         ("googledrive", "Google Drive"), ("dropbox", "Dropbox"), ("icloud drive", "iCloud"),
         ("iclouddrive", "iCloud"), ("box sync", "Box"))


def service(path: str | Path, env: dict | None = None) -> str:
    """The cloud service that syncs this folder ('OneDrive', 'Google Drive', …), or '' for none."""
    if not str(path).strip():
        return ""
    env = os.environ if env is None else env
    p = str(path).replace("/", "\\").rstrip("\\").casefold()
    for key in ENV_ROOTS:
        root = (env.get(key) or "").replace("/", "\\").rstrip("\\").casefold()
        if root and (p == root or p.startswith(root + "\\")):
            return "OneDrive"
    for part in p.split("\\"):
        for needle, name in NAMES:
            if part == needle or part.startswith(needle + " - ") or part.startswith(needle + " ("):
                return name
    return ""


def note(path: str | Path, what: str = "Your lists") -> str:
    """One line for under a folder box, or '' when the folder isn't synced."""
    name = service(path)
    if not name:
        return ""
    return (f"This folder syncs to {name}. {what}, including client labels, will be stored there. "
            "Check this is allowed where you work.")
