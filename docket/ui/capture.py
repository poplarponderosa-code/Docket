"""Quick capture: a small box that opens anywhere with a shortcut (F16 by default).

Type an item the same way as in the add box, press Enter and it's filed. Tab picks the
list, #listname works too, and pasting several lines adds them all.
"""
from __future__ import annotations

import datetime as dt
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QToolButton, QVBoxLayout)

from .. import capture, dates, importer, links, system
from ..parser import parse_quick_add, take_link
from .icons import dot_icon, icon_button, make_icon
from .common import GrowEdit, round_corners

if TYPE_CHECKING:
    from ..app import DocketApp

PASTE_CONFIRM_OVER = 10


class CaptureEdit(GrowEdit):
    """The typing box: wraps and grows. Enter adds (Shift: keep the box open, Ctrl: other end of the list),
    Tab opens the list picker, Esc closes, and a multi-line paste is handed to the window."""

    def __init__(self, window: "CaptureWindow"):
        super().__init__(max_lines=4)
        self.win = window
        self.on_paste = window.paste
        self.submitted.connect(lambda mods: window.submit(
            keep_open=bool(mods & Qt.KeyboardModifier.ShiftModifier),
            flip=bool(mods & Qt.KeyboardModifier.ControlModifier)))

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.KeyPress and e.key() == Qt.Key.Key_Tab:
            self.win.pick_list()
            return True
        return super().event(e)

    def keyPressEvent(self, e) -> None:
        if self.win.pending is not None:
            # A question is showing ("Add 21 items?"): Enter or Y says yes, Esc or N says no.
            key = e.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Y):
                self.win.answer(True)
            elif key in (Qt.Key.Key_Escape, Qt.Key.Key_N):
                self.win.answer(False)
            e.accept()
            return
        if e.key() == Qt.Key.Key_Escape:
            self.win.cancel()
            return
        super().keyPressEvent(e)


