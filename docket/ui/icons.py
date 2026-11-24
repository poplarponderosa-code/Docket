"""Small stroke icons drawn from SVG, recoloured to match the theme."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QToolButton, QWidget

from .. import themes

PATHS = {
    "minimize": '<path d="M4 8.5h8"/>',
    "close": '<path d="M4.5 4.5l7 7M11.5 4.5l-7 7"/>',
    "sliders": '<path d="M2.5 5h6M11.5 5h2M2.5 11h2M7.5 11h6"/><circle cx="10" cy="5" r="1.5"/><circle cx="6" cy="11" r="1.5"/>',
    "pin": '<path d="M6 2.5h4l-.5 4 2 2v1h-7v-1l2-2z"/><path d="M8 9.5v4"/>',
    "pin_fill": '<path d="M6 2.5h4l-.5 4 2 2v1h-7v-1l2-2z" fill="currentFill"/><path d="M8 9.5v4"/>',
    "play": '<path d="M5.5 3.5v9l7-4.5z" fill="currentFill"/>',
    "pause": '<path d="M5.5 3.5v9M10.5 3.5v9" stroke-width="2.2"/>',
    "info": '<circle cx="8" cy="8" r="6"/><path d="M8 7.3v3.9M8 5v.2"/>',
    "stopwatch": '<circle cx="8" cy="9" r="5"/><path d="M8 9V6.5M6.5 2.5h3M12.2 4.8l.9-.9"/>',
    "ledger": '<path d="M4 2.5h5.5L12 5v8.5H4z"/><path d="M9.5 2.5V5H12M6 8h4M6 10.5h4"/>',
    "tag": '<path d="M2.5 8.2V3h5.2l5.8 5.8-5.2 5.2z"/><circle cx="5.3" cy="5.8" r=".9"/>',
    "grip": '<circle cx="6" cy="4" r=".9"/><circle cx="10" cy="4" r=".9"/><circle cx="6" cy="8" r=".9"/>'
            '<circle cx="10" cy="8" r=".9"/><circle cx="6" cy="12" r=".9"/><circle cx="10" cy="12" r=".9"/>',
    "moon": '<path d="M12.5 9.5A5 5 0 0 1 6.5 3.5a5 5 0 1 0 6 6z"/>',
    "sun": '<circle cx="8" cy="8" r="3"/><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1"/>',
    "plus": '<path d="M8 3.5v9M3.5 8h9"/>',
    "chevron_down": '<path d="M4.5 6.5L8 10l3.5-3.5"/>',
    "chevron_up": '<path d="M4.5 10L8 6.5l3.5 3.5"/>',
    "popout": '<path d="M9.5 3H13v3.5M13 3L8 8M11 9.5V13H3V5h3.5"/>',
    "dock": '<path d="M3 3h10v10H3zM3 6h10"/>',
    "bell": '<path d="M4.5 11V7.5a3.5 3.5 0 0 1 7 0V11l1 1.5h-9z"/><path d="M6.8 14h2.4"/>',
    "notes": '<path d="M3.5 4.5h9M3.5 8h9M3.5 11.5h5"/>',
    "trash": '<path d="M3.5 4.5h9M6.5 4.5V3h3v1.5M5 4.5l.5 8.5h5l.5-8.5"/>',
    "calendar": '<path d="M3 4h10v9H3zM3 7h10M6 2.5v3M10 2.5v3"/>',
    "globe": '<circle cx="8" cy="8" r="5.5"/><path d="M2.5 8h11M8 2.5c-2 2.2-2 8.8 0 11M8 2.5c2 2.2 2 8.8 0 11"/>',
    "folder": '<path d="M2.5 4.5h4l1.2 1.5h5.8v6.5h-11z"/>',
    "file": '<path d="M4.5 2.5h4.5l2.5 2.5v8.5h-7z"/><path d="M9 2.5V5h2.5"/>',
    "mic": '<rect x="6" y="2.5" width="4" height="7" rx="2"/><path d="M4 8a4 4 0 0 0 8 0M8 12v1.8"/>',
    "reset": '<path d="M3.5 8a4.5 4.5 0 1 0 1.4-3.3"/><path d="M3.5 2.8v2.4h2.4"/>',
}


def make_icon(name: str, color: str, size: int = 16, stroke: float = 1.5) -> QIcon:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" '
           f'fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
           f'stroke-linejoin="round">{PATHS[name].replace("currentFill", color)}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    icon = QIcon()
    for scale in (1, 2, 3):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def dot_icon(color: str, size: int = 8) -> QIcon:
    icon = QIcon()
    for scale in (1, 2, 3):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(0, 0, size * scale, size * scale)
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def swatch_icon(left: str, right: str, w: int = 40, h: int = 26) -> QIcon:
    icon = QIcon()
    for scale in (1, 2):
        pm = QPixmap(w * scale, h * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w * scale, h * scale), 6 * scale, 6 * scale)
        p.setClipPath(path)
        p.fillRect(0, 0, int(w * scale * 2 / 3), h * scale, QColor(left))
        p.fillRect(int(w * scale * 2 / 3), 0, w * scale, h * scale, QColor(right))
        p.setClipping(False)
        p.setPen(QColor(0, 0, 0, 40))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def logo_path(size: float) -> QPainterPath:
    """A 'D': square on the left, curved on the right."""
    S = float(size)
    r = S * 0.18
    path = QPainterPath()
    path.moveTo(r, 0)
    path.lineTo(S * 0.42, 0)
    path.arcTo(QRectF(S * 0.42 - S * 0.58, 0, S * 1.16, S), 90, -180)
    path.lineTo(r, S)
    path.arcTo(QRectF(0, S - 2 * r, 2 * r, 2 * r), 270, -90)
    path.lineTo(0, r)
    path.arcTo(QRectF(0, 0, 2 * r, 2 * r), 180, -90)
    path.closeSubpath()
    return path


def app_icon(accent: str, background: str = "#FFFFFF") -> QIcon:
    """The Docket mark: a D with three list lines, in the theme's accent colour."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent))
        p.drawPath(logo_path(size))
        p.setBrush(QColor(background))
        bar_h = max(1.5, size * 0.11)
        for i, width in enumerate((0.5, 0.5, 0.32)):
            y = size * (0.26 + i * 0.21)
            p.drawRoundedRect(QRectF(size * 0.2, y, size * width, bar_h), bar_h / 2, bar_h / 2)
        p.end()
        icon.addPixmap(pm)
    return icon


