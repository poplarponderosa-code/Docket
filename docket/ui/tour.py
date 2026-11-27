"""The tour and tips on screen: a small card next to the part of the window it talks about, with an
outline around that part. One-time tips use the same card with a "Got it" button."""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import themes, tour
from .common import round_corners

if TYPE_CHECKING:
    from ..app import DocketApp

CARD_W = 360
GAP = 10


class Highlight(QWidget):
    """A rounded outline around the part of the window a step is about. Clicks go straight through."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def cover(self, rect: QRect) -> None:
        self.setGeometry(rect.adjusted(-5, -5, 5, 5))
        self.show()
        self.raise_()
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(themes.current.get("accent", "#3b82f6")))
        pen.setWidth(3)
        p.setPen(pen)
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 8, 8)
        p.end()


class Card(QFrame):
    """The card: a step count, a title, the text and buttons."""

    def __init__(self, on_escape: Callable[[], None]):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.on_escape = on_escape
        self.setObjectName("TourCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(CARD_W)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)
        self.count = QLabel()
        self.count.setObjectName("TourCount")
        v.addWidget(self.count)
        self.title = QLabel()
        self.title.setObjectName("TourTitle")
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        self.text = QLabel()
        self.text.setObjectName("TourText")
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        v.addWidget(self.text)
        self.moved_by_user = False
        self._drag_from = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("Drag to move")
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(6)
        v.addSpacing(4)
        v.addLayout(self.buttons)

    def set_buttons(self, left: list[QPushButton], right: list[QPushButton]) -> None:
        while self.buttons.count():
            item = self.buttons.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.hide()
                w.deleteLater()
        for b in left:
            self.buttons.addWidget(b)
        self.buttons.addStretch(1)
        for b in right:
            self.buttons.addWidget(b)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.on_escape()
            return
        super().keyPressEvent(e)

    # Drag the card anywhere by its background (e.g. off a pill it's covering).
    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_from = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.moved_by_user = True
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:
        start = getattr(self, "_drag_from", None)
        if start is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - start)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:
        self._drag_from = None
        super().mouseReleaseEvent(e)

    def fit_height(self) -> int:
        """Height that shows every line of the wrapped text, including letters like g and y."""
        for lbl in (self.count, self.title, self.text):
            lbl.ensurePolished()
        self.ensurePolished()
        lay = self.layout()
        lay.activate()
        h = lay.totalHeightForWidth(CARD_W) if lay.hasHeightForWidth() else lay.sizeHint().height()
        h = max(int(h), self.sizeHint().height()) + 6
        self.setFixedHeight(h)
        return h

    def place_near(self, target: QRect | None, fallback: QRect) -> None:
        """Below the target if there's room, otherwise above, beside, or in the middle of fallback."""
        w, h = CARD_W, self.fit_height()
        anchor = target if target is not None else fallback
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        if target is None:
            pos = QPoint(fallback.center().x() - w // 2, fallback.center().y() - h // 2)
        elif target.bottom() + GAP + h <= area.bottom():
            pos = QPoint(target.center().x() - w // 2, target.bottom() + GAP)
        elif target.top() - GAP - h >= area.top():
            pos = QPoint(target.center().x() - w // 2, target.top() - GAP - h)
        elif target.right() + GAP + w <= area.right():
            pos = QPoint(target.right() + GAP, target.center().y() - h // 2)
        else:
            pos = QPoint(target.left() - GAP - w, target.center().y() - h // 2)
        x = max(area.left() + 4, min(pos.x(), area.right() - w - 4))
        y = max(area.top() + 4, min(pos.y(), area.bottom() - h - 4))
        self.move(x, y)


def _button(text: str, primary: bool = False, flat: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", True)
    if flat:
        b.setObjectName("TourLink")
        b.setFlat(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class Tour:
    """Runs a list of tour.Step on screen. Finishing or skipping calls on_end(finished)."""

    def __init__(self, app: "DocketApp", steps: list[tour.Step], on_end: Callable[[bool], None] | None = None):
        self.app = app
        self.steps = steps
        self.on_end = on_end
        self.index = 0
        self.card = Card(lambda: self.stop(False))
        self.highlight = Highlight()
        self._ended = False
        # The window can change under the tour (shrunk to a pill, moved, resized): keep the outline on
        # its target, or hide it when the target isn't showing.
        self._follow = QTimer(self.card)
        self._follow.setInterval(250)
        self._follow.timeout.connect(self._follow_target)

    # ---- targets ------------------------------------------------------------------------------
    def _target(self, name: str) -> QWidget | None:
        main = self.app.main
        page = main.current_page() if hasattr(main, "current_page") else None
        widget = {
            "tabs": getattr(main, "tabs", None),
            "add_tab": getattr(main, "add_tab_btn", None),
            "collapse": getattr(main, "collapse_btn", None),
            "settings": getattr(main, "settings_btn", None),
            "logo": getattr(main, "logo", None),
            "input": getattr(page, "input", None) if page is not None else None,
            "list": getattr(page, "scroll", None) if page is not None else None,
        }.get(name)
        if widget is None or not widget.isVisible() or widget.width() < 4:
            return None
        return widget

    @staticmethod
    def _global_rect(w: QWidget) -> QRect:
        return QRect(w.mapToGlobal(QPoint(0, 0)), w.size())

    # ---- running ------------------------------------------------------------------------------
    def start(self) -> None:
        main = self.app.main
        self.app.show_main()
        if getattr(main, "collapsed", False):
            main.toggle_collapse()
        QTimer.singleShot(150, self.show_step)

    def _expand_main(self) -> bool:
        """Bring the main window back from a pill (the tour points at its buttons). True if it changed."""
        main = self.app.main
        if getattr(main, "collapsed", False):
            main.toggle_collapse()
            return True
        return False

    def _follow_target(self) -> None:
        if self._ended or not self.steps:
            return
        step = self.steps[self.index]
        target = self._target(step.target) if step.target else None
        if target is None or getattr(self.app.main, "collapsed", False):
            self.highlight.hide()
            return
        rect = self._global_rect(target).adjusted(-5, -5, 5, 5)
        if self.highlight.geometry() != rect or not self.highlight.isVisible():
            self.highlight.cover(self._global_rect(target))

    def show_step(self) -> None:
        if self._ended or not self.steps:
            return
        if self._expand_main():
            QTimer.singleShot(200, self.show_step)
            return
        step = self.steps[self.index]
        last = self.index == len(self.steps) - 1
        self.card.count.setText(f"{self.index + 1} of {len(self.steps)}")
        self.card.title.setText(step.title)
        self.card.text.setText(step.text)
        left = []
        if not last:
            skip = _button("Skip tour", flat=True)
            skip.clicked.connect(lambda: self.stop(False))
            left.append(skip)
        right = []
        if self.index > 0:
            back = _button("Back")
            back.clicked.connect(self.back)
            right.append(back)
        nxt = _button("Finish" if last else "Next", primary=True)
        nxt.clicked.connect(self.next)
        right.append(nxt)
        self.card.set_buttons(left, right)
        target = self._target(step.target) if step.target else None
        if target is not None:
            rect = self._global_rect(target)
            self.highlight.cover(rect)
        else:
            rect = None
            self.highlight.hide()
        self.card.place_near(rect, self._global_rect(self.app.main))
        self.card.show()
        round_corners(self.card)
        self.card.raise_()
        self.card.activateWindow()
        nxt.setFocus()
        self._follow.start()

    def next(self) -> None:
        if self.index >= len(self.steps) - 1:
            self.stop(True)
            return
        self.index += 1
        self.show_step()

    def back(self) -> None:
        if self.index > 0:
            self.index -= 1
            self.show_step()

    def stop(self, finished: bool) -> None:
        if self._ended:
            return
        self._ended = True
        self._follow.stop()
        self.card.hide()
        self.highlight.hide()
        self.card.deleteLater()
        self.highlight.deleteLater()
        if self.on_end is not None:
            self.on_end(finished)


class Invite:
    """A one-card question: "Take the tour?" with two buttons."""

    def __init__(self, app: "DocketApp", title: str, text: str, yes: str, no: str,
                 on_answer: Callable[[bool], None]):
        self.app = app
        self.on_answer = on_answer
        self._done = False
        self.card = Card(lambda: self.answer(False))
        self.card.count.hide()
        self.card.title.setText(title)
        self.card.text.setText(text)
        no_btn = _button(no)
        no_btn.clicked.connect(lambda: self.answer(False))
        yes_btn = _button(yes, primary=True)
        yes_btn.clicked.connect(lambda: self.answer(True))
        self.card.set_buttons([], [no_btn, yes_btn])

    def show(self) -> None:
        main = self.app.main
        target = QRect(main.mapToGlobal(QPoint(0, 0)), main.size()) if main.isVisible() else None
        fallback = target or (QGuiApplication.primaryScreen().availableGeometry()
                              if QGuiApplication.primaryScreen() is not None else QRect(0, 0, 1280, 800))
        self.card.place_near(target, fallback)
        self.card.show()
        round_corners(self.card)
        self.card.raise_()

    def answer(self, yes: bool) -> None:
        if self._done:
            return
        self._done = True
        self.card.hide()
        self.card.deleteLater()
        self.on_answer(yes)


class Tip:
    """A one-time tip next to a widget: "Got it" closes it; "Turn off tips" stops them for good."""

    def __init__(self, app: "DocketApp", key: str, anchor: QWidget | None):
        self.app = app
        self.key = key
        title, text = tour.TIPS[key]
        self.card = Card(self.close)
        self.card.count.setText("TIP")
        self.card.title.setText(title)
        self.card.text.setText(text)
        off = _button("Turn off tips", flat=True)
        off.clicked.connect(self.turn_off)
        ok = _button("Got it", primary=True)
        ok.clicked.connect(self.close)
        self.card.set_buttons([off], [ok])
        self.anchor = anchor
        self._closed = False
        self._timeout = QTimer(self.card)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(20_000)
        self._timeout.timeout.connect(self.close)

    def show(self) -> None:
        a = self.anchor
        if a is None or not a.isVisible():
            self.close()
            return
        rect = QRect(a.mapToGlobal(QPoint(0, 0)), a.size())
        self.card.place_near(rect, rect)
        self.card.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.card.show()
        round_corners(self.card)
        self.card.raise_()
        self._timeout.start()

    def turn_off(self) -> None:
        self.app.set_setting("tips_on", False)
        self.app.flash("Tips are off. Turn them back on in Settings > General.")
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.card.hide()
        self.card.deleteLater()
        if self.app.active_tip is self:
            self.app.active_tip = None
