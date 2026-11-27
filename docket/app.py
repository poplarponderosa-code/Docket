"""Docket: wires the store, windows, tray, reminders, backups and startup together."""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QFileDialog,
                               QProgressDialog,
                               QMenu, QMessageBox, QSystemTrayIcon, QWidget)

from . import __version__, backup, capture, companions, dates, diagnostics, importer, modes, system, themes, timelogs, tour, updates
from .store import Store
from .timer import TimerEngine, fmt_duration
from .ui.icons import app_icon, dot_icon, refresh_icons
from .ui.settings import SettingsDialog
from .ui.windows import MainWindow, PopoutWindow, confirm

APP_NAME = "Docket"
SERVER_NAME = "Docket-single-instance"

class WheelGuard(QObject):
    """Stops the scroll wheel from changing dropdowns, dates, times and number boxes by
    accident: the wheel scrolls the page they sit in instead."""

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() == QEvent.Type.Wheel and isinstance(obj, (QAbstractSpinBox, QComboBox)):
            parent = obj.parentWidget()
            while parent is not None and not isinstance(parent, QAbstractScrollArea):
                parent = parent.parentWidget()
            if parent is not None:
                QApplication.sendEvent(parent.verticalScrollBar(), ev)
            return True
        return False


class NativeSink(QWidget):
    """A hidden window that never changes: shortcuts and lock/sleep notices are tied to it, so they
    keep working while Docket's visible windows are remade (pill, keep-on-top, Alt+Tab)."""

    def __init__(self, app: "DocketApp"):
        super().__init__(None, Qt.WindowType.Tool)
        self.app = app
        self.setWindowTitle("Docket messages")

    def nativeEvent(self, event_type, message):
        from .ui.common import win_message
        msg = win_message(event_type, message)
        if msg is not None and msg.message in (system.WM_HOTKEY, system.WM_WTSSESSION_CHANGE,
                                               system.WM_POWERBROADCAST):
            self.app.handle_native(msg)
        return super().nativeEvent(event_type, message)


HOTKEYS = {1: "hotkey_show", 2: "hotkey_tick", 3: "hotkey_timer", 4: "hotkey_capture"}
HOTKEY_FEATURE = {"hotkey_show": "shortcuts", "hotkey_tick": "shortcuts", "hotkey_timer": "timer",
                  "hotkey_capture": "quick_capture"}

DEFAULTS = {
    "theme": "light",
    "sort_key": "due", "sort_dir": 1,
    "col_order": ["due", "item", "pri"], "hide_pri": False, "tab_tint": False,
    "show_done": True,
    "startup": True, "start_hidden": False, "on_top": False, "pill_on_top": True,
    "pill_sizes": {},
    "templates_dir": "",
    "main_collapsed": False, "current_tab": None,
    "reminders": True, "remind_time": "09:00",
    "backup": True, "backup_dir": "", "backup_freq": "change", "backup_keep": 10,
    "last_backup": "",
    "main_geometry": "",
    "tray_hint_shown": False,
    "pill_lines": 1, "snap_pills": True,
    "timer_sound": True, "timelog_dir": "", "timelog_csv": True,
    "hotkey_show": "F13", "hotkey_tick": "F14", "hotkey_timer": "F15",
    "auto_update": True, "last_update_check": "", "skip_version": "",
    "last_logs": {},
    # 1.3.0
    "mode": None, "setup_done": False,
    "wrap_items": True, "pill_wrap": False, "show_links": True, "new_list_kind": "checklist",
    "alt_tab": True, "copy_client": False,
    "hotkey_capture": "F16", "capture_target": "inbox", "capture_list": None,
    "capture_fullscreen": "ignore", "last_capture_tab": None,
    "clear_logs_n": 3, "clear_logs_unit": "months",
    # 1.3.2
    "new_item_pos": "bottom", "check_cols": ["step", "category", "time"], "hide_time": False,
    "hide_category": False, "capture_inbox_id": None, "synced_logs_warned": "",
    # 1.4.0
    "ai_phrase": "put it on the Docket", "ai_phrase_custom": "", "ai_copied_version": 0,
    "tour_done": False, "tour_seen_mode": "", "tips_on": True, "tips_seen": [],
}


def _alive(obj) -> bool:
    """False once Qt has deleted the C++ side of a widget."""
    try:
        import shiboken6
        return shiboken6.isValid(obj)
    except Exception:
        return obj is not None


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
        path = base / APP_NAME
    else:
        path = Path.home() / ".local" / "share" / "docket"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---- Windows startup (current user only, no admin needed) ----------------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --startup'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = Path(__file__).resolve().parent.parent / "run.py"
    return f'"{pythonw if pythonw.exists() else exe}" "{runner}" --startup'


