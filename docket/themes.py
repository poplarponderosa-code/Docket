"""Colour palettes and the Qt stylesheet built from them."""
from __future__ import annotations

from pathlib import Path

PALETTES: dict[str, dict[str, str]] = {
    "light":    dict(name="Light",    bg="#E7E5E0", win="#F7F6F3", surface="#FFFFFF", text="#2B2A27", muted="#64615B",
                     border="#E3E0DA", accent="#3F6596", accentSoft="#E6EDF6", hover="#F3F1ED", warn="#B0412A"),
    "dark":     dict(name="Dark",     bg="#111214", win="#1D1E22", surface="#25272C", text="#E7E5E0", muted="#A5A29C",
                     border="#373A40", accent="#94B5E4", accentSoft="#2C3747", hover="#2C2E34", warn="#F0907A"),
    "sage":     dict(name="Sage",     bg="#DCE3D8", win="#EEF2EB", surface="#F9FBF7", text="#27302A", muted="#56635A",
                     border="#D3DCCF", accent="#46704F", accentSoft="#DCE8DA", hover="#F0F4EE", warn="#A33F2A"),
    "lavender": dict(name="Lavender", bg="#E1DDEB", win="#F1EFF6", surface="#FBFAFD", text="#2D2938", muted="#625B74",
                     border="#DCD6E7", accent="#634F98", accentSoft="#E7E1F4", hover="#F3F1F8", warn="#A8402F"),
    "sand":     dict(name="Sand",     bg="#E8DFD2", win="#F5EFE6", surface="#FDFAF5", text="#372E25", muted="#6E6152",
                     border="#E6DBCB", accent="#985A33", accentSoft="#F2E3D4", hover="#F7F1E8", warn="#A33B2A"),
}

PRIORITY_COLORS = ("#D0613B", "#D3A03C", "#7C9CC4")   # High, Med, Low

# Ten soft colours a list can wear: key -> (name, on light themes, on dark mode)
LIST_COLORS: dict[str, tuple[str, str, str]] = {
    "blue":     ("Blue",     "#5878A8", "#8FAEDB"),
    "teal":     ("Teal",     "#3D8783", "#79C1BC"),
    "sage":     ("Sage",     "#63905F", "#9CC497"),
    "olive":    ("Olive",    "#8A8A3E", "#C4C47A"),
    "amber":    ("Amber",    "#C08A2E", "#E5BC6E"),
    "peach":    ("Peach",    "#D07E52", "#EDA984"),
    "rose":     ("Rose",     "#C26571", "#E89AA4"),
    "plum":     ("Plum",     "#9A6896", "#C99BC5"),
    "lavender": ("Lavender", "#7D6FB0", "#ADA1DD"),
    "slate":    ("Slate",    "#6C7A89", "#A3B0BE"),
}
COLOR_ORDER = list(LIST_COLORS)

current: dict[str, str] = dict(PALETTES["light"])
check_image = ""        # path of the tick image used by checkboxes


def mix(a: str, b: str, amount: float) -> str:
    """Blend colour b into colour a by amount (0..1)."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02X}" for x, y in zip(ca, cb))


def tint(key: str, strength: float = 0.22) -> str:
    """A soft background in a list's colour, readable with the theme's text colour."""
    return mix(current["surface"], list_color(key), strength)


def list_color(key: str) -> str:
    """A list's colour for the current theme ("" = the theme's accent)."""
    entry = LIST_COLORS.get(key or "")
    if not entry:
        return current["accent"]
    return entry[2] if current.get("name") == "Dark" else entry[1]


def set_current(name: str) -> dict[str, str]:
    current.clear()
    current.update(PALETTES.get(name, PALETTES["light"]))
    return current


def _check_svg(folder: Path, p: dict[str, str]) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"check-{p['name'].lower()}.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
        f'<path d="M4 8.3l2.6 2.6L12 5.5" fill="none" stroke="{p["win"]}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
    return path.as_posix()


def stylesheet(p: dict[str, str], asset_dir: Path) -> str:
    global check_image
    check = _check_svg(asset_dir, p)
    check_image = check
    return f"""
* {{ outline: none; }}
QWidget {{ color: {p['text']}; }}
QToolTip {{ background: {p['text']}; color: {p['win']}; border: 0; padding: 4px 7px; border-radius: 4px; }}

