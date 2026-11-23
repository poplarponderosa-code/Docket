"""Windows bits: global keyboard shortcuts, lock/sleep notices, and the alert sound.

Everything here does nothing (and fails quietly) on other systems.
"""
from __future__ import annotations

import sys

WM_HOTKEY = 0x0312
WM_WTSSESSION_CHANGE = 0x02B1
WM_POWERBROADCAST = 0x0218
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 7, 8
PBT_APMSUSPEND, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 4, 7, 0x12

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

# Qt key code -> Windows virtual-key code, for keys that differ.
_QT_TO_VK = {
    0x20: 0x20,                     # Space
    0x01000004: 0x0D, 0x01000005: 0x0D,   # Return, Enter
    0x01000001: 0x09,               # Tab
    0x01000003: 0x08,               # Backspace
    0x01000006: 0x2D, 0x01000007: 0x2E,   # Insert, Delete
    0x01000008: 0x13,               # Pause
    0x01000010: 0x24, 0x01000011: 0x23,   # Home, End
    0x01000012: 0x25, 0x01000013: 0x26, 0x01000014: 0x27, 0x01000015: 0x28,   # arrows
    0x01000016: 0x21, 0x01000017: 0x22,   # Page Up, Page Down
    0x2C: 0xBC, 0x2E: 0xBE, 0x2D: 0xBD, 0x3D: 0xBB, 0x2F: 0xBF, 0x3B: 0xBA,
    0x5B: 0xDB, 0x5D: 0xDD, 0x5C: 0xDC, 0x27: 0xDE, 0x60: 0xC0,
}


def _int(value) -> int:
    return int(getattr(value, "value", value))


def vk_for_qt_key(key: int) -> int | None:
    if 0x41 <= key <= 0x5A or 0x30 <= key <= 0x39:      # A-Z, 0-9 are the same
        return key
    if 0x01000030 <= key <= 0x01000047:                 # F1-F24
        return 0x70 + (key - 0x01000030)
    return _QT_TO_VK.get(key)


def parse_shortcut(text: str) -> tuple[int, int] | None:
    """'Ctrl+Alt+D' -> (modifiers, virtual key) for RegisterHotKey, or None if it can't be used."""
    if not text:
        return None
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence
    seq = QKeySequence(text, QKeySequence.SequenceFormat.PortableText)
    if seq.isEmpty():
        return None
    combo = seq[0]
    key = _int(combo.key())
    mods = combo.keyboardModifiers()
    vk = vk_for_qt_key(key)
    if vk is None:
        return None
    flags = MOD_NOREPEAT
    if mods & Qt.KeyboardModifier.ControlModifier:
        flags |= MOD_CONTROL
    if mods & Qt.KeyboardModifier.AltModifier:
        flags |= MOD_ALT
    if mods & Qt.KeyboardModifier.ShiftModifier:
        flags |= MOD_SHIFT
    if mods & Qt.KeyboardModifier.MetaModifier:
        flags |= MOD_WIN
    return flags, vk


def register_hotkey(hwnd: int, hotkey_id: int, text: str) -> str:
    """Returns '' when it worked, or a short reason it didn't."""
    if sys.platform != "win32":
        return ""
    unregister_hotkey(hwnd, hotkey_id)
    if not text:
        return ""
    parsed = parse_shortcut(text)
    if parsed is None:
        return "That key can't be used as a shortcut"
    try:
        import ctypes
        ok = ctypes.windll.user32.RegisterHotKey(hwnd, hotkey_id, parsed[0], parsed[1])
    except Exception:
        return "Couldn't set the shortcut"
    return "" if ok else "Already used by another program"


def unregister_hotkey(hwnd: int, hotkey_id: int) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.UnregisterHotKey(hwnd, hotkey_id)
    except Exception:
        pass


def watch_session(hwnd: int) -> None:
    """Ask Windows to tell this window when the PC is locked or unlocked."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.wtsapi32.WTSRegisterSessionNotification(hwnd, 0)
    except Exception:
        pass


def play_alert() -> None:
    """Windows' own soft notification sound (follows the person's sound settings)."""
    try:
        import winsound
        winsound.MessageBeep(0x40)          # MB_ICONASTERISK
        return
    except Exception:
        pass
    try:
        from PySide6.QtWidgets import QApplication
        QApplication.beep()
    except Exception:
        pass
