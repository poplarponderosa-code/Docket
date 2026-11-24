"""One list (tab): quick-add box, sortable header and expandable item rows."""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFrame, QGridLayout, QInputDialog, QListWidget,
                               QListWidgetItem, QMenu,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QSizePolicy, QTimeEdit, QVBoxLayout, QWidget)

from .. import dates, links, themes
from ..parser import parse_quick_add, take_link
from ..timer import fmt_duration, fmt_limit, parse_duration
from ..store import PRIORITIES, Item
from .common import ClickableWidget, ClickLabel, ElideLabel, GrowEdit, OptionalDateEdit, repolish, set_prop
from .icons import dot_icon, icon_button, make_icon, set_icon_name

if TYPE_CHECKING:
    from ..app import DocketApp

DUE_W, PRI_W, CHECK_W, CHEV_W, TIME_W, PLAY_W, CAT_W = 92, 70, 20, 28, 92, 26, 100
CELL_H = 28            # height of the cells beside a wrapped name, so they line up with its first line
EDGE_PX, MAX_SCROLL = 36, 22   # dragging a step near the list's top or bottom edge scrolls it
NEW_CATEGORY, EDIT_CATEGORIES = "\x00new", "\x00edit"
ROW_MIME = "application/x-docket-item"
COLUMN_TITLES = {"due": "DUE", "item": "ITEM", "pri": "PRIORITY"}


def _d(iso: str) -> dt.date | None:
    return dates.from_iso(iso)


