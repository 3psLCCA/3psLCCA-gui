"""
gui/components/traffic_data/wpi_selector.py

_WPISelector - profile selector bar for WPI adjustment ratio profiles.

Layout:
    [▾ profile combo] - sits in the table card heading; the card's •••
    menu holds Duplicate… / Edit… / Delete (built-in profiles are
    read-only, so Edit and Delete work only on custom ones)

Signals:
    profile_selected(WPIProfile)   - user picked a profile from combo
    profile_saved(WPIProfile)      - user saved a custom profile
    profile_deleted(str)           - user deleted a profile (id)
    edit_requested()               - user wants to edit current profile
"""

from __future__ import annotations

from typing import Optional

from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.theme import SP1, SP2, SP3, SP4
from ..utils.icons import make_icon
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QScreen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
    QScrollArea,
)
from ..utils.wpi_manager import (
    WPIManager, WPIProfile,
    save_to_user_library, delete_from_user_library,
)
import json
import uuid

# ── Dev mode ──────────────────────────────────────────────────────────────────

DEV = False # Set to True to print JSON data on add/edit

# ── WPI Editor Dialog ─────────────────────────────────────────────────────────

class _WPIEditorDialog(QDialog):
    """
    Duplicate: a new copy of any profile under a new name.
    Edit: change one of the user's own (custom) profiles in place.
    Contains metadata fields and an integrated _WPITable.
    """

    def __init__(self, manager: WPIManager, profile: WPIProfile,
                 duplicate: bool, parent=None):
        super().__init__(parent)
        verb = "Duplicate" if duplicate else "Edit"
        self.setWindowTitle(f"{verb} {profile.name}")
        self.setMinimumWidth(900)

        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen().availableGeometry()
        max_h = int(screen.height() * 0.90)
        self.setMaximumHeight(max_h)
        self.resize(900, min(780, max_h))
        
        self._manager = manager
        self._duplicate = duplicate
        self._result_profile: Optional[WPIProfile] = None

        # Work on a copy; a duplicate gets its own id, a free name
        # (e.g. "2019-user") and an empty remark (the source's remark
        # describes the source, not the copy)
        self._profile = WPIProfile(
            id=(f"wpi_custom_{uuid.uuid4().hex[:8]}" if duplicate else profile.id),
            name=(manager.suggest_custom_name(profile.name) if duplicate else profile.name),
            year=profile.year, is_custom=True,
            remark="" if duplicate else profile.remark,
            hash=profile.hash, data=json.loads(json.dumps(profile.data)),
            is_shared=profile.is_shared if profile.is_custom else True,
        )

        self._build_ui()
        self._load_meta()
        self._table.load_from_data(self._profile.data)

    def _build_ui(self):
        from .wpi_table import _WPITable
        layout = QVBoxLayout(self)

        # ── Header: Metadata ──────────────────────────────────────────────────
        meta_group = QWidget()
        meta_layout = QFormLayout(meta_group)
        meta_layout.setContentsMargins(0, 0, 0, 10)

        self._name = QLineEdit()
        meta_layout.addRow("Profile Name:", self._name)

        self._year = QSpinBox()
        self._year.setRange(1900, 2200)
        meta_layout.addRow("Year (metadata):", self._year)

        self._remark = QLineEdit()
        self._remark.setPlaceholderText("Optional remarks...")
        meta_layout.addRow("Remark:", self._remark)

        self._shared = QCheckBox("Save for later projects (global library)")
        meta_layout.addRow("", self._shared)

        layout.addWidget(meta_group)

        # ── Body: Table ───────────────────────────────────────────────────────
        layout.addWidget(QLabel("<b>Adjust WPI Ratios:</b>"))
        self._table = _WPITable()
        self._table.set_editable(True)
        # Allow vertical scrolling so the dialog doesn't overflow the screen
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._table, 1)

        # ── Footer: Actions ───────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        if self._duplicate:
            btns.button(QDialogButtonBox.Save).setText("Create")
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_meta(self):
        self._name.setText(self._profile.name)
        self._year.setValue(self._profile.year)
        self._remark.setText(self._profile.remark)
        self._shared.setChecked(self._profile.is_shared)

    def _on_save(self):
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Profile name is required.")
            return

        if self._manager.is_name_taken(name, exclude_id=self._profile.id):
            QMessageBox.warning(self, "Taken", f"A profile named '{name}' already exists.")
            return

        self._profile.name = name
        self._profile.year = self._year.value()
        self._profile.remark = self._remark.text().strip()
        self._profile.is_shared = self._shared.isChecked()
        self._profile.data = self._table.collect_to_data()
        self._profile.stamp_hash()
        self._result_profile = self._profile
        self.accept()

    @property
    def result_profile(self) -> Optional[WPIProfile]:
        return self._result_profile


# ── _WPISelector ──────────────────────────────────────────────────────────────


