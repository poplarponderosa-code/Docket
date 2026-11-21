"""Settings: themes, startup, reminders, columns, sorting, backups, templates and import/export.

Everything is laid out to fit the window's width (rows wrap or stack), so nothing
hides off to the side.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QTime, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QTimeEdit, QToolButton, QVBoxLayout, QWidget)

from .. import themes
from .icons import make_icon, swatch_icon

if TYPE_CHECKING:
    from ..app import DocketApp

COLUMN_NAMES = {"due": "Due date", "item": "Item", "pri": "Priority"}
SORT_CHOICES = [("due", "Due date"), ("pri", "Priority"), ("item", "Name")]
FREQ_CHOICES = [("change", "After every change"), ("hourly", "Hourly"), ("daily", "Daily")]


class SettingsDialog(QDialog):
    def __init__(self, app: "DocketApp", parent: QWidget):
        super().__init__(parent)
        self.app = app
        self.setObjectName("Settings")
        self.setWindowTitle("Docket settings")
        self.resize(480, 680)
        self.setMinimumWidth(420)
        s = app.settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("SettingsBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(18, 14, 18, 18)
        v.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # ---- theme
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
        v.addWidget(self._check("Fill whole tabs with their list's colour", "tab_tint"))
        v.addWidget(self._hint("Each list has its own colour (right-click its tab > Colour). Off: a coloured "
                               "dot. On: the whole tab, the list's own window title and its pill are tinted."))

        # ---- general
        v.addWidget(self._section("GENERAL"))
        v.addWidget(self._check("Launch when Windows starts", "startup"))
        v.addWidget(self._check("Start hidden in the tray", "start_hidden"))
        v.addWidget(self._check("Keep windows on top", "on_top"))
        v.addWidget(self._check("Keep pills on top", "pill_on_top"))
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

        # ---- columns & sorting
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
        sort_row.addStretch(1)
        v.addLayout(sort_row)
        v.addWidget(self._check("Show completed items", "show_done"))

        # ---- backup
        v.addWidget(self._section("BACKUP"))
        v.addWidget(self._check("Auto-backup to plain-text files", "backup"))
        v.addWidget(self._field_label("Backup folder (pick one inside OneDrive or Google Drive to sync it)"))
        self.folder = QLineEdit(s["backup_dir"] or str(app.default_backup_dir()))
        self.folder.editingFinished.connect(lambda: app.set_setting("backup_dir", self.folder.text().strip()))
        v.addWidget(self.folder)
        v.addLayout(self._buttons([("Change folder…", self._browse), ("Open folder", self._open_backups)]))
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

        # ---- templates
        v.addWidget(self._section("CHECKLIST TEMPLATES"))
        v.addWidget(self._hint("Save a checklist as a template from its tab's right-click menu, then start "
                               "new ones from + ▾ > New from template. Templates are plain text files you "
                               "can share."))
        v.addWidget(self._field_label("Templates folder"))
        self.tpl_folder = QLineEdit(str(app.templates_dir()))
        self.tpl_folder.setReadOnly(True)
        v.addWidget(self.tpl_folder)
        v.addLayout(self._buttons([("Change folder…", self._change_templates),
                                   ("Open folder", self._open_templates)]))

        # ---- import / export
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

        close = QPushButton("Close")
        close.setProperty("primary", True)
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(18, 8, 18, 14)
        bottom.addStretch(1)
        bottom.addWidget(close)
        outer.addLayout(bottom)

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

    def _sort_changed(self, i: int) -> None:
        self.app.set_setting("sort_key", self.sort_box.itemData(i))
        self.app.set_setting("sort_dir", 1)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a backup folder", self.folder.text())
        if path:
            self.folder.setText(path)
            self.app.set_setting("backup_dir", path)
            self.tpl_folder.setText(str(self.app.templates_dir()))

    def _open_backups(self) -> None:
        self._open(Path(self.app.backup_dir()))

    def _change_templates(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose a templates folder", self.tpl_folder.text())
        if path:
            self.app.set_setting("templates_dir", path)
            self.tpl_folder.setText(str(self.app.templates_dir()))

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

    def update_last(self) -> None:
        self.last_label.setText(self.app.backup_status(long=True))

    def sync_theme_buttons(self) -> None:
        for b, key in zip(self.theme_group.buttons(), themes.PALETTES):
            b.setChecked(key == self.app.settings["theme"])
