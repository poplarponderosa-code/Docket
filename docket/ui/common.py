"""Small shared widgets and Windows helpers."""
from __future__ import annotations

import sys

from PySide6.QtCore import QDate, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (QApplication, QCheckBox, QDateEdit, QHBoxLayout, QLabel, QSizePolicy,
                               QWidget)

NONE_DATE = QDate(2000, 1, 1)


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def set_prop(w: QWidget, name: str, value) -> None:
    if w.property(name) != value:
        w.setProperty(name, value)
        repolish(w)


def round_corners(w: QWidget) -> None:
    """Ask Windows 11 to round a frameless window's corners. Harmless elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        pref = ctypes.c_int(2)  # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(w.winId()), 33, ctypes.byref(pref),
                                                   ctypes.sizeof(pref))
    except Exception:
        pass


class OptionalDateEdit(QDateEdit):
    """A date box that can also be empty ("No date")."""

    def __init__(self, parent: QWidget | None = None, empty_text: str = "No date"):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setMinimumDate(NONE_DATE)
        self.setSpecialValueText(empty_text)
        self.setDisplayFormat("MMM d, yyyy")
        self.setDate(NONE_DATE)
        self.setMinimumWidth(122)

    def iso(self) -> str:
        d = self.date()
        return "" if d == NONE_DATE else d.toString("yyyy-MM-dd")

    def set_iso(self, value: str) -> None:
        self.blockSignals(True)
        d = QDate.fromString(value, "yyyy-MM-dd") if value else NONE_DATE
        self.setDate(d if d.isValid() else NONE_DATE)
        self.blockSignals(False)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        # Open the calendar on today rather than on the "empty" year 2000.
        if self.date() == NONE_DATE:
            self.setDate(QDate.currentDate())
        super().mousePressEvent(e)


class ElideLabel(QLabel):
    """A one-line label that shortens itself with … when there's no room."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._refresh()

    def setFullText(self, text: str) -> None:
        self._full = text
        self._refresh()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._refresh()

    def minimumSizeHint(self) -> QSize:
        return QSize(24, super().minimumSizeHint().height())

    def _refresh(self) -> None:
        width = max(16, self.width())
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, width)
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


class ClickableWidget(QWidget):
    """Click to activate; with draggable=True a press-and-drag emits drag_started instead."""

    clicked = Signal()
    drag_started = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.draggable = False
        self._press: QPoint | None = None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        # Accept the press so the matching release comes back to this widget.
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
        e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if (self.draggable and self._press is not None and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            self._press = None
            self.drag_started.emit()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        pressed, self._press = self._press, None
        if (e.button() == Qt.MouseButton.LeftButton and pressed is not None
                and self.rect().contains(e.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class TitleBar(QWidget):
    """Drag to move, double-click to collapse into a pill.

    The main window uses Windows' own move (so it snaps to screen edges). List
    windows use a manual move so they can be dropped onto the main tab bar.
    """

    drag_moved = Signal(QPoint)      # global cursor position (manual mode)
    drag_released = Signal(QPoint)

    def __init__(self, title: str, leading: QWidget, parent: QWidget | None = None, manual: bool = False):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self.manual = manual
        self._press: QPoint | None = None
        self._dragging = False
        self._offset = QPoint()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(2)
        self.strip = QWidget()           # the list's colour, shown on pills
        self.strip.setFixedWidth(5)
        self.strip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.strip.hide()
        lay.addWidget(self.strip)
        lay.addSpacing(10)
        self.check = QCheckBox()         # tick the top item, on pills
        self.check.setToolTip("Tick off this item")
        self.check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check.hide()
        lay.addWidget(self.check)
        self.leading = leading
        lay.addWidget(leading)
        lay.addSpacing(8)
        self.name = ElideLabel(title)
        self.name.setObjectName("TitleName")
        lay.addWidget(self.name, 1)
        lay.addSpacing(6)
        self.extra = QLabel()
        self.extra.setObjectName("TitleExtra")
        lay.addWidget(self.extra)
        lay.addSpacing(4)
        self._lay = lay

    def add(self, w: QWidget) -> None:
        self._lay.addWidget(w)

    def begin_manual_drag(self, offset: QPoint) -> None:
        """Keep moving the window with the mouse (used when a tab is torn off)."""
        self._offset = offset
        self._dragging = True
        self.grabMouse()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        super().mousePressEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
            e.accept()   # keep the following move events coming here

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        gpos = e.globalPosition().toPoint()
        if self._dragging:
            self.window().move(gpos - self._offset)
            self.drag_moved.emit(gpos)
            e.accept()
            return
        if self._press is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            if (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
                if self.manual:
                    self._offset = gpos - self.window().pos()
                    self._dragging = True
                    self._press = None
                    self.drag_moved.emit(gpos)
                else:
                    self._press = None
                    handle = self.window().windowHandle()
                    if handle is not None:
                        handle.startSystemMove()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._press = None
        if self._dragging:
            self._dragging = False
            self.releaseMouse()
            self.drag_released.emit(e.globalPosition().toPoint())
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        win = self.window()
        if hasattr(win, "toggle_collapse"):
            win.toggle_collapse()


# Windows hit-test codes for resizing a frameless window from its edges.
_HT = {(True, False, False, False): 10, (False, True, False, False): 11,
       (False, False, True, False): 12, (True, False, True, False): 13,
       (False, True, True, False): 14, (False, False, False, True): 15,
       (True, False, False, True): 16, (False, True, False, True): 17}


WM_NCHITTEST, WM_NCLBUTTONDBLCLK = 0x0084, 0x00A3
SIDE_EDGES = {10, 11, 13, 14, 16, 17}       # left/right edges and corners


def win_message(event_type, message):
    """The Windows MSG behind a nativeEvent, or None."""
    if sys.platform != "win32":
        return None
    try:
        if bytes(event_type) != b"windows_generic_MSG":
            return None
        from ctypes import wintypes
        return wintypes.MSG.from_address(int(message))
    except Exception:
        return None


def edge_hit_test(widget: QWidget, event_type, message, margin: int = 6):
    """For nativeEvent: lets Windows resize a frameless window from any edge.
    Returns the hit-test code, or None to let Qt handle the event normally."""
    if sys.platform != "win32":
        return None
    try:
        if bytes(event_type) != b"windows_generic_MSG":
            return None
        import ctypes
        from ctypes import wintypes
        msg = wintypes.MSG.from_address(int(message))
        if msg.message != 0x0084:          # WM_NCHITTEST
            return None
        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(msg.hWnd, ctypes.byref(rect))
        m = max(4, int(margin * widget.devicePixelRatioF()))
        key = (x < rect.left + m, x >= rect.right - m, y < rect.top + m, y >= rect.bottom - m)
        return _HT.get(key)
    except Exception:
        return None
