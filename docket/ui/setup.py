"""First run: choose Basic, Advanced or Pro, then a few essentials (and companion apps).

People upgrading from 1.2.x only see the mode question, with Pro picked for them, plus a
"Review settings" button that opens the second page.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QProgressDialog, QPushButton, QRadioButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import companions, modes, updates
from .common import set_prop
from .icons import icon_button

if TYPE_CHECKING:
    from ..app import DocketApp


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


class CompanionChip(QFrame):
    """A companion app under a mode: its name and an ⓘ with what it does."""

    def __init__(self, comp: companions.Companion, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("CompanionChip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 2, 2, 2)
        h.setSpacing(2)
        icon = QLabel()
        from .icons import make_icon
        from .. import themes
        icon.setPixmap(make_icon("ledger" if comp.key == "ledger" else "plus", themes.current["accent"], 13)
                       .pixmap(13, 13))
        h.addWidget(icon)
        h.addWidget(QLabel(comp.full_name))
        info = icon_button("info", f"What {comp.name} does", size=22)
        info.clicked.connect(lambda: self._info(comp))
        h.addWidget(info)

    def _info(self, comp: companions.Companion) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(comp.full_name)
        box.setText(f"<b>{comp.full_name}</b><br>{comp.description}")
        box.setInformativeText("\n".join(f"• {f}" for f in comp.features)
                               + "\n\nA separate free app. Install it from the next page or any time later.")
        box.exec()


class SetupDialog(QDialog):
    def __init__(self, app: "DocketApp", upgrading: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.app = app
        self.upgrading = upgrading
        self.setObjectName("Settings")
        self.setWindowTitle("Welcome to Docket")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(560, 620)
        self.available: dict[str, dict] = {}      # companion key -> its latest release
        self.install_rows: dict[str, tuple[QWidget, QPushButton, QLabel]] = {}
        self.mode_chips: dict[str, QWidget] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 16)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.stack.addWidget(self._mode_page())
        self.stack.addWidget(self._setup_page())

        bottom = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(lambda: self._go(0))
        self.review_btn = QPushButton("Review settings")
        self.review_btn.setToolTip("Check your backup folder and other essentials")
        self.review_btn.clicked.connect(lambda: self._go(1))
        self.next_btn = QPushButton("Next")
        self.next_btn.setProperty("primary", True)
        self.next_btn.clicked.connect(self._next)
        bottom.addWidget(self.back_btn)
        bottom.addWidget(self.review_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.next_btn)
        outer.addLayout(bottom)
        self._go(0)

        self._installed_timer = QTimer(self)
        self._installed_timer.setInterval(3000)
        self._installed_timer.timeout.connect(self._sync_installed)
        self._installed_timer.start()
        QTimer.singleShot(0, self._check_companions)

    # ---- page 1: the mode ---------------------------------------------------------------
    def _mode_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        title = QLabel("How would you like to use Docket?")
        title.setObjectName("SetupTitle")
        v.addWidget(title)
        self.mode_group = QButtonGroup(self)
        start = self.app.settings.get("mode") or "pro"
        if not self.upgrading and not self.app.settings.get("mode"):
            start = "basic"
        self._mode = start
        for mode in modes.MODES:
            tagline, features = modes.SUMMARIES[mode]
            card = QFrame()
            card.setObjectName("ModeCard")
            card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            cv = QVBoxLayout(card)
            cv.setContentsMargins(14, 10, 14, 10)
            cv.setSpacing(3)
            radio = QRadioButton(f"{modes.LABELS[mode]}  —  {tagline}")
            radio.setObjectName("ModeRadio")
            radio.setChecked(mode == start)
            radio.toggled.connect(lambda on, m=mode, c=card: self._picked(m, on, c))
            card.setProperty("on", mode == start)
            self.mode_group.addButton(radio)
            radio.setProperty("mode", mode)
            cv.addWidget(radio)
            cv.addWidget(_hint(" · ".join(features)))
            chips = QWidget()
            ch = QHBoxLayout(chips)
            ch.setContentsMargins(22, 2, 0, 0)
            ch.setSpacing(6)
            lab = QLabel("Companion apps:")
            lab.setObjectName("FieldLabel")
            ch.addWidget(lab)
            for comp in companions.suits_exactly(mode):
                chip = CompanionChip(comp, chips)
                chip.setProperty("key", comp.key)
                chip.hide()                       # shown once its release is found
                ch.addWidget(chip)
            ch.addStretch(1)
            chips.hide()
            self.mode_chips[mode] = chips
            cv.addWidget(chips)
            card.mousePressEvent = lambda e, r=radio: r.setChecked(True)
            v.addWidget(card)
        free = QLabel("All modes are free, and you can switch any time in Settings. Switching never loses anything.")
        free.setObjectName("FieldLabel")
        free.setWordWrap(True)
        v.addWidget(free)
        if self.upgrading:
            v.addWidget(_hint("Your lists, folders and settings carried over from your last version. "
                              "Pro keeps everything you're used to."))
        v.addStretch(1)
        return page

    def _picked(self, mode: str, on: bool, card: QWidget) -> None:
        set_prop(card, "on", on)
        if on:
            self._mode = mode

    def chosen_mode(self) -> str:
        return self._mode

    # ---- page 2: essentials and companion apps --------------------------------------------------
    def _setup_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        title = QLabel("A few essentials")
        title.setObjectName("SetupTitle")
        v.addWidget(title)
        v.addWidget(_hint("Everything here is already filled in. Change what you like, or just click Done."))

        sec = QLabel("BACKUP FOLDER")
        sec.setObjectName("Section")
        v.addWidget(sec)
        v.addWidget(_hint("Docket keeps a plain-text copy of your lists here. Pick a folder inside OneDrive or "
                          "Google Drive to keep it safe on another PC too."))
        row = QHBoxLayout()
        self.backup_edit = QLineEdit(str(self.app.backup_dir()))
        row.addWidget(self.backup_edit, 1)
        b = QPushButton("Change…")
        b.clicked.connect(lambda: self._pick(self.backup_edit, "Choose a backup folder"))
        row.addWidget(b)
        v.addLayout(row)

        self.logs_box = QWidget()
        lv = QVBoxLayout(self.logs_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        sec = QLabel("TIME LOGS FOLDER")
        sec.setObjectName("Section")
        lv.addWidget(sec)
        lv.addWidget(_hint("Where checklist time logs are saved. Ledger finds them here by itself."))
        row = QHBoxLayout()
        self.logs_edit = QLineEdit(str(self.app.timelog_dir()))
        self.logs_edit.setPlaceholderText("Inside the backup folder")
        row.addWidget(self.logs_edit, 1)
        b = QPushButton("Change…")
        b.clicked.connect(lambda: self._pick(self.logs_edit, "Choose a folder for time logs"))
        row.addWidget(b)
        lv.addLayout(row)
        v.addWidget(self.logs_box)

        sec = QLabel("GENERAL")
        sec.setObjectName("Section")
        v.addWidget(sec)
        self.startup_box = QCheckBox("Launch Docket when Windows starts")
        self.startup_box.setChecked(bool(self.app.settings["startup"]))
        v.addWidget(self.startup_box)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme"))
        self.light_btn = QRadioButton("Light")
        self.dark_btn = QRadioButton("Dark")
        (self.dark_btn if self.app.settings["theme"] == "dark" else self.light_btn).setChecked(True)
        self.dark_btn.toggled.connect(lambda on: self.app.set_setting(
            "theme", "dark" if on else self.app.store.get_setting("last_light_theme", "light")))
        theme_row.addWidget(self.light_btn)
        theme_row.addWidget(self.dark_btn)
        theme_row.addStretch(1)
        v.addLayout(theme_row)

        self.comp_box = QWidget()
        cv = QVBoxLayout(self.comp_box)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)
        sec = QLabel("COMPANION APPS")
        sec.setObjectName("Section")
        cv.addWidget(sec)
        for comp in companions.COMPANIONS:
            row_w = QWidget()
            rh = QHBoxLayout(row_w)
            rh.setContentsMargins(0, 0, 0, 0)
            text = QLabel(f"<b>{comp.full_name}</b><br>{comp.description}")
            text.setWordWrap(True)
            rh.addWidget(text, 1)
            info = icon_button("info", f"What {comp.name} does", size=26)
            info.clicked.connect(lambda _=False, c=comp: CompanionChip._info(self, c))
            rh.addWidget(info)
            state = QLabel()
            state.setObjectName("Hint")
            rh.addWidget(state)
            btn = QPushButton("Install")
            btn.clicked.connect(lambda _=False, c=comp: self._install(c))
            rh.addWidget(btn)
            row_w.hide()
            cv.addWidget(row_w)
            self.install_rows[comp.key] = (row_w, btn, state)
        cv.addWidget(_hint("Companion apps are separate, free and optional. Each one's installer runs normally, "
                           "so you can see what it does."))
        v.addWidget(self.comp_box)
        v.addStretch(1)
        return page

    def _pick(self, edit: QLineEdit, title: str) -> None:
        path = QFileDialog.getExistingDirectory(self, title, edit.text())
        if path:
            edit.setText(path)
            if edit is self.backup_edit and not self.app.settings.get("timelog_dir"):
                self.logs_edit.setText(str(Path(path) / "Time logs"))

    # ---- moving between pages --------------------------------------------------------------
    def _go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        on_setup = index == 1
        self.back_btn.setVisible(on_setup)
        self.review_btn.setVisible(self.upgrading and not on_setup)
        self.next_btn.setText("Done" if on_setup or self.upgrading else "Next")
        if on_setup:
            mode = self.chosen_mode()
            self.logs_box.setVisible(modes.has(mode, "timelogs"))
            self._sync_companions()

    def _next(self) -> None:
        if self.stack.currentIndex() == 0 and not self.upgrading:
            self._go(1)
            return
        self.finish(save_page_two=self.stack.currentIndex() == 1)

    def finish(self, save_page_two: bool = True) -> None:
        app = self.app
        if save_page_two:
            backup = self.backup_edit.text().strip()
            if backup and Path(backup) != app.default_backup_dir():
                app.set_setting("backup_dir", backup)
            logs = self.logs_edit.text().strip()
            if logs and modes.has(self.chosen_mode(), "timelogs") and Path(logs) != app.timelog_dir():
                app.set_setting("timelog_dir", logs)
            app.set_setting("startup", self.startup_box.isChecked())
        app.set_setting("mode", self.chosen_mode())
        app.set_setting("setup_done", True)
        self.accept()

    def reject(self) -> None:
        # Closing the window still settles the mode, so the question doesn't come back every start.
        if not self.app.settings.get("mode"):
            self.app.set_setting("mode", self.chosen_mode())
            self.app.set_setting("setup_done", True)
        super().reject()

    # ---- companion apps -----------------------------------------------------------------------
    def _check_companions(self) -> None:
        for comp in companions.COMPANIONS:
            self.app.updater.check(lambda release, _err, c=comp: self._release_found(c, release), comp.api_latest)

    def _release_found(self, comp: companions.Companion, release: dict | None) -> None:
        if release is None:
            return
        self.available[comp.key] = release
        for mode, chips in self.mode_chips.items():
            for chip in chips.findChildren(CompanionChip):
                if chip.property("key") == comp.key:
                    chip.show()
                    chips.show()
        self._sync_companions()

    def _sync_companions(self) -> None:
        mode = self.chosen_mode()
        fits = {c.key for c in companions.for_mode(mode)}
        any_shown = False
        for key, (row, _btn, _state) in self.install_rows.items():
            show = key in self.available and key in fits
            row.setVisible(show)
            any_shown = any_shown or show
        self.comp_box.setVisible(any_shown)
        self._sync_installed()

    def _sync_installed(self) -> None:
        for key, (_row, btn, state) in self.install_rows.items():
            comp = companions.get(key)
            installed = comp is not None and companions.find(comp) is not None
            btn.setVisible(not installed)
            state.setText("Installed ✓" if installed else "")

    def _install(self, comp: companions.Companion) -> None:
        release = self.available.get(comp.key)
        asset = updates.pick_installer(release) if release else None
        if asset is None:
            QDesktopServices.openUrl(QUrl(comp.releases_url))
            return
        name, url = asset
        dest = updates.download_path(name)
        progress = QProgressDialog(f"Downloading {comp.full_name}…", "Cancel", 0, 100, self)
        progress.setWindowTitle(comp.full_name)
        progress.setMinimumDuration(0)
        progress.canceled.connect(self.app.updater.cancel)

        def on_progress(received: int, total: int) -> None:
            if total > 0:
                progress.setValue(int(received * 100 / total))

        def on_done(path, error) -> None:
            progress.close()
            if path is None or not companions.run_installer(path):
                if error and "cancel" in error.lower():
                    return
                QDesktopServices.openUrl(QUrl(comp.releases_url))

        self.app.updater.download(url, dest, on_progress, on_done)
