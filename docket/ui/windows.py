"""The main tabbed window and the small list windows.

Both can collapse into a "pill": a slim, resizable bar with a tick box for the
list's top item (and the next ones if you make it taller), its own keep-on-top
pin, and buttons that only show while the mouse is over it.
"""
from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QCloseEvent, QColor, QFont, QGuiApplication, QIcon, QKeyEvent, QMouseEvent, QPainter,
                           QPainterPath)
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QSizeGrip, QStackedWidget, QStyle, QStyleOptionTab, QStylePainter,
                               QTabBar, QToolButton, QVBoxLayout, QWidget)

from .. import dates, themes
from ..store import Item
from .common import (SIDE_EDGES, WM_NCLBUTTONDBLCLK, ClickableWidget, ElideLabel, TitleBar, edge_hit_test,
                     round_corners, set_prop, win_message)
from .icons import apply_icon, app_icon, dot_icon, icon_button, set_icon_name, tinted_checkbox_qss
from .listpage import ListPage, open_count

if TYPE_CHECKING:
    from ..app import DocketApp

FRAMELESS = Qt.WindowType.FramelessWindowHint
PILL_LINE_H = 26


class FitGrip(QSizeGrip):
    """The resize corner. Double-click it to fit the window to everything in the list."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setToolTip("Drag to resize. Double-click to fit the window to all its items.")

    def mouseDoubleClickEvent(self, e) -> None:
        win = self.window()
        if hasattr(win, "autosize"):
            win.autosize()


class RenameEdit(QLineEdit):
    """The box that appears over a tab while renaming it. Enter or clicking away saves,
    Esc cancels, and it always goes away."""

    finished = Signal(bool)   # True = save the new name

    def __init__(self, text: str, parent: QWidget):
        super().__init__(text, parent)
        self._done = False

    def end(self, commit: bool) -> None:
        if not self._done:
            self._done = True
            self.finished.emit(commit)

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)
        self.end(True)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.end(False)
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.end(True)
            return
        super().keyPressEvent(e)


class ColorTabBar(QTabBar):
    """Tabs that can be filled with their list's colour (Settings > whole-tab colour)."""

    def __init__(self, app: "DocketApp"):
        super().__init__()
        self.app = app

    def _key(self, i: int) -> str:
        tab = self.app.store.tab(self.tabData(i))
        return tab.color if tab else ""

    def paintEvent(self, e) -> None:
        if not self.app.settings.get("tab_tint"):
            super().paintEvent(e)
            return
        p = QStylePainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        current = self.currentIndex()
        for i in range(self.count()):
            rect = QRectF(self.tabRect(i)).adjusted(1, 2, -1, 0)
            key = self._key(i)
            selected = i == current
            path = QPainterPath()
            path.addRoundedRect(rect.adjusted(0, 0, 0, 10), 7, 7)
            p.save()
            p.setClipRect(rect)
            p.fillPath(path, QColor(themes.tint(key, 0.40 if selected else 0.18)))
            if selected:
                p.fillRect(QRectF(rect.left(), rect.bottom() - 3, rect.width(), 3), QColor(themes.list_color(key)))
            p.restore()
            opt = QStyleOptionTab()
            self.initStyleOption(opt, i)
            opt.icon = QIcon()
            font = QFont(self.font())
            font.setBold(selected)
            p.setFont(font)
            p.drawControl(QStyle.ControlElement.CE_TabBarTabLabel, opt)


