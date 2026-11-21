"""Docket: wires the store, windows, tray, reminders, backups and startup together."""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QFileDialog,
                               QMenu, QMessageBox, QSystemTrayIcon, QWidget)

from . import backup, dates, importer, themes
from .store import Store
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
}


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
        self.settings = {k: self.store.get_setting(k, v) for k, v in DEFAULTS.items()}
        first_run = not self.store.tabs()
        if first_run:
            self._seed()
        for tab in self.store.tabs():                    # lists from before colours existed
            if not tab.color:
                self.store.set_tab_color(tab.id, self.next_color())
        self.popouts: dict[int, PopoutWindow] = {}
        self.settings_dialog: SettingsDialog | None = None

        themes.set_current(self.settings["theme"])
        qapp.setStyleSheet(themes.stylesheet(themes.current, self.data_dir / "assets"))
        qapp.setWindowIcon(app_icon(themes.current["accent"]))

        self.wheel_guard = WheelGuard(self)
        qapp.installEventFilter(self.wheel_guard)

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
        menu.addAction("Import a list…", lambda: self.import_lists(self.main))
        menu.addSeparator()
        menu.addAction("Back up now", lambda: self.backup_now(manual=True))
        menu.addAction("Settings", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit Docket", self.quit)
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
        elif key == "tab_tint":
            self.main.rebuild_tabs()
            for w in [self.main, *self.popouts.values()]:
                w.apply_tint()
        elif key == "reminders":
            pass
        elif key in ("backup", "backup_dir", "backup_freq"):
            self.main.update_footer()
            if key == "backup" and value:
                self.dirty = True
                self._backup_debounce.start()

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

    def pill_rect(self, key: str) -> list[int] | None:
        """[width, height] or [width, height, x, y] of a window's pill."""
        rect = self.settings["pill_sizes"].get(key)
        return [int(v) for v in rect] if rect else None

    def save_pill_rect(self, key: str, width: int, height: int, x: int, y: int) -> None:
        sizes = dict(self.settings["pill_sizes"])
        sizes[key] = [int(width), int(height), int(x), int(y)]
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

    def open_settings(self) -> None:
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self, self.main)
            self.settings_dialog.finished.connect(self._settings_closed)
        else:
            self.settings_dialog.refresh_export_choices()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _settings_closed(self) -> None:
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
        w = self.popouts.pop(tab_id, None)
        if w is not None:
            w.closing_for_good = True
            w.close()
            w.deleteLater()

    def pop_out(self, tab_id: int) -> PopoutWindow:
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
        w = self.pop_out(tab_id)
        if w.collapsed:
            w.toggle_collapse()
        offset = QPoint(min(90, w.width() // 3), 18)
        w.move(gpos - offset)
        w.title.begin_manual_drag(offset)

    def dock(self, tab_id: int, index: int | None = None) -> None:
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
        menu.addAction("New priority list", lambda: self.main.new_tab("list"))
        menu.addAction("New checklist", lambda: self.main.new_tab("checklist"))
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
        if tab.is_checklist:
            menu.addAction("Show as a priority list", lambda: self.store.set_tab_kind(tab_id, "list"))
            menu.addAction("Reset checklist…", lambda: self.reset_checklist(tab_id, parent))
            menu.addAction("Save as template…", lambda: self.save_template(tab_id, parent))
        else:
            menu.addAction("Show as a checklist", lambda: self.store.set_tab_kind(tab_id, "checklist"))
        menu.addAction("Export this list…", lambda: self.export_list(tab_id, parent))

    def reset_checklist(self, tab_id: int, parent: QWidget) -> None:
        done = sum(1 for i in self.store.items(tab_id) if i.done)
        if not done:
            self.flash("Nothing ticked yet")
            return
        if confirm(parent, "Reset checklist", f"Untick all {done} step{'s' if done != 1 else ''}?"):
            self.store.reset_checklist(tab_id)
            self.flash("Checklist reset")

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
    def quit(self) -> None:
        self.quitting = True
        self.qapp.quit()

    def _shutdown(self) -> None:
        self.quitting = True
        for page in list(self.pages()):
            page.flush()
        if self.main.isVisible() and not self.main.collapsed:
            self.store.set_setting("main_geometry", bytes(self.main.saveGeometry().toBase64()).decode("ascii"))
        for w in list(self.popouts.values()):
            w.closing_for_good = True
            w.close()
        if self.settings["backup"] and self.dirty:
            try:
                backup.write_backup(self.store, self.backup_dir(), int(self.settings["backup_keep"]))
                self.store.set_setting("last_backup", dt.datetime.now().isoformat(timespec="seconds"))
            except OSError:
                pass
        self.tray.hide()
        self.store.close()


# ---------------------------------------------------------------------------------
def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Docket.Desktop")
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

    app = DocketApp(qapp, sys.argv)

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        app.show_main()

    server.newConnection.connect(on_connection)
    return qapp.exec()
