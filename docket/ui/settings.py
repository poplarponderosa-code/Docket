"""Settings, in tabs across the top: General, Appearance, Lists, AI, Timer, Shortcuts, Backup, About.

Each mode only shows what it uses, and everything is laid out to fit the window's width.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QTime, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QMessageBox,
                               QFrame, QGridLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem,
                               QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QTabWidget, QTimeEdit, QToolButton, QVBoxLayout, QWidget)

from .. import __version__, aiprompt, modes, syncfolders, themes, updates
from .icons import make_icon, swatch_icon

if TYPE_CHECKING:
    from ..app import DocketApp

COLUMN_NAMES = {"due": "Due date", "item": "Item", "pri": "Priority"}
SORT_CHOICES = [("due", "Due date"), ("pri", "Priority"), ("item", "Name")]
FREQ_CHOICES = [("change", "After every change"), ("hourly", "Hourly"), ("daily", "Daily")]


class SettingsDialog(QDialog):
    """Settings in tabs across the top. Each mode only shows the tabs and options it uses."""

    def __init__(self, app: "DocketApp", parent: QWidget, tab: str = ""):
        super().__init__(parent)
        self.app = app
        self.setObjectName("Settings")
        self.setWindowTitle("Docket settings")
        self.resize(540, 660)
        self.setMinimumWidth(460)
        s = app.settings
        mode = app.mode()
        self.tabs = QTabWidget()
        self.tabs.setObjectName("SettingsTabs")
        self.tabs.setDocumentMode(True)
        self.tab_keys: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 6, 0, 0)
        outer.addWidget(self.tabs, 1)

        # ---- General
        v = self._page("general", "General")
        v.addWidget(self._section("MODE"))
        mrow = QHBoxLayout()
        self.mode_box = QComboBox()
        for key in modes.MODES:
            self.mode_box.addItem(f"{modes.LABELS[key]}: {modes.SUMMARIES[key][0]}", key)
        self.mode_box.setCurrentIndex(modes.MODES.index(mode))
        self.mode_box.activated.connect(lambda i: app.change_mode(self.mode_box.itemData(i)))
        mrow.addWidget(self.mode_box, 1)
        v.addLayout(mrow)
        v.addWidget(self._hint(" · ".join(modes.SUMMARIES[mode][1])))
        v.addWidget(self._hint("All modes are free. Switching only hides or shows features; nothing is lost."))
        v.addLayout(self._buttons([("Run first-time setup again…", app.show_setup)]))
        v.addWidget(self._section("TOUR & TIPS"))
        v.addLayout(self._buttons([("Take the tour", app.start_tour), ("Show tips again", self._tips_again)]))
        self.tips_box = self._check("Show a tip the first time I use a feature", "tips_on")
        v.addWidget(self.tips_box)
        v.addWidget(self._section("WINDOWS"))
        v.addWidget(self._check("Launch when Windows starts", "startup"))
        v.addWidget(self._check("Start hidden in the tray", "start_hidden"))
        v.addWidget(self._check("Keep windows on top", "on_top"))
        v.addWidget(self._check("Show Docket in Alt+Tab and Task View (it still has no taskbar icon)", "alt_tab"))
        v.addWidget(self._section("REMINDERS"))
        rem = QHBoxLayout()
        rem.addWidget(self._check("Reminders, by default at", "reminders"))
        self.time_edit = QTimeEdit(QTime.fromString(s["remind_time"], "HH:mm"))
        self.time_edit.setDisplayFormat("h:mm AP")
        self.time_edit.timeChanged.connect(lambda t: app.set_setting("remind_time", t.toString("HH:mm")))
        rem.addWidget(self.time_edit)
        rem.addStretch(1)
        v.addLayout(rem)
        v.addWidget(self._hint("Each item can have its own time (open the item). Reminders arrive on the "
                               "item's start date, or right away if it's already late. Checklists have none."))
        v.addStretch(1)

        # ---- Appearance
        v = self._page("appearance", "Appearance")
        v.addWidget(self._section("THEME"))
        grid = QGridLayout()
        grid.setSpacing(4)
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        for i, (key, pal) in enumerate(themes.PALETTES.items()):
            b = QToolButton()
            b.setProperty("swatch", True)
            b.setCheckable(True)
            b.setChecked(key == s["theme"])
            b.setText(pal["name"])
            b.setIcon(swatch_icon(pal["win"], pal["accent"]))
            b.setIconSize(QSize(40, 26))
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: app.set_setting("theme", k))
            self.theme_group.addButton(b)
            grid.addWidget(b, 0, i)
        grid.setColumnStretch(len(themes.PALETTES), 1)
        v.addLayout(grid)
        if modes.has(mode, "tab_tint"):
            v.addWidget(self._check("Fill whole tabs with their list's colour", "tab_tint"))
            v.addWidget(self._hint("Each list has its own colour (right-click its tab > Colour). Off: a coloured "
                                   "dot. On: the whole tab, the list's own window title and its pill are tinted."))
        else:
            v.addWidget(self._hint("Each list has its own colour: right-click its tab > Colour."))
        v.addWidget(self._section("PILLS"))
        v.addWidget(self._check("Keep pills on top", "pill_on_top"))
        prow = QHBoxLayout()
        prow.addWidget(QLabel("New pills show"))
        self.lines_box = QComboBox()
        for n in (1, 2, 3):
            self.lines_box.addItem(f"{n} item{'s' if n > 1 else ''}", n)
        self.lines_box.setCurrentIndex(max(0, int(s.get("pill_lines", 1)) - 1))
        self.lines_box.currentIndexChanged.connect(
            lambda i: app.set_setting("pill_lines", self.lines_box.itemData(i)))
        prow.addWidget(self.lines_box)
        prow.addStretch(1)
        v.addLayout(prow)
        v.addWidget(self._check("Snap pills to each other, the main window and screen edges", "snap_pills"))
        v.addWidget(self._hint("Drag a pill's bottom edge to show 1, 2 or 3 items. Double-click its side edge to "
                               "fit the whole item's width. Hold Ctrl while dragging a pill to move every pill "
                               "snapped to it."))
        v.addStretch(1)

        # ---- Lists
        v = self._page("lists", "Lists")
        v.addWidget(self._section("NEW LISTS"))
        krow = QHBoxLayout()
        krow.addWidget(QLabel("+ New list makes a"))
        self.kind_box = QComboBox()
        self.kind_box.addItem("Checklist", "checklist")
        self.kind_box.addItem("Priority list", "list")
        self.kind_box.setCurrentIndex(0 if s.get("new_list_kind", "checklist") == "checklist" else 1)
        self.kind_box.currentIndexChanged.connect(
            lambda i: app.set_setting("new_list_kind", self.kind_box.itemData(i)))
        krow.addWidget(self.kind_box)
        krow.addStretch(1)
        v.addLayout(krow)
        v.addWidget(self._hint("Switch any list with one click: right-click its tab > Switch to…"))
        prow2 = QHBoxLayout()
        prow2.addWidget(QLabel("New items go at the"))
        self.pos_box = QComboBox()
        self.pos_box.addItem("Bottom", "bottom")
        self.pos_box.addItem("Top", "top")
        self.pos_box.setCurrentIndex(0 if s.get("new_item_pos", "bottom") == "bottom" else 1)
        self.pos_box.currentIndexChanged.connect(lambda i: app.set_setting("new_item_pos", self.pos_box.itemData(i)))
        prow2.addWidget(self.pos_box)
        prow2.addWidget(QLabel("of a list"))
        prow2.addStretch(1)
        v.addLayout(prow2)
        v.addWidget(self._hint("Ctrl+Enter adds an item to the other end, just that once. Priority lists stay "
                               "sorted; this decides where a new item goes among items with the same "
                               "priority and date."))
        v.addWidget(self._section("LONG ITEMS"))
        wrow = QHBoxLayout()
        wrow.addWidget(QLabel("Long item names"))
        self.wrap_box = QComboBox()
        self.wrap_box.addItem("Wrap to fit", True)
        self.wrap_box.addItem("Single line with …", False)
        self.wrap_box.setCurrentIndex(0 if s.get("wrap_items", True) else 1)
        self.wrap_box.currentIndexChanged.connect(lambda i: app.set_setting("wrap_items", self.wrap_box.itemData(i)))
        wrow.addWidget(self.wrap_box)
        wrow.addStretch(1)
        v.addLayout(wrow)
        v.addWidget(self._check("Wrap long items in pills too (the pill grows taller to fit)", "pill_wrap"))
        v.addWidget(self._section("ITEMS"))
        v.addWidget(self._check("Show link icons next to items", "show_links"))
        v.addWidget(self._check("Show completed items", "show_done"))
        v.addWidget(self._section("COLUMNS & SORTING (PRIORITY LISTS)"))
        v.addWidget(self._hint("Drag a column by its handle to change the order, left to right. "
                               "Untick Priority to hide that column."))
        self.col_list = QListWidget()
        self.col_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.col_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.col_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.col_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.col_list.setIconSize(QSize(16, 16))
        self._filling = False
        self._fill_cols()
        model = self.col_list.model()
        model.rowsMoved.connect(lambda *a: QTimer.singleShot(0, self._save_cols))
        model.rowsInserted.connect(lambda *a: QTimer.singleShot(0, self._save_cols))
        self.col_list.itemChanged.connect(self._col_checked)
        v.addWidget(self.col_list)
        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Sort by"))
        self.sort_box = QComboBox()
        for key, label in SORT_CHOICES:
            self.sort_box.addItem(label, key)
        self.sort_box.setCurrentIndex([k for k, _ in SORT_CHOICES].index(s["sort_key"]))
        self.sort_box.currentIndexChanged.connect(self._sort_changed)
        sort_row.addWidget(self.sort_box)
        reset_sort = QPushButton("Reset to due date")
        reset_sort.setObjectName("LinkBtn")
        reset_sort.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_sort.setToolTip("Clicking a column header also changes the sort; this puts it back")
        reset_sort.clicked.connect(self._reset_sort)
        sort_row.addWidget(reset_sort)
        sort_row.addStretch(1)
        v.addLayout(sort_row)
        self.check_list = None
        if modes.has(mode, "timer") or modes.has(mode, "categories"):
            v.addWidget(self._section("COLUMNS (CHECKLISTS)"))
            v.addWidget(self._hint("Drag to change the order. Untick Category or Time to hide that column in "
                                   "every checklist (the timer still runs and the pill still shows it)."))
            self.check_list = QListWidget()
            self.check_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.check_list.setDefaultDropAction(Qt.DropAction.MoveAction)
            self.check_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.check_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.check_list.setIconSize(QSize(16, 16))
            self._fill_check_cols()
            cmodel = self.check_list.model()
            cmodel.rowsMoved.connect(lambda *a: QTimer.singleShot(0, self._save_check_cols))
            cmodel.rowsInserted.connect(lambda *a: QTimer.singleShot(0, self._save_check_cols))
            self.check_list.itemChanged.connect(self._check_col_ticked)
            v.addWidget(self.check_list)
        v.addStretch(1)

        # ---- AI (all modes)
        v = self._page("ai", "AI")
        v.addWidget(self._section("LISTS FROM AN AI CHAT"))
        v.addWidget(self._hint("Copy these instructions into your AI's custom instructions or a project's "
                               "instructions (Claude, ChatGPT, Gemini and others). Then say the phrase below in "
                               "any chat, and it writes the list in Docket's format, ready to paste into "
                               + ("quick capture or " if modes.has(mode, "quick_capture") else "")
                               + "a list's add box."))
        v.addWidget(self._hint("Pasted into a single chat instead, they only last for that conversation."))
        phrow = QHBoxLayout()
        phrow.addWidget(QLabel("Trigger phrase"))
        self.phrase_box = QComboBox()
        for p in aiprompt.PHRASES:
            self.phrase_box.addItem(f"“{p}”", p)
        self.phrase_box.addItem("Custom…", "custom")
        current = s.get("ai_phrase", aiprompt.DEFAULT_PHRASE)
        idx = self.phrase_box.findData(current)
        self.phrase_box.setCurrentIndex(idx if idx >= 0 else 0)
        phrow.addWidget(self.phrase_box, 1)
        v.addLayout(phrow)
        self.phrase_edit = QLineEdit(s.get("ai_phrase_custom", ""))
        self.phrase_edit.setPlaceholderText("Your own phrase, e.g. “docket this”")
        self.phrase_edit.setMaxLength(60)
        self.phrase_edit.setVisible(current == "custom")
        self.phrase_edit.editingFinished.connect(self._custom_phrase_done)
        self.phrase_edit.textChanged.connect(lambda _t: self._refresh_ai_text())
        v.addWidget(self.phrase_edit)
        self.phrase_box.currentIndexChanged.connect(self._phrase_changed)
        self.ai_update = self._hint("")
        self.ai_update.setObjectName("AttentionHint")
        v.addWidget(self.ai_update)
        ai_btns = QHBoxLayout()
        self.copy_ai_btn = QPushButton("Copy instructions")
        self.copy_ai_btn.setProperty("primary", True)
        self.copy_ai_btn.setMinimumWidth(150)
        self.copy_ai_btn.clicked.connect(self._copy_ai)
        ai_btns.addWidget(self.copy_ai_btn)
        self.ai_show = QPushButton("Show full instructions")
        self.ai_show.setCheckable(True)
        self.ai_show.toggled.connect(self._toggle_ai_text)
        ai_btns.addWidget(self.ai_show)
        ai_btns.addStretch(1)
        v.addLayout(ai_btns)
        from PySide6.QtWidgets import QPlainTextEdit
        self.ai_text = QPlainTextEdit()
        self.ai_text.setReadOnly(True)
        self.ai_text.setMinimumHeight(260)
        self.ai_text.setVisible(False)
        v.addWidget(self.ai_text)
        self._refresh_ai_text()
        v.addWidget(self._hint("The instructions tell the AI to leave out client labels unless you typed one, "
                               "and to use your own category names. Nothing is sent anywhere by Docket: you "
                               "copy and paste."))
        v.addStretch(1)

        # ---- Timer (Pro)
        self.log_folder = QLineEdit(str(app.timelog_dir()))
        if modes.has(mode, "timer"):
            v = self._page("timer", "Timer")
            v.addWidget(self._section("CHECKLIST TIMER"))
            v.addWidget(self._hint("Turn a checklist's timer on with right-click its tab > Use a timer. Time runs "
                                   "on the top unticked step; ticking it starts the next one. Click a step's time "
                                   "to give it a limit, and the total in the header for the whole checklist."))
            v.addWidget(self._check("Play a sound when time's up", "timer_sound"))
            v.addWidget(self._section("TIME LOGS"))
            v.addWidget(self._field_label("Time logs folder (saved when you tick the last step)"))
            self.log_folder.setReadOnly(True)
            v.addWidget(self.log_folder)
            v.addLayout(self._buttons([("Change folder…", self._change_logs), ("Open folder", self._open_logs)]))
            self.csv_box = QCheckBox("Also save a CSV copy (opens in Excel or Google Sheets)")
            self.csv_box.setChecked(bool(s["timelog_csv"]))
            self.csv_box.toggled.connect(self._csv_toggled)
            v.addWidget(self.csv_box)
            self.logs_note = self._hint(syncfolders.note(app.timelog_dir(), "Time logs"))
            self.logs_note.setVisible(bool(self.logs_note.text()))
            v.addWidget(self.logs_note)
            crow = QHBoxLayout()
            crow.addWidget(QLabel("Clear logs older than"))
            self.clear_n = QSpinBox()
            self.clear_n.setRange(1, 999)
            self.clear_n.setValue(int(s.get("clear_logs_n", 3)))
            crow.addWidget(self.clear_n)
            self.clear_unit = QComboBox()
            for unit in ("days", "weeks", "months"):
                self.clear_unit.addItem(unit, unit)
            self.clear_unit.setCurrentIndex(max(0, self.clear_unit.findData(s.get("clear_logs_unit", "months"))))
            crow.addWidget(self.clear_unit)
            older = QPushButton("Clear…")
            older.clicked.connect(self._clear_older)
            crow.addWidget(older)
            crow.addStretch(1)
            v.addLayout(crow)
            v.addLayout(self._buttons([("Clear all time logs…", lambda: app.clear_time_logs(None, self))]))
            v.addWidget(self._hint("Only Docket's own time logs are deleted. Nothing is cleared automatically."))
            v.addWidget(self._section("COPY LIST"))
            v.addWidget(self._check("Include the client label when copying a list", "copy_client"))
            v.addWidget(self._hint("Off: Copy list leaves the client label out, so pasting a list into an AI chat "
                                   "doesn't send it. Backups and exports always keep it."))
            v.addWidget(self._section("LEDGER"))
            from .. import companions
            ledger = companions.get("ledger")
            has_ledger = ledger is not None and companions.find(ledger) is not None
            v.addLayout(self._buttons([("Open Ledger" if has_ledger else "Get Ledger…",
                                        lambda: app.open_companion("ledger"))]))
            v.addWidget(self._hint("Docket Ledger, the companion app, turns time logs into tidy PDF timesheets "
                                   "and invoices. It finds the time logs folder by itself."))
            v.addStretch(1)

        # ---- Shortcuts & quick capture (Advanced)
        self.key_edits: dict[str, QKeySequenceEdit] = {}
        self.key_status: dict[str, QLabel] = {}
        if modes.has(mode, "shortcuts"):
            v = self._page("shortcuts", "Shortcuts")
            v.addWidget(self._section("KEYBOARD SHORTCUTS"))
            v.addWidget(self._hint("These work from any program. Click a box and press the keys you want; "
                                   "Backspace clears it."))
            grid = QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(4)
            for row, (key, label) in enumerate((("hotkey_capture", "Quick capture"),
                                                ("hotkey_show", "Show or hide Docket"),
                                                ("hotkey_tick", "Tick the top item"),
                                                ("hotkey_timer", "Start or pause the timer"))):
                grid.addWidget(QLabel(label), row * 2, 0)
                edit = QKeySequenceEdit(QKeySequence(s.get(key, ""), QKeySequence.SequenceFormat.PortableText))
                if hasattr(edit, "setMaximumSequenceLength"):
                    edit.setMaximumSequenceLength(1)
                if hasattr(edit, "setClearButtonEnabled"):
                    edit.setClearButtonEnabled(True)
                edit.editingFinished.connect(lambda k=key, e=edit: self._save_key(k, e))
                edit.keySequenceChanged.connect(lambda seq, k=key, e=edit: seq.isEmpty() and self._save_key(k, e))
                grid.addWidget(edit, row * 2, 1)
                status = QLabel()
                status.setObjectName("Hint")
                status.setWordWrap(True)
                grid.addWidget(status, row * 2 + 1, 1)
                self.key_edits[key] = edit
                self.key_status[key] = status
            grid.setColumnStretch(1, 1)
            v.addLayout(grid)
            v.addLayout(self._buttons([("Reset to F16, F13, F14, F15", self._reset_keys)]))
            v.addWidget(self._section("QUICK CAPTURE"))
            trow = QHBoxLayout()
            trow.addWidget(QLabel("New items go to"))
            self.target_box = QComboBox()
            self.target_box.addItem("Inbox", "inbox")
            self.target_box.addItem("The last list I used", "last")
            self.target_box.addItem("A list I choose", "list")
            self.target_box.setCurrentIndex(max(0, self.target_box.findData(s.get("capture_target", "inbox"))))
            self.target_box.currentIndexChanged.connect(self._target_changed)
            trow.addWidget(self.target_box)
            self.target_list = QComboBox()
            self.target_list.setMinimumContentsLength(10)
            self._fill_target_lists()
            self.target_list.activated.connect(
                lambda i: app.set_setting("capture_list", self.target_list.itemData(i)))
            trow.addWidget(self.target_list)
            trow.addStretch(1)
            v.addLayout(trow)
            self.target_list.setVisible(s.get("capture_target") == "list")
            frow = QHBoxLayout()
            frow.addWidget(QLabel("While a full-screen app is open"))
            self.fs_box = QComboBox()
            self.fs_box.addItem("Ignore the shortcut", "ignore")
            self.fs_box.addItem("Open anyway", "open")
            self.fs_box.setCurrentIndex(0 if s.get("capture_fullscreen", "ignore") == "ignore" else 1)
            self.fs_box.currentIndexChanged.connect(
                lambda i: app.set_setting("capture_fullscreen", self.fs_box.itemData(i)))
            frow.addWidget(self.fs_box)
            frow.addStretch(1)
            v.addLayout(frow)
            v.addWidget(self._hint("In the capture box: Enter adds and closes, Shift+Enter adds and stays open, "
                                   "Esc closes. Tab picks a list, or type #listname. Paste several lines to add "
                                   "them all; paste text starting with “## Name” to make a new list."))
            info = QFrame()
            info.setObjectName("InfoBox")
            ib = QVBoxLayout(info)
            ib.setContentsMargins(12, 10, 12, 10)
            text = QLabel(
                "<b>Using a Stream Deck</b><br>"
                "1. In the Stream Deck app, drag a <b>Hotkey</b> action (under System) onto a key.<br>"
                "2. Click its Hotkey box and press the shortcut from above. Keys like F13 to F16 "
                "aren't on most keyboards, so they can't clash with other programs' shortcuts. Pick them "
                "from the Stream Deck's own key list if your keyboard has no F13.<br>"
                "3. Do the same for the other actions. For a one-press capture of the same phrase, add a "
                "<b>Text</b> action after the quick capture hotkey.<br>"
                "Tick and timer act on the checklist whose timer is running, otherwise on the list you "
                "used last.")
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.RichText)
            ib.addWidget(text)
            v.addWidget(info)
            v.addStretch(1)
            self.sync_hotkey_status()

        # ---- Backup (and templates, import & export)
        v = self._page("backup", "Backup")
        v.addWidget(self._section("BACKUP"))
        v.addWidget(self._check("Auto-backup to plain-text files", "backup"))
        v.addWidget(self._field_label("Backup folder (pick one inside OneDrive or Google Drive to sync it)"))
        self.folder = QLineEdit(s["backup_dir"] or str(app.default_backup_dir()))
        self.folder.editingFinished.connect(lambda: app.set_setting("backup_dir", self.folder.text().strip()))
        v.addWidget(self.folder)
        v.addLayout(self._buttons([("Change folder…", self._browse), ("Open folder", self._open_backups)]))
        self.backup_note = self._hint(syncfolders.note(app.backup_dir(), "Your lists"))
        self.backup_note.setVisible(bool(self.backup_note.text()))
        v.addWidget(self.backup_note)
        fq = QGridLayout()
        fq.setHorizontalSpacing(8)
        fq.addWidget(QLabel("Save a copy"), 0, 0)
        self.freq_box = QComboBox()
        for key, label in FREQ_CHOICES:
            self.freq_box.addItem(label, key)
        self.freq_box.setCurrentIndex([k for k, _ in FREQ_CHOICES].index(s["backup_freq"]))
        self.freq_box.currentIndexChanged.connect(
            lambda i: app.set_setting("backup_freq", self.freq_box.itemData(i)))
        fq.addWidget(self.freq_box, 0, 1)
        fq.addWidget(QLabel("Keep"), 1, 0)
        self.keep_box = QSpinBox()
        self.keep_box.setRange(1, 200)
        self.keep_box.setValue(int(s["backup_keep"]))
        self.keep_box.setSuffix(" files")
        self.keep_box.valueChanged.connect(lambda n: app.set_setting("backup_keep", n))
        fq.addWidget(self.keep_box, 1, 1)
        fq.setColumnStretch(2, 1)
        v.addLayout(fq)
        v.addLayout(self._buttons([("Back up now", self._backup_now),
                                   ("Restore from backup…", lambda: app.restore_backup(self))]))
        self.last_label = self._hint("")
        v.addWidget(self.last_label)
        self.update_last()

        self.tpl_folder = QLineEdit(str(app.templates_dir()))
        if modes.has(mode, "templates"):
            v.addWidget(self._section("CHECKLIST TEMPLATES"))
            v.addWidget(self._hint("Save a checklist as a template from its tab's right-click menu, then start "
                                   "new ones from + ▾ > New from template. Templates are plain text files you "
                                   "can share."))
            v.addWidget(self._field_label("Templates folder"))
            self.tpl_folder.setReadOnly(True)
            v.addWidget(self.tpl_folder)
            v.addLayout(self._buttons([("Change folder…", self._change_templates),
                                       ("Open folder", self._open_templates)]))
            self.tpl_note = self._hint(syncfolders.note(app.templates_dir(), "Your templates"))
            self.tpl_note.setVisible(bool(self.tpl_note.text()))
            v.addWidget(self.tpl_note)

        v.addWidget(self._section("IMPORT & EXPORT"))
        v.addWidget(self._hint("Import adds lists from a text file or a spreadsheet saved as CSV, each as a "
                               "new tab. Export saves one list as a file that can be imported again, here "
                               "or on another PC."))
        v.addLayout(self._buttons([("Import a list…", lambda: app.import_lists(self))]))
        exp = QHBoxLayout()
        self.export_box = QComboBox()
        self.export_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.export_box.setMinimumContentsLength(10)
        self.refresh_export_choices()
        exp.addWidget(self.export_box, 1)
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export)
        exp.addWidget(export_btn)
        v.addLayout(exp)
        v.addLayout(self._buttons([("Save example files…", lambda: app.save_examples(self))]))
        v.addWidget(self._hint("Example files show every format Docket reads, including checklists and colours."))
        v.addStretch(1)

        # ---- About & updates (and companion apps)
        v = self._page("about", "About")
        v.addWidget(self._section("ABOUT & UPDATES"))
        v.addWidget(QLabel(f"Docket {__version__} · {modes.LABELS[mode]} mode"))
        v.addWidget(self._check("Check for updates once a day", "auto_update"))
        v.addLayout(self._buttons([("Check for updates", lambda: app.check_for_updates(True, self)),
                                   ("Release page", self._open_releases)]))
        self.update_status = self._hint("")
        v.addWidget(self.update_status)
        from .. import companions as _comps
        if _comps.for_mode(mode):
            v.addWidget(self._section("COMPANION APPS"))
            v.addWidget(self._hint("Free apps that work alongside Docket."))
            v.addLayout(self._buttons([("Companion apps…", app.show_companions)]))
        v.addLayout(self._buttons([("Third-party notices", self._open_notices)]))
        v.addStretch(1)

        close = QPushButton("Close")
        close.setProperty("primary", True)
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(18, 8, 18, 14)
        bottom.addStretch(1)
        bottom.addWidget(close)
        outer.addLayout(bottom)
        if tab in self.tab_keys:
            self.tabs.setCurrentIndex(self.tab_keys.index(tab))

    def _page(self, key: str, title: str) -> QVBoxLayout:
        """A tab with its own scroll area; returns the layout to fill."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("SettingsBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(18, 12, 18, 18)
        v.setSpacing(8)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, title)
        self.tab_keys.append(key)
        return v

    def _tips_again(self) -> None:
        self.app.reset_tips()
        self.tips_box.setChecked(True)
        self.app.flash("Tips will show again")

    # ---- AI instructions
    def _ai_phrase(self) -> str:
        choice = self.phrase_box.itemData(self.phrase_box.currentIndex())
        if choice == "custom":
            return aiprompt.clean_phrase(self.phrase_edit.text()) or aiprompt.DEFAULT_PHRASE
        return choice or aiprompt.DEFAULT_PHRASE

    def _phrase_changed(self, i: int) -> None:
        choice = self.phrase_box.itemData(i)
        self.phrase_edit.setVisible(choice == "custom")
        if choice == "custom":
            self.phrase_edit.setFocus()
        self.app.set_setting("ai_phrase", choice)
        self._refresh_ai_text()

    def _custom_phrase_done(self) -> None:
        self.app.set_setting("ai_phrase_custom", aiprompt.clean_phrase(self.phrase_edit.text()))
        self._refresh_ai_text()

    def _refresh_ai_text(self) -> None:
        self.ai_text.setPlainText(aiprompt.instructions(self._ai_phrase()))
        copied = int(self.app.settings.get("ai_copied_version", 0) or 0)
        if aiprompt.update_available(copied):
            self.ai_update.setText("Updated instructions available: copy them again and replace the old ones "
                                   "in your AI.")
        else:
            self.ai_update.setText("")
        self.ai_update.setVisible(bool(self.ai_update.text()))

    def _toggle_ai_text(self, on: bool) -> None:
        self.ai_text.setVisible(on)
        self.ai_show.setText("Hide full instructions" if on else "Show full instructions")

    def _copy_ai(self) -> None:
        from PySide6.QtWidgets import QApplication
        if self.phrase_box.itemData(self.phrase_box.currentIndex()) == "custom":
            self._custom_phrase_done()
        QApplication.clipboard().setText(aiprompt.instructions(self._ai_phrase()))
        self.app.set_setting("ai_copied_version", aiprompt.VERSION)
        self._refresh_ai_text()
        self.copy_ai_btn.setText("Copied ✓")
        QTimer.singleShot(2000, lambda: self.copy_ai_btn.setText("Copy instructions"))

    def current_tab_key(self) -> str:
        i = self.tabs.currentIndex()
        return self.tab_keys[i] if 0 <= i < len(self.tab_keys) else ""

    def _reset_sort(self) -> None:
        self.app.set_setting("sort_key", "due")
        self.app.set_setting("sort_dir", 1)
        self.sort_box.setCurrentIndex(0)

    CHECK_NAMES = {"step": "Step", "category": "Category", "time": "Time"}

    def _fill_check_cols(self) -> None:
        if self.check_list is None:
            return
        self._filling = True
        self.check_list.clear()
        grip = make_icon("grip", themes.current["muted"])
        order = [c for c in self.app.settings.get("check_cols", []) if c in self.CHECK_NAMES]
        order += [c for c in self.CHECK_NAMES if c not in order]
        for key in order:
            item = QListWidgetItem(grip, self.CHECK_NAMES[key])
            item.setData(Qt.ItemDataRole.UserRole, key)
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
            if key != "step":
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                hidden = self.app.settings.get("hide_category" if key == "category" else "hide_time", False)
                item.setCheckState(Qt.CheckState.Unchecked if hidden else Qt.CheckState.Checked)
            item.setFlags(flags)
            self.check_list.addItem(item)
        rows = self.check_list.count()
        row_h = max(30, self.check_list.sizeHintForRow(0)) if rows else 30
        self.check_list.setFixedHeight(rows * row_h + 2 * self.check_list.frameWidth() + 8)
        self._filling = False

    def _save_check_cols(self) -> None:
        if self._filling or self.check_list is None:
            return
        order = []
        for i in range(self.check_list.count()):
            key = self.check_list.item(i).data(Qt.ItemDataRole.UserRole)
            if key and key not in order:
                order.append(key)
        if sorted(order) == sorted(self.CHECK_NAMES) and order != self.app.settings.get("check_cols"):
            self.app.set_setting("check_cols", order)

    def _check_col_ticked(self, item: QListWidgetItem) -> None:
        if self._filling:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key in ("category", "time"):
            self.app.set_setting("hide_category" if key == "category" else "hide_time",
                                 item.checkState() != Qt.CheckState.Checked)

    def _csv_toggled(self, on: bool) -> None:
        if not on and self.app.has("ledger"):
            box = QMessageBox(self)
            box.setWindowTitle("CSV copies")
            box.setText("Ledger reads the CSV copies of your time logs to make timesheets and invoices.\n\n"
                        "Turn them off anyway?")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(QMessageBox.StandardButton.Cancel)
            if box.exec() != QMessageBox.StandardButton.Yes:
                self.csv_box.blockSignals(True)
                self.csv_box.setChecked(True)
                self.csv_box.blockSignals(False)
                return
        self.app.set_setting("timelog_csv", on)

    def _fill_target_lists(self) -> None:
        self.target_list.clear()
        for t in self.app.store.tabs():
            self.target_list.addItem(t.name, t.id)
        i = self.target_list.findData(self.app.settings.get("capture_list"))
        self.target_list.setCurrentIndex(max(0, i))

    def _target_changed(self, i: int) -> None:
        value = self.target_box.itemData(i)
        self.app.set_setting("capture_target", value)
        self.target_list.setVisible(value == "list")
        if value == "list" and not self.app.settings.get("capture_list") and self.target_list.count():
            self.app.set_setting("capture_list", self.target_list.itemData(self.target_list.currentIndex()))

    def _clear_older(self) -> None:
        n, unit = self.clear_n.value(), self.clear_unit.currentData()
        self.app.set_setting("clear_logs_n", n)
        self.app.set_setting("clear_logs_unit", unit)
        from .. import timelogs
        self.app.clear_time_logs(n * timelogs.UNITS[unit], self, f"{n} {unit if n != 1 else unit[:-1]}")

    # ---- helpers --------------------------------------------------------------------
    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Section")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Hint")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _field_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _buttons(items) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, slot in items:
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        return row

    def _check(self, text: str, key: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(bool(self.app.settings[key]))
        box.toggled.connect(lambda on: self.app.set_setting(key, on))
        return box

    def _fill_cols(self) -> None:
        self._filling = True
        self.col_list.clear()
        grip = make_icon("grip", themes.current["muted"])
        for key in self.app.settings["col_order"]:
            item = QListWidgetItem(grip, COLUMN_NAMES[key])
            item.setData(Qt.ItemDataRole.UserRole, key)
            flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            if key == "pri":
                flags |= Qt.ItemFlag.ItemIsUserCheckable
                item.setCheckState(Qt.CheckState.Unchecked if self.app.settings.get("hide_pri")
                                   else Qt.CheckState.Checked)
            item.setFlags(flags)
            self.col_list.addItem(item)
        rows = self.col_list.count()
        row_h = max(30, self.col_list.sizeHintForRow(0)) if rows else 30
        self.col_list.setFixedHeight(rows * row_h + 2 * self.col_list.frameWidth() + 8)
        self._filling = False

    def _save_cols(self) -> None:
        if self._filling:
            return
        order = []
        for i in range(self.col_list.count()):
            key = self.col_list.item(i).data(Qt.ItemDataRole.UserRole)
            if key and key not in order:
                order.append(key)
        if sorted(order) == sorted(COLUMN_NAMES) and order != self.app.settings["col_order"]:
            self.app.set_setting("col_order", order)

    def _col_checked(self, item: QListWidgetItem) -> None:
        if self._filling or item.data(Qt.ItemDataRole.UserRole) != "pri":
            return
        self.app.set_setting("hide_pri", item.checkState() != Qt.CheckState.Checked)

    def sync_columns(self) -> None:
        self._fill_cols()
        self._fill_check_cols()

    def _sort_changed(self, i: int) -> None:
        self.app.set_setting("sort_key", self.sort_box.itemData(i))
        self.app.set_setting("sort_dir", 1)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a backup folder", self.folder.text())
        if path:
            self.folder.setText(path)
            self.app.set_setting("backup_dir", path)
            self.tpl_folder.setText(str(self.app.templates_dir()))
            self.log_folder.setText(str(self.app.timelog_dir()))
            self._sync_notes()
            self.app.warn_synced_logs(self)

    def _open_backups(self) -> None:
        self._open(Path(self.app.backup_dir()))

    def _change_templates(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a templates folder", self.tpl_folder.text())
        if path:
            self.app.set_setting("templates_dir", path)
            self.tpl_folder.setText(str(self.app.templates_dir()))
            self._sync_notes()

    def _open_templates(self) -> None:
        self._open(self.app.templates_dir())

    @staticmethod
    def _open(folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _backup_now(self) -> None:
        self.app.backup_now(manual=True)
        self.update_last()

    def refresh_export_choices(self) -> None:
        if hasattr(self, "target_list"):
            self._fill_target_lists()
        current = self.export_box.currentData()
        self.export_box.clear()
        for tab in self.app.store.tabs():
            self.export_box.addItem(tab.name + ("  (checklist)" if tab.is_checklist else ""), tab.id)
        if current is not None:
            i = self.export_box.findData(current)
            if i >= 0:
                self.export_box.setCurrentIndex(i)
        page = self.app.main.current_page()
        if current is None and page is not None:
            i = self.export_box.findData(page.tab_id)
            if i >= 0:
                self.export_box.setCurrentIndex(i)

    def _export(self) -> None:
        tid = self.export_box.currentData()
        if tid is not None:
            self.app.export_list(tid, self)

    def _save_key(self, key: str, edit: QKeySequenceEdit) -> None:
        text = edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        self.app.set_setting(key, text)
        self.sync_hotkey_status()

    def _reset_keys(self) -> None:
        for key, default in (("hotkey_capture", "F16"), ("hotkey_show", "F13"), ("hotkey_tick", "F14"),
                             ("hotkey_timer", "F15")):
            self.key_edits[key].setKeySequence(QKeySequence(default))
            self.app.set_setting(key, default)
        self.sync_hotkey_status()

    def sync_hotkey_status(self) -> None:
        for key, label in self.key_status.items():
            problem = self.app.hotkey_status.get(key, "")
            label.setText(problem if problem else ("" if self.app.settings.get(key) else "Off"))

    def set_update_status(self, text: str) -> None:
        self.update_status.setText(text)

    def _change_logs(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a folder for time logs", self.log_folder.text())
        if path:
            self.app.set_setting("timelog_dir", path)
            self.log_folder.setText(str(self.app.timelog_dir()))
            self._sync_notes()
            self.app.warn_synced_logs(self)

    def _open_logs(self) -> None:
        self._open(self.app.timelog_dir())

    def _open_releases(self) -> None:
        QDesktopServices.openUrl(QUrl(updates.RELEASES_PAGE))

    def _open_notices(self) -> None:
        import sys
        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
        notices = base / "THIRD-PARTY-NOTICES.txt"
        if notices.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(notices)))
        else:
            QDesktopServices.openUrl(QUrl(f"https://github.com/{updates.GITHUB_REPO}"))

    def _sync_notes(self) -> None:
        for attr, folder, what in (("backup_note", self.app.backup_dir(), "Your lists"),
                                   ("logs_note", self.app.timelog_dir(), "Time logs"),
                                   ("tpl_note", self.app.templates_dir(), "Your templates")):
            label = getattr(self, attr, None)
            if label is not None:
                label.setText(syncfolders.note(folder, what))
                label.setVisible(bool(label.text()))

    def update_last(self) -> None:
        self.last_label.setText(self.app.backup_status(long=True))

    def sync_theme_buttons(self) -> None:
        for b, key in zip(self.theme_group.buttons(), themes.PALETTES):
            b.setChecked(key == self.app.settings["theme"])