class DocketWindow(QWidget):
    """Shared behaviour: frameless, edge resizing, pill mode, keep-on-top."""

    title: TitleBar
    body: QWidget
    pin_btn: QToolButton

    def __init__(self, app: "DocketApp", flags, pill_key: str, min_size: QSize):
        super().__init__(None, flags | FRAMELESS)
        self.app = app
        self.pill_key = pill_key
        self.min_size = min_size
        self.collapsed = False
        self.pill_buttons: list[QWidget] = []
        self._full_size: QSize | None = None
        self._rounded = False
        self._pill_wide = False
        self._pill_set_w = 0
        self._resizing_myself = False
        self._pill_top_id: int | None = None
        self._pill_lines: list[QWidget] = []
        self._line_widths: list[int] = []
        self.setObjectName("Window")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumSize(min_size)

        self.pill_list = QWidget()
        self.pill_list.setObjectName("PillList")
        self.pill_list.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._pill_lay = QVBoxLayout(self.pill_list)
        self._pill_lay.setContentsMargins(15, 0, 10, 6)
        self._pill_lay.setSpacing(0)
        self.pill_list.hide()

        self._pill_timer = QTimer(self)
        self._pill_timer.setSingleShot(True)
        self._pill_timer.setInterval(500)
        self._pill_timer.timeout.connect(self._save_pill_size)

    def _wire_title(self) -> None:
        """Call once the subclass has made self.title."""
        self.title.check.toggled.connect(self._tick_top)

    # ---- native window bits ------------------------------------------------------
    def nativeEvent(self, event_type, message):
        msg = win_message(event_type, message)
        if msg is not None and msg.message == WM_NCLBUTTONDBLCLK and self.collapsed:
            if msg.wParam in SIDE_EDGES:
                QTimer.singleShot(0, self.toggle_pill_width)
            return True, 0           # no vertical maximise on a pill
        code = edge_hit_test(self, event_type, message)
        if code is not None:
            return True, code
        return super().nativeEvent(event_type, message)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._rounded:
            round_corners(self)
            self._rounded = True

    def enterEvent(self, e) -> None:
        super().enterEvent(e)
        if self.collapsed:
            for b in self.pill_buttons:
                b.show()

    def leaveEvent(self, e) -> None:
        super().leaveEvent(e)
        if self.collapsed:
            for b in self.pill_buttons:
                b.hide()

    def set_on_top(self, on: bool) -> None:
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == on:
            return
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self._rounded = False          # Windows makes a new native window
        if visible:
            self.show()

    def wants_on_top(self) -> bool:
        return bool(self.app.settings["pill_on_top"] if self.collapsed else self.app.settings["on_top"])

    def sync_pin(self) -> None:
        pin = getattr(self, "pin_btn", None)
        if pin is None:
            return
        pin.blockSignals(True)
        pin.setChecked(self.wants_on_top())
        pin.blockSignals(False)
        apply_icon(pin)
        pin.setToolTip("Keep the pill on top of other windows" if self.collapsed
                       else "Keep on top of other windows")

    def _pin_toggled(self, on: bool) -> None:
        apply_icon(self.pin_btn)
        self.app.set_setting("pill_on_top" if self.collapsed else "on_top", on)

    # ---- which list this window shows ----------------------------------------------------
    def pill_page(self) -> ListPage | None:
        return None

    def list_key(self) -> str:
        return ""

    def list_color(self) -> str:
        return themes.list_color(self.list_key())

    tint_title_when_open = False

    def apply_tint(self) -> None:
        """With whole-tab colour on, the pill (and a list window's title bar) wear the list's colour."""
        on = bool(self.app.settings.get("tab_tint")) and (self.collapsed or self.tint_title_when_open)
        css = f"background: {themes.tint(self.list_key(), 0.32)};" if on else ""
        self.title.setStyleSheet(f"#TitleBar {{ {css} }}" if css else "")
        self.pill_list.setStyleSheet(f"#PillList {{ {css} }}" if css and self.collapsed else "")

    def autosize(self) -> None:
        """Grow or shrink the window so every item in the list shows in full."""
        page = self.pill_page()
        if self.collapsed or page is None:
            return
        want_w, want_h = page.ideal_size()
        width = max(self.minimumWidth(), want_w + (self.width() - page.width()), self.extra_min_width())
        height = max(self.minimumHeight(), want_h + (self.height() - page.height()))
        screen = self.screen().availableGeometry()
        width, height = min(width, screen.width() - 20), min(height, screen.height() - 20)
        geo = QRect(self.geometry())
        geo.setSize(QSize(width, height))
        if geo.right() > screen.right() - 4:
            geo.moveRight(screen.right() - 4)
        if geo.bottom() > screen.bottom() - 4:
            geo.moveBottom(screen.bottom() - 4)
        self.setGeometry(geo)

    def extra_min_width(self) -> int:
        return 0

    def normal_title(self) -> str:
        return "Docket"

    def mode_changed(self) -> None:
        pass

    # ---- pill mode ----------------------------------------------------------------------
    def toggle_collapse(self) -> None:
        if not self.collapsed:
            self._full_size = self.size()
            self.body.hide()
            self.pill_list.show()
            self.collapsed = True
            self._pill_wide = False
            self.setMinimumSize(220, self.title.height() + 2)
            saved = self.app.pill_rect(self.pill_key)
            self._resize_myself(QSize(saved[0], saved[1]) if saved else
                                QSize(self.width(), self.title.height() + 2))
            for b in self.pill_buttons:
                b.setVisible(self.underMouse())
            self.title.strip.show()
        else:
            self.pill_list.hide()
            self.body.show()
            self.collapsed = False
            self.setMinimumSize(self.min_size)
            self.resize(self._full_size or QSize(440, 640))
            for b in self.pill_buttons:
                b.show()
            self.title.strip.hide()
            self.title.check.hide()
            self.title.name.setFullText(self.normal_title())
            self.title.setToolTip("")
            set_prop(self.title.extra, "status", "none")
        self.mode_changed()
        self.set_on_top(self.wants_on_top())
        self.sync_pin()
        self.update_pill()
        self.apply_tint()
        self.app.on_collapse_changed(self)

    def restore_pill_position(self) -> None:
        rect = self.app.pill_rect(self.pill_key)
        if rect and len(rect) >= 4:
            pos = QPoint(rect[2], rect[3])
            if QGuiApplication.screenAt(pos + QPoint(20, 10)) is not None:
                self.move(pos)

    def _resize_myself(self, size: QSize) -> None:
        self._resizing_myself = True
        self.resize(size)
        self._resizing_myself = False

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.collapsed:
            if not self._resizing_myself:
                self._pill_wide = False          # dragged by hand: that's the new width
            self.update_pill()
            self._pill_timer.start()

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        if self.collapsed:
            self._pill_timer.start()

    def _save_pill_size(self) -> None:
        if self.collapsed:
            width = self._pill_set_w if self._pill_wide and self._pill_set_w else self.width()
            self.app.save_pill_rect(self.pill_key, width, self.height(), self.x(), self.y())

    def toggle_pill_width(self) -> None:
        """Double-click a pill's side edge: widen to fit the whole item, then back again."""
        if not self.collapsed:
            return
        if not self._pill_wide:
            self._pill_set_w = self.width()
            width = max(self.width(), self._pill_fit_width())
            self._pill_wide = True
        else:
            width = self._pill_set_w or self.width()
            self._pill_wide = False
        geo = QRect(self.geometry())
        geo.setWidth(width)
        screen = self.screen().availableGeometry()
        if geo.right() > screen.right() - 8:
            geo.moveRight(screen.right() - 8)
        self._resizing_myself = True
        self.setGeometry(geo)
        self._resizing_myself = False
        self._pill_timer.start()

    def _pill_fit_width(self) -> int:
        fm = self.title.name.fontMetrics()
        buttons = sum(b.sizeHint().width() + 2 for b in self.pill_buttons)
        need = (5 + 10 + 24 + fm.horizontalAdvance(self.title.name.fullText()) + 20
                + fm.horizontalAdvance(self.title.extra.text()) + 12 + buttons + 16)
        for w in self._line_widths:
            need = max(need, w)
        screen = self.screen().availableGeometry()
        return int(min(need, screen.width() - 40))

    def _tick_top(self, checked: bool) -> None:
        if checked and self._pill_top_id is not None:
            self.app.store.update_item(self._pill_top_id, done=True)

    def update_pill(self) -> None:
        if not self.collapsed:
            return
        page = self.pill_page()
        items: list[Item] = [i for i in page.sorted_items() if not i.done] if page is not None else []
        checklist = page is not None and page.is_checklist
        today = dt.date.today()
        color = self.list_color()
        self.title.strip.setStyleSheet(f"background: {color};")
        self.title.check.setStyleSheet(tinted_checkbox_qss(color))
        self.title.check.blockSignals(True)
        self.title.check.setChecked(False)
        self.title.check.blockSignals(False)
        progress = ""
        if checklist:
            done, total = page.progress()
            progress = f"{done} of {total}" if total else ""
        if items:
            top = items[0]
            self._pill_top_id = top.id
            self.title.check.show()
            self.title.name.setFullText(top.name)
            if checklist:
                self.title.extra.setText(progress)
                set_prop(self.title.extra, "status", "none")
            else:
                due, end = dates.from_iso(top.due), dates.from_iso(top.end)
                self.title.extra.setText(dates.due_label(due, end, today) if due else "")
                set_prop(self.title.extra, "status", dates.status(due, end, False, today))
            self.title.setToolTip(f"{top.name}\nTick the box when it's done. Double-click to open the list.")
        else:
            self._pill_top_id = None
            self.title.check.hide()
            self.title.name.setFullText("All done" if checklist and progress else "All clear")
            self.title.extra.setText(progress)
            set_prop(self.title.extra, "status", "none")
            self.title.setToolTip("Nothing left in this list. Double-click to open it.")

        for w in self._pill_lines:
            self._pill_lay.removeWidget(w)
            w.hide()
            w.deleteLater()
        self._pill_lines, self._line_widths = [], []
        while self._pill_lay.count():
            self._pill_lay.takeAt(0)
        room = max(0, (self.height() - self.title.height() - 8) // PILL_LINE_H)
        fm = self.title.name.fontMetrics()
        for it in items[1:1 + room]:
            line, label = self._pill_line(it, today, color, checklist)
            self._pill_lay.addWidget(line)
            self._pill_lines.append(line)
            self._line_widths.append(15 + 24 + fm.horizontalAdvance(it.name) + 20
                                     + fm.horizontalAdvance(label) + 30)
        self._pill_lay.addStretch(1)
        self.apply_tint()

    def _pill_line(self, it: Item, today: dt.date, color: str, checklist: bool) -> tuple[QWidget, str]:
        line = ClickableWidget()
        line.setFixedHeight(PILL_LINE_H)
        line.setCursor(Qt.CursorShape.PointingHandCursor)
        line.setToolTip("Click to open the list")
        line.clicked.connect(self.toggle_collapse)
        h = QHBoxLayout(line)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        check = QCheckBox()
        check.setStyleSheet(tinted_checkbox_qss(color))
        check.setCursor(Qt.CursorShape.PointingHandCursor)
        check.setToolTip("Tick off")
        item_id = it.id
        check.toggled.connect(lambda on: on and self.app.store.update_item(item_id, done=True))
        name = ElideLabel(it.name)
        label = ""
        if not checklist and it.due:
            due, end = dates.from_iso(it.due), dates.from_iso(it.end)
            label = dates.due_label(due, end, today)
        when = QLabel(label)
        when.setObjectName("Due")
        if not checklist and it.due:
            when.setProperty("status", dates.status(dates.from_iso(it.due), dates.from_iso(it.end), False, today))
        h.addWidget(check)
        h.addWidget(name, 1)
        h.addWidget(when)
        return line, label


# ---------------------------------------------------------------------------
class MainWindow(DocketWindow):
    def __init__(self, app: "DocketApp"):
        super().__init__(app, Qt.WindowType.Window, "main", QSize(360, 320))
        self.pages: dict[int, ListPage] = {}
        self.setWindowTitle("Docket")
        self.resize(440, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.logo = QLabel()
        self.title = TitleBar("Docket", self.logo)
        self._wire_title()
        self.theme_btn = icon_button("moon", "Dark mode")
        self.theme_btn.clicked.connect(app.toggle_dark)
        self.pin_btn = icon_button("pin", "Keep on top of other windows", checkable=True)
        self.pin_btn.toggled.connect(self._pin_toggled)
        self.settings_btn = icon_button("sliders", "Settings")
        self.settings_btn.clicked.connect(app.open_settings)
        self.collapse_btn = icon_button("chevron_up", "Shrink to a pill")
        self.collapse_btn.clicked.connect(self.toggle_collapse)
        self.min_btn = icon_button("minimize", "Minimize")
        self.min_btn.clicked.connect(self.showMinimized)
        self.close_btn = icon_button("close", "Close to the tray (Docket keeps running)")
        self.close_btn.clicked.connect(self.close)
        for b in (self.theme_btn, self.pin_btn, self.settings_btn, self.collapse_btn, self.min_btn, self.close_btn):
            self.title.add(b)
        self.pill_buttons = [self.pin_btn, self.collapse_btn, self.close_btn]
        root.addWidget(self.title)
        root.addWidget(self.pill_list, 1)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.tab_row = QWidget()
        self.tab_row.setObjectName("TabRow")
        self.tab_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        tr = QHBoxLayout(self.tab_row)
        tr.setContentsMargins(8, 2, 8, 0)
        tr.setSpacing(2)
        self.tabs = ColorTabBar(app)
        self.tabs.setMovable(True)
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setIconSize(QSize(10, 10))
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.currentChanged.connect(self._on_current_changed)
        self.tabs.tabMoved.connect(self._on_tab_moved)
        self.tabs.tabBarDoubleClicked.connect(self.start_rename)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        self.tabs.installEventFilter(self)
        self._drag_tid: int | None = None
        tr.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignBottom)
        self.add_tab_btn = icon_button("plus", "New priority list (arrow: checklist or template)", size=28)
        self.add_tab_btn.setFixedSize(42, 28)
        self.add_tab_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        new_menu = QMenu(self.add_tab_btn)
        new_menu.aboutToShow.connect(lambda: app.fill_new_menu(new_menu, self))
        self.add_tab_btn.setMenu(new_menu)
        self.add_tab_btn.clicked.connect(lambda: self.new_tab("list"))
        tr.addWidget(self.add_tab_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        tr.addStretch(1)
        body.addWidget(self.tab_row)

        self.stack = QStackedWidget()
        self.placeholder = QLabel("Every list is in its own window right now.\n"
                                  "Drag a list window's title onto this tab bar to put it back.")
        self.placeholder.setObjectName("Empty")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.stack.addWidget(self.placeholder)
        body.addWidget(self.stack, 1)

        footer = QWidget()
        footer.setObjectName("Footer")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer.setFixedHeight(28)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 0, 0, 0)
        fl.setSpacing(10)
        self.status = QLabel()
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setObjectName("LinkBtn")
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.setToolTip("Untick every step to start the checklist again")
        self.reset_btn.clicked.connect(lambda: self.current_tab_id() is not None
                                       and app.reset_checklist(self.current_tab_id(), self))
        self.done_btn = QPushButton()
        self.done_btn.setObjectName("LinkBtn")
        self.done_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.done_btn.clicked.connect(lambda: app.set_setting("show_done", not app.settings["show_done"]))
        self.backup_label = QLabel()
        grip = FitGrip(self)
        grip.setFixedSize(16, 16)
        fl.addWidget(self.status, 1)
        fl.addWidget(self.reset_btn)
        fl.addWidget(self.done_btn)
        fl.addWidget(self.backup_label)
        fl.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        body.addWidget(footer)
        root.addWidget(self.body, 1)

        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self.update_footer)
        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(600)
        self._geo_timer.timeout.connect(self._save_geometry)
        self._rename_editor: RenameEdit | None = None
        self.retheme()

    # ---- window behaviour ------------------------------------------------------------
    def closeEvent(self, e: QCloseEvent) -> None:
        if self.app.quitting:
            e.accept()
            return
        e.ignore()
        self.hide()
        self.app.on_main_hidden()

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        if not self.collapsed:
            self._geo_timer.start()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if not self.collapsed:
            self._geo_timer.start()

    def _save_geometry(self) -> None:
        if not self.collapsed and self.isVisible() and not self.isMinimized():
            self.app.store.set_setting("main_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))

    def pill_page(self) -> ListPage | None:
        return self.current_page()

    def list_key(self) -> str:
        tid = self.current_tab_id()
        tab = self.app.store.tab(tid) if tid is not None else None
        return tab.color if tab else ""

    def extra_min_width(self) -> int:
        return self.tabs.sizeHint().width() + 80

    def mode_changed(self) -> None:
        for b in (self.theme_btn, self.settings_btn, self.min_btn):
            b.setVisible(not self.collapsed)
        self.logo.setVisible(not self.collapsed)
        set_icon_name(self.collapse_btn, "chevron_down" if self.collapsed else "chevron_up")
        self.collapse_btn.setToolTip("Open the full window" if self.collapsed else "Shrink to a pill")
        self.update_footer()

    def retheme(self) -> None:
        self.logo.setPixmap(app_icon(themes.current["accent"], themes.current["win"]).pixmap(16, 16))
        dark = self.app.settings["theme"] == "dark"
        set_icon_name(self.theme_btn, "sun" if dark else "moon")
        self.theme_btn.setToolTip("Light mode" if dark else "Dark mode")
        for page in self.pages.values():
            page.retheme()
        self._refresh_tab_buttons()
        self.update_pill()
        self.apply_tint()

    # ---- dropping list windows onto the tab bar ----------------------------------------------
    def drop_zone_contains(self, gpos: QPoint) -> bool:
        if not self.isVisible() or self.isMinimized() or self.collapsed:
            return False
        top_left = self.tab_row.mapToGlobal(QPoint(0, 0))
        zone = QRect(top_left, self.tab_row.size()).adjusted(0, -self.title.height(), 0, 12)
        return zone.contains(gpos)

    def drop_index(self, gpos: QPoint) -> int:
        i = self.tabs.tabAt(self.tabs.mapFromGlobal(gpos))
        return i if i >= 0 else self.tabs.count()

    def set_drop_hint(self, on: bool) -> None:
        set_prop(self.tab_row, "drop", on)

    # ---- dragging a tab out of the bar ----------------------------------------------------------
    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if obj is self.tabs:
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress and self._rename_editor is not None \
                    and not self._rename_editor.geometry().contains(ev.position().toPoint()):
                self._rename_editor.end(True)
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                i = self.tabs.tabAt(ev.position().toPoint())
                self._drag_tid = self.tabs.tabData(i) if i >= 0 else None
            elif (t == QEvent.Type.MouseMove and self._drag_tid is not None
                  and ev.buttons() & Qt.MouseButton.LeftButton):
                y = ev.position().toPoint().y()
                if y < -30 or y > self.tabs.height() + 30:
                    tid, self._drag_tid = self._drag_tid, None
                    gpos = ev.globalPosition().toPoint()
                    release = QMouseEvent(QEvent.Type.MouseButtonRelease, ev.position(), ev.globalPosition(),
                                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                          Qt.KeyboardModifier.NoModifier)
                    QApplication.sendEvent(self.tabs, release)
                    QTimer.singleShot(0, lambda: self.app.tear_off(tid, gpos))
                    return True
            elif t == QEvent.Type.MouseButtonRelease:
                self._drag_tid = None
        return super().eventFilter(obj, ev)

    # ---- tabs -------------------------------------------------------------------------------------
    def current_tab_id(self) -> int | None:
        i = self.tabs.currentIndex()
        return self.tabs.tabData(i) if i >= 0 else None

    def current_page(self) -> ListPage | None:
        tid = self.current_tab_id()
        return self.pages.get(tid) if tid is not None else None

    def rebuild_tabs(self, select: int | None = None) -> None:
        self._drop_rename_editor()
        keep = select if select is not None else self.current_tab_id()
        docked = [t for t in self.app.store.tabs() if not t.popped]
        docked_ids = {t.id for t in docked}
        for tid in list(self.pages):
            if tid not in docked_ids:
                page = self.pages.pop(tid)
                page.flush()
                self.stack.removeWidget(page)
                page.deleteLater()
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for t in docked:
            if t.id not in self.pages:
                page = ListPage(self.app, t.id)
                self.pages[t.id] = page
                self.stack.addWidget(page)
            else:
                self.pages[t.id].sync_kind()
            i = self.tabs.addTab(t.name)
            self.tabs.setTabData(i, t.id)
            self.tabs.setTabIcon(i, QIcon() if self.app.settings.get("tab_tint")
                                 else dot_icon(themes.list_color(t.color), 10))
            btn = icon_button("popout", "Open in its own window (or drag the tab out)", size=22)
            btn.clicked.connect(lambda _=False, tid=t.id: self.app.pop_out(tid))
            self.tabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, btn)
        index = 0
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) == keep:
                index = i
        if self.tabs.count():
            self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)
        self._on_current_changed(self.tabs.currentIndex())
        self.update_tab_labels()

    def _refresh_tab_buttons(self) -> None:
        for i in range(self.tabs.count()):
            btn = self.tabs.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if btn is not None:
                set_icon_name(btn, "popout")
            tab = self.app.store.tab(self.tabs.tabData(i))
            if tab:
                self.tabs.setTabIcon(i, QIcon() if self.app.settings.get("tab_tint")
                                     else dot_icon(themes.list_color(tab.color), 10))
        self.tabs.update()

    def update_tab_labels(self) -> None:
        for i in range(self.tabs.count()):
            tid = self.tabs.tabData(i)
            tab = self.app.store.tab(tid)
            if not tab:
                continue
            if self.tabs.tabText(i) != tab.name:
                self.tabs.setTabText(i, tab.name)
            if tab.is_checklist:
                items = self.app.store.items(tid)
                done = sum(1 for it in items if it.done)
                self.tabs.setTabToolTip(i, f"{tab.name}: checklist, {done} of {len(items)} done. "
                                           "Double-click to rename, right-click for more.")
            else:
                n = open_count(self.app, tid)
                self.tabs.setTabToolTip(i, f"{tab.name}: {n} open. Double-click to rename, "
                                           "drag out for its own window, right-click for more.")
        self.update_footer()

    def _on_current_changed(self, index: int) -> None:
        if self._rename_editor is not None and not self.tabs.signalsBlocked():
            self._rename_editor.end(True)
        tid = self.tabs.tabData(index) if index >= 0 else None
        page = self.pages.get(tid) if tid is not None else None
        self.stack.setCurrentWidget(page if page is not None else self.placeholder)
        if tid is not None:
            self.app.store.set_setting("current_tab", tid)
        self.update_footer()
        self.apply_tint()

    def _on_tab_moved(self, _from: int, _to: int) -> None:
        docked = [self.tabs.tabData(i) for i in range(self.tabs.count())]
        popped = [t.id for t in self.app.store.tabs() if t.popped]
        self.app.store.reorder_tabs(docked + popped)

    def new_tab(self, kind: str = "list") -> None:
        tab = self.app.new_list("New checklist" if kind == "checklist" else "New list", kind)
        self.rebuild_tabs(select=tab.id)
        # Wait a moment: when this came from a menu, the menu takes focus back as it closes.
        QTimer.singleShot(60, lambda: self.rename_tab_id(tab.id))

    def rename_tab_id(self, tab_id: int) -> None:
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) == tab_id:
                self.start_rename(i)

    def _drop_rename_editor(self) -> None:
        editor, self._rename_editor = self._rename_editor, None
        if editor is not None:
            editor._done = True
            editor.hide()
            editor.deleteLater()

    def start_rename(self, index: int) -> None:
        if index < 0:
            return
        self._drop_rename_editor()
        tid = self.tabs.tabData(index)
        tab = self.app.store.tab(tid)
        if not tab:
            return
        editor = RenameEdit(tab.name, self.tabs)
        editor.setGeometry(self.tabs.tabRect(index).adjusted(4, 3, -4, -3))
        editor.selectAll()
        editor.show()
        self.activateWindow()
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._rename_editor = editor

        def finish(commit: bool) -> None:
            if self._rename_editor is editor:
                self._rename_editor = None
            name = editor.text().strip()
            editor.hide()
            editor.deleteLater()
            if commit and name and name != tab.name:
                QTimer.singleShot(0, lambda: self.app.store.rename_tab(tid, name))

        editor.finished.connect(finish)

    def _tab_menu(self, pos: QPoint) -> None:
        index = self.tabs.tabAt(pos)
        menu = QMenu(self)
        if index >= 0:
            tid = self.tabs.tabData(index)
            menu.addAction("Rename", lambda: self.start_rename(index))
            menu.addAction("Open in its own window", lambda: self.app.pop_out(tid))
            menu.addSeparator()
            self.app.fill_list_menu(menu, tid, self)
            menu.addSeparator()
        new = menu.addMenu("New")
        self.app.fill_new_menu(new, self)
        menu.addAction("Import a list…", lambda: self.app.import_lists(self))
        if index >= 0:
            menu.addSeparator()
            menu.addAction("Delete list…", lambda: self.app.delete_tab(tid, self))
        menu.exec(self.tabs.mapToGlobal(pos))

    # ---- footer ----------------------------------------------------------------------------------
    def update_footer(self) -> None:
        page = self.current_page()
        checklist = page is not None and page.is_checklist
        if self._flash_timer.isActive():
            pass
        elif page is not None and checklist:
            done, total = page.progress()
            self.status.setText(f"{done} of {total} steps done" if total else "No steps yet")
        elif page is not None:
            open_n, today_n, late_n, _ = page.counts()
            text = f"{open_n} open · {today_n} due today"
            if late_n:
                text += f" · {late_n} late"
            self.status.setText(text)
        else:
            self.status.setText("")
        self.reset_btn.setVisible(checklist)
        self.done_btn.setText("Hide done" if self.app.settings["show_done"] else "Show done")
        self.done_btn.setVisible(page is not None)
        self.backup_label.setText(self.app.backup_status())
        self.update_pill()

    def flash(self, message: str) -> None:
        self.status.setText(message)
        self._flash_timer.start(3000)


