"""Companion apps (Docket Ledger first): find them, open them, and tell them where things are.

How a companion fits in (Ledger implements its side of this):
* Its installer registers its exe under Windows' "App Paths", the standard way
  (HKCU or HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\<exe>).
  Docket also looks in the usual install folders, in case that's missing.
* Docket keeps %APPDATA%\\Docket\\shared.json up to date with where its time logs are.
  A companion reads it whenever it starts, so it always looks in the right folder.
* When Docket opens a companion it passes   --folder "<time logs folder>"
  and, for one checklist's log,             --open "<path to the .csv time log>".
To add another companion later, add one line to COMPANIONS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SHARED_FILE = "shared.json"


@dataclass(frozen=True)
class Companion:
    key: str
    name: str            # short name for menus ("Open Ledger")
    full_name: str
    exe: str
    repo: str            # owner/name on GitHub
    folders: tuple[str, ...]

    @property
    def releases_url(self) -> str:
        return f"https://github.com/{self.repo}/releases/latest"


COMPANIONS: tuple[Companion, ...] = (
    Companion("ledger", "Ledger", "Docket Ledger", "DocketLedger.exe", "poplarponderosa-code/Docket-Ledger",
              ("Docket Ledger", "Ledger")),
)


def get(key: str) -> Companion | None:
    return next((c for c in COMPANIONS if c.key == key), None)


def _from_registry(exe: str) -> Path | None:
    if sys.platform != "win32":
        return None
    import winreg
    sub = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, sub) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        path = Path(str(value).strip('"'))
        if path.is_file():
            return path
    return None


def find(companion: Companion) -> Path | None:
    """The companion's exe if it's installed, else None."""
    found = _from_registry(companion.exe)
    if found:
        return found
    bases = [os.environ.get("LOCALAPPDATA", "") and Path(os.environ["LOCALAPPDATA"]) / "Programs",
             os.environ.get("ProgramFiles") and Path(os.environ["ProgramFiles"]),
             os.environ.get("ProgramFiles(x86)") and Path(os.environ["ProgramFiles(x86)"])]
    for base in bases:
        if not base:
            continue
        for folder in companion.folders:
            candidate = Path(base) / folder / companion.exe
            if candidate.is_file():
                return candidate
    return None


def launch(companion: Companion, args: list[str]) -> bool:
    exe = find(companion)
    if exe is None:
        return False
    try:
        subprocess.Popen([str(exe), *args], cwd=str(exe.parent),
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except OSError:
        return False
    return True


def write_shared(data_dir: Path, info: dict) -> None:
    """Update %APPDATA%\\Docket\\shared.json, keeping any keys a companion added."""
    path = Path(data_dir) / SHARED_FILE
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(current, dict):
            current = {}
    except (OSError, ValueError):
        current = {}
    current.update(info)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