def set_launch_at_startup(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


# ---------------------------------------------------------------------------------
class DocketApp(QObject):
    def __init__(self, qapp: QApplication, argv: list[str]):
        super().__init__()
        self.qapp = qapp
        self.quitting = False
        self.dirty = False
        self.data_dir = data_dir()
        self.store = Store(self.data_dir / "docket.db")
        self.timer = TimerEngine(self.store)
        self.hotkey_status: dict[str, str] = {}
        self.last_active_tab: int | None = None
        self._lock_paused: list[int] = []
        self._last_clock = dt.datetime.now()
        self._clock_count = 0
        self.settings = {k: self.store.get_setting(k, v) for k, v in DEFAULTS.items()}
        first_run = not self.store.tabs()
        self.upgrading = not first_run and not self.settings["mode"]      # from 1.2.x: ask once, Pro picked
        self.setup_dialog = None
        self.capture_window = None
        self._capture_warned = False
        if first_run:
            self._seed()
        for tab in self.store.tabs():                    # lists from before colours existed
            if not tab.color:
                self.store.set_tab_color(tab.id, self.next_color())
        self.popouts: dict[int, PopoutWindow] = {}
        self.settings_dialog: SettingsDialog | None = None
        self.active_tour = None
        self.active_tip = None
        self.tour_invite = None

        themes.set_current(self.settings["theme"])
        qapp.setStyleSheet(themes.stylesheet(themes.current, self.data_dir / "assets"))
        qapp.setWindowIcon(app_icon(themes.current["accent"]))

        self.wheel_guard = WheelGuard(self)
        qapp.installEventFilter(self.wheel_guard)

        self.sink = NativeSink(self)
        self.sink.winId()                         # makes its native window without showing it
        self.main = MainWindow(self)
        self.main.rebuild_tabs(select=self.settings["current_tab"])
        if self.settings["main_geometry"]:
            self.main.restoreGeometry(QByteArray.fromBase64(self.settings["main_geometry"].encode("ascii")))
        self.apply_on_top()

        self.tray = QSystemTrayIcon(app_icon(themes.current["accent"]), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.addAction("Show Docket", self.show_main)
        menu.addAction("Show all list windows", self.show_all)
        menu.addAction("Quick add…", self.quick_add)
        self._tray_capture = menu.addAction("Quick capture…", self.open_capture)
        menu.addAction("Import a list…", lambda: self.import_lists(self.main))
        menu.addSeparator()
        menu.addAction("Back up now", lambda: self.backup_now(manual=True))
        menu.addAction("Settings", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit Docket", lambda: self.quit())
        self._tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

        self.store.subscribe(self._on_change)
        self.store.subscribe_dirty(self._on_dirty)

        self._backup_debounce = QTimer(self)
        self._backup_debounce.setSingleShot(True)
        self._backup_debounce.setInterval(5000)
        self._backup_debounce.timeout.connect(self.backup_now)
        self._minute = QTimer(self)
        self._minute.setInterval(60_000)
        self._minute.timeout.connect(self._tick)
        self._minute.start()
        QTimer.singleShot(3000, self._tick)

        # Put every window back the way it was: pop-outs, and which ones were pills.
        self._restoring = True
        for tab in self.store.tabs():
            if tab.popped:
                w = self._open_popout(tab.id)
                if tab.collapsed:
                    w.toggle_collapse()
                    w.restore_pill_position()
        if self.settings["main_collapsed"]:
            self.main.toggle_collapse()
            self.main.restore_pill_position()
        self._restoring = False

        if first_run and self.settings["startup"]:
            set_launch_at_startup(True)
        elif self.settings["startup"]:
            set_launch_at_startup(True)   # keeps the path current if the app moved

        hidden = "--startup" in argv and self.settings["start_hidden"]
        if not hidden:
            self.show_main()
        self.update_counts()
        qapp.aboutToQuit.connect(self._shutdown)
        # Windows signing out or shutting down: save and back up first, since the app may be ended
        # without a normal quit.
        try:
            qapp.commitDataRequest.connect(lambda _manager: self._save_before_exit())
        except AttributeError:
            pass

        # Windows: shortcuts and lock/unlock notices go to a hidden window that's never remade.
        system.watch_session(int(self.sink.winId()))
        self.register_hotkeys()

        # The checklist timer's clock.
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._clock_tick)
        self._clock.start()
        recovered = self.timer.recover()
        if recovered:
            QTimer.singleShot(1500, lambda: self.offer_resume([t.id for t in recovered],
                                                              "when Docket was last closed"))

        self.write_shared()
        self.updater = updates.UpdateChecker(self)
        QTimer.singleShot(20_000, self._auto_update_check)
        self._sync_mode_bits()
        if not self.settings["mode"]:
            QTimer.singleShot(700, self.show_setup)
        elif tour.should_offer_tour(self.settings) and not hidden:
            QTimer.singleShot(2500, self._invite_tour)
        if "--updated" in argv:
            QTimer.singleShot(1200, lambda: self.flash(f"Updated to Docket {__version__}"))

    def _seed(self) -> None:
        today = dt.date.today()
        t = self.store.add_tab("Welcome", color="blue")
        add = self.store.add_item
        add(t.id, "Type an item above and press Enter", priority=2)
        add(t.id, "Try typing: dentist fri !high", due=today.isoformat(), priority=0,
            notes="Dates and priority at the end of what you type are picked up for you:\n"
                  "  call mom tomorrow\n  plan offsite nov 24-28 !low\n"
                  "  renew passport next week !h\n  pay invoice 12/15\n"
                  "The line under the box shows what it understood before you press Enter.")
        add(t.id, "Click a row to open notes, dates and a reminder", priority=1)
        add(t.id, "Right-click a tab to rename it, colour it, pop it out, or delete it", priority=1)
        self.store.add_tab("My list", color="sage")

    # ---- settings ----------------------------------------------------------------------
    def set_setting(self, key: str, value) -> None:
        if self.settings.get(key) == value:
            return
        self.settings[key] = value
        self.store.set_setting(key, value)
        if key == "theme":
            self.apply_theme()
        elif key in ("on_top", "pill_on_top"):
            self.apply_on_top()
        elif key == "startup":
            set_launch_at_startup(bool(value))
        elif key in ("sort_key", "sort_dir", "col_order", "show_done", "hide_pri"):
            for page in self.pages():
                page.columns_changed()
            self.update_counts()
            if key in ("hide_pri", "col_order") and self.settings_dialog is not None:
                dialog = self.settings_dialog
                QTimer.singleShot(0, lambda: dialog.sync_columns())
        elif key == "pill_lines":
            # The new default applies to every pill; their widths and places are kept.
            sizes = {k: [v[0], 0] + list(v[2:4]) for k, v in self.settings["pill_sizes"].items() if v}
            self.settings["pill_sizes"] = sizes
            self.store.set_setting("pill_sizes", sizes)
            for w in self.all_windows():
                if w.collapsed:
                    w._pill_count = 0
                    w._resize_myself(QSize(w.width(), w.pill_height(int(value))))
                    w.fit_pill_height()
                    w.update_pill()
        elif key.startswith("hotkey_"):
            self.register_hotkeys()
        elif key in ("timelog_dir", "backup_dir", "templates_dir"):
            self.write_shared()
        elif key == "tab_tint":
            self.main.rebuild_tabs()
            for w in [self.main, *self.popouts.values()]:
                w.apply_tint()
        elif key == "reminders":
            pass
        elif key == "mode":
            self._sync_mode_bits()
            for page in self.pages():
                page.columns_changed()
            self.main.rebuild_tabs()
            for w in self.all_windows():
                w.apply_tint()
                w.update_pill()
        elif key in ("check_cols", "hide_time", "hide_category"):
            for page in self.pages():
                page.columns_changed()
            if self.settings_dialog is not None:
                dialog = self.settings_dialog
                QTimer.singleShot(0, lambda: dialog.sync_columns())
        elif key in ("wrap_items", "show_links"):
            for page in self.pages():
                page.refresh()
            for w in self.all_windows():
                w.update_pill()
        elif key == "pill_wrap":
            for w in self.all_windows():
                if w.collapsed:
                    w.fit_pill_height()
                    w.update_pill()
        elif key == "alt_tab":
            for w in self.all_windows():
                w.apply_window_flags()
            self._raise_dialogs()
        elif key in ("backup", "backup_dir", "backup_freq"):
            self.main.update_footer()
            if key == "backup" and value:
                self.dirty = True
                self._backup_debounce.start()

    # ---- modes ---------------------------------------------------------------------------
    def mode(self) -> str:
        m = self.settings.get("mode")
        return m if m in modes.MODES else "pro"

    def has(self, feature: str) -> bool:
        return modes.has(self.mode(), feature)

    def tint_on(self) -> bool:
        return bool(self.settings.get("tab_tint")) and self.has("tab_tint")

    def _sync_mode_bits(self) -> None:
        if hasattr(self, "_tray_capture"):
            self._tray_capture.setVisible(self.has("quick_capture"))
        if hasattr(self, "updater"):
            self.register_hotkeys()

    def change_mode(self, mode: str) -> None:
        old = self.mode()
        if mode == old:
            return
        self.set_setting("mode", mode)
        steps = tour.steps_new_in(old, mode, self.tour_keys())
        if steps:
            QTimer.singleShot(600, lambda: self._invite_mode_tour(mode, steps))
        self.flash(f"{modes.LABELS[mode]} mode")
        if self.settings_dialog is not None:          # rebuild Settings so it shows the new mode's tabs
            tab = self.settings_dialog.current_tab_key()
            old, self.settings_dialog = self.settings_dialog, None
            old.close()
            old.deleteLater()
            QTimer.singleShot(0, lambda: self.open_settings(tab))

    # ---- diagnostics ------------------------------------------------------------------------------
    def copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(f"Docket {__version__}\n\n" + diagnostics.report(data_dir()))
        self.flash("Diagnostic log copied. Paste it into a chat or an email.")

    def open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))

    def offer_crash_report(self) -> None:
        box = QMessageBox(self.main if self.main.isVisible() else None)
        box.setWindowTitle("Docket")
        box.setText("Docket closed unexpectedly last time.")
        box.setInformativeText("To report it, copy the details and paste them into a chat or an email. "
                               "They show what Docket was doing, not your lists.")
        copy = box.addButton("Copy details", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is copy:
            self.copy_diagnostics()

    # ---- tour and tips ---------------------------------------------------------------------------------
    def tour_keys(self) -> dict:
        s = self.settings
        return {"capture_key": s.get("hotkey_capture", ""), "show_key": s.get("hotkey_show", ""),
                "tick_key": s.get("hotkey_tick", "")}

    def start_tour(self, steps=None) -> None:
        """The full tour for the current mode (or the given steps). Restartable from Settings > General."""
        from .ui.tour import Tour
        if self.active_tour is not None:
            self.active_tour.stop(False)
        if self.active_tip is not None:
            self.active_tip.close()
        if self.settings_dialog is not None:
            self.settings_dialog.close()
        steps = steps or tour.steps_for(self.mode(), self.tour_keys())

        def ended(_finished: bool) -> None:
            self.active_tour = None
            self.set_setting("tour_done", True)

        self.active_tour = Tour(self, steps, ended)
        self.active_tour.start()

    def _invite_tour(self) -> None:
        if self.settings.get("tour_done") or self.active_tour is not None or self.tour_invite is not None:
            return
        from .ui.tour import Invite

        def answered(yes: bool) -> None:
            self.tour_invite = None
            self.set_setting("tour_done", True)
            if yes:
                self.start_tour()
            else:
                self.flash("You can take the tour any time: Settings > General")

        self.tour_invite = Invite(self, "Take a quick tour?",
                                  "About a minute: where things are and a few things you might not know "
                                  "Docket does.", "Take the tour", "Not now", answered)
        self.tour_invite.show()

    def _invite_mode_tour(self, mode: str, steps) -> None:
        if self.active_tour is not None or self.tour_invite is not None or self.mode() != mode:
            return
        from .ui.tour import Invite

        def answered(yes: bool) -> None:
            self.tour_invite = None
            if yes:
                self.start_tour(steps)

        label = modes.LABELS.get(mode, mode)
        self.tour_invite = Invite(self, f"{label} mode is on",
                                  f"Want a short tour of what {label} adds?", "Show me", "No thanks", answered)
        self.tour_invite.show()

    def tip(self, key: str, anchor) -> None:
        """Show a one-time tip next to anchor (a widget), if tips are on and it hasn't been shown."""
        if not tour.tip_due(self.settings, key) or self.active_tour is not None or self.active_tip is not None:
            return
        try:
            if anchor is None or not anchor.isVisible():
                return                 # try again next time
        except RuntimeError:           # the widget was rebuilt in the meantime
            return
        from .ui.tour import Tip
        self.set_setting("tips_seen", list(self.settings.get("tips_seen") or []) + [key])
        self.active_tip = Tip(self, key, anchor)
        self.active_tip.show()

    def reset_tips(self) -> None:
        self.set_setting("tips_seen", [])
        self.set_setting("tips_on", True)

    def show_setup(self) -> None:
        from .ui.setup import SetupDialog
        if self.setup_dialog is not None:
            self.setup_dialog.raise_()
            self.setup_dialog.activateWindow()
            return
        dialog = SetupDialog(self, upgrading=self.upgrading or bool(self.settings.get("setup_done")),
                             parent=self.main if self.main.isVisible() else None)
        self.setup_dialog = dialog

        new_install = not self.upgrading and not self.settings.get("setup_done")

        def done(_result) -> None:
            self.setup_dialog = None
            self.upgrading = False
            dialog.deleteLater()
            if not self.settings.get("tour_done"):
                QTimer.singleShot(500, self.start_tour if new_install else self._invite_tour)

        dialog.finished.connect(done)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_companions(self, parent: QWidget | None = None) -> None:
        """Companion apps for this mode, with Install (or Open) buttons, in their own small window."""
        from .ui.setup import CompanionsDialog
        dialog = CompanionsDialog(self, parent or self.settings_dialog or self.main)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def pages(self):
        yield from self.main.pages.values()
        for w in self.popouts.values():
            yield w.page

    def apply_theme(self) -> None:
        themes.set_current(self.settings["theme"])
        self.qapp.setStyleSheet(themes.stylesheet(themes.current, self.data_dir / "assets"))
        icon = app_icon(themes.current["accent"])
        self.qapp.setWindowIcon(icon)
        self.tray.setIcon(icon)
        windows: list[QWidget] = [self.main, *self.popouts.values()]
        if self.settings_dialog:
            windows.append(self.settings_dialog)
            self.settings_dialog.sync_theme_buttons()
        for w in windows:
            refresh_icons(w)
        self.main.retheme()
        for w in self.popouts.values():
            w.retheme()

    def toggle_dark(self) -> None:
        if self.settings["theme"] == "dark":
            self.set_setting("theme", self.store.get_setting("last_light_theme", "light"))
        else:
            self.store.set_setting("last_light_theme", self.settings["theme"])
            self.set_setting("theme", "dark")

    def apply_on_top(self) -> None:
        """Full windows follow "Keep on top"; pills follow their own pin."""
        for w in [self.main, *self.popouts.values()]:
            w.set_on_top(w.wants_on_top())
            w.sync_pin()
        self._raise_dialogs()

    def _raise_dialogs(self) -> None:
        """Remaking a window (keep on top, Alt+Tab) brings it to the front; put Settings back on top."""
        dialog = self.settings_dialog
        if dialog is not None and dialog.isVisible():
            QTimer.singleShot(0, dialog.raise_)
            QTimer.singleShot(0, dialog.activateWindow)

    def pill_rect(self, key: str) -> list[int] | None:
        """[width, height] or [width, height, x, y] of a window's pill."""
        rect = self.settings["pill_sizes"].get(key)
        return [int(v) for v in rect] if rect else None

    def all_windows(self) -> list:
        return [self.main, *self.popouts.values()]

    def save_pill_rect(self, key: str, width: int, height: int, x: int, y: int, count: int = 0) -> None:
        sizes = dict(self.settings["pill_sizes"])
        sizes[key] = [int(width), int(height), int(x), int(y), int(count)]
        self.settings["pill_sizes"] = sizes
        self.store.set_setting("pill_sizes", sizes)

    def on_collapse_changed(self, w) -> None:
        if getattr(self, "_restoring", False):
            return
        if w is self.main:
            self.settings["main_collapsed"] = w.collapsed
            self.store.set_setting("main_collapsed", w.collapsed)
        else:
            self.store.set_tab_collapsed(w.tab_id, w.collapsed)

    def open_settings(self, tab: str = "") -> None:
        if self.settings_dialog is None:
            dialog = SettingsDialog(self, self.main, tab)
            self.settings_dialog = dialog
            dialog.finished.connect(lambda _r=0, d=dialog: self._settings_closed(d))
        else:
            self.settings_dialog.refresh_export_choices()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _settings_closed(self, dialog=None) -> None:
        if dialog is not None and dialog is not self.settings_dialog:
            return
        if self.settings_dialog is not None:
            self.settings_dialog.deleteLater()
            self.settings_dialog = None

    # ---- store events -----------------------------------------------------------------------
    def _on_change(self, tab_id: int | None) -> None:
        if tab_id is None:
            live = {t.id: t for t in self.store.tabs()}
            for tid in list(self.popouts):
                if tid not in live or not live[tid].popped:
                    self._close_popout(tid)
            for tid, w in self.popouts.items():
                w.update_name()
            if self.settings_dialog is not None:
                self.settings_dialog.refresh_export_choices()
            self.main.rebuild_tabs()
            for w in self.popouts.values():
                w.page.schedule_refresh()
        else:
            for page in self.pages():
                if page.tab_id == tab_id:
                    page.schedule_refresh()
        self.update_counts()

    def _on_dirty(self) -> None:
        self.dirty = True
        self.update_counts()
        if self.settings["backup"] and self.settings["backup_freq"] == "change":
            self._backup_debounce.start()

    def update_counts(self) -> None:
        self.main.update_tab_labels()
        for w in self.popouts.values():
            w.update_counts()
        n = self.due_now_count()
        self.tray.setToolTip(f"{APP_NAME}: {n} due now" if n else APP_NAME)

    def checklist_ids(self) -> set[int]:
        return {t.id for t in self.store.tabs() if t.is_checklist}

    def due_now_count(self) -> int:
        today = dt.date.today()
        skip = self.checklist_ids()
        return sum(1 for i in self.store.all_items()
                   if i.tab_id not in skip
                   and dates.status(dates.from_iso(i.due), dates.from_iso(i.end), i.done, today)
                   in ("today", "overdue"))

    def flash(self, message: str) -> None:
        self.main.flash(message)

    # ---- tabs / pop-outs -------------------------------------------------------------------------
    def _open_popout(self, tab_id: int) -> PopoutWindow:
        w = PopoutWindow(self, tab_id)
        self.popouts[tab_id] = w
        w.show()
        return w

    def _close_popout(self, tab_id: int) -> None:
        """Close a pop-out window for good, safely.

        This is often called from inside the pop-out itself (its dock button, its close button, a tab
        dropped back on the main window). Closing and deleting it right there pulled the window out from
        under the code still running in it, and Docket crashed (1.4.3 and earlier). So: hide it now,
        close and delete it once the current event has finished, and keep a reference until Qt has
        actually deleted it (dropping the last reference early also deleted its hidden owner window,
        and the pop-out with it)."""
        w = self.popouts.pop(tab_id, None)
        if w is None:
            return
        diagnostics.note(f"pop-out {tab_id} closing")
        w.closing_for_good = True
        try:
            w.page.flush()
        except Exception:
            pass
        w.hide()
        self._retired = [r for r in getattr(self, "_retired", []) if _alive(r)]
        self._retired.append(w)
        QTimer.singleShot(0, lambda: self._finish_close(w))

    def _finish_close(self, w) -> None:
        if not _alive(w):
            return
        w.close()
        w.deleteLater()

    def pop_out(self, tab_id: int) -> PopoutWindow:
        diagnostics.note(f"pop out list {tab_id}")
        if tab_id in self.popouts:
            self.popouts[tab_id].raise_()
            return self.popouts[tab_id]
        if tab_id in self.main.pages:
            self.main.pages[tab_id].flush()
        self.store.set_tab_popped(tab_id, True)
        self.main.rebuild_tabs()
        w = self._open_popout(tab_id)
        w.activateWindow()
        return w

    def tear_off(self, tab_id: int, gpos: QPoint) -> None:
        """A tab was dragged out of the bar: give it a window that follows the mouse."""
        diagnostics.note(f"tab {tab_id} dragged out")
        w = self.pop_out(tab_id)
        if w.collapsed:
            w.toggle_collapse()
        offset = QPoint(min(90, w.width() // 3), 18)
        w.move(gpos - offset)
        w.title.begin_manual_drag(offset)

    def dock(self, tab_id: int, index: int | None = None) -> None:
        diagnostics.note(f"put list {tab_id} back in the main window" + (f" at {index}" if index is not None else ""))
        if tab_id not in self.popouts and not (self.store.tab(tab_id) and self.store.tab(tab_id).popped):
            return
        self.store.set_tab_popped(tab_id, False)
        if index is not None:
            docked = [self.main.tabs.tabData(i) for i in range(self.main.tabs.count())]
            docked = [t for t in docked if t != tab_id]
            docked.insert(max(0, min(index, len(docked))), tab_id)
            popped = [t.id for t in self.store.tabs() if t.popped and t.id != tab_id]
            self.store.reorder_tabs(docked + popped)
        self._close_popout(tab_id)
        self.main.rebuild_tabs(select=tab_id)
        self.show_main()

    # ---- list colour, type, templates ------------------------------------------------------------
    def paste_lists(self, text: str) -> list:
        """Make new lists from pasted text that starts with "## List name" (quick capture, add box)."""
        data = importer.parse_text(capture.strip_fences(text), "Pasted list")
        picked: list[str] = []
        for t in data:
            if not t.get("color"):
                t["color"] = self.next_color(picked)
            picked.append(t["color"])
        made = self.store.add_lists(data) if data else []
        if made:
            self.main.rebuild_tabs(select=made[0].id)
        return made

    def next_color(self, also_used: list[str] | None = None) -> str:
        used = [t.color for t in self.store.tabs()] + list(also_used or [])
        for key in themes.COLOR_ORDER:
            if key not in used:
                return key
        return themes.COLOR_ORDER[len(used) % len(themes.COLOR_ORDER)]

    def new_list(self, name: str, kind: str = "list"):
        return self.store.add_tab(name, kind=kind, color=self.next_color())

    def fill_new_menu(self, menu: QMenu, parent: QWidget) -> None:
        menu.clear()
        kinds = [("checklist", "New checklist"), ("list", "New priority list")]
        if self.settings.get("new_list_kind") == "list":
            kinds.reverse()
        for kind, label in kinds:
            menu.addAction(label, lambda k=kind: self.main.new_tab(k))
        if not self.has("templates"):
            menu.addSeparator()
            menu.addAction("Import a list…", lambda: self.import_lists(parent))
            return
        tmenu = menu.addMenu("New from template")
        templates = importer.list_templates(self.templates_dir())
        for path in templates:
            tmenu.addAction(path.stem, lambda p=path: self.new_from_template(p, parent))
        if not templates:
            none = tmenu.addAction("No templates yet")
            none.setEnabled(False)
        tmenu.addSeparator()
        tmenu.addAction("Load a template file…", lambda: self.load_template_file(parent))
        tmenu.addAction("Open templates folder", self.open_templates_folder)
        menu.addSeparator()
        menu.addAction("Import a list…", lambda: self.import_lists(parent))

    def fill_list_menu(self, menu: QMenu, tab_id: int, parent: QWidget) -> None:
        tab = self.store.tab(tab_id)
        if tab is None:
            return
        colours = menu.addMenu("Colour")
        for key in themes.COLOR_ORDER:
            name = themes.LIST_COLORS[key][0]
            act = colours.addAction(dot_icon(themes.list_color(key), 12), name,
                                    lambda k=key: self.store.set_tab_color(tab_id, k))
            act.setCheckable(True)
            act.setChecked(tab.color == key)
        menu.addAction("Edit description…", lambda: self.edit_description(tab_id))
        if tab.is_checklist and self.has("client"):
            menu.addAction(f"Client: {tab.client}…" if tab.client else "Client label…",
                           lambda: self.set_client(tab_id, parent))
        if any(i.done for i in self.store.items(tab_id)):
            menu.addAction("Clear checked items…", lambda: self.clear_checked(tab_id, parent))
        menu.addSeparator()
        menu.addAction("Copy list", lambda: self.copy_list(tab_id))
        menu.addAction("Copy as plain text", lambda: self.copy_list(tab_id, plain=True))
        menu.addAction("Export this list…", lambda: self.export_list(tab_id, parent))
        menu.addSeparator()
        if tab.is_checklist:
            if self.has("categories"):
                menu.addAction("Categories…", lambda: self._edit_categories(tab_id))
            if self.has("timer"):
                menu.addAction("Turn the timer off" if tab.timer_on else "Use a timer",
                               lambda: self.set_timer_on(tab_id, not tab.timer_on))
                if tab.timer_on:
                    menu.addAction("Export time log…", lambda: self.save_time_log(tab_id, parent=parent))
                    if self.has("ledger"):
                        ledger = companions.get("ledger")
                        installed = companions.find(ledger) is not None
                        menu.addAction("Make a PDF in Ledger…" if installed else "Get Ledger to make PDFs…",
                                       lambda: self.make_pdf(tab_id))
            menu.addAction("Reset checklist…", lambda: self.reset_checklist(tab_id, parent))
            if self.has("templates"):
                menu.addAction("Save as template…", lambda: self.save_template(tab_id, parent))
            menu.addAction("Switch to priority list", lambda: self.store.set_tab_kind(tab_id, "list"))
        else:
            menu.addAction("Switch to checklist", lambda: self.store.set_tab_kind(tab_id, "checklist"))

    def tick_all(self, tab_id: int, on: bool) -> None:
        """The tick box in a list's header: tick every item, or untick them all."""
        tab = self.store.tab(tab_id)
        if tab is None:
            return
        items = self.store.items(tab_id)
        page = self.page_for(tab_id)
        if on:
            todo = [i for i in (page.sorted_items() if page is not None else items) if not i.done]
            if not todo:
                return
            timed = tab.is_checklist and tab.timer_on and self.has("timer") and \
                (tab.timer_started or any(i.started or i.elapsed for i in items))
            if timed and not confirm(self.main if page is None else page, "Tick every step",
                                     f"Tick all {len(todo)} remaining step{'s' if len(todo) != 1 else ''}? "
                                     "This finishes the checklist and saves its time log."):
                if page is not None:
                    page.refresh()
                return
            for it in todo:
                self.set_done(it.id, True)
        else:
            for it in items:
                if it.done:
                    self.timer.set_done(it.id, False)
        if page is not None:
            page.schedule_refresh()

    def add_typed(self, tab_id: int, text: str, top: bool = False, due: str = "", end: str = "",
                  priority: int = 1):
        """Add one typed or pasted line to a list, the same way an import reads it: dates and !priority at
        the end, a web address as the link, or "name | category Setup | limit 15m | link …" fields.
        due/end/priority are the add box's own picks, used when the text doesn't set them."""
        tab = self.store.tab(tab_id)
        text = (text or "").strip()
        if tab is None or not text:
            return None
        it = importer.parse_line(text, dt.date.today(), checklist=tab.is_checklist, default_priority=priority)
        if it is None:
            return None
        if not it["due"] and due and not tab.is_checklist:
            it["due"], it["end"] = due, end
        category = (it.get("category") or "").strip()
        if category and tab.is_checklist:
            if category not in tab.category_list:
                self.store.add_categories(tab_id, [category])
            if not tab.show_category and self.has("categories"):
                self.store.update_tab(tab_id, show_category=True)
        return self.store.add_item(tab_id, it["name"], due=it["due"], end=it["end"], priority=it["priority"],
                                   notes=it.get("notes", ""), reminder=it["reminder"],
                                   remind_time=it["remind_time"], done=it["done"], link=it.get("link", ""),
                                   category=category if tab.is_checklist else "",
                                   time_limit=it.get("time_limit", 0), top=top)

    def new_items_on_top(self, flip: bool = False) -> bool:
        """New items go to the bottom unless Settings says top; Ctrl+Enter adds to the other end once."""
        top = self.settings.get("new_item_pos", "bottom") == "top"
        return not top if flip else top

    def copy_list(self, tab_id: int, plain: bool = False) -> None:
        tab = self.store.tab(tab_id)
        if tab is None:
            return
        page = self.page_for(tab_id)
        items = page.sorted_items() if page is not None and not plain else self.store.items(tab_id)
        if plain:
            text = importer.plain_text([i for i in items if not i.done] or items)
        else:
            text = importer.export_list(tab, items, comments=False,
                                        include_client=bool(self.settings.get("copy_client")))
        QApplication.clipboard().setText(text)
        self.flash(f"Copied “{tab.name}”" + ("" if plain else " (paste it into quick capture to make a copy)"))

    def set_client(self, tab_id: int, parent: QWidget) -> None:
        tab = self.store.tab(tab_id)
        if tab is None:
            return
        label = ask_client(parent, tab.client, f"Client label for “{tab.name}”")
        if label is not None and label != tab.client:
            self.store.update_tab(tab_id, client=label)
            self.flash(f"Client: {label}" if label else "Client label cleared")

    def reset_checklist(self, tab_id: int, parent: QWidget) -> None:
        items = self.store.items(tab_id)
        done = sum(1 for i in items if i.done)
        timed = any(i.started or i.elapsed for i in items)
        if not done and not timed:
            self.flash("Nothing to reset yet")
            return
        text = f"Untick all {done} step{'s' if done != 1 else ''}?" if done else "Clear the recorded times?"
        if not timed:
            if confirm(parent, "Reset checklist", text):
                self._do_reset(tab_id)
            return
        box = QMessageBox(parent)
        box.setWindowTitle("Reset checklist")
        box.setText(text + "\n\nThis also clears the recorded times.")
        export_btn = box.addButton("Export time log and reset", QMessageBox.ButtonRole.AcceptRole)
        reset_btn = box.addButton("Reset", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(export_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == export_btn:
            if self.save_time_log(tab_id, parent=parent) is None:
                return
            self._do_reset(tab_id)
        elif clicked == reset_btn:
            self._do_reset(tab_id)

    def _do_reset(self, tab_id: int) -> None:
        self.timer.reset(tab_id)
        self.store.reset_checklist(tab_id)
        self.flash("Checklist reset")

    # ---- the checklist timer -----------------------------------------------------------------
    def page_for(self, tab_id: int):
        if tab_id in self.main.pages:
            return self.main.pages[tab_id]
        w = self.popouts.get(tab_id)
        return w.page if w is not None else None

    def windows_showing(self, tab_id: int) -> list:
        shown = []
        w = self.popouts.get(tab_id)
        if w is not None and w.isVisible():
            shown.append(w)
        if self.main.isVisible() and self.main.current_tab_id() == tab_id:
            shown.append(self.main)
        return shown

    def set_done(self, item_id: int, done: bool) -> None:
        item = self.store.item(item_id)
        finished = self.timer.set_done(item_id, done)
        if finished and item is not None:
            path = self.save_time_log(item.tab_id, auto=True)
            total = fmt_duration(self.timer.total_elapsed(item.tab_id))
            self.flash(f"Checklist done in {total}" + (" · time log saved" if path else ""))

    def toggle_timer(self, tab_id: int) -> None:
        tab = self.store.tab(tab_id)
        if tab is None:
            return
        if not tab.timer_on:
            self.set_timer_on(tab_id, True)
        running = self.timer.toggle(tab_id)
        if not running and not self.store.tab(tab_id).timer_running and self.timer.current_item(tab_id) is None:
            self.flash("Every step is ticked. Reset the checklist to time it again.")
        self.refresh_times()

    def play_item(self, tab_id: int, item_id: int) -> None:
        item = self.store.item(item_id)
        if item is not None and item.run_from:
            self.timer.pause(tab_id)
        else:
            self.timer.make_current(tab_id, item_id)
        self.refresh_times()

    def set_timer_on(self, tab_id: int, on: bool) -> None:
        tab = self.store.tab(tab_id)
        if tab is None:
            return
        if not on and tab.timer_running:
            self.timer.pause(tab_id)
        self.store.update_tab(tab_id, timer_on=on)
        if on:
            page = self.page_for(tab_id)
            if page is not None:
                QTimer.singleShot(400, lambda: self.tip("timer", getattr(page, "scroll", page)))

    def open_link(self, link: str) -> None:
        from . import links
        link = links.normalize(link)
        kind = links.kind(link)
        if kind == "web":
            QDesktopServices.openUrl(QUrl(link))
        elif kind in ("folder", "file"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(link))
        elif kind == "missing":
            self.flash(f"Couldn't find {link}")

    def edit_description(self, tab_id: int) -> None:
        page = self.page_for(tab_id)
        if page is not None:
            page.edit_description()

    def warn_synced_logs(self, parent: QWidget | None = None) -> None:
        """Pro: once per folder, point out that time logs (which carry client labels) will sync to the cloud."""
        from . import syncfolders
        if not self.has("timelogs"):
            return
        folder = str(self.timelog_dir())
        name = syncfolders.service(folder)
        if not name or self.settings.get("synced_logs_warned") == folder:
            return
        self.set_setting("synced_logs_warned", folder)
        QMessageBox.information(parent or self.main, "Time logs folder",
                                f"Your time logs folder syncs to {name}:\n{folder}\n\n"
                                "Time logs include step names, categories and client labels. If your work has "
                                "rules about where client information can be stored, check that this folder is "
                                "allowed, or choose a folder that isn't synced in Settings > Timer.")

    def timelog_dir(self) -> Path:
        if self.settings["timelog_dir"]:
            return Path(self.settings["timelog_dir"])
        return self.backup_dir() / "Time logs"

    def save_time_log(self, tab_id: int, auto: bool = False, parent: QWidget | None = None) -> Path | None:
        tab = self.store.tab(tab_id)
        if tab is None:
            return None
        folder = self.timelog_dir()
        stem = f"{importer.safe_filename(tab.name)} {dt.datetime.now():%Y-%m-%d %H%M}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{stem}.txt"
            path.write_text(self.timer.log_text(tab_id), encoding="utf-8")
            if self.settings["timelog_csv"]:
                (folder / f"{stem}.csv").write_text(self.timer.log_csv(tab_id), encoding="utf-8-sig",
                                                     newline="")
        except OSError as e:
            if not auto:
                QMessageBox.warning(parent or self.main, "Time log", f"Couldn't save the time log: {e}")
            return None
        logs = dict(self.settings["last_logs"])
        csv_path = folder / f"{stem}.csv"
        logs[str(tab_id)] = str(csv_path if csv_path.exists() else path)
        self.settings["last_logs"] = logs
        self.store.set_setting("last_logs", logs)
        if not auto:
            self.flash(f"Saved “{path.name}”")
        return path

    def refresh_times(self) -> None:
        for page in self.pages():
            if page.timer_on:
                page.update_times()
        for w in self.all_windows():
            w.update_pill_time()

    def _clock_tick(self) -> None:
        now = dt.datetime.now()
        gap = (now - self._last_clock).total_seconds()
        last = self._last_clock
        self._last_clock = now
        if gap > 90:                                   # the PC was asleep
            paused = self.timer.pause_all(at=last)
            if paused:
                self.offer_resume([t.id for t in paused], "while your PC was asleep")
            return
        running = self.timer.running_tab()
        if running is None:
            return
        self._clock_count += 1
        if self._clock_count % 15 == 0:
            self.timer.heartbeat(now)
        page = self.page_for(running.id)
        if page is not None:
            page.update_times()
        for w in self.windows_showing(running.id) + [p for p in self.popouts.values() if p.tab_id == running.id]:
            w.update_pill_time()
        for tab, item in self.timer.due_alerts(now):
            self.times_up(tab, item)

    def times_up(self, tab, item) -> None:
        if self.settings["timer_sound"]:
            system.play_alert()
        windows = self.windows_showing(tab.id)
        for w in windows:
            w.pulse()
        what = f"“{item.name}”" if item is not None else f"the whole of “{tab.name}”"
        if not windows:
            self.tray.showMessage("Time's up", f"The time for {what} is up.",
                                  QSystemTrayIcon.MessageIcon.Information, 8000)
        else:
            self.flash(f"Time's up for {what}")

    def offer_resume(self, tab_ids: list[int], reason: str) -> None:
        tabs = [self.store.tab(t) for t in tab_ids]
        tabs = [t for t in tabs if t is not None and not t.timer_running]
        if not tabs:
            return
        tab = tabs[0]
        box = QMessageBox(self.main if self.main.isVisible() else None)
        box.setWindowTitle("Timer paused")
        box.setText(f"The timer for “{tab.name}” was paused {reason}.\n\nResume it now?")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()
        if box.clickedButton() == box.button(QMessageBox.StandardButton.Yes):
            self.timer.start(tab.id)
            self.refresh_times()

    # ---- Windows messages: shortcuts, lock, sleep ------------------------------------------------
    def handle_native(self, msg) -> None:
        if msg.message == system.WM_HOTKEY:
            QTimer.singleShot(0, lambda hid=int(msg.wParam): self.on_hotkey(hid))
        elif msg.message == system.WM_WTSSESSION_CHANGE:
            if msg.wParam == system.WTS_SESSION_LOCK:
                self._pause_for_lock()
            elif msg.wParam == system.WTS_SESSION_UNLOCK:
                QTimer.singleShot(800, self._resume_after_lock)
        elif msg.message == system.WM_POWERBROADCAST:
            if msg.wParam == system.PBT_APMSUSPEND:
                self._pause_for_lock()
            elif msg.wParam in (system.PBT_APMRESUMEAUTOMATIC, system.PBT_APMRESUMESUSPEND):
                QTimer.singleShot(1500, self._resume_after_lock)

    def _pause_for_lock(self) -> None:
        paused = self.timer.pause_all()
        self._lock_paused += [t.id for t in paused]
        if paused:
            self.refresh_times()

    def _resume_after_lock(self) -> None:
        ids, self._lock_paused = self._lock_paused, []
        self._last_clock = dt.datetime.now()
        if ids:
            self.offer_resume(ids, "while your PC was locked")

    def register_hotkeys(self) -> None:
        hwnd = int(self.sink.winId())
        for hotkey_id, key in HOTKEYS.items():
            if self.has(HOTKEY_FEATURE[key]) and self.has("shortcuts"):
                self.hotkey_status[key] = system.register_hotkey(hwnd, hotkey_id, self.settings[key])
            else:
                system.unregister_hotkey(hwnd, hotkey_id)
                self.hotkey_status[key] = ""
        if self.settings_dialog is not None:
            self.settings_dialog.sync_hotkey_status()
        problem = self.hotkey_status.get("hotkey_capture", "")
        if problem and self.has("quick_capture") and not self._capture_warned and self.settings.get("mode"):
            self._capture_warned = True
            QTimer.singleShot(2500, lambda: self._warn_capture_key(problem))

    def _warn_capture_key(self, problem: str) -> None:
        box = QMessageBox(self.main if self.main.isVisible() else None)
        box.setWindowTitle("Quick capture")
        box.setText(f"The quick capture shortcut ({self.settings['hotkey_capture']}) couldn't be set up: "
                    f"{problem.lower()}.\n\nChoose another key in Settings > Shortcuts.")
        open_btn = box.addButton("Open Settings", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.exec()
        if box.clickedButton() == open_btn:
            self.open_settings("shortcuts")

    def note_active(self, window) -> None:
        page = window.pill_page()
        if page is not None:
            self.last_active_tab = page.tab_id

    def active_tab_id(self) -> int | None:
        running = self.timer.running_tab()
        if running is not None:
            return running.id
        if self.last_active_tab is not None and self.store.tab(self.last_active_tab) is not None:
            return self.last_active_tab
        return self.main.current_tab_id()

    def on_hotkey(self, hotkey_id: int) -> None:
        key = HOTKEYS.get(hotkey_id)
        if key == "hotkey_capture":
            if self.settings.get("capture_fullscreen", "ignore") == "ignore" and \
                    system.foreground_is_fullscreen(tuple(int(w.winId()) for w in self.all_windows())):
                return
            self.open_capture()
        elif key == "hotkey_show":
            if self.main.isVisible() and self.main.isActiveWindow() and not self.main.isMinimized():
                self.main.hide()
            else:
                self.show_all()
        elif key == "hotkey_tick":
            tab_id = self.active_tab_id()
            if tab_id is None:
                return
            page = self.page_for(tab_id)
            items = page.sorted_items() if page is not None else self.store.items(tab_id)
            top = next((i for i in items if not i.done), None)
            if top is not None:
                self.set_done(top.id, True)
                self.flash(f"Ticked “{top.name}”")
        elif key == "hotkey_timer":
            running = self.timer.running_tab()
            tab_id = running.id if running is not None else self.active_tab_id()
            if tab_id is None:
                return
            tab = self.store.tab(tab_id)
            if tab is None or not tab.is_checklist:
                self.flash("The timer is for checklists")
                return
            self.toggle_timer(tab_id)

    # ---- quick capture -----------------------------------------------------------------------
    def open_capture(self) -> None:
        if not self.has("quick_capture"):
            self.quick_add()
            return
        if self.capture_window is None:
            from .ui.capture import CaptureWindow
            self.capture_window = CaptureWindow(self)
        self.capture_window.open()

    def find_inbox(self):
        """Quick capture's own list. Remembered by the list itself, so it can be renamed freely;
        a list called "Inbox" from 1.3.0/1.3.1 is picked up the first time."""
        tid = self.settings.get("capture_inbox_id")
        tab = self.store.tab(tid) if tid else None
        if tab is None:
            names = {capture.INBOX.casefold(), "inbox"}
            tab = next((t for t in self.store.tabs() if t.name.strip().casefold() in names), None)
            if tab is not None:
                self.set_setting("capture_inbox_id", tab.id)
        return tab

    def inbox_id(self) -> int:
        """Quick capture's list, made the first time something is captured into it."""
        tab = self.find_inbox()
        if tab is None:
            tab = self.store.add_tab(capture.INBOX, kind="list", color=self.next_color())
            self.set_setting("capture_inbox_id", tab.id)
        return tab.id

    def note_capture(self, tab_id: int) -> None:
        self.settings["last_capture_tab"] = tab_id
        self.store.set_setting("last_capture_tab", tab_id)

    # ---- clearing time logs -------------------------------------------------------------------
    def clear_time_logs(self, older_than_days: int | None, parent: QWidget, label: str = "") -> None:
        files = timelogs.to_clear(self.timelog_dir(), older_than_days)
        if not files:
            self.flash("No time logs to clear" if older_than_days is None else f"No time logs older than {label}")
            QMessageBox.information(parent, "Clear time logs", "There are no time logs to clear."
                                    if older_than_days is None else f"No time logs are older than {label}.")
            return
        what = "every time log" if older_than_days is None else f"time logs older than {label}"
        if not confirm(parent, "Clear time logs",
                       f"Delete {what} ({len(files)} file{'s' if len(files) != 1 else ''}) from\n"
                       f"{self.timelog_dir()}?\n\nThis can't be undone. Only Docket's own time logs are deleted."):
            return
        gone = timelogs.clear(files)
        self.flash(f"Deleted {gone} time log file{'s' if gone != 1 else ''}")

    # ---- updates -------------------------------------------------------------------------------
    def _auto_update_check(self) -> None:
        if not self.settings["auto_update"]:
            return
        last = self.settings["last_update_check"]
        try:
            if last and dt.datetime.now() - dt.datetime.fromisoformat(last) < dt.timedelta(hours=20):
                return
        except ValueError:
            pass
        self.check_for_updates(manual=False)

    def check_for_updates(self, manual: bool = True, parent: QWidget | None = None) -> None:
        def result(release, error) -> None:
            self.set_setting("last_update_check", dt.datetime.now().isoformat(timespec="seconds"))
            if release is None:
                if manual:
                    QMessageBox.information(parent or self.main, "Updates",
                                            f"Couldn't check for updates right now.\n\n{error}")
                return
            tag = release.get("tag_name", "")
            if not updates.is_newer(tag):
                if manual:
                    QMessageBox.information(parent or self.main, "Updates",
                                            f"You have the latest version ({__version__}).")
                return
            if not manual and tag == self.settings["skip_version"]:
                return
            self._offer_update(release, parent)

        if manual and self.settings_dialog is not None:
            self.settings_dialog.set_update_status("Checking…")
        self.updater.check(result)

    def _offer_update(self, release: dict, parent: QWidget | None) -> None:
        tag = release.get("tag_name", "")
        notes = (release.get("body") or "").strip()
        box = QMessageBox(parent or self.main)
        box.setWindowTitle("Update available")
        box.setText(f"Docket {tag.lstrip('vV')} is available. You have {__version__}.")
        if notes:
            box.setInformativeText(notes[:600] + ("…" if len(notes) > 600 else ""))
        now_btn = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip_btn = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == skip_btn:
            self.set_setting("skip_version", tag)
        elif clicked == now_btn:
            self._download_update(release, parent)

    def _download_update(self, release: dict, parent: QWidget | None) -> None:
        asset = updates.pick_installer(release)
        page = release.get("html_url") or updates.RELEASES_PAGE
        if not getattr(sys, "frozen", False):
            QDesktopServices.openUrl(QUrl(page))       # running from the Python files: get the code there
            return
        if asset is None:
            box = QMessageBox(parent or self.main)
            box.setWindowTitle("Update")
            box.setText(f"Docket {release.get('tag_name', '').lstrip('vV')} doesn't have an installer attached yet, "
                        "so it can't update itself.\n\nTry again in a little while, or open the release page.")
            open_btn = box.addButton("Open release page", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() == open_btn:
                QDesktopServices.openUrl(QUrl(page))
            return
        name, url = asset
        dest = updates.download_path(name)
        progress = QProgressDialog("Downloading the update…", "Cancel", 0, 100, parent or self.main)
        progress.setWindowTitle("Updating Docket")
        progress.setMinimumDuration(0)
        progress.canceled.connect(self.updater.cancel)

        def on_progress(received: int, total: int) -> None:
            if total > 0:
                progress.setValue(int(received * 100 / total))

        def on_done(path, error) -> None:
            progress.close()
            if path is None:
                if error and "cancel" not in error.lower():
                    QMessageBox.warning(parent or self.main, "Update", f"The download didn't finish: {error}")
                return
            for page in list(self.pages()):
                page.flush()
            if updates.run_installer_and_quit_soon(path):
                self.quit(ask=False)
            else:
                QMessageBox.warning(parent or self.main, "Update",
                                    f"Couldn't start the installer. It's saved here:\n{path}")

        self.updater.download(url, dest, on_progress, on_done)

    def templates_dir(self) -> Path:
        if self.settings["templates_dir"]:
            return Path(self.settings["templates_dir"])
        return self.backup_dir() / "Templates"

    def open_templates_folder(self) -> None:
        folder = self.templates_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def save_template(self, tab_id: int, parent: QWidget) -> None:
        tab = self.store.tab(tab_id)
        if tab is None:
            return
        folder = self.templates_dir()
        path = folder / (importer.safe_filename(tab.name) + ".txt")
        if path.exists() and not confirm(parent, "Save template",
                                         f"A template called “{path.stem}” already exists. Replace it?"):
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(importer.template_text(tab, self.store.items(tab_id)), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(parent, "Save template", f"Couldn't save the template: {e}")
            return
        self.flash(f"Saved template “{path.stem}”")

    def new_from_template(self, path: Path, parent: QWidget) -> None:
        try:
            data = importer.load_template(path)
        except OSError as e:
            QMessageBox.warning(parent, "Template", f"Couldn't read that template: {e}")
            return
        if not data:
            QMessageBox.warning(parent, "Template", "That file has no steps in it.")
            return
        if not data.get("color"):
            data["color"] = self.next_color()
        if self.has("client"):
            label = ask_client(parent, "", f"Client for “{data.get('name') or path.stem}”", skippable=True)
            data["client"] = label or ""
        made = self.store.add_lists([data])
        if made:
            self.main.rebuild_tabs(select=made[0].id)
            self.show_main()
            self.flash(f"Started “{made[0].name}” from a template")

    def load_template_file(self, parent: QWidget) -> None:
        path, _ = QFileDialog.getOpenFileName(parent, "Load a template", str(Path.home()),
                                              "Templates (*.txt *.md);;All files (*)")
        if not path:
            return
        src = Path(path)
        if confirm(parent, "Load template", f"Also keep “{src.stem}” in your templates folder for next time?"):
            try:
                folder = self.templates_dir()
                folder.mkdir(parents=True, exist_ok=True)
                (folder / src.name).write_bytes(src.read_bytes())
            except OSError:
                pass
        self.new_from_template(src, parent)

    def export_list(self, tab_id: int, parent: QWidget) -> None:
        tab = self.store.tab(tab_id)
        if tab is None:
            return
        start = Path.home() / "Documents" / (importer.safe_filename(tab.name) + ".txt")
        path, _ = QFileDialog.getSaveFileName(parent, f"Export “{tab.name}”", str(start),
                                              "Text file (*.txt);;All files (*)")
        if not path:
            return
        try:
            Path(path).write_text(importer.export_list(tab, self.store.items(tab_id)), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(parent, "Export", f"Couldn't save the file: {e}")
            return
        self.flash(f"Exported “{tab.name}”")

    # ---- clearing ticked items ------------------------------------------------------------------
    def clear_checked(self, tab_id: int, parent: QWidget) -> None:
        items = self.store.items(tab_id)
        done = [i for i in items if i.done]
        if not done:
            self.flash("Nothing is ticked")
            return
        tab = self.store.tab(tab_id)
        n = len(done)
        what = "step" if tab is not None and tab.is_checklist else "item"
        text = f"Delete the {n} checked {what}{'s' if n != 1 else ''} in “{tab.name if tab else ''}”?"
        if any(i.elapsed or i.started for i in done):
            text += "\n\nTheir recorded times go too. Export the time log first if you want to keep it."
        text += "\n\nThis can't be undone here, but your backups still have them."
        if confirm(parent, "Clear checked items", text):
            removed = self.store.delete_done(tab_id)
            self.flash(f"Cleared {removed} checked {what}{'s' if removed != 1 else ''}")

    def _edit_categories(self, tab_id: int) -> None:
        page = self.page_for(tab_id)
        if page is not None:
            page.edit_categories()

    # ---- companion apps (Ledger) ----------------------------------------------------------------
    def write_shared(self) -> None:
        """Tell companion apps where Docket keeps things (they read %APPDATA%\\Docket\\shared.json)."""
        companions.write_shared(self.data_dir, {
            "docket_version": __version__,
            "timelog_dir": str(self.timelog_dir()),
            "templates_dir": str(self.templates_dir()),
            "backup_dir": str(self.backup_dir()),
            "updated": dt.datetime.now().isoformat(timespec="seconds"),
        })

    def fill_app_menu(self, menu: QMenu, parent: QWidget) -> None:
        """The D logo's menu. Each companion app gets an Open (or Get…) line."""
        menu.clear()
        added = False
        for comp in companions.for_mode(self.mode()):
            installed = companions.find(comp) is not None
            act = menu.addAction(f"Open {comp.name}" if installed else f"Get {comp.name}…",
                                 lambda c=comp.key: self.open_companion(c))
            act.setToolTip(comp.full_name)
            added = True
        if self.has("timelogs"):
            menu.addAction("Open time logs folder", self.open_timelogs)
            added = True
        if added:
            menu.addSeparator()
        menu.addAction("Settings", self.open_settings)
        menu.addAction("Check for updates", lambda: self.check_for_updates(True, parent))
        menu.addSeparator()
        menu.addAction("Quit Docket", lambda: self.quit())

    def open_companion(self, key: str, extra_args: list[str] | None = None) -> bool:
        """Open a companion app at Docket's time logs, or its download page if it isn't installed."""
        comp = companions.get(key)
        if comp is None:
            return False
        self.write_shared()
        args = ["--folder", str(self.timelog_dir())] + list(extra_args or [])
        if companions.launch(comp, args):
            return True
        QDesktopServices.openUrl(QUrl(comp.releases_url))
        self.flash(f"{comp.full_name} isn't installed yet. Opening its download page.")
        return False

    def open_timelogs(self) -> None:
        folder = self.timelog_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def make_pdf(self, tab_id: int) -> None:
        """Open this checklist's newest time log in Ledger (saving one first if there isn't one)."""
        comp = companions.get("ledger")
        if comp is None:
            return
        if companions.find(comp) is None:
            self.open_companion("ledger")
            return
        last = Path(self.settings["last_logs"].get(str(tab_id), "") or ".")
        if not last.is_file():
            if self.save_time_log(tab_id, auto=True) is None:
                self.flash("Couldn't save a time log for Ledger")
                return
            last = Path(self.settings["last_logs"].get(str(tab_id), ""))
        self.open_companion("ledger", ["--open", str(last)])

    def delete_tab(self, tab_id: int, parent: QWidget) -> None:
        tabs = self.store.tabs()
        if len(tabs) <= 1:
            QMessageBox.information(parent, "Delete list", "You need at least one list.")
            return
        tab = self.store.tab(tab_id)
        n = len(self.store.items(tab_id))
        if n and not confirm(parent, "Delete list",
                             f"Delete “{tab.name}” and its {n} item{'s' if n != 1 else ''}?"):
            return
        self._close_popout(tab_id)
        self.store.delete_tab(tab_id)

    # ---- showing / hiding ------------------------------------------------------------------------
    def show_main(self) -> None:
        if self.main.isMinimized():
            self.main.showNormal()
        self.main.show()
        self.main.raise_()
        self.main.activateWindow()

    def show_all(self) -> None:
        self.show_main()
        for w in self.popouts.values():
            w.show()
            w.raise_()

    def quick_add(self) -> None:
        self.show_main()
        if self.main.collapsed:
            self.main.toggle_collapse()
        page = self.main.current_page()
        if page is not None:
            page.focus_input()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.main.isVisible() and not self.main.isMinimized():
                self.main.hide()
            else:
                self.show_main()

    def on_main_hidden(self) -> None:
        if not self.settings["tray_hint_shown"]:
            self.tray.showMessage(APP_NAME, "Docket is still running here in the tray. "
                                            "Right-click the icon to quit.",
                                  QSystemTrayIcon.MessageIcon.Information, 5000)
            self.set_setting("tray_hint_shown", True)

    # ---- reminders ----------------------------------------------------------------------------------
    def _tick(self) -> None:
        self.check_reminders()
        self.main.update_footer()
        if self.settings["backup"] and self.dirty and self.settings["backup_freq"] in ("hourly", "daily"):
            hours = 1 if self.settings["backup_freq"] == "hourly" else 24
            last = self._last_backup_time()
            if last is None or dt.datetime.now() - last >= dt.timedelta(hours=hours):
                self.backup_now()

    def check_reminders(self) -> None:
        if not self.settings["reminders"]:
            return
        now = dt.datetime.now()
        today = now.date()

        def time_reached(hhmm: str) -> bool:
            try:
                hh, mm = (int(x) for x in hhmm.split(":"))
            except ValueError:
                hh, mm = 9, 0
            return now.time() >= dt.time(hh, mm)

        due_items = []
        skip = self.checklist_ids()
        for it in self.store.all_items():
            if it.tab_id in skip or not it.reminder or it.done or it.reminded or not it.due:
                continue
            start = dates.from_iso(it.due)
            if start is None:
                continue
            if start < today or (start == today and time_reached(it.remind_time or self.settings["remind_time"])):
                due_items.append(it)
        if not due_items:
            return
        for it in due_items:
            self.store.update_item(it.id, quiet=True, reminded=True)
        if len(due_items) == 1:
            it = due_items[0]
            label = dates.due_label(dates.from_iso(it.due), dates.from_iso(it.end), today)
            self.tray.showMessage(f"Reminder: {it.name}", label,
                                  QSystemTrayIcon.MessageIcon.Information, 10_000)
        else:
            names = "\n".join(f"• {i.name}" for i in due_items[:5])
            more = f"\n…and {len(due_items) - 5} more" if len(due_items) > 5 else ""
            self.tray.showMessage(f"{len(due_items)} reminders", names + more,
                                  QSystemTrayIcon.MessageIcon.Information, 10_000)

    # ---- backups ---------------------------------------------------------------------------------------
    def default_backup_dir(self) -> Path:
        return self.data_dir / "backups"

    def backup_dir(self) -> Path:
        return Path(self.settings["backup_dir"]) if self.settings["backup_dir"] else self.default_backup_dir()

    def _last_backup_time(self) -> dt.datetime | None:
        try:
            return dt.datetime.fromisoformat(self.settings["last_backup"]) if self.settings["last_backup"] else None
        except ValueError:
            return None

    def backup_status(self, long: bool = False) -> str:
        if not self.settings["backup"] and not long:
            return "Backup off"
        last = self._last_backup_time()
        if last is None:
            return "Not backed up yet"
        mins = int((dt.datetime.now() - last).total_seconds() // 60)
        if mins < 1:
            ago = "just now"
        elif mins < 60:
            ago = f"{mins} min ago"
        elif mins < 60 * 24:
            ago = f"{mins // 60} h ago"
        else:
            ago = last.strftime("%b %d")
        if long:
            return f"Last backup: {last:%b %d, %Y at %I:%M %p} ({ago}) in {self.backup_dir()}"
        return f"Backed up {ago}"

    def backup_now(self, manual: bool = False) -> Path | None:
        self._backup_debounce.stop()
        try:
            path = backup.write_backup(self.store, self.backup_dir(), int(self.settings["backup_keep"]))
        except OSError as e:
            msg = f"Backup failed: {e}"
            if manual:
                QMessageBox.warning(self.main, "Backup", msg)
            self.flash("Backup failed. Check the folder in Settings.")
            return None
        self.dirty = False
        self.set_setting("last_backup", dt.datetime.now().isoformat(timespec="seconds"))
        self.main.update_footer()
        if manual:
            self.flash(f"Saved {path.name}")
        return path

    def restore_backup(self, parent: QWidget) -> None:
        path, _ = QFileDialog.getOpenFileName(parent, "Restore from backup", str(self.backup_dir()),
                                              "Docket backups (*.txt);;All files (*)")
        if not path:
            return
        try:
            data = backup.parse(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            QMessageBox.warning(parent, "Restore", f"Couldn't read that file: {e}")
            return
        if not data:
            QMessageBox.warning(parent, "Restore", "No lists were found in that file.")
            return
        n = sum(len(t["items"]) for t in data)
        if not confirm(parent, "Restore backup",
                       f"Replace all your lists with {len(data)} list(s) and {n} item(s) from this backup?\n\n"
                       "Your current lists are saved to a backup file first."):
            return
        try:
            backup.write_backup(self.store, self.default_backup_dir(), keep=max(10, int(self.settings["backup_keep"])))
        except OSError:
            pass
        for tid in list(self.popouts):
            self._close_popout(tid)
        for page in list(self.main.pages.values()):
            page.expanded.clear()
        self.store.replace_all(data)
        self.flash("Backup restored")

    # ---- importing lists ----------------------------------------------------------------------------
    def import_lists(self, parent: QWidget) -> None:
        path, _ = QFileDialog.getOpenFileName(parent, "Import a list", str(Path.home()),
                                              "Lists (*.txt *.md *.csv);;All files (*)")
        if not path:
            return
        try:
            data = importer.load(Path(path))
        except OSError as e:
            QMessageBox.warning(parent, "Import", f"Couldn't read that file: {e}")
            return
        if not data:
            QMessageBox.warning(parent, "Import", "No items were found in that file.\n\n"
                                "Settings > Save example files shows the formats Docket reads.")
            return
        n = sum(len(t["items"]) for t in data)
        picked: list[str] = []
        for t in data:
            if not t.get("color"):
                t["color"] = self.next_color(picked)
            picked.append(t["color"])
        made = self.store.add_lists(data)
        if made:
            self.main.rebuild_tabs(select=made[0].id)
            self.show_main()
        names = ", ".join(f"“{t.name}”" for t in made)
        self.flash(f"Imported {n} item{'s' if n != 1 else ''} into {names}")

    def save_examples(self, parent: QWidget) -> None:
        folder = QFileDialog.getExistingDirectory(parent, "Save the example import files in…",
                                                  str(Path.home() / "Documents"))
        if not folder:
            return
        files = {"Docket import example.txt": importer.TEMPLATE_TXT,
                 "Docket import example.csv": importer.TEMPLATE_CSV,
                 "Docket import examples - read me.txt": importer.TEMPLATE_README}
        try:
            for name, text in files.items():
                (Path(folder) / name).write_text(text, encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(parent, "Examples", f"Couldn't save the example files: {e}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ---- quitting -----------------------------------------------------------------------------------------
    def quit(self, ask: bool = True) -> None:
        """Quit Docket. With auto-backup off and unsaved changes, offer a backup first.
        With auto-backup on (any schedule: every change, hourly or daily), changes since the last
        backup are backed up quietly on the way out (_save_before_exit)."""
        if ask and self.dirty and not self.settings["backup"]:
            box = QMessageBox(self.main if self.main.isVisible() else None)
            box.setWindowTitle("Quit Docket")
            box.setText("Your lists have changed since the last backup.\n\nBack up before quitting?")
            backup_btn = box.addButton("Back up and quit", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Quit without backing up", QMessageBox.ButtonRole.DestructiveRole)
            cancel_btn = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(backup_btn)
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            box.exec()
            clicked = box.clickedButton()
            if clicked == cancel_btn:
                return
            if clicked == backup_btn and self.backup_now(manual=True) is None:
                return
        self.quitting = True
        self.qapp.quit()

    def _save_before_exit(self) -> None:
        """Save what's typed and, with auto-backup on, back up changes made since the last backup,
        whatever the schedule, so a Daily backup doesn't lose today's changes on quit."""
        for page in list(self.pages()):
            try:
                page.flush()
            except Exception:
                pass
        if self.settings["backup"] and self.dirty:
            try:
                self._backup_debounce.stop()
                backup.write_backup(self.store, self.backup_dir(), int(self.settings["backup_keep"]))
                self.store.set_setting("last_backup", dt.datetime.now().isoformat(timespec="seconds"))
                self.dirty = False
            except OSError:
                pass

    def _shutdown(self) -> None:
        self.quitting = True
        try:
            self.timer.heartbeat()
            hwnd = int(self.sink.winId())
            for hotkey_id in HOTKEYS:
                system.unregister_hotkey(hwnd, hotkey_id)
        except Exception:
            pass
        for page in list(self.pages()):
            page.flush()
        if self.main.isVisible() and not self.main.collapsed:
            self.store.set_setting("main_geometry", bytes(self.main.saveGeometry().toBase64()).decode("ascii"))
        for w in list(self.popouts.values()):
            w.closing_for_good = True
            w.close()
        if self.capture_window is not None:
            self.capture_window.hide()
            self.capture_window.toast.hide()
        self._save_before_exit()
        diagnostics.clean_exit()
        self.tray.hide()
        self.store.close()


def ask_client(parent: QWidget | None, current: str, title: str, skippable: bool = False) -> str | None:
    """A client label (a short name, never contact details). None = cancelled."""
    from PySide6.QtWidgets import QInputDialog
    tip = ("A short label for who this work is for, like “Acme”. It goes into the time log so Ledger "
           "knows the client; their details stay in Ledger.\n"
           "Use this field instead of putting client names in the checklist title.")
    if skippable:
        tip += "\n\nLeave it empty to skip."
    text, ok = QInputDialog.getText(parent, title, tip, text=current)
    if not ok:
        return "" if skippable else None
    return " ".join(text.split())[:60]


# ---------------------------------------------------------------------------------
_RUNNING_MUTEX = None


def main() -> int:
    global _RUNNING_MUTEX
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Docket.Desktop")
            # Lets the installer and uninstaller see that Docket is running and ask to close it.
            _RUNNING_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "DocketRunningMutex")
        except Exception:
            pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"])
    font.setPointSize(10)
    qapp.setFont(font)

    # One copy at a time: a second launch just brings the first one forward.
    probe = QLocalSocket()
    probe.connectToServer(SERVER_NAME)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    # Only the copy that keeps running logs (a second launch above just hands over and exits).
    crashed_last_time = diagnostics.previous_session_crashed(data_dir())
    diagnostics.start(data_dir(), __version__)
    app = DocketApp(qapp, sys.argv)
    if crashed_last_time:
        QTimer.singleShot(1500, app.offer_crash_report)

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        app.show_main()

    server.newConnection.connect(on_connection)
    return qapp.exec()