def tinted_checkbox_qss(color: str, size: int = 13) -> str:
    """Stylesheet for a checkbox drawn in a list's colour (used on pills)."""
    surface = themes.current["surface"]
    return (f"QCheckBox {{ spacing: 0px; }}"
            f"QCheckBox::indicator {{ width: {size}px; height: {size}px; border-radius: 3px;"
            f" border: 1.5px solid {color}; background: {surface}; }}"
            f"QCheckBox::indicator:checked {{ background: {color}; image: url(\"{themes.check_image}\"); }}")


# ---- themed icon buttons -----------------------------------------------------

def icon_button(name: str, tooltip: str, role: str = "muted", size: int = 30,
                checkable: bool = False) -> QToolButton:
    b = QToolButton()
    b.setProperty("iconBtn", True)
    b.setProperty("iconName", name)
    b.setProperty("iconRole", role)
    b.setToolTip(tooltip)
    b.setAccessibleName(tooltip)
    b.setFixedSize(size, size)
    b.setIconSize(QSize(16, 16) if size >= 26 else QSize(13, 13))
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    apply_icon(b)
    return b


def set_icon_name(b: QAbstractButton, name: str) -> None:
    b.setProperty("iconName", name)
    apply_icon(b)


def apply_icon(b: QAbstractButton) -> None:
    name = b.property("iconName")
    if not name:
        return
    role = b.property("iconRole") or "muted"
    if name == "pin" and b.isCheckable() and b.isChecked():
        name, role = "pin_fill", "accent"          # a filled pin means "on top"
    color = themes.current.get(role, themes.current["muted"])
    b.setIcon(make_icon(name, color))


def refresh_icons(root: QWidget) -> None:
    for b in root.findChildren(QAbstractButton):
        apply_icon(b)