#Window {{ background: {p['win']}; border: 1px solid {p['border']}; }}
#TitleBar {{ background: {p['win']}; }}
#TitleName {{ font-weight: 600; font-size: 13px; }}
#TitleExtra, #Muted, #Hint, #Footer QLabel {{ color: {p['muted']}; }}
#TitleExtra {{ font-size: 12px; }}
#TitleExtra[status="today"] {{ color: {p['accent']}; font-weight: 600; }}
#TitleExtra[status="overdue"] {{ color: {p['warn']}; font-weight: 600; }}
#PillList {{ background: {p['win']}; }}
#Hint {{ font-size: 11px; }}
#AttentionHint {{ color: {p['accent']}; font-size: 11px; font-weight: 600; }}
#Body, #ListContainer, #Popup, #Settings, #SettingsBody {{ background: {p['surface']}; }}
#TabRow {{ background: {p['win']}; border-bottom: 1px solid {p['border']}; }}
#TabRow[drop="true"] {{ background: {p['accentSoft']}; border-bottom: 2px solid {p['accent']}; }}
#Footer {{ background: {p['win']}; border-top: 1px solid {p['border']}; }}
#Footer QLabel {{ font-size: 11px; }}
#Section {{ color: {p['muted']}; font-size: 10px; font-weight: 600; padding-top: 6px; }}
#Empty {{ color: {p['muted']}; padding: 40px 20px; }}

QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {p['muted']}; padding: 6px 4px 6px 10px; margin-right: 2px;
    border: 1px solid transparent; border-top-left-radius: 7px; border-top-right-radius: 7px; min-width: 40px; }}
QTabBar::tab:hover {{ color: {p['text']}; }}
QTabBar::tab:selected {{ background: {p['surface']}; color: {p['text']}; border-color: {p['border']};
    border-bottom-color: {p['surface']}; font-weight: 600; }}
QTabBar QToolButton {{ background: {p['win']}; border: 0; }}

QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox, QPlainTextEdit {{
    background: {p['win']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 6px;
    padding: 4px 8px; min-height: 20px;
    selection-background-color: {p['accentSoft']}; selection-color: {p['text']}; }}
#Row QLineEdit, #Row QPlainTextEdit, #Row QDateEdit, #Popup QDateEdit {{ background: {p['surface']}; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border-color: {p['accent']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: 0; width: 18px; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
    selection-background-color: {p['accentSoft']}; selection-color: {p['text']}; outline: 0; }}

QPushButton {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
    border-radius: 6px; padding: 5px 10px; }}
QPushButton:hover {{ background: {p['hover']}; }}
QPushButton[on="true"] {{ background: {p['accentSoft']}; color: {p['accent']}; border-color: {p['accent']}; font-weight: 600; }}
QPushButton[primary="true"] {{ background: {p['accent']}; color: {p['win']}; border-color: {p['accent']}; font-weight: 600; }}
QPushButton[flat="true"], #HeaderBtn, #Pri, #LinkBtn {{ background: transparent; border: 0; padding: 0; text-align: left; }}
#HeaderBtn {{ color: {p['muted']}; font-size: 10px; font-weight: 600; }}
#HeaderBtn[active="true"] {{ color: {p['accent']}; }}
#LinkBtn {{ color: {p['accent']}; font-size: 11px; }}
#Pri {{ font-size: 12px; }}

QToolButton[iconBtn="true"] {{ background: transparent; border: 0; border-radius: 6px; padding: 0; }}
QToolButton[iconBtn="true"]:hover {{ background: {p['hover']}; }}
QToolButton[iconBtn="true"]:checked {{ background: {p['accentSoft']}; }}
QToolButton[primary="true"] {{ background: {p['accent']}; }}
QToolButton[primary="true"]:hover {{ background: {p['accent']}; }}
QToolButton[swatch="true"] {{ background: transparent; border: 2px solid transparent; border-radius: 8px;
    padding: 4px; color: {p['muted']}; font-size: 11px; }}
QToolButton[swatch="true"]:checked {{ border-color: {p['accent']}; color: {p['text']}; }}