class Toast(QLabel):
    """A short "Added to Inbox" note that fades away on its own."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setContentsMargins(14, 8, 14, 8)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(700)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InQuad)
        self._fade.finished.connect(self.hide)
        self._wait = QTimer(self)
        self._wait.setSingleShot(True)
        self._wait.timeout.connect(self._fade.start)

    def show_at(self, text: str, top_centre: QPoint) -> None:
        self._fade.stop()
        self.setText(text)
        self.adjustSize()
        self.move(top_centre - QPoint(self.width() // 2, 0))
        self.setWindowOpacity(1.0)
        self.show()
        self._wait.start(1100)


class CaptureWindow(QFrame):
    def __init__(self, app: "DocketApp"):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.app = app
        self.setObjectName("Capture")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(560)
        self.target_id: int | None = None       # chosen with Tab for this item; None = the default
        self.toast = Toast()

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 8)
        v.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.list_btn = QToolButton()
        self.list_btn.setObjectName("CaptureList")
        self.list_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.list_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.list_btn.setToolTip("Which list it goes to. Press Tab to choose, or type #listname.")
        self.list_btn.clicked.connect(self.pick_list)
        self.edit = CaptureEdit(self)
        self.edit.setPlaceholderText("Capture an item… try “call Sam fri 3pm !high”")
        self.edit.textChanged.connect(self._preview)
        self.mic = icon_button("mic", "Dictate with Windows voice typing (Win+H)", size=30)
        self.mic.clicked.connect(self._dictate)
        row.addWidget(self.list_btn)
        row.addWidget(self.edit, 1)
        row.addWidget(self.mic)
        v.addLayout(row)

        prev = QHBoxLayout()
        prev.setContentsMargins(4, 0, 0, 0)
        prev.setSpacing(6)
        self.link_icon = QLabel()
        self.link_icon.hide()
        self.preview = QLabel()
        self.preview.setObjectName("Hint")
        prev.addWidget(self.link_icon)
        prev.addWidget(self.preview, 1)
        v.addLayout(prev)
        # The question bar ("Add 21 items to Inbox?"), shown inside the window instead of a popup.
        self.pending = None
        self.ask_bar = QFrame()
        self.ask_bar.setObjectName("CaptureAsk")
        self.ask_bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        ask = QHBoxLayout(self.ask_bar)
        ask.setContentsMargins(12, 6, 6, 6)
        ask.setSpacing(6)
        self.ask_text = QLabel()
        self.ask_text.setObjectName("CaptureAskText")
        ask.addWidget(self.ask_text, 1)
        self.ask_yes = QPushButton("Yes")
        self.ask_yes.setProperty("primary", True)
        self.ask_yes.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ask_yes.clicked.connect(lambda: self.answer(True))
        ask.addWidget(self.ask_yes)
        self.ask_no = QPushButton("No")
        self.ask_no.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ask_no.clicked.connect(lambda: self.answer(False))
        ask.addWidget(self.ask_no)
        self.ask_bar.hide()
        v.addWidget(self.ask_bar)
        self._flashes = 0
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(180)
        self._flash_timer.timeout.connect(self._flash_step)
        self.keys = QLabel("Enter adds · Shift+Enter adds another · Ctrl+Enter adds to the other end · "
                           "Tab picks the list · Esc closes")
        self.keys.setWordWrap(True)
        self.keys.setObjectName("Hint")
        v.addWidget(self.keys)

    # ---- where things go -------------------------------------------------------------
    def default_target(self) -> int:
        s = self.app.settings
        if s.get("capture_target") == "last" and s.get("last_capture_tab") and \
                self.app.store.tab(s["last_capture_tab"]) is not None:
            return s["last_capture_tab"]
        if s.get("capture_target") == "list" and s.get("capture_list") and \
                self.app.store.tab(s["capture_list"]) is not None:
            return s["capture_list"]
        return self.app.inbox_id()

    def _target_for(self, text: str) -> tuple[str, int]:
        names = {t.name: t.id for t in self.app.store.tabs()}
        rest, name = capture.route(text, list(names))
        if name is not None:
            return rest, names[name]
        if self.target_id is not None and self.app.store.tab(self.target_id) is not None:
            return text, self.target_id
        return text, -1                        # -1: the default (Inbox is only made when used)

    def _resolve(self, tab_id: int) -> int:
        return self.default_target() if tab_id == -1 else tab_id

    def _target_name(self, tab_id: int) -> str:
        if tab_id == -1:
            s = self.app.settings
            if s.get("capture_target") in ("last", "list"):
                tid = self.default_target()
                tab = self.app.store.tab(tid)
                return tab.name if tab else capture.INBOX
            existing = self.app.find_inbox()
            return existing.name if existing else capture.INBOX
        tab = self.app.store.tab(tab_id)
        return tab.name if tab else capture.INBOX

    def _sync_list_btn(self, tab_id: int) -> None:
        tab = self.app.store.tab(tab_id) if tab_id != -1 else None
        from .. import themes
        color = themes.list_color(tab.color) if tab else themes.current["accent"]
        self.list_btn.setIcon(dot_icon(color, 9))
        self.list_btn.setText(self._target_name(tab_id) + " ▾")

    # ---- showing -------------------------------------------------------------------------
    def open(self) -> None:
        self.target_id = None
        self._clear_question()
        self.edit.clear()
        self._preview()
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        self.adjustSize()
        self.move(geo.center().x() - self.width() // 2, geo.top() + max(40, geo.height() // 9))
        self.show()
        round_corners(self)
        self.raise_()
        self.activateWindow()
        self.edit.setFocus(Qt.FocusReason.OtherFocusReason)
        if sys.platform == "win32":
            QTimer.singleShot(60, self._force_front)

    def _force_front(self) -> None:
        """Windows only lets the app in front take focus; a shortcut press counts, so ask now."""
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except Exception:
            pass
        self.activateWindow()
        self.edit.setFocus()

    def cancel(self) -> None:
        self.hide()

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and self.isVisible():
            if QApplication.activePopupWidget() is None and QApplication.activeModalWidget() is None:
                QTimer.singleShot(150, self._hide_if_away)

    def _hide_if_away(self) -> None:
        if self.isVisible() and not self.isActiveWindow() and QApplication.activePopupWidget() is None \
                and QApplication.activeModalWidget() is None:
            self.hide()

    def _toast(self, text: str) -> None:
        self.toast.show_at(text, QPoint(self.geometry().center().x(), self.geometry().top() + 6))

    # ---- list picker ---------------------------------------------------------------------
    def pick_list(self) -> None:
        menu = QMenu(self)
        from .. import themes
        current = self._target_for(self.edit.text())[1]
        default = menu.addAction(make_icon("plus", themes.current["muted"], 12),
                                 f"Default ({self._target_name(-1)})", lambda: self._chose(None))
        default.setCheckable(True)
        default.setChecked(current == -1)
        menu.addSeparator()
        for tab in self.app.store.tabs():
            act = menu.addAction(dot_icon(themes.list_color(tab.color), 9), tab.name,
                                 lambda tid=tab.id: self._chose(tid))
            act.setCheckable(True)
            act.setChecked(current == tab.id)
            if current == tab.id:
                menu.setActiveAction(act)
        if current == -1:
            menu.setActiveAction(default)
        menu.exec(self.list_btn.mapToGlobal(QPoint(0, self.list_btn.height() + 2)))
        self.activateWindow()
        self.edit.setFocus()

    def _chose(self, tab_id: int | None) -> None:
        self.target_id = tab_id
        self._preview()

    # ---- preview -------------------------------------------------------------------------
    def _preview(self) -> None:
        text = self.edit.text().strip()
        rest, tab_id = self._target_for(text)
        self._sync_list_btn(tab_id)
        if not rest:
            self.preview.setText("")
            self.link_icon.hide()
            return
        tab = self.app.store.tab(tab_id) if tab_id != -1 else None
        checklist = tab is not None and tab.is_checklist
        today = dt.date.today()
        if "|" in rest:
            it = importer.parse_line(rest, today, checklist=checklist) or {}
            name, link = it.get("name", rest), it.get("link", "")
            parts = [p for p in (f"category {it['category']}" if it.get("category") else "",
                                 dates.due_label(dates.from_iso(it["due"]), dates.from_iso(it.get("end", "")), today)
                                 if it.get("due") else "") if p]
        elif checklist:
            name, link = take_link(rest)
            parts = []
        else:
            q = parse_quick_add(rest, today)
            name, link, parts = q.name, q.link, []
            if q.due:
                parts.append(dates.range_label(q.due, q.end) if q.end else
                             dates.due_label(q.due, None, today).replace(" · late", ""))
            if q.priority:
                parts.append(f"{q.priority} priority")
            if q.remind_time:
                parts.append(f"reminder {dates.fmt_time(q.remind_time)}")
        from .. import themes
        if link:
            self.link_icon.setPixmap(make_icon(links.icon_name(link) or "globe", themes.current["accent"], 13)
                                     .pixmap(13, 13))
            self.link_icon.setToolTip(link)
        self.link_icon.setVisible(bool(link))
        self.preview.setText(f"Adds “{name or link}” to {self._target_name(tab_id)}"
                             + ("  ·  " + "  ·  ".join(parts) if parts else ""))

    # ---- adding ----------------------------------------------------------------------------
    def _add_one(self, text: str, tab_id: int, flip: bool = False) -> str | None:
        """Add one typed line to a list. Returns the list's name, or None if there was nothing."""
        text = text.strip()
        if not text:
            return None
        tid = self._resolve(tab_id)
        tab = self.app.store.tab(tid)
        if tab is None:
            return None
        top = self.app.new_items_on_top(flip)
        if self.app.add_typed(tid, text, top=top) is None:
            return None
        self.app.note_capture(tid)
        return tab.name

    def submit(self, keep_open: bool = False, flip: bool = False) -> None:
        text = self.edit.text().strip()
        if not text:
            if not keep_open:
                self.hide()
            return
        rest, tab_id = self._target_for(text)
        where = self._add_one(rest, tab_id, flip)
        self.edit.clear()
        if where is None:
            return
        if keep_open:
            self._toast(f"Added to {where}")
            self.edit.setFocus()
        else:
            geo = self.geometry()
            self.hide()
            self.toast.show_at(f"Added to {where}", QPoint(geo.center().x(), geo.top() + 6))

    def paste(self, text: str) -> None:
        text = capture.strip_fences(text)
        kind = capture.paste_kind(text)
        if kind == "one":
            self.edit.insertPlainText(" ".join(text.split()))
            return
        if kind == "list":
            made = self.app.paste_lists(text)
            if not made:
                return
            n = sum(len(self.app.store.items(t.id)) for t in made)
            self.hide()
            if len(made) > 1:
                note = f"Made {len(made)} lists with {n} item{'s' if n != 1 else ''}"
            else:
                note = f"Made “{made[0].name}” with {n} item{'s' if n != 1 else ''}" if made else ""
            self.toast.show_at(note,
                               QPoint(self.geometry().center().x(), self.geometry().top() + 6))
            return
        lines = capture.paste_lines(text)
        _, tab_id = self._target_for(self.edit.text().strip())     # #list typed before pasting, or Tab's pick
        where_name = self._target_name(tab_id)
        if len(lines) > PASTE_CONFIRM_OVER:
            self.ask(f"Add {len(lines)} items to {where_name}?", lines, tab_id)
            return
        self._add_pasted(lines, tab_id)

    # ---- the question bar ------------------------------------------------------------------------
    def ask(self, question: str, lines: list[str], tab_id: int) -> None:
        self.pending = (lines, tab_id)
        self.ask_text.setText(question + "   Enter = yes · Esc = no")
        self.ask_bar.show()
        self.adjustSize()
        self._flashes = 6
        self._flash_timer.start()
        self.activateWindow()
        self.edit.setFocus()

    def _flash_step(self) -> None:
        self._flashes -= 1
        on = self._flashes % 2 == 1
        self.ask_bar.setProperty("flash", on)
        self.ask_bar.style().unpolish(self.ask_bar)
        self.ask_bar.style().polish(self.ask_bar)
        if self._flashes <= 0:
            self._flash_timer.stop()

    def _clear_question(self) -> None:
        self.pending = None
        self._flash_timer.stop()
        self.ask_bar.setProperty("flash", False)
        self.ask_bar.hide()
        self.adjustSize()

    def answer(self, yes: bool) -> None:
        pending = self.pending
        self._clear_question()
        self.edit.setFocus()
        if yes and pending is not None:
            self._add_pasted(*pending)

    def _add_pasted(self, lines: list[str], tab_id: int) -> None:
        where = None
        if self.app.new_items_on_top():
            lines = list(reversed(lines))        # added one by one to the top: keep the pasted order
        for line in lines:
            rest, tid = self._target_for(line)
            if tid == -1:
                tid = tab_id
            where = self._add_one(rest, tid) or where
        n = len(lines)
        self.edit.clear()
        self._toast(f"Added {n} item{'s' if n != 1 else ''}" + (f" to {where}" if where else ""))
        self.edit.setFocus()

    def _dictate(self) -> None:
        self.activateWindow()
        self.edit.setFocus()
        QTimer.singleShot(120, system.start_voice_typing)