# ---------------------------------------------------------------------------
class PopoutWindow(DocketWindow):
    """One list in its own small sticky-note style window."""

    def __init__(self, app: "DocketApp", tab_id: int):
        super().__init__(app, Qt.WindowType.Tool, str(tab_id), QSize(300, 220))
        self.tab_id = tab_id
        self.closing_for_good = False
        if app.settings["on_top"]:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        tab = app.store.tab(tab_id)

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)
        self.dot = QLabel()
        self.title = TitleBar(tab.name if tab else "List", self.dot, manual=True)
        self._wire_title()
        self.title.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.title.customContextMenuRequested.connect(self._title_menu)
        self.title.drag_moved.connect(self._dragging)
        self.title.drag_released.connect(self._dropped)
        self.pin_btn = icon_button("pin", "Keep the pill on top of other windows", checkable=True)
        self.pin_btn.toggled.connect(self._pin_toggled)
        self.pin_btn.hide()
        self.collapse_btn = icon_button("chevron_up", "Shrink to a pill")
        self.collapse_btn.clicked.connect(self.toggle_collapse)
        self.dock_btn = icon_button("dock", "Put back into the main window's tabs")
        self.dock_btn.clicked.connect(lambda: app.dock(tab_id))
        self.title.add(self.pin_btn)
        self.title.add(self.collapse_btn)
        self.title.add(self.dock_btn)
        self.pill_buttons = [self.pin_btn, self.collapse_btn, self.dock_btn]
        root.addWidget(self.title)
        root.addWidget(self.pill_list, 1)

        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.page = ListPage(app, tab_id)
        bl.addWidget(self.page, 1)
        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch(1)
        grip = FitGrip(self)
        grip.setFixedSize(14, 14)
        grip_row.addWidget(grip)
        bl.addLayout(grip_row)
        root.addWidget(self.body, 1)

        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(600)
        self._geo_timer.timeout.connect(self._save_geometry)

        if tab and tab.geometry:
            self.restoreGeometry(QByteArray.fromBase64(tab.geometry.encode("ascii")))
        else:
            self.resize(330, 380)
            self.move(app.main.geometry().topRight() + QPoint(16, 24 * (len(app.popouts) + 1)))
        self.retheme()
        self.update_counts()
        self.apply_tint()

    def pill_page(self) -> ListPage | None:
        return self.page

    tint_title_when_open = True

    def list_key(self) -> str:
        tab = self.app.store.tab(self.tab_id)
        return tab.color if tab else ""

    def normal_title(self) -> str:
        tab = self.app.store.tab(self.tab_id)
        return tab.name if tab else "List"

    def mode_changed(self) -> None:
        self.pin_btn.setVisible(self.collapsed and self.underMouse())
        self.dot.setVisible(not self.collapsed)
        set_icon_name(self.collapse_btn, "chevron_down" if self.collapsed else "chevron_up")
        self.collapse_btn.setToolTip("Open the list" if self.collapsed else "Shrink to a pill")
        self.update_counts()

    def toggle_collapse(self) -> None:
        super().toggle_collapse()
        if not self.collapsed:
            self.pin_btn.hide()           # the pill's pin only shows on the pill

    def retheme(self) -> None:
        self.dot.setPixmap(dot_icon(self.list_color(), 10).pixmap(10, 10))
        self.page.retheme()
        self.update_pill()
        self.apply_tint()

    def update_name(self) -> None:
        name = self.normal_title()
        self.setWindowTitle(name)
        self.dot.setPixmap(dot_icon(self.list_color(), 10).pixmap(10, 10))
        self.apply_tint()
        self.page.sync_kind()
        if not self.collapsed:
            self.title.name.setFullText(name)

    def update_counts(self) -> None:
        if self.collapsed:
            self.update_pill()
            return
        if self.page.is_checklist:
            done, total = self.page.progress()
            self.title.extra.setText(f"{done} of {total}" if total else "")
            return
        open_n, today_n, late_n, _ = self.page.counts()
        parts = []
        if late_n:
            parts.append(f"{late_n} late")
        if today_n:
            parts.append(f"{today_n} today")
        if not parts:
            parts.append(f"{open_n} open")
        self.title.extra.setText(" · ".join(parts))

    def _title_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        self.app.fill_list_menu(menu, self.tab_id, self)
        menu.addSeparator()
        menu.addAction("Put back in the main window", lambda: self.app.dock(self.tab_id))
        menu.exec(self.title.mapToGlobal(pos))

    # ---- drag onto the main tab bar to dock -------------------------------------------------------
    def _dragging(self, gpos: QPoint) -> None:
        self.app.main.set_drop_hint(self.app.main.drop_zone_contains(gpos))

    def _dropped(self, gpos: QPoint) -> None:
        main = self.app.main
        main.set_drop_hint(False)
        if main.drop_zone_contains(gpos):
            index = main.drop_index(gpos)
            QTimer.singleShot(0, lambda: self.app.dock(self.tab_id, index))

    # ---- geometry ---------------------------------------------------------------------------------
    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self._geo_timer.start()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._geo_timer.start()

    def _save_geometry(self) -> None:
        if self.collapsed or not self.isVisible():
            return
        self.app.store.set_tab_geometry(self.tab_id, bytes(self.saveGeometry().toBase64()).decode("ascii"))

    def closeEvent(self, e: QCloseEvent) -> None:
        if self.closing_for_good or self.app.quitting:
            self._geo_timer.stop()
            if self.isVisible():
                self._save_geometry()
            self.page.flush()
            e.accept()
            return
        e.ignore()
        self.app.dock(self.tab_id)


def confirm(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() == box.button(QMessageBox.StandardButton.Yes)