# ---------------------------------------------------------------------------
class DatePopup(QFrame):
    """One day or a date range, with one-click picks."""

    picked = Signal(str, str)   # due, end (ISO or "")

    def __init__(self, parent: QWidget, due: str, end: str):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Popup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedWidth(320)
        self.today = dt.date.today()
        self.range_mode = bool(end)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        modes = QHBoxLayout()
        modes.setSpacing(4)
        self.one_btn = QPushButton("One day")
        self.range_btn = QPushButton("Date range")
        for b in (self.one_btn, self.range_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            modes.addWidget(b)
        self.one_btn.clicked.connect(lambda: self._set_mode(False))
        self.range_btn.clicked.connect(lambda: self._set_mode(True))
        lay.addLayout(modes)

        grid = QGridLayout()
        grid.setSpacing(6)
        self.pick_buttons: list[tuple[QPushButton, dt.date, dt.date | None]] = []
        for i, (label, start, stop) in enumerate(dates.quick_picks(self.today)):
            b = QPushButton()
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumHeight(34)
            inner = QHBoxLayout(b)
            inner.setContentsMargins(10, 0, 10, 0)
            name = QLabel(label)
            hint = QLabel(dates.range_label(start, stop))
            hint.setObjectName("Hint")
            for lab in (name, hint):
                lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            inner.addWidget(name)
            inner.addStretch(1)
            inner.addWidget(hint)
            b.clicked.connect(lambda _=False, s=start, e=stop: self._pick(s, e))
            grid.addWidget(b, i // 2, i % 2)
            self.pick_buttons.append((b, start, stop))
        lay.addLayout(grid)

        fields = QHBoxLayout()
        fields.setSpacing(8)
        start_box, self.start_label = self._field("Due")
        self.start = OptionalDateEdit()
        self.start.set_iso(due)
        start_box.addWidget(self.start)
        end_box, _ = self._field("End")
        self.end = OptionalDateEdit(empty_text="Pick end")
        self.end.set_iso(end)
        end_box.addWidget(self.end)
        self.end_wrap = QWidget()
        self.end_wrap.setLayout(end_box)
        start_wrap = QWidget()
        start_wrap.setLayout(start_box)
        fields.addWidget(start_wrap, 1)
        fields.addWidget(self.end_wrap, 1)
        lay.addLayout(fields)
        self.start.dateChanged.connect(self._dates_edited)
        self.end.dateChanged.connect(self._dates_edited)

        bottom = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("Hint")
        bottom.addWidget(self.summary, 1)
        clear = QPushButton("Clear")
        done = QPushButton("Done")
        done.setProperty("primary", True)
        clear.clicked.connect(self._clear)
        done.clicked.connect(self.close)
        bottom.addWidget(clear)
        bottom.addWidget(done)
        lay.addLayout(bottom)
        self._sync()

    @staticmethod
    def _field(title: str):
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        label = QLabel(title)
        label.setObjectName("FieldLabel")
        box.addWidget(label)
        return box, label

    def _values(self) -> tuple[str, str]:
        due = self.start.iso()
        end = self.end.iso() if self.range_mode else ""
        if not due or (end and end <= due):
            end = ""
        return due, end

    def _set_mode(self, rng: bool) -> None:
        self.range_mode = rng
        if rng and not self.start.iso():
            self.start.set_iso(self.today.isoformat())
        self._emit()

    def _pick(self, start: dt.date, stop: dt.date | None) -> None:
        self.range_mode = stop is not None
        self.start.set_iso(start.isoformat())
        self.end.set_iso(stop.isoformat() if stop else "")
        self._emit()

    def _dates_edited(self) -> None:
        if self.end.iso() and self.start.iso() and self.end.iso() < self.start.iso():
            self.end.set_iso("")
        self._emit()

    def _clear(self) -> None:
        self.range_mode = False
        self.start.set_iso("")
        self.end.set_iso("")
        self._emit()

    def _emit(self) -> None:
        self._sync()
        self.picked.emit(*self._values())

    def _sync(self) -> None:
        set_prop(self.one_btn, "on", not self.range_mode)
        set_prop(self.range_btn, "on", self.range_mode)
        self.end_wrap.setVisible(self.range_mode)
        self.start_label.setText("Start" if self.range_mode else "Due")
        due, end = self._values()
        for b, s, e in self.pick_buttons:
            set_prop(b, "on", due == s.isoformat() and end == (e.isoformat() if e else ""))
        if not due:
            text = "No date: sorts to the bottom"
        elif end:
            days = (_d(end) - _d(due)).days + 1
            text = f"{days} days, {dates.range_label(_d(due), _d(end))}"
        elif self.range_mode:
            text = "Pick an end date"
        else:
            text = "Due " + dates.due_label(_d(due), None, self.today)
        self.summary.setText(text)
        self.adjustSize()

    def show_under(self, anchor: QWidget) -> None:
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(anchor.width() - self.width(), anchor.height() + 4))
        screen = anchor.screen().availableGeometry()
        pos.setX(max(screen.left() + 4, min(pos.x(), screen.right() - self.width() - 4)))
        if pos.y() + self.height() > screen.bottom():
            pos.setY(anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4)
        self.move(pos)
        self.show()


# ---------------------------------------------------------------------------
class DescriptionPopup(QFrame):
    """A small box for the list's description, opened from the ⓘ in its header."""

    def __init__(self, parent: QWidget, app: "DocketApp", tab_id: int):
        super().__init__(parent, Qt.WindowType.Popup)
        self.app = app
        self.tab_id = tab_id
        self.setObjectName("Popup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedWidth(340)
        tab = app.store.tab(tab_id)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        title = QLabel(f"About “{tab.name if tab else ''}”")
        title.setObjectName("FieldLabel")
        lay.addWidget(title)
        self.edit = QPlainTextEdit(tab.description if tab else "")
        self.edit.setPlaceholderText("What this list is for, links, reminders to yourself…")
        self.edit.setFixedHeight(130)
        lay.addWidget(self.edit)
        self.client_edit = None
        if tab is not None and tab.is_checklist and app.has("client"):
            lab = QLabel("Client")
            lab.setObjectName("FieldLabel")
            lay.addWidget(lab)
            self.client_edit = QLineEdit(tab.client)
            self.client_edit.setPlaceholderText("A short label, like Acme (optional)")
            self.client_edit.setMaxLength(60)
            lay.addWidget(self.client_edit)
            tip = QLabel("Goes into the time log so Ledger knows the client; their details stay in Ledger. "
                         "Use this instead of putting client names in the checklist title.")
            tip.setObjectName("Hint")
            tip.setWordWrap(True)
            lay.addWidget(tip)
        row = QHBoxLayout()
        hint = QLabel("Saved with the list, its exports and templates.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        row.addWidget(hint, 1)
        done = QPushButton("Done")
        done.setProperty("primary", True)
        done.clicked.connect(self.close)
        row.addWidget(done)
        lay.addLayout(row)

    def closeEvent(self, e) -> None:
        tab = self.app.store.tab(self.tab_id)
        text = self.edit.toPlainText().strip()
        if tab is not None and text != tab.description:
            self.app.store.update_tab(self.tab_id, description=text)
        if tab is not None and self.client_edit is not None:
            client = " ".join(self.client_edit.text().split())
            if client != tab.client:
                self.app.store.update_tab(self.tab_id, client=client)
        super().closeEvent(e)

    def show_under(self, anchor: QWidget) -> None:
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(anchor.width() - self.width(), anchor.height() + 4))
        screen = anchor.screen().availableGeometry()
        pos.setX(max(screen.left() + 4, min(pos.x(), screen.right() - self.width() - 4)))
        self.move(pos)
        self.show()
        self.edit.setFocus()


# ---------------------------------------------------------------------------
class CategoriesDialog(QDialog):
    """Add, rename (double-click) or remove a checklist's categories."""

    def __init__(self, parent: QWidget, names: list[str], others: list[tuple[str, list[str]]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Categories")
        self.resize(320, 360)
        lay = QVBoxLayout(self)
        hint = QLabel("Categories for this checklist. Double-click one to rename it; steps using it follow. "
                      "Removing one clears it from those steps.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.list = QListWidget()
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.list.addItem(item)
        lay.addWidget(self.list, 1)
        self.others = [(n, c) for n, c in (others or []) if c]
        if self.others:
            copy_row = QHBoxLayout()
            self.copy_box = QComboBox()
            self.copy_box.addItem("Copy from another checklist…", None)
            for i, (name, cats) in enumerate(self.others):
                self.copy_box.addItem(f"{name}  ({len(cats)})", i)
            self.copy_box.activated.connect(self._copy_from)
            copy_row.addWidget(self.copy_box, 1)
            lay.addLayout(copy_row)
        row = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        done = QPushButton("Done")
        done.setProperty("primary", True)
        done.clicked.connect(self.accept)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        row.addWidget(done)
        lay.addLayout(row)

    def _copy_from(self, index: int) -> None:
        """Add the other checklist's categories that this one doesn't have yet."""
        which = self.copy_box.itemData(index)
        self.copy_box.setCurrentIndex(0)
        if which is None:
            return
        have = {self.list.item(i).text().strip() for i in range(self.list.count())}
        for name in self.others[which][1]:
            if name not in have:
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, "")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.list.addItem(item)
                have.add(name)

    def _add(self) -> None:
        item = QListWidgetItem("New category")
        item.setData(Qt.ItemDataRole.UserRole, "")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list.addItem(item)
        self.list.setCurrentItem(item)
        self.list.editItem(item)

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)

    def result_names(self) -> tuple[list[str], dict[str, str]]:
        names, renamed = [], {}
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = item.text().strip()
            original = item.data(Qt.ItemDataRole.UserRole) or ""
            if not name:
                continue
            names.append(name)
            if original and original != name:
                renamed[original] = name
        return names, renamed


# ---------------------------------------------------------------------------
class ItemRow(QFrame):
    def __init__(self, page: "ListPage", item: Item):
        super().__init__()
        self.page = page
        self.app = page.app
        self.item = item
        self.expanded = item.id in page.expanded
        self.checklist = page.is_checklist
        self.setObjectName("Row")
        self.setProperty("expanded", self.expanded)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.top = ClickableWidget()
        self.top.setCursor(Qt.CursorShape.PointingHandCursor)
        self.top.setMinimumHeight(40)
        self.top.clicked.connect(self.toggle)
        if self.checklist:
            self.top.draggable = True
            self.top.setToolTip("Click to open; drag to move this step")
            self.top.drag_started.connect(lambda: page.start_drag(self))
        top = QHBoxLayout(self.top)
        top.setContentsMargins(12, 0, 8, 0)
        top.setSpacing(8)

        self.check = QCheckBox()
        self.check.setFixedWidth(CHECK_W)
        self.check.setToolTip("Mark done")
        self.check.setChecked(item.done)
        self.check.toggled.connect(self._on_done)

        self.due = QLabel()
        self.due.setObjectName("Due")
        self.due.setFixedWidth(DUE_W)

        self.wrap = bool(self.app.settings.get("wrap_items", True))
        self.name_cell = QWidget()
        nc = QHBoxLayout(self.name_cell)
        nc.setContentsMargins(0, 5 if self.wrap else 8, 0, 5 if self.wrap else 8)
        nc.setSpacing(6)
        self.name = ElideLabel()
        self.name.setObjectName("Name")
        self.name.set_wrap(self.wrap)
        self.link_btn = icon_button("globe", "Open the link", size=22)
        self.link_btn.clicked.connect(lambda: self.app.open_link(self.item.link))
        self.link_btn.hide()
        self.notes_icon = QLabel()
        self.bell_icon = QLabel()
        self.notes_icon.setToolTip("Has notes")
        self.bell_icon.setToolTip("Reminder on")
        nc.addWidget(self.name, 1)
        nc.addWidget(self.link_btn, 0, Qt.AlignmentFlag.AlignTop if self.wrap else Qt.AlignmentFlag.AlignVCenter)
        nc.addWidget(self.notes_icon, 0, Qt.AlignmentFlag.AlignTop if self.wrap else Qt.AlignmentFlag.AlignVCenter)
        nc.addWidget(self.bell_icon, 0, Qt.AlignmentFlag.AlignTop if self.wrap else Qt.AlignmentFlag.AlignVCenter)
        if self.wrap:
            self.name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            for icon in (self.notes_icon, self.bell_icon):
                icon.setFixedHeight(self.fontMetrics().height() + 2)

        self.pri = QPushButton()
        self.pri.setObjectName("Pri")
        self.pri.setFixedWidth(PRI_W)
        self.pri.setIconSize(QSize(8, 8))
        self.pri.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pri.setToolTip("Click to change priority")
        self.pri.clicked.connect(self._cycle_priority)

        self.chev = icon_button("chevron_up" if self.expanded else "chevron_down",
                                "Hide details" if self.expanded else "Show notes and dates", size=CHEV_W)
        self.chev.clicked.connect(self.toggle)

        top.addWidget(self.check)
        self.play_btn = None
        self.time_lbl = None
        self.cat_lbl = None
        if self.checklist:                 # steps only: no dates, no priority
            self.due.hide()
            self.pri.hide()
            cells: dict[str, list] = {"step": [(self.name_cell, 1)], "category": [], "time": []}
            if page.show_category:
                self.cat_lbl = ElideLabel(item.category)
                self.cat_lbl.setObjectName("CategoryCell")
                self.cat_lbl.setFixedWidth(CAT_W)
                self.cat_lbl.clickable = True
                self.cat_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                self.cat_lbl.clicked.connect(self._category_menu)
                cells["category"].append((self.cat_lbl, 0))
            if page.timer_on and page.show_time:
                self.play_btn = icon_button("play", "Time this step", size=PLAY_W)
                keep = self.play_btn.sizePolicy()
                keep.setRetainSizeWhenHidden(True)
                self.play_btn.setSizePolicy(keep)
                self.play_btn.hide()                     # appears when the mouse is over the row
                self.play_btn.clicked.connect(lambda: self.app.play_item(self.item.tab_id, self.item.id))
                self.time_lbl = ClickLabel()
                self.time_lbl.clickable = True
                self.time_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
                self.time_lbl.clicked.connect(lambda: self.page.set_step_limit(self.item.id))
                self.time_lbl.setObjectName("TimeCell")
                self.time_lbl.setFixedWidth(TIME_W)
                self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                cells["time"] += [(self.play_btn, 0), (self.time_lbl, 0)]
            for key in page.checklist_columns():
                for w, stretch in cells[key]:
                    top.addWidget(w, stretch)
        else:
            cells = {"due": self.due, "item": self.name_cell, "pri": self.pri}
            for key in page.visible_columns():
                top.addWidget(cells[key], 1 if key == "item" else 0)
            if "pri" not in page.visible_columns():
                self.pri.hide()
        top.addWidget(self.chev)
        if self.wrap:                      # long names wrap: everything else lines up with the first line
            top.setContentsMargins(12, 6, 8, 6)
            for i in range(top.count()):
                w = top.itemAt(i).widget()
                if w is None or w is self.name_cell:
                    continue
                top.setAlignment(w, Qt.AlignmentFlag.AlignTop)
                if not isinstance(w, QPushButton) and w.minimumHeight() < CELL_H and w is not self.chev:
                    w.setFixedHeight(CELL_H)
        outer.addWidget(self.top)

        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(500)
        self._notes_timer.timeout.connect(self._save_notes)
        self.panel = self._build_panel() if self.expanded else None
        if self.panel is not None:
            outer.addWidget(self.panel)
        self.update_display()

    # ---- display -------------------------------------------------------------
    def update_display(self) -> None:
        it = self.item
        today = dt.date.today()
        due, end = _d(it.due), _d(it.end)
        self.due.setText(dates.due_label(due, end, today))
        self.due.setToolTip(due.strftime("%A, %B %d, %Y") + (end.strftime(" – %A, %B %d") if end else "") if due else "")
        set_prop(self.due, "status", dates.status(due, end, it.done, today))
        self.name.setFullText(it.name)
        set_prop(self.name, "done", it.done)
        if getattr(self, "cat_lbl", None) is not None:
            self.cat_lbl.setFullText(it.category)
        muted, accent = themes.current["muted"], themes.current["accent"]
        self.notes_icon.setPixmap(make_icon("notes", muted, 12).pixmap(12, 12))
        self.bell_icon.setPixmap(make_icon("bell", accent, 12).pixmap(12, 12))
        self.notes_icon.setVisible(bool(it.notes.strip()))
        show_link = bool(it.link) and bool(self.app.settings.get("show_links", True))
        self.link_btn.setVisible(show_link)
        if show_link:
            set_icon_name(self.link_btn, links.icon_name(it.link) or "globe")
            k = links.kind(it.link)
            self.link_btn.setToolTip({"web": "Open ", "folder": "Open folder ", "file": "Open "}.get(k, "Not found: ")
                                     + it.link)
        self.bell_icon.setVisible(it.reminder and not self.checklist)
        self.bell_icon.setToolTip(f"Reminder at {dates.fmt_time(self.remind_time())}")
        self.pri.setText(" " + PRIORITIES[it.priority])
        self.pri.setIcon(dot_icon(themes.PRIORITY_COLORS[it.priority]))
        if self.panel is not None and not self.checklist:
            set_prop(self.remind_btn, "on", it.reminder)
            self.time_edit.setEnabled(it.reminder)
        self.update_time()

    def update_time(self) -> None:
        if self.time_lbl is None:
            return
        text, status, tip = self.page.time_text(self.item)
        self.time_lbl.setText(text)
        self.time_lbl.setToolTip(tip)
        set_prop(self.time_lbl, "status", status)
        running = bool(self.item.run_from)
        if self.play_btn is not None:
            set_icon_name(self.play_btn, "pause" if running else "play")
            self.play_btn.setToolTip("Pause the timer" if running else "Time this step")
        if self.panel is not None and hasattr(self, "recorded_lbl"):
            self.recorded_lbl.setText(f"Recorded {fmt_duration(self.app.timer.live_elapsed(self.item))}")

    def enterEvent(self, e) -> None:
        super().enterEvent(e)
        if self.play_btn is not None and not self.item.done:
            self.play_btn.show()

    def leaveEvent(self, e) -> None:
        super().leaveEvent(e)
        if self.play_btn is not None:
            self.play_btn.hide()

    def remind_time(self) -> str:
        return self.item.remind_time or self.app.settings.get("remind_time", "09:00")

    def _build_panel(self) -> QWidget:
        it = self.item
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(12 + CHECK_W + 8, 0, 12, 12)
        v.setSpacing(8)
        self.name_edit = GrowEdit(it.name, max_lines=5)
        self.name_edit.setPlaceholderText("Step" if self.checklist else "Item name")
        self.name_edit.editingFinished.connect(self._save_name)
        self.name_edit.submitted.connect(lambda _m: self._name_entered())
        v.addWidget(self.name_edit)
        self.notes_edit = GrowEdit(it.notes, max_lines=8, multiline=True)
        self.notes_edit.setPlaceholderText("Notes…")
        self.notes_edit.textChanged.connect(self._notes_timer.start)
        v.addWidget(self.notes_edit)
        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        lab = QLabel("Link")
        lab.setObjectName("FieldLabel")
        link_row.addWidget(lab)
        self.link_edit = QLineEdit(it.link)
        self.link_edit.setPlaceholderText("A web address, folder or file")
        self.link_edit.setToolTip("Paste a web address, or a folder or file path. The icon by the item opens it.")
        self.link_edit.editingFinished.connect(self._save_link)
        link_row.addWidget(self.link_edit, 1)
        browse = QPushButton("Browse…")
        bmenu = QMenu(browse)
        bmenu.addAction("A folder…", lambda: self._browse_link(folder=True))
        bmenu.addAction("A file…", lambda: self._browse_link(folder=False))
        browse.setMenu(bmenu)
        link_row.addWidget(browse)
        v.addLayout(link_row)
        if self.checklist and self.page.categories_on:
            cat_row = QHBoxLayout()
            cat_row.setSpacing(8)
            lab = QLabel("Category")
            lab.setObjectName("FieldLabel")
            cat_row.addWidget(lab)
            self.cat_box = QComboBox()
            self.cat_box.addItem("None", "")
            for name in self.page.categories():
                self.cat_box.addItem(name, name)
            self.cat_box.insertSeparator(self.cat_box.count())
            self.cat_box.addItem("New category…", NEW_CATEGORY)
            self.cat_box.addItem("Edit categories…", EDIT_CATEGORIES)
            i = self.cat_box.findData(it.category)
            self.cat_box.setCurrentIndex(i if i >= 0 else 0)
            self.cat_box.setMinimumWidth(150)
            self.cat_box.activated.connect(self._category_chosen)
            cat_row.addWidget(self.cat_box)
            cat_row.addStretch(1)
            v.addLayout(cat_row)
        if self.checklist:
            row = QHBoxLayout()
            row.setSpacing(8)
            if self.page.timer_on:
                lab = QLabel("Time limit")
                lab.setObjectName("FieldLabel")
                row.addWidget(lab)
                self.limit_edit = QLineEdit(fmt_limit(it.time_limit))
                self.limit_edit.setPlaceholderText("none")
                self.limit_edit.setToolTip("How long this step should take: 15m, 1h30, 1:30 (hours:minutes) or 90s.\n"
                                           "Leave empty for no limit.")
                self.limit_edit.setFixedWidth(96)
                self.limit_edit.editingFinished.connect(self._save_limit)
                row.addWidget(self.limit_edit)
                self.recorded_lbl = QLabel()
                self.recorded_lbl.setObjectName("FieldLabel")
                row.addWidget(self.recorded_lbl)
            row.addStretch(1)
            delete = icon_button("trash", "Delete step")
            delete.clicked.connect(self._delete)
            row.addWidget(delete)
            v.addLayout(row)
            return panel

        row = QHBoxLayout()
        row.setSpacing(8)
        self.start_edit = OptionalDateEdit()
        self.start_edit.set_iso(it.due)
        self.end_edit = OptionalDateEdit(empty_text="No end")
        self.end_edit.set_iso(it.end)
        for title, w in (("Start / due", self.start_edit), ("End (for a range)", self.end_edit)):
            box = QVBoxLayout()
            box.setSpacing(3)
            lab = QLabel(title)
            lab.setObjectName("FieldLabel")
            box.addWidget(lab)
            box.addWidget(w)
            row.addLayout(box)
        row.addStretch(1)
        v.addLayout(row)
        self.start_edit.dateChanged.connect(self._save_dates)
        self.end_edit.dateChanged.connect(self._save_dates)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.remind_btn = QPushButton("Remind")
        self.remind_btn.setProperty("iconName", "bell")
        self.remind_btn.setProperty("iconRole", "accent")
        self.remind_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remind_btn.setToolTip("Windows notification on the day")
        self.remind_btn.clicked.connect(self._toggle_reminder)
        set_icon_name(self.remind_btn, "bell")
        row.addWidget(self.remind_btn)
        at = QLabel("at")
        at.setObjectName("FieldLabel")
        row.addWidget(at)
        self.time_edit = QTimeEdit(QTime.fromString(self.remind_time(), "HH:mm"))
        self.time_edit.setDisplayFormat("h:mm AP")
        self.time_edit.setToolTip("Reminder time for this item (the default is set in Settings)")
        self.time_edit.timeChanged.connect(self._save_time)
        row.addWidget(self.time_edit)
        row.addStretch(1)
        delete = icon_button("trash", "Delete item")
        delete.clicked.connect(self._delete)
        row.addWidget(delete)
        v.addLayout(row)
        return panel

    # ---- actions ----------------------------------------------------------------
    def toggle(self) -> None:
        self.flush()
        if self.item.id in self.page.expanded:
            self.page.expanded.discard(self.item.id)
        else:
            self.page.expanded.add(self.item.id)
        self.page.schedule_refresh()

    def _quiet_update(self, **fields) -> None:
        updated = self.app.store.update_item(self.item.id, quiet=True, **fields)
        if updated:
            self.item = updated
            self.update_display()

    def _on_done(self, checked: bool) -> None:
        self.flush()
        self.app.set_done(self.item.id, checked)

    def _category_chosen(self, index: int) -> None:
        value = self.cat_box.itemData(index)
        item_id = self.item.id
        if value == NEW_CATEGORY:
            i = self.cat_box.findData(self.item.category)
            self.cat_box.setCurrentIndex(i if i >= 0 else 0)
            QTimer.singleShot(0, lambda: self.page.new_category(item_id))
        elif value == EDIT_CATEGORIES:
            i = self.cat_box.findData(self.item.category)
            self.cat_box.setCurrentIndex(i if i >= 0 else 0)
            QTimer.singleShot(0, self.page.edit_categories)
        elif value != self.item.category:
            QTimer.singleShot(0, lambda: self.app.store.update_item(item_id, category=value or ""))

    def _category_menu(self) -> None:
        """Click the Category cell: pick from a dropdown right there."""
        menu = QMenu(self)
        item_id, current = self.item.id, self.item.category
        none = menu.addAction("None", lambda: self.app.store.update_item(item_id, category=""))
        none.setCheckable(True)
        none.setChecked(not current)
        menu.addSeparator()
        for name in self.page.categories():
            act = menu.addAction(name, lambda n=name: self.app.store.update_item(item_id, category=n))
            act.setCheckable(True)
            act.setChecked(name == current)
        menu.addSeparator()
        menu.addAction("New category…", lambda: QTimer.singleShot(0, lambda: self.page.new_category(item_id)))
        menu.addAction("Edit categories…", lambda: QTimer.singleShot(0, self.page.edit_categories))
        menu.exec(self.cat_lbl.mapToGlobal(QPoint(0, self.cat_lbl.height())))

    def _save_link(self) -> None:
        if self.panel is None or not hasattr(self, "link_edit"):
            return
        value = links.normalize(self.link_edit.text())
        if value != self.item.link:
            self._quiet_update(link=value)

    def _browse_link(self, folder: bool) -> None:
        from PySide6.QtWidgets import QFileDialog
        start = self.item.link if self.item.link and not links.is_web(self.item.link) else ""
        if folder:
            path = QFileDialog.getExistingDirectory(self, "Link a folder", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Link a file", start)
        if path:
            from pathlib import Path
            path = str(Path(path))
            self.link_edit.setText(path)
            self._quiet_update(link=path)

    def _save_limit(self) -> None:
        if self.panel is None or not hasattr(self, "limit_edit"):
            return
        seconds = parse_duration(self.limit_edit.text())
        if seconds is None:
            self.app.flash("Try a time like 15m, 1h30, 1:30 or 90s")
            self.limit_edit.setText(fmt_limit(self.item.time_limit))
            return
        if seconds != self.item.time_limit:
            self.app.timer.set_item_limit(self.item.id, seconds)

    def _cycle_priority(self) -> None:
        self.flush()
        self.app.store.update_item(self.item.id, priority=(self.item.priority + 1) % 3)

    def _name_entered(self) -> None:
        """Enter in the name box: save it and close the item."""
        self._save_name()
        if self.item.id in self.page.expanded:
            self.toggle()

    def _save_name(self) -> None:
        if self.panel is None:
            return
        text = self.name_edit.text().strip()
        if text and text != self.item.name:
            self._quiet_update(name=text)

    def _save_notes(self) -> None:
        if self.panel is None:
            return
        text = self.notes_edit.toPlainText()
        if text != self.item.notes:
            self._quiet_update(notes=text)

    def _save_dates(self) -> None:
        due, end = self.start_edit.iso(), self.end_edit.iso()
        if not due or (end and end <= due):
            end = ""
        self._quiet_update(due=due, end=end)

    def _toggle_reminder(self) -> None:
        turning_on = not self.item.reminder
        self._quiet_update(reminder=turning_on)
        if turning_on:
            when = dates.fmt_time(self.remind_time())
            if self.item.due:
                self.app.flash(f"Reminder at {when} on {dates.fmt(_d(self.item.due))}")
            else:
                self.app.flash("Add a date to get the reminder")

    def _save_time(self, t: QTime) -> None:
        value = t.toString("HH:mm")
        default = self.app.settings.get("remind_time", "09:00")
        self._quiet_update(remind_time="" if value == default else value)

    def _delete(self) -> None:
        self._notes_timer.stop()
        self.app.store.delete_item(self.item.id)
        self.app.flash(f"Deleted “{self.item.name}”")

    def flush(self) -> None:
        """Save anything typed but not yet stored (called before the row is rebuilt)."""
        if self.panel is None:
            return
        if self._notes_timer.isActive():
            self._notes_timer.stop()
        self._save_notes()
        self._save_name()
        self._save_link()


# ---------------------------------------------------------------------------
class RowsContainer(QWidget):
    """Holds the rows; in a checklist, steps can be dragged to a new place."""

    def __init__(self, page: "ListPage"):
        super().__init__()
        self.page = page
        self.setObjectName("ListContainer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.line = QFrame(self)
        self.line.setObjectName("DropLine")
        self.line.setFixedHeight(3)
        self.line.hide()
        self._scroll_step = 0
        self._scroller = QTimer(self)
        self._scroller.setInterval(30)
        self._scroller.timeout.connect(self._autoscroll)

    def _edge_speed(self, y_in_container: int) -> int:
        """How fast to scroll while dragging near the visible top or bottom: faster nearer the edge."""
        view = self.page.scroll.viewport()
        y = self.mapTo(view, QPoint(0, y_in_container)).y()
        if y < EDGE_PX:
            return -max(2, int(MAX_SCROLL * (EDGE_PX - y) / EDGE_PX))
        if y > view.height() - EDGE_PX:
            return max(2, int(MAX_SCROLL * (y - (view.height() - EDGE_PX)) / EDGE_PX))
        return 0

    def _autoscroll(self) -> None:
        bar = self.page.scroll.verticalScrollBar()
        if not self._scroll_step or (self._scroll_step < 0 and bar.value() <= bar.minimum()) or \
                (self._scroll_step > 0 and bar.value() >= bar.maximum()):
            self._scroller.stop()
            return
        bar.setValue(bar.value() + self._scroll_step)

    def _stop_scroll(self) -> None:
        self._scroll_step = 0
        self._scroller.stop()

    def _target(self, y: int) -> "ItemRow | None":
        for row in self.page.rows:
            if y < row.geometry().center().y():
                return row
        return None

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat(ROW_MIME) and self.page.is_checklist:
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        if not e.mimeData().hasFormat(ROW_MIME):
            return
        self._scroll_step = self._edge_speed(e.position().toPoint().y())
        if self._scroll_step and not self._scroller.isActive():
            self._scroller.start()
        rows = self.page.rows
        row = self._target(e.position().toPoint().y())
        if row is not None:
            y = row.geometry().top()
        else:
            y = rows[-1].geometry().bottom() if rows else 0
        self.line.setGeometry(10, max(0, y - 1), max(10, self.width() - 20), 3)
        self.line.show()
        self.line.raise_()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self.line.hide()
        self._stop_scroll()

    def dropEvent(self, e) -> None:
        self.line.hide()
        self._stop_scroll()
        if not e.mimeData().hasFormat(ROW_MIME):
            return
        try:
            item_id = int(bytes(e.mimeData().data(ROW_MIME)).decode())
        except ValueError:
            return
        row = self._target(e.position().toPoint().y())
        before = row.item.id if row is not None else None
        e.acceptProposedAction()
        if before != item_id:
            QTimer.singleShot(0, lambda: self.page.app.store.move_item(item_id, before))


# ---------------------------------------------------------------------------
class ListPage(QWidget):
    def __init__(self, app: "DocketApp", tab_id: int):
        super().__init__()
        self.app = app
        self.tab_id = tab_id
        self.expanded: set[int] = set()
        self.rows: list[ItemRow] = []
        self.draft_due = ""
        self.draft_end = ""
        self.popup: DatePopup | None = None
        tab = app.store.tab(tab_id)
        self.kind = tab.kind if tab else "list"
        self.setObjectName("Body")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # quick add
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 10, 12, 2)
        bar.setSpacing(6)
        self.input = GrowEdit(max_lines=4)
        self.input.setPlaceholderText("Add an item… try “dentist fri 3pm !high”")
        self.input.setToolTip("Enter adds it. Ctrl+Enter adds it to the other end of the list.")
        self.input.submitted.connect(self._entered)
        self.input.textChanged.connect(self._update_preview)
        self.date_btn = QPushButton("Date")
        self.date_btn.setProperty("iconName", "calendar")
        self.date_btn.setProperty("iconRole", "muted")
        set_icon_name(self.date_btn, "calendar")
        self.date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.date_btn.setToolTip("Set a date or a date range")
        self.date_btn.setMaximumWidth(130)
        self.date_btn.clicked.connect(self._open_date_popup)
        self.pri_box = QComboBox()
        self.pri_box.addItems(PRIORITIES)
        self.pri_box.setCurrentIndex(1)
        self.pri_box.setFixedWidth(72)
        self.pri_box.setToolTip("Priority")
        add = icon_button("plus", "Add", role="win")
        add.setProperty("primary", True)
        repolish(add)
        add.clicked.connect(self.add_item)
        bar.addWidget(self.input, 1)
        bar.addWidget(self.date_btn, 0, Qt.AlignmentFlag.AlignTop)
        bar.addWidget(self.pri_box, 0, Qt.AlignmentFlag.AlignTop)
        bar.addWidget(add, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(bar)

        self.preview_row = QWidget()
        pr = QHBoxLayout(self.preview_row)
        pr.setContentsMargins(14, 2, 12, 0)
        pr.setSpacing(6)
        self.preview_link = QLabel()
        self.preview = QLabel()
        self.preview.setObjectName("Hint")
        pr.addWidget(self.preview_link)
        pr.addWidget(self.preview, 1)
        self.preview_row.hide()
        v.addWidget(self.preview_row)
        v.addSpacing(6)

        # header
        self.header = QWidget()
        self.header.setObjectName("Header")
        self.header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.header.setFixedHeight(28)
        self.header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self._header_menu)
        QHBoxLayout(self.header)
        v.addWidget(self.header)

        # rows
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.container = RowsContainer(self)
        self.rows_layout = QVBoxLayout(self.container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(0)
        self.empty = QLabel("Nothing here yet. Add an item above.")
        self.empty.setObjectName("Empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.rows_layout.addWidget(self.empty)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.container)
        v.addWidget(self.scroll, 1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)

        self._apply_kind()
        self.build_header()
        self.refresh()

    # ---- list or checklist ---------------------------------------------------------
    @property
    def is_checklist(self) -> bool:
        return self.kind == "checklist"

    def _apply_kind(self) -> None:
        checklist = self.is_checklist
        self.date_btn.setVisible(not checklist)
        self.pri_box.setVisible(not checklist and not self.app.settings.get("hide_pri"))
        self.input.setPlaceholderText("Add a step…" if checklist else "Add an item… try “dentist fri 3pm !high”")
        self.empty.setText("No steps yet. Add the first one above." if checklist
                           else "Nothing here yet. Add an item above.")
        if checklist:
            self.preview_row.hide()

    def sync_kind(self) -> None:
        """Called when the list is switched between a priority list and a checklist."""
        tab = self.app.store.tab(self.tab_id)
        kind = tab.kind if tab else "list"
        if kind != self.kind:
            self.flush()
            self.kind = kind
            self.expanded.clear()
            self._apply_kind()
            self.build_header()
            self.refresh()

    def start_drag(self, row: "ItemRow") -> None:
        if not self.is_checklist:
            return
        row.flush()
        mime = QMimeData()
        mime.setData(ROW_MIME, str(row.item.id).encode())
        drag = QDrag(row)
        drag.setMimeData(mime)
        pm = row.top.grab()
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(24, pm.height() // 2))
        drag.exec(Qt.DropAction.MoveAction)
        self.container.line.hide()
        self.container._stop_scroll()

    @property
    def timer_on(self) -> bool:
        tab = self.app.store.tab(self.tab_id)
        return bool(tab and tab.is_checklist and tab.timer_on and self.app.has("timer"))

    @property
    def categories_on(self) -> bool:
        return self.app.has("categories")

    @property
    def show_time(self) -> bool:
        """The Time column (the timer keeps running and the pill shows it even when it's hidden)."""
        return not self.app.settings.get("hide_time", False)

    def checklist_columns(self) -> list[str]:
        order = [c for c in self.app.settings.get("check_cols", ["step", "category", "time"])
                 if c in ("step", "category", "time")]
        for c in ("step", "category", "time"):
            if c not in order:
                order.append(c)
        return order

    def time_text(self, item: Item, pill: bool = False) -> tuple[str, str, str]:
        """(text, status, tooltip) for a step's Time cell. On a pill, a step that hasn't started
        and has no limit shows nothing (in the list it shows a dash you can click)."""
        timer = self.app.timer
        spent = timer.live_elapsed(item)
        limit = item.time_limit
        limit_tip = f"Limit {fmt_duration(limit)}. " if limit else ""
        if not item.started and not item.done:
            return (fmt_duration(limit) if limit else ("" if pill else "—"), "none",
                    limit_tip + "Not started. Click to set a time limit for this step.")
        if item.done:
            over = limit and spent > limit
            return fmt_duration(spent), ("over" if over else "done"), limit_tip + f"Took {fmt_duration(spent)}"
        running = bool(item.run_from)
        if limit:
            left = limit - spent
            if left >= 0:
                return f"{fmt_duration(left)} left", ("running" if running else "paused"), \
                    limit_tip + f"{fmt_duration(spent)} so far"
            return f"+{fmt_duration(-left)}", "over", limit_tip + f"{fmt_duration(-left)} over the limit"
        return fmt_duration(spent), ("running" if running else "paused"), "Time so far"

    def total_text(self) -> tuple[str, str, str]:
        tab = self.app.store.tab(self.tab_id)
        total = self.app.timer.total_elapsed(self.tab_id)
        if tab is None:
            return "", "none", ""
        if tab.time_limit:
            left = tab.time_limit - total
            tip = f"Checklist limit {fmt_duration(tab.time_limit)}. Click to change it."
            if left >= 0:
                return f"{fmt_duration(left)} left", ("running" if tab.timer_running else "paused"), tip
            return f"+{fmt_duration(-left)}", "over", tip
        return (fmt_duration(total) if total else "0:00", "running" if tab.timer_running else "paused",
                "Total time. Click to give the whole checklist a time limit.")

    def update_times(self) -> None:
        for row in self.rows:
            row.update_time()
        if hasattr(self, "total_btn") and self.timer_on:
            text, status, tip = self.total_text()
            self.total_btn.setText(text)
            self.total_btn.setToolTip(tip)
            set_prop(self.total_btn, "status", status)
            tab = self.app.store.tab(self.tab_id)
            running = bool(tab and tab.timer_running)
            set_icon_name(self.head_play, "pause" if running else "play")
            self.head_play.setToolTip("Pause the timer" if running else "Start the timer on the next step")

    def _set_total_limit(self) -> None:
        tab = self.app.store.tab(self.tab_id)
        if tab is None:
            return
        text, ok = QInputDialog.getText(self, "Time limit for the whole checklist",
                                        "How long should the whole checklist take?\n"
                                        "e.g. 3h, 2h30, 1:45. Leave empty for no limit.",
                                        text=fmt_limit(tab.time_limit))
        if not ok:
            return
        seconds = parse_duration(text)
        if seconds is None:
            self.app.flash("Try a time like 3h, 2h30 or 1:45")
            return
        self.app.timer.set_tab_limit(self.tab_id, seconds)

    def set_step_limit(self, item_id: int) -> None:
        """Click a step's time (in the list or on the pill): give that step a time limit."""
        item = self.app.store.item(item_id)
        if item is None:
            return
        text, ok = QInputDialog.getText(self, "Time limit for this step",
                                        f"How long should “{item.name}” take?\n"
                                        "e.g. 15m, 1h30, 1:30 or 90s. Leave empty for no limit.",
                                        text=fmt_limit(item.time_limit))
        if not ok:
            return
        seconds = parse_duration(text)
        if seconds is None:
            self.app.flash("Try a time like 15m, 1h30, 1:30 or 90s")
            return
        self.app.timer.set_item_limit(item_id, seconds)
        self.app.refresh_times()

    def edit_description(self) -> None:
        DescriptionPopup(self, self.app, self.tab_id).show_under(self.desc_btn)

    @property
    def show_category(self) -> bool:
        tab = self.app.store.tab(self.tab_id)
        return bool(tab and tab.is_checklist and tab.show_category and self.categories_on
                    and not self.app.settings.get("hide_category", False))

    def categories(self) -> list[str]:
        tab = self.app.store.tab(self.tab_id)
        return tab.category_list if tab else []

    def new_category(self, item_id: int | None = None) -> None:
        name, ok = QInputDialog.getText(self, "New category", "Name for the new category:")
        name = name.strip() if ok else ""
        if not name:
            return
        cats = self.categories()
        if name not in cats:
            self.app.store.set_categories(self.tab_id, cats + [name])
        if not self.show_category:
            self.app.store.update_tab(self.tab_id, show_category=True)
        if item_id is not None:
            self.app.store.update_item(item_id, category=name)

    def edit_categories(self) -> None:
        others = [(t.name, t.category_list) for t in self.app.store.tabs()
                  if t.id != self.tab_id and t.is_checklist and t.category_list]
        dialog = CategoriesDialog(self, self.categories(), others)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            names, renamed = dialog.result_names()
            self.app.store.set_categories(self.tab_id, names, renamed)
            if names and not self.show_category:
                self.app.store.update_tab(self.tab_id, show_category=True)

    def visible_columns(self) -> list[str]:
        cols = list(self.app.settings["col_order"])
        if self.app.settings.get("hide_pri"):
            cols = [c for c in cols if c != "pri"]
        return cols

    def ideal_size(self) -> tuple[int, int]:
        """Width and height this page needs to show every item in full."""
        fm = self.fontMetrics()
        longest = max((fm.horizontalAdvance(r.item.name) for r in self.rows), default=160)
        width = 12 + 8 + CHECK_W + CHEV_W + 8 * 3 + longest + 2 * 18 + 14
        if not self.is_checklist:
            cols = self.visible_columns()
            width += (DUE_W + 8 if "due" in cols else 0) + (PRI_W + 8 if "pri" in cols else 0)
        elif self.timer_on:
            width += TIME_W + PLAY_W + 16
        if self.show_category:
            width += CAT_W + 8
        width = max(width, 360)
        chrome = self.height() - self.scroll.viewport().height()
        height = chrome + self.container.sizeHint().height() + 4
        return width, height

    def _header_menu(self, pos) -> None:
        menu = QMenu(self)
        if self.is_checklist:
            if self.categories_on:
                shown = self.show_category
                menu.addAction("Hide the Category column" if shown else "Show the Category column",
                               lambda: self.app.store.update_tab(self.tab_id, show_category=not shown))
                menu.addAction("Edit categories…", self.edit_categories)
                menu.addSeparator()
            if self.app.has("timer"):
                menu.addAction("Turn the timer off" if self.timer_on else "Use a timer",
                               lambda: self.app.set_timer_on(self.tab_id, not self.timer_on))
                if self.timer_on:
                    menu.addAction("Show the Time column" if not self.show_time else "Hide the Time column",
                                   lambda: self.app.set_setting("hide_time", self.show_time))
            menu.addAction("Switch to priority list", lambda: self.app.store.set_tab_kind(self.tab_id, "list"))
        else:
            hidden = bool(self.app.settings.get("hide_pri"))
            menu.addAction("Show the Priority column" if hidden else "Hide the Priority column",
                           lambda: self.app.set_setting("hide_pri", not hidden))
            menu.addAction("Switch to checklist", lambda: self.app.store.set_tab_kind(self.tab_id, "checklist"))
        menu.exec(self.header.mapToGlobal(pos))

    def progress(self) -> tuple[int, int]:
        items = self.app.store.items(self.tab_id)
        return sum(1 for i in items if i.done), len(items)

    # ---- header ----------------------------------------------------------------
    def build_header(self) -> None:
        lay = self.header.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(8)
        items = self.app.store.items(self.tab_id)
        self.check_all = QCheckBox()
        self.check_all.setFixedWidth(CHECK_W)
        self.check_all.setEnabled(bool(items))
        self.check_all.setChecked(bool(items) and all(i.done for i in items))
        self.check_all.setToolTip("Untick everything" if self.check_all.isChecked() else "Tick everything")
        self.check_all.clicked.connect(lambda on: QTimer.singleShot(0, lambda: self.app.tick_all(self.tab_id, on)))
        lay.addWidget(self.check_all)
        tab = self.app.store.tab(self.tab_id)
        self.desc_btn = icon_button("info", "Description", size=CHEV_W)
        has_desc = bool(tab and tab.description.strip())
        self.desc_btn.setProperty("iconRole", "accent" if has_desc else "muted")
        set_icon_name(self.desc_btn, "info")
        self.desc_btn.setToolTip(("Description: " + tab.description.strip()[:200]) if has_desc
                                 else "Add a description for this list")
        self.desc_btn.clicked.connect(self.edit_description)
        if self.is_checklist:
            groups: dict[str, list] = {"step": [], "category": [], "time": []}
            label = QLabel("STEP")
            label.setObjectName("HeaderLabel")
            self.progress_label = QLabel()
            self.progress_label.setObjectName("HeaderLabel")
            groups["step"] += [(label, 1), (self.progress_label, 0)]
            if self.show_category:
                cat = QLabel("CATEGORY")
                cat.setObjectName("HeaderLabel")
                cat.setFixedWidth(CAT_W)
                groups["category"].append((cat, 0))
            if tab is not None and self.timer_on and tab.timer_finished and self.app.has("ledger"):
                ledger = icon_button("ledger", "Make a PDF of this time log in Ledger", role="accent", size=PLAY_W)
                ledger.clicked.connect(lambda: self.app.make_pdf(self.tab_id))
                groups["time"].append((ledger, 0))
            if self.timer_on:
                self.head_play = icon_button("play", "Start the timer", size=PLAY_W)
                self.head_play.clicked.connect(lambda: self.app.toggle_timer(self.tab_id))
                self.total_btn = QPushButton()
                self.total_btn.setObjectName("TotalBtn")
                self.total_btn.setFixedWidth(TIME_W)
                self.total_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                self.total_btn.clicked.connect(self._set_total_limit)
                if self.show_time:
                    groups["time"] += [(self.head_play, 0), (self.total_btn, 0)]
            for key in self.checklist_columns():
                for w, stretch in groups[key]:
                    lay.addWidget(w, stretch)
            lay.addWidget(self.desc_btn)
            self._update_progress()
            self.update_times()
            return
        key, direction = self.app.settings["sort_key"], self.app.settings["sort_dir"]
        if key == "pri" and self.app.settings.get("hide_pri"):
            key = "due"
        for col in self.visible_columns():
            arrow = (" ↑" if direction == 1 else " ↓") if col == key else ""
            b = QPushButton(COLUMN_TITLES[col] + arrow)
            b.setObjectName("HeaderBtn")
            b.setProperty("active", col == key)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip("Sort by this column (click again to reverse). Right-click for more.")
            b.clicked.connect(lambda _=False, c=col: self._sort_by(c))
            if col == "due":
                b.setFixedWidth(DUE_W)
            elif col == "pri":
                b.setFixedWidth(PRI_W)
            else:
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            lay.addWidget(b, 1 if col == "item" else 0)
        lay.addWidget(self.desc_btn)

    def _sort_by(self, col: str) -> None:
        if self.app.settings["sort_key"] == col:
            self.app.set_setting("sort_dir", -self.app.settings["sort_dir"])
        else:
            self.app.set_setting("sort_key", col)
            self.app.set_setting("sort_dir", 1)

    # ---- rows ------------------------------------------------------------------------
    def _update_progress(self) -> None:
        if self.is_checklist and hasattr(self, "progress_label"):
            done, total = self.progress()
            self.progress_label.setText(f"{done} OF {total} DONE" if total else "")

    def sorted_items(self) -> list[Item]:
        items = self.app.store.items(self.tab_id)        # manual order
        if not self.app.settings["show_done"]:
            items = [i for i in items if not i.done]
        if self.is_checklist:
            return items                                  # ticked steps stay in place
        key, direction = self.app.settings["sort_key"], self.app.settings["sort_dir"]
        if key == "pri" and self.app.settings.get("hide_pri"):
            key = "due"
        far = "9999-12-31"

        def date_key(i: Item) -> str:
            return i.due or far

        if key == "pri":
            primary = lambda i: (i.priority, date_key(i), i.id)          # noqa: E731
        elif key == "item":
            primary = lambda i: (i.name.casefold(), i.id)                # noqa: E731
        else:
            primary = lambda i: (date_key(i), i.priority, i.id)          # noqa: E731
        items.sort(key=primary, reverse=(direction == -1))
        items.sort(key=lambda i: i.done)          # stable: done items sink to the bottom
        return items

    def schedule_refresh(self) -> None:
        self._refresh_timer.start()

    def refresh(self) -> None:
        bar = self.scroll.verticalScrollBar()
        pos = bar.value()
        for row in self.rows:
            row.flush()
            self.rows_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self.rows = []
        self.build_header()          # timer on/off, description and progress live in the header
        items = self.sorted_items()
        live_ids = {i.id for i in items}
        self.expanded &= live_ids
        for i, it in enumerate(items):
            row = ItemRow(self, it)
            self.rows_layout.insertWidget(i, row)
            self.rows.append(row)
        self.empty.setVisible(not items)
        self._update_progress()
        QTimer.singleShot(0, lambda: bar.setValue(pos))

    def flush(self) -> None:
        for row in self.rows:
            row.flush()

    def columns_changed(self) -> None:
        self._apply_kind()
        self.build_header()
        self.refresh()

    def retheme(self) -> None:
        self.build_header()
        self.refresh()
        self._update_date_button()

    # ---- quick add ------------------------------------------------------------------
    def _update_preview(self) -> None:
        text = self.input.text().strip()
        if not text:
            self.preview_row.hide()
            return
        if self.is_checklist:
            name, link = take_link(text)
            self._show_preview(f"Adds “{name or link}”", link) if link else self.preview_row.hide()
            return
        q = parse_quick_add(text, dt.date.today())
        parts = []
        if q.due:
            parts.append(dates.range_label(q.due, q.end) if q.end else
                         dates.due_label(q.due, None, dt.date.today()).replace(" · late", ""))
        if q.priority:
            parts.append(f"{q.priority} priority")
        if q.remind_time:
            parts.append(f"reminder {dates.fmt_time(q.remind_time)}")
        if parts or q.link:
            self._show_preview(f"Adds “{q.name or q.link}”" + ("  ·  " + "  ·  ".join(parts) if parts else ""), q.link)
        else:
            self.preview_row.hide()

    def _show_preview(self, text: str, link: str) -> None:
        """The line under the add box; a web address shows as a small link icon, not the address."""
        self.preview.setText(text)
        if link:
            self.preview_link.setPixmap(make_icon(links.icon_name(link) or "globe", themes.current["accent"], 13)
                                        .pixmap(13, 13))
            self.preview_link.setToolTip(link)
        self.preview_link.setVisible(bool(link))
        self.preview_row.show()

    def _open_date_popup(self) -> None:
        self.popup = DatePopup(self, self.draft_due, self.draft_end)
        self.popup.picked.connect(self._draft_picked)
        self.popup.show_under(self.date_btn)

    def _draft_picked(self, due: str, end: str) -> None:
        self.draft_due, self.draft_end = due, end
        self._update_date_button()

    def _update_date_button(self) -> None:
        if self.draft_due:
            label = dates.range_label(_d(self.draft_due), _d(self.draft_end)) if self.draft_end else \
                dates.due_label(_d(self.draft_due), None, dt.date.today()).replace(" · late", "")
            self.date_btn.setText(label)
            self.date_btn.setProperty("iconRole", "accent")
            set_prop(self.date_btn, "on", True)
        else:
            self.date_btn.setText("Date")
            self.date_btn.setProperty("iconRole", "muted")
            set_prop(self.date_btn, "on", False)
        set_icon_name(self.date_btn, "calendar")

    def _entered(self, modifiers) -> None:
        flip = bool(modifiers & Qt.KeyboardModifier.ControlModifier) if modifiers is not None else False
        self.add_item(flip)

    def add_item(self, flip: bool = False) -> None:
        text = self.input.text().strip()
        if not text:
            self.input.setFocus()
            return
        top = self.app.new_items_on_top(flip) if self.is_checklist else False
        self.app.add_typed(self.tab_id, text, top=top, due=self.draft_due, end=self.draft_end,
                           priority=self.pri_box.currentIndex() if not self.is_checklist else 1)
        self.input.clear()
        self.draft_due = self.draft_end = ""
        self.pri_box.setCurrentIndex(1)
        self._update_date_button()
        self.input.setFocus()

    def focus_input(self) -> None:
        self.input.setFocus()
        self.input.selectAll()

    def counts(self) -> tuple[int, int, int, int]:
        """(open, due today, late, done)"""
        today = dt.date.today()
        items = self.app.store.items(self.tab_id)
        open_items = [i for i in items if not i.done]
        st = [dates.status(_d(i.due), _d(i.end), i.done, today) for i in open_items]
        return len(open_items), st.count("today"), st.count("overdue"), len(items) - len(open_items)


def open_count(app: "DocketApp", tab_id: int) -> int:
    return sum(1 for i in app.store.items(tab_id) if not i.done)

