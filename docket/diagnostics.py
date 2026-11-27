"""A small diagnostic log, so a crash can be reported by pasting its details into a chat.

Two files in Docket's data folder (%APPDATA%\\Docket):
* docket-log.txt     a short trail of what Docket was doing (windows opened, docked, pills...),
                     plus any Python error with its traceback. Trimmed to ~200 KB.
* docket-crash.txt   written by Python's faulthandler if Docket crashes hard (Qt or Windows level),
                     with where each thread was at the time.

Nothing is sent anywhere. Settings > About has "Copy diagnostic log" to paste into a chat.
"""
from __future__ import annotations

import datetime as dt
import faulthandler
import platform
import sys
import threading
import traceback
from pathlib import Path

MAX_BYTES = 200_000
KEEP_BYTES = 120_000
START = "=== Docket {version} started {time}"
CLEAN = "=== clean exit {time}"

_log_path: Path | None = None
_crash_path: Path | None = None
_crash_file = None
_lock = threading.Lock()


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _trim(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            data = path.read_bytes()[-KEEP_BYTES:]
            cut = data.find(b"\n")
            path.write_bytes(b"(older lines trimmed)\n" + data[cut + 1:])
    except OSError:
        pass


def write(line: str) -> None:
    if _log_path is None:
        return
    with _lock:
        try:
            with _log_path.open("a", encoding="utf-8") as f:
                f.write(line.rstrip("\n") + "\n")
        except OSError:
            pass


def note(event: str) -> None:
    """One line in the trail, e.g. note("pop-out 4 closing")."""
    write(f"{dt.datetime.now().strftime('%H:%M:%S')} {event}")


def _excepthook(kind, value, tb) -> None:
    write(f"{_now()} ERROR\n" + "".join(traceback.format_exception(kind, value, tb)).rstrip())
    if sys.stderr is not None:
        sys.__excepthook__(kind, value, tb)


def _thread_hook(args) -> None:
    _excepthook(args.exc_type, args.exc_value, args.exc_traceback)


def _qt_messages(mode, context, message) -> None:
    # Only warnings and worse; Qt's routine debug chatter isn't useful here.
    try:
        from PySide6.QtCore import QtMsgType
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            write(f"{dt.datetime.now().strftime('%H:%M:%S')} Qt: {message}")
    except Exception:
        pass


def previous_session_crashed(folder: Path) -> bool:
    """True if the last run ended with a hard crash or an unhandled error (checked before start())."""
    crash = folder / "docket-crash.txt"
    log = folder / "docket-log.txt"
    try:
        crashed = crash.exists() and "Fatal Python error" in crash.read_text(encoding="utf-8", errors="replace") \
            .rsplit("=== session", 1)[-1]
    except OSError:
        crashed = False
    if crashed:
        return True
    try:
        last = log.read_text(encoding="utf-8", errors="replace").rsplit("=== Docket", 1)[-1]
    except OSError:
        return False
    return "ERROR" in last and "=== clean exit" not in last


def start(folder: Path, version: str) -> None:
    """Begin logging for this session. Safe to call once at start-up."""
    global _log_path, _crash_path, _crash_file
    _log_path = folder / "docket-log.txt"
    _crash_path = folder / "docket-crash.txt"
    _trim(_log_path)
    _trim(_crash_path)
    write(START.format(version=version, time=_now())
          + f" · Windows {platform.version()} · Python {platform.python_version()}")
    try:
        from PySide6 import __version__ as qt_version
        write(f"PySide6 {qt_version}")
    except Exception:
        pass
    try:
        _crash_file = _crash_path.open("a", encoding="utf-8")
        _crash_file.write(f"=== session {_now()} (Docket {version})\n")
        _crash_file.flush()
        faulthandler.enable(_crash_file, all_threads=True)
    except OSError:
        _crash_file = None
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_qt_messages)
    except Exception:
        pass


def clean_exit() -> None:
    write(CLEAN.format(time=_now()))


def report(folder: Path | None = None, lines: int = 200) -> str:
    """The text to paste into a chat: the end of the log, and the last crash record if there is one."""
    folder = folder or (_log_path.parent if _log_path else None)
    if folder is None:
        return "No diagnostic log yet."
    parts = []
    try:
        log = (folder / "docket-log.txt").read_text(encoding="utf-8", errors="replace").splitlines()
        parts.append("---- docket-log.txt (last lines) ----\n" + "\n".join(log[-lines:]))
    except OSError:
        parts.append("(no docket-log.txt)")
    try:
        crash = (folder / "docket-crash.txt").read_text(encoding="utf-8", errors="replace")
        sessions = [s for s in crash.split("=== session") if "Fatal Python error" in s]
        if sessions:
            parts.append("---- docket-crash.txt (last crash) ----\n=== session" + sessions[-1].rstrip())
    except OSError:
        pass
    return "\n\n".join(parts)
