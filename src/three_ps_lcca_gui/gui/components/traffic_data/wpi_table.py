"""
gui/components/traffic_data/wpi_table.py

_WPITable - vehicle × category matrix for WPI adjustment ratios.

Header  : group label over the column labels (GroupedHeaderView)
Rows    : 1 checkbox row + 8 vehicles
Columns : 16 cost categories grouped under 6 headings
Modes   : read-only (DB profile) / editable (custom profile)
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHeaderView,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
    QHBoxLayout,
    QAbstractScrollArea,
)
from ..utils.table_widgets import EditableCellDelegate, GroupedHeaderView, TableDoubleSpinBox
from three_ps_lcca_gui.gui.assets.themes.table_style import apply_column_style

# ── Vehicles ──────────────────────────────────────────────────────────────────

_VEHICLES = [
    ("small_cars", "Small Car"),
    ("big_cars", "Big Car"),
    ("two_wheelers", "Two Wheeler"),
    ("o_buses", "Ordinary Bus"),
    ("d_buses", "Deluxe Bus"),
    ("lcv", "LCV"),
    ("hcv", "HCV"),
    ("mcv", "MCV"),
]
from ..utils.wpi_manager import WPIManager, WPIProfile, empty_data
from three_ps_lcca_gui.gui.themes import theme_manager

# ── Column definitions ────────────────────────────────────────────────────────


@dataclass
class _ColDef:
    group: str
    label: str
    path: tuple
    head: str = ""  # header text with line breaks; label is the plain name

    @property
    def header(self) -> str:
        return self.head or self.label


_COLUMNS: list[_ColDef] = [
    _ColDef("Fuel Cost\n(INR)", "Petrol Cost", ("fuel_cost", "petrol", "{v}"), "Petrol\nCost"),
    _ColDef("Fuel Cost\n(INR)", "Diesel Cost", ("fuel_cost", "diesel", "{v}"), "Diesel\nCost"),
    _ColDef("Fuel Cost\n(INR)", "Engine Oil Cost", ("fuel_cost", "engine_oil", "{v}"), "Engine Oil\nCost"),
    _ColDef("Fuel Cost\n(INR)", "Other Oil Cost", ("fuel_cost", "other_oil", "{v}"), "Other Oil\nCost"),
    _ColDef("Fuel Cost\n(INR)", "Grease Cost", ("fuel_cost", "grease", "{v}"), "Grease\nCost"),

    _ColDef("Vehicle Cost\n(INR)", "Property Damage Cost", ("vehicle_cost", "property_damage", "{v}"), "Property\nDamage Cost"),
    _ColDef("Vehicle Cost\n(INR)", "Tyre Cost", ("vehicle_cost", "tyre_cost", "{v}"), "Tyre\nCost"),
    _ColDef("Vehicle Cost\n(INR)", "Spare Parts Cost", ("vehicle_cost", "spare_parts", "{v}"), "Spare Parts\nCost"),
    _ColDef("Vehicle Cost\n(INR)", "Fixed Depreciation", ("vehicle_cost", "fixed_depreciation", "{v}"), "Fixed\nDepreciation"),

    _ColDef("Commodity\nCost (INR)", "Commodity Holding Cost", ("commodity_holding_cost", "{v}"), "Commodity\nHolding Cost"),

    _ColDef("Passenger and Crew Cost\n(INR)", "Passenger Cost", ("passenger_crew_cost", "passenger_cost", "{v}"), "Passenger\nCost"),
    _ColDef("Passenger and Crew Cost\n(INR)", "Crew Cost", ("passenger_crew_cost", "crew_cost", "{v}"), "Crew\nCost"),

    _ColDef("Medical Cost\n(INR)", "Fatal Injury Cost", ("medical_cost", "fatal", "{v}"), "Fatal\nInjury Cost"),
    _ColDef("Medical Cost\n(INR)", "Major Injury Cost", ("medical_cost", "major", "{v}"), "Major\nInjury Cost"),
    _ColDef("Medical Cost\n(INR)", "Minor Injury Cost", ("medical_cost", "minor", "{v}"), "Minor\nInjury Cost"),

    _ColDef("Value of Time\nCost (INR)", "Value of Time Cost", ("vot_cost", "{v}"), "Value of Time\nCost"),
]

_N_COLS = len(_COLUMNS)
_N_ROWS = len(_VEHICLES) + 1  # checkbox + 8 vehicles
_ROW_CB = 0
_ROW_DATA = 1


def _col_key(col: _ColDef) -> str:
    """Last non-{v} segment of the column path - used as the flat data key."""
    return next(s for s in reversed(col.path) if s != "{v}")


def _get_value(data: dict, col: _ColDef, vehicle_key: str) -> float:
    val = data.get(vehicle_key, {}).get(_col_key(col), 1.0)
    return float(val) if isinstance(val, (int, float)) else 1.0


def _set_value(data: dict, col: _ColDef, vehicle_key: str, value: float):
    data.setdefault(vehicle_key, {})[_col_key(col)] = value


def _header_groups() -> list[tuple[int, int, str]]:
    """(first column, span, label) for each cost group, for GroupedHeaderView."""
    groups: list[list] = []
    for col, cdef in enumerate(_COLUMNS):
        if groups and groups[-1][2] == cdef.group:
            groups[-1][1] += 1
        else:
            groups.append([col, 1, cdef.group])
    return [tuple(g) for g in groups]


def _is_vehicle_dim(col: _ColDef) -> bool:
    """All columns now support vehicle-specific overrides."""
    return True


# ── _WPITable ─────────────────────────────────────────────────────────────────


class _WPITable(QTableWidget):
    """
    Vehicle × Category WPI ratio table.

    Header : group labels (Fuel Cost, Vehicle Cost …) over column labels
    Row 0  : "Common to All" checkboxes
    Rows 1+: one row per vehicle
    """

    data_changed = Signal()

    def __init__(self, parent=None, strict_read_only: bool = False):
        super().__init__(_N_ROWS, _N_COLS, parent)
        self._strict_read_only = strict_read_only
        self._editable: bool = False
        self._spinboxes: dict[tuple[int, int], QDoubleSpinBox] = {}
        self._checkboxes: dict[int, QCheckBox] = {}
        self._loading: bool = False

        self._setup_table()
        self.verticalHeader().sectionResized.connect(lambda: QTimer.singleShot(0, self.updateGeometry))
        self._build_checkbox_row()
        self._build_data_rows()
        # Apply initial read-only opacity to all spinboxes
        for sb in self._spinboxes.values():
            self._apply_spinbox_opacity(sb, False)
        self.updateGeometry()
        theme_manager().theme_changed.connect(self._refresh_styles)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _setup_table(self):
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setItemDelegate(EditableCellDelegate(self))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideNone)
        self.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)

        # two-tier header: each cost group spans its columns
        self.setHorizontalHeader(GroupedHeaderView(groups=_header_groups()))
        for col, cdef in enumerate(_COLUMNS):
            item = QTableWidgetItem(cdef.header)
            item.setToolTip(f"{' '.join(cdef.group.split())} - {cdef.label}")
            self.setHorizontalHeaderItem(col, item)
        # every column holds a 4-decimal ratio (assets/themes/table_style.py)
        apply_column_style(self, {col: "wpi" for col in range(_N_COLS)})

        self.verticalHeader().setVisible(True)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.verticalHeader().setTextElideMode(Qt.ElideNone)

    def _build_checkbox_row(self):
        """Row 2 - one centered QCheckBox per column."""
        for col in range(_N_COLS):
            cb = QCheckBox()
            is_veh_dim = _is_vehicle_dim(_COLUMNS[col])
            cb.setChecked(True)
            if not is_veh_dim:
                cb.setEnabled(False)
                cb.setToolTip(
                    "This factor is not vehicle-specific - always common to all"
                )
            else:
                cb.setToolTip("Common to all vehicles")
            cb.stateChanged.connect(lambda state, c=col: self._on_common_toggled(c))

            container = QWidget()
            layout = QHBoxLayout(container)
            layout.addWidget(cb)
            layout.setAlignment(Qt.AlignCenter)
            layout.setContentsMargins(0, 0, 0, 0)
            self.setCellWidget(_ROW_CB, col, container)
            self._checkboxes[col] = cb

            item = QTableWidgetItem()
            item.setFlags(Qt.ItemIsEnabled)
            self.setItem(_ROW_CB, col, item)

        self.setVerticalHeaderItem(_ROW_CB, QTableWidgetItem("Common\nto All"))

    def _build_data_rows(self):
        """Rows 3+ - one QDoubleSpinBox per cell, vehicle name in vertical header."""
        for row_idx, (vkey, vlabel) in enumerate(_VEHICLES):
            row = _ROW_DATA + row_idx
            self.setVerticalHeaderItem(row, QTableWidgetItem(vlabel))

            for col in range(_N_COLS):
                cdef = _COLUMNS[col]
                sb = TableDoubleSpinBox()
                sb.setRange(0.0, float("inf"))
                sb.setDecimals(4)
                sb.setValue(1.0)
                sb.setButtonSymbols(TableDoubleSpinBox.NoButtons)
                sb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                sb.setReadOnly(True)
                sb.setFrame(False)
                sb.setToolTip(f"{vlabel}: {cdef.group} / {cdef.label}")
                # opacity applied via _apply_spinbox_opacity after palette is available
                sb.valueChanged.connect(
                    lambda val, r=row, c=col: self._on_spinbox_changed(r, c, val)
                )
                self.setCellWidget(row, col, sb)
                self._spinboxes[(row, col)] = sb

    # ── Theme refresh ─────────────────────────────────────────────────────────

    def _refresh_styles(self):
        """Re-bake spinbox opacity colors using the current palette/theme."""
        for sb in self._spinboxes.values():
            self._apply_spinbox_opacity(sb, not sb.isReadOnly())

    # ── Mode ──────────────────────────────────────────────────────────────────

    def freeze(self, frozen: bool = True):
        """Freeze/unfreeze the whole table regardless of editable state."""
        if frozen:
            for sb in self._spinboxes.values():
                sb.setReadOnly(True)
                sb.setFrame(False)
                self._apply_spinbox_opacity(sb, False)
            for cb in self._checkboxes.values():
                cb.setEnabled(False)
        else:
            self.set_editable(self._editable)

    def set_editable(self, editable: bool):
        if self._strict_read_only:
            editable = False
        self._editable = editable
        for (row, col), sb in self._spinboxes.items():
            cb = self._checkboxes[col]
            is_first = row == _ROW_DATA
            is_common = cb.isChecked()
            self._set_cell_editable(row, col, editable and (is_first or not is_common))
        for col, cb in self._checkboxes.items():
            # Enable checkboxes for vehicle-specific columns when in edit mode
            is_veh_dim = _is_vehicle_dim(_COLUMNS[col])
            cb.setEnabled(editable and is_veh_dim)
            if not is_veh_dim:
                cb.setToolTip("This factor is not vehicle-specific - always common to all")
            else:
                cb.setToolTip("Common to all vehicles" if editable else "View-only (common to all)")

    def _set_cell_editable(self, row: int, col: int, editable: bool):
        sb = self._spinboxes.get((row, col))
        if sb is None:
            return
        sb.setReadOnly(not editable)
        sb.setFrame(editable)
        self._apply_spinbox_opacity(sb, editable)

    # ── Common-to-all logic ───────────────────────────────────────────────────

    def _on_common_toggled(self, col: int):
        if self._loading:
            return
        cb = self._checkboxes[col]
        is_common = cb.isChecked()

        if is_common:
            first_val = self._spinboxes[(_ROW_DATA, col)].value()
            self._loading = True
            for row_idx in range(1, len(_VEHICLES)):
                self._spinboxes[(_ROW_DATA + row_idx, col)].setValue(first_val)
            self._loading = False

        for row_idx in range(len(_VEHICLES)):
            row = _ROW_DATA + row_idx
            is_first = row == _ROW_DATA
            self._set_cell_editable(
                row, col, self._editable and (is_first or not is_common)
            )

        self._apply_common_style(col, is_common)
        self.data_changed.emit()

    def _apply_spinbox_opacity(self, sb: QDoubleSpinBox, active: bool):
        """Grey out read-only values via main.qss [frozen="true"]."""
        sb.setProperty("frozen", not active)
        sb.style().unpolish(sb)
        sb.style().polish(sb)

    def _apply_common_style(self, col: int, is_common: bool):
        for row_idx in range(1, len(_VEHICLES)):
            row = _ROW_DATA + row_idx
            sb = self._spinboxes.get((row, col))
            if sb is None:
                continue
            # Dimmed when common (non-editable secondary rows), active when independent
            active = not is_common and self._editable
            self._apply_spinbox_opacity(sb, active)

    def _on_spinbox_changed(self, row: int, col: int, value: float):
        if self._loading or self._strict_read_only:
            return
        if row == _ROW_DATA and self._checkboxes[col].isChecked():
            self._loading = True
            for row_idx in range(1, len(_VEHICLES)):
                self._spinboxes[(_ROW_DATA + row_idx, col)].setValue(value)
            self._loading = False
        self.data_changed.emit()

    # ── Load / Collect ────────────────────────────────────────────────────────

    def load_from_data(self, data: dict):
        self._loading = True
        try:
            for col, cdef in enumerate(_COLUMNS):
                values = []
                for row_idx, (vkey, _) in enumerate(_VEHICLES):
                    val = _get_value(data, cdef, vkey)
                    values.append(val)
                    self._spinboxes[(_ROW_DATA + row_idx, col)].setValue(val)

                all_same = len(set(round(v, 6) for v in values)) == 1
                cb = self._checkboxes[col]
                cb.setChecked(all_same)
                self._apply_common_style(col, all_same)
        finally:
            self._loading = False

        self.set_editable(self._editable)

    def collect_to_data(self) -> dict:
        data = empty_data()
        for col, cdef in enumerate(_COLUMNS):
            for row_idx, (vkey, _) in enumerate(_VEHICLES):
                row = _ROW_DATA + row_idx
                val = self._spinboxes[(row, col)].value()
                _set_value(data, cdef, vkey, val)
        return data

    def validate(self) -> list[str]:
        """Return list of error strings for any WPI cell that is zero."""
        errors = []
        for col, cdef in enumerate(_COLUMNS):
            cb = self._checkboxes[col]
            is_common = cb.isChecked()
            rows_to_check = (
                [_ROW_DATA]
                if is_common
                else range(_ROW_DATA, _ROW_DATA + len(_VEHICLES))
            )
            for row in rows_to_check:
                if self._spinboxes[(row, col)].value() == 0.0:
                    vkey, vlabel = _VEHICLES[row - _ROW_DATA]
                    label = f"{cdef.group} / {cdef.label}"
                    if is_common:
                        errors.append(f"WPI value cannot be zero: {label}")
                    else:
                        errors.append(f"WPI value cannot be zero: {label} ({vlabel})")
        return errors

    def is_common(self, col: int) -> bool:
        return self._checkboxes[col].isChecked()

    def common_state(self) -> dict[int, bool]:
        return {col: cb.isChecked() for col, cb in self._checkboxes.items()}

    def load_common_state(self, state: dict[int, bool]):
        self._loading = True
        for col, checked in state.items():
            if col in self._checkboxes:
                self._checkboxes[col].setChecked(checked)
                self._apply_common_style(col, checked)
        self._loading = False