#Header {{ background: {p['surface']}; border-bottom: 1px solid {p['border']}; }}
#Row {{ background: transparent; border-bottom: 1px solid {p['border']}; }}
#Row:hover, #Row[expanded="true"] {{ background: {p['hover']}; }}
#Due {{ color: {p['muted']}; font-size: 12px; }}
#Due[status="today"] {{ color: {p['accent']}; font-weight: 600; }}
#Due[status="overdue"] {{ color: {p['warn']}; font-weight: 600; }}
#Name[done="true"] {{ color: {p['muted']}; text-decoration: line-through; }}
#FieldLabel {{ color: {p['muted']}; font-size: 11px; }}
#HeaderLabel {{ color: {p['muted']}; font-size: 10px; font-weight: 600; }}
#DropLine {{ background: {p['accent']}; border-radius: 1px; }}
#TimeCell, #TotalBtn {{ color: {p['muted']}; font-size: 12px; }}
#TotalBtn {{ background: transparent; border: 0; padding: 0; text-align: right; font-weight: 600; }}
#TimeCell[status="running"], #TotalBtn[status="running"] {{ color: {p['accent']}; font-weight: 600; }}
#TimeCell[status="over"], #TotalBtn[status="over"] {{ color: {p['warn']}; font-weight: 600; }}
#TimeCell[status="done"] {{ color: {p['muted']}; }}
#InfoBox {{ background: {p['accentSoft']}; border-radius: 8px; }}
#CategoryCell {{ color: {p['muted']}; font-size: 12px; }}
QToolButton#LogoBtn {{ background: transparent; border: 0; border-radius: 6px; padding: 3px; }}
QToolButton#LogoBtn:hover {{ background: {p['hover']}; }}
QToolButton#LogoBtn::menu-indicator {{ image: none; width: 0px; }}
#InfoBox QLabel {{ color: {p['text']}; font-size: 12px; }}
QKeySequenceEdit QLineEdit {{ background: {p['win']}; }}
#CategoryCell:hover {{ color: {p['text']}; }}
#TimeCell:hover {{ text-decoration: underline; }}
QTabWidget#SettingsTabs::pane {{ border: 0; border-top: 1px solid {p['border']}; }}
QTabWidget#SettingsTabs QTabBar::tab {{ padding: 6px 12px; margin: 0 2px; border: 0; color: {p['muted']};
    background: transparent; }}
QTabWidget#SettingsTabs QTabBar::tab:selected {{ color: {p['text']}; border-bottom: 2px solid {p['accent']}; }}
QTabWidget#SettingsTabs QTabBar::tab:hover {{ color: {p['text']}; }}
#SetupTitle {{ font-size: 17px; font-weight: 600; padding-bottom: 4px; }}
#ModeCard {{ background: {p['win']}; border: 1px solid {p['border']}; border-radius: 10px; }}
#ModeCard[on="true"] {{ border: 2px solid {p['accent']}; background: {p['accentSoft']}; }}
#ModeRadio {{ font-weight: 600; }}
#CompanionChip {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; }}
#Capture {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; }}
#Capture QLineEdit {{ font-size: 15px; padding: 6px 8px; }}
QToolButton#CaptureList {{ border: 1px solid {p['border']}; border-radius: 8px; padding: 5px 8px;
    background: {p['win']}; color: {p['text']}; }}
QToolButton#CaptureList:hover {{ background: {p['hover']}; }}
#TourCard {{ background: {p['surface']}; border: 1px solid {p['accent']}; border-radius: 12px; }}
#TourCount {{ color: {p['muted']}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
#TourTitle {{ color: {p['text']}; font-size: 14px; font-weight: 600; }}
#TourText {{ color: {p['text']}; font-size: 12px; }}
QPushButton#TourLink {{ border: 0; background: transparent; color: {p['muted']}; padding: 4px 2px; }}
QPushButton#TourLink:hover {{ color: {p['text']}; text-decoration: underline; }}
#Toast {{ background: {p['text']}; color: {p['surface']}; border-radius: 10px; font-size: 13px; }}
QToolButton[iconBtn="true"]::menu-button {{ border: 0; width: 12px; }}
QToolButton[iconBtn="true"]::menu-arrow {{ width: 8px; height: 8px; }}

QCheckBox {{ spacing: 8px; }}
#Row QCheckBox {{ spacing: 0px; padding: 0px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 3px; border: 1px solid {p['muted']};
    background: {p['surface']}; }}
QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url("{check}"); }}

QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

#Popup {{ border: 1px solid {p['border']}; border-radius: 10px; }}
QMenu {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {p['accentSoft']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 4px 6px; }}

QCalendarWidget QWidget {{ alternate-background-color: {p['hover']}; }}
QCalendarWidget QAbstractItemView {{ background: {p['surface']}; color: {p['text']};
    selection-background-color: {p['accent']}; selection-color: {p['win']}; outline: 0; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {p['muted']}; }}
#qt_calendar_navigationbar {{ background: {p['win']}; }}
QCalendarWidget QToolButton {{ color: {p['text']}; background: transparent; border: 0; padding: 4px 8px; }}
QCalendarWidget QSpinBox {{ background: {p['surface']}; }}

QListWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 2px; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {p['accentSoft']}; color: {p['text']}; }}
QDialog {{ background: {p['surface']}; }}
QMessageBox {{ background: {p['surface']}; }}
"""