class _WPISelector(QWidget):
    profile_selected = Signal(object)   # WPIProfile
    profile_saved    = Signal(object)   # WPIProfile
    profile_deleted  = Signal(str)      # profile id
    edit_requested   = Signal()

    def __init__(self, manager: WPIManager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._current: Optional[WPIProfile] = None
        self._build_ui()
        self._populate_combo()
        self._select_first()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # just the dropdown: the page puts it in the card heading, after
        # the "WPI Profile" title
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        self._combo = QComboBox()
        self._combo.setObjectName("wpiProfileCombo")  # compact, main.qss
        self._combo.setMinimumWidth(180)
        self._combo.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self._combo)

        # Profile actions: the page puts this menu behind the ••• button of
        # the Adjustment Factors card, as on Machinery
        self._frozen = False
        menu = self.menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ padding: {SP1}px; }}"
            f"QMenu::item {{ padding: {SP2}px {SP4}px {SP2}px {SP2}px; }}"
            f"QMenu::icon {{ padding-left: {SP3}px; }}"
            f"QMenu::separator {{ margin: {SP1}px {SP2}px; }}"
        )
        # built-in profiles are read-only: Duplicate makes one you can change
        self._act_duplicate = menu.addAction("Duplicate…")
        self._act_edit = menu.addAction("Edit…")
        menu.addSeparator()
        self._act_delete = menu.addAction("Delete")
        self._act_duplicate.triggered.connect(lambda checked=False: self._open_dialog(duplicate=True))
        self._act_edit.triggered.connect(lambda checked=False: self._open_dialog(duplicate=False))
        self._act_delete.triggered.connect(lambda checked=False: self._on_delete_current())

        def _on_menu_show():  # icons follow the theme, so set them on open
            self._act_edit.setIcon(make_icon("edit"))
            self._act_delete.setIcon(make_icon("trash", color=get_token("danger")))
        menu.aboutToShow.connect(_on_menu_show)
        self._sync_actions()

    # ── Combo management ──────────────────────────────────────────────────────

    def freeze(self, frozen: bool = True):
        self._combo.setEnabled(not frozen)
        self._frozen = frozen
        self._sync_actions()

    def _sync_actions(self):
        """Duplicate any profile; Edit and Delete only your own (custom) ones."""
        custom = bool(self._current and self._current.is_custom)
        self._act_duplicate.setEnabled(not self._frozen and self._current is not None)
        self._act_edit.setEnabled(not self._frozen and custom)
        self._act_delete.setEnabled(not self._frozen and custom)

    def _populate_combo(self, select_id: Optional[str] = None):
        self._combo.blockSignals(True)
        self._combo.clear()
        bold = QFont()
        bold.setBold(True)
        for profile in self._manager.all_listed():
            label = profile.name if not profile.is_custom else f"★ {profile.name}"
            self._combo.addItem(label, userData=profile.id)
            idx = self._combo.count() - 1
            if not profile.is_custom:
                self._combo.setItemData(idx, bold, Qt.FontRole)
        self._combo.blockSignals(False)
        if select_id:
            for i in range(self._combo.count()):
                if self._combo.itemData(i) == select_id:
                    self._combo.setCurrentIndex(i)
                    break
        elif self._combo.count() > 0:
            self._combo.setCurrentIndex(0)

    def _on_combo_changed(self, idx: int):
        profile_id = self._combo.itemData(idx)
        if not profile_id: return
        profile = self._manager.get_by_id(profile_id)
        if profile:
            self._current = profile
            self._sync_actions()
            self.profile_selected.emit(profile)

    def _select_first(self):
        if self._combo.count() > 0:
            self._combo.setCurrentIndex(0)
            self._on_combo_changed(0)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    def _open_dialog(self, duplicate: bool):
        """Duplicate the current profile, or edit it in place (custom only)."""
        if not self._current or (not duplicate and not self._current.is_custom):
            return
        dlg = _WPIEditorDialog(self._manager, self._current, duplicate, parent=self)
        if dlg.exec() != QDialog.Accepted or not dlg.result_profile:
            return
        p = dlg.result_profile
        if duplicate:
            self._manager.add_custom(p)
        else:
            self._manager.save_custom(p)

        if p.is_shared:
            save_to_user_library(p)
        elif not duplicate:
            delete_from_user_library(p.id)  # unticked "Save for later projects"

        if DEV:
            print(f"\n[DEV] {'Duplicated' if duplicate else 'Edited'} WPI Profile:")
            print(json.dumps(p.to_dict(), indent=2))

        self.refresh(select_id=p.id)
        self.profile_saved.emit(p)

    def _on_delete_current(self):
        if not self._current or not self._current.is_custom:
            return

        reply = QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete custom profile '{self._current.name}'?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        deleted_id = self._current.id
        self._manager.delete_custom(deleted_id)
        if self._current.is_shared:
            delete_from_user_library(deleted_id)
            
        self._current = None
        self._populate_combo()
        self._select_first()
        self.profile_deleted.emit(deleted_id)

    # ── Public API ────────────────────────────────────────────────────────────

    def current_profile(self) -> Optional[WPIProfile]:
        return self._current

    def current_is_custom(self) -> bool:
        return self._current is not None and self._current.is_custom

    def refresh(self, select_id: Optional[str] = None):
        self._populate_combo(select_id=select_id or (self._current.id if self._current else None))

    def select_by_id(self, profile_id: str):
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == profile_id:
                self._combo.setCurrentIndex(i)
                return


