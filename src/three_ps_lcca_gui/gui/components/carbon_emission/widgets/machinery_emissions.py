"""
gui/components/carbon_emission/widgets/machinery_emissions.py

Chunk: machinery_emissions_data

Two modes toggled by radio buttons:
  - Detailed Equipment List  (table card, one row per machine)
  - Lump Sum                 (electricity + fuel - built via build_form)

Grand total shown at top and bottom.
Currency label pulled from general_info chunk.
"""

import math
import re

from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.theme import FS_SECTION, SP1, SP2, SP3, SP4
from three_ps_lcca_gui.gui.assets.themes.table_style import (
    ColumnMinWidthMixin,
    apply_column_style,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QEvent, QModelIndex
from PySide6.QtGui import QFont

from ...base_widget import ScrollableForm
from ...utils.form_builder.form_definitions import FieldDef, Section
from ...utils.form_builder.form_builder import build_form
from ...utils.remarks_editor import RemarksEditor
from ...utils.display_format import fmt, fmt_comma, DECIMAL_PLACES
from ...utils.icons import make_icon
from ...utils.table_widgets import (
    BaseActionDelegate,
    TableCard,
    TooltipTableMixin,
    WordWrapHeaderView,
    fit_to_contents,
)
from ...utils.validation_helpers import freeze_widgets, confirm_clear_all
from ...utils.common_requested_data import get_bridge_data

CHUNK = "machinery_emissions_data"

ENERGY_SOURCES = [
    "Diesel",
    "Electricity (Grid)",
    "Electricity (Solar/Renewable)",
    "Other",
]

EF_DEFAULTS = {
    "Diesel": 2.69,
    "Electricity (Grid)": 0.71,
    "Electricity (Solar/Renewable)": 0.0,
    "Other": 0.0,
}

RATE_SUFFIX = {
    "Diesel": " l/hr",
    "Electricity (Grid)": " kW",
    "Electricity (Solar/Renewable)": " kW",
    "Other": " units/hr",
}

CONSUMPTION_UNIT = {
    "Diesel": "litres",
    "Electricity (Grid)": "kWh",
    "Electricity (Solar/Renewable)": "kWh",
    "Other": "units",
}

DEFAULT_MACHINERY_DATA = [
    {"name": "Backhoe loader (JCB)", "source": "Diesel", "rate": 5.0, "ef": 2.69},
    {
        "name": "Bar bending machine",
        "source": "Electricity (Grid)",
        "rate": 3.0,
        "ef": 0.71,
    },
    {
        "name": "Bar cutting machine",
        "source": "Electricity (Grid)",
        "rate": 4.0,
        "ef": 0.71,
    },
    {"name": "Bitumen boiler", "source": "Diesel", "rate": 1.0, "ef": 2.69},
    {"name": "Bitumen sprayer", "source": "Diesel", "rate": 5.0, "ef": 2.69},
    {"name": "Concrete pump", "source": "Diesel", "rate": 12.0, "ef": 2.69},
    {"name": "Crane (crawler)", "source": "Diesel", "rate": 12.0, "ef": 2.69},
    {"name": "Crane (mobile)", "source": "Diesel", "rate": 8.0, "ef": 2.69},
    {"name": "Dewatering pump", "source": "Diesel", "rate": 2.0, "ef": 2.69},
    {"name": "DG set", "source": "Diesel", "rate": 4.0, "ef": 2.69},
    {"name": "Grouting mixer", "source": "Electricity (Grid)", "rate": 1.0, "ef": 0.71},
    {"name": "Grouting pump", "source": "Electricity (Grid)", "rate": 5.0, "ef": 0.71},
    {"name": "Hydraulic excavator", "source": "Diesel", "rate": 14.0, "ef": 2.69},
    {
        "name": "Hydraulic stressing jack",
        "source": "Electricity (Grid)",
        "rate": 3.0,
        "ef": 0.71,
    },
    {
        "name": "Needle Vibrator",
        "source": "Electricity (Grid)",
        "rate": 1.0,
        "ef": 0.71,
    },
    {"name": "Paver finisher", "source": "Diesel", "rate": 7.0, "ef": 2.69},
    {"name": "Road roller", "source": "Diesel", "rate": 4.0, "ef": 2.69},
    {
        "name": "Rotary piling rig/Hydraulic piling rig",
        "source": "Diesel",
        "rate": 15.0,
        "ef": 2.69,
    },
    {
        "name": "Site office (If Grid electricity is used)",
        "source": "Electricity (Grid)",
        "rate": 4.0,
        "ef": 0.71,
    },
    {
        "name": "Welding machine",
        "source": "Electricity (Grid)",
        "rate": 4.0,
        "ef": 0.71,
    },
]

# ── Field definitions - passed to build_form ──────────────────────────────────

LUMPSUM_ELEC_FIELDS = [
    Section("Electricity Consumption"),
    FieldDef(
        "elec_consumption_per_day",
        "Electricity Consumption per Day",
        "Total electricity consumed per working day across all equipment.",
        "float",
        options=(0.0, 1e12, DECIMAL_PLACES),
        unit="(kWh/day)",
    ),
    FieldDef(
        "elec_days",
        "Number of Days",
        "Total number of working days for electricity consumption.",
        "int",
        options=(0, 9999),
        unit="(days)",
    ),
    FieldDef(
        "elec_ef",
        "Emission Factor",
        "Grid electricity emission factor (kg CO₂e per kWh).",
        "float",
        options=(0.0, 999.0, DECIMAL_PLACES),
        unit="(kg CO₂e/kWh)",
    ),
]

LUMPSUM_FUEL_FIELDS = [
    Section("Fuel Consumption"),
    FieldDef(
        "fuel_consumption_per_day",
        "Fuel Consumption per Day",
        "Total fuel consumed per working day across all equipment.",
        "float",
        options=(0.0, 1e12, DECIMAL_PLACES),
        unit="(litres/day)",
    ),
    FieldDef(
        "fuel_days",
        "Number of Days",
        "Total number of working days for fuel consumption.",
        "int",
        options=(0, 9999),
        unit="(days)",
    ),
    FieldDef(
        "fuel_ef",
        "Emission Factor",
        "Emission factor (kg CO₂e per litre).",
        "float",
        options=(0.0, 999.0, DECIMAL_PLACES),
        unit="(kg CO₂e/litre)",
    ),
]

_LUMPSUM_KEYS = [
    ("elec_consumption_per_day", 0.0),
    ("elec_days", 0),
    ("elec_ef", 0.0),
    ("fuel_consumption_per_day", 0.0),
    ("fuel_days", 0),
    ("fuel_ef", 0.0),
]



# ── Equipment table ───────────────────────────────────────────────────────────
# Built from the shared table parts, like Construction Work Data's tables:
# TableCard (heading, ••• menu, "+ Add" row), BaseActionDelegate (Edit /
# Delete buttons), fit_to_contents (every row shows, the page scrolls) and
# table_style.py (column widths from the header labels).

_HEADERS = [
    "Equipment Name",                    # 0
    "Energy Source",                     # 1
    "Fuel / Power\nRating",              # 2
    "Avg\nHrs/Day",                      # 3
    "No. of\nDays",                      # 4
    "Emission Factor\n(kg CO₂e/unit)",   # 5
    "Consumption",                       # 6
    "Emissions\n(kg CO₂e)",              # 7
    "Action",                            # 8  Edit / Delete buttons
]
_ACTION_COL = len(_HEADERS) - 1


def _clean_row(d: dict) -> dict:
    """A saved row with every key present and the right type."""
    src = d.get("source") or ENERGY_SOURCES[0]
    return {
        "name":   str(d.get("name", "")),
        "source": src,
        "rate":   float(d.get("rate") or 0.0),
        "hrs":    float(d.get("hrs") or 0.0),
        "days":   int(d.get("days") or 0),
        "ef":     float(d.get("ef", EF_DEFAULTS.get(src, 0.0)) or 0.0),
    }


def _consumption(r: dict) -> float:
    return r["rate"] * r["hrs"] * r["days"]


NAME_MAX_LEN = 100
# letters, digits, spaces and - _ / . ( )  - brackets as in the default list
_NAME_OK = re.compile(r"[\w \-/.()]+")  # plain space only: no tabs or line breaks
# sources whose emission factor may be 0 (no combustion / grid draw)
_ZERO_EF_OK = {"Electricity (Solar/Renewable)"}


def _construction_days() -> int | None:
    """The construction period in days (bridge data months x days per month),
    or None when the project does not have it yet."""
    bridge = get_bridge_data()
    try:
        months = float(bridge["duration_construction_months"])
        per_month = float(bridge["days_per_month"])
    except (KeyError, TypeError, ValueError):
        return None
    return int(months * per_month) if months > 0 and per_month > 0 else None


def check_equipment(row: dict, other_names, max_days: int | None
                    ) -> list[tuple[str, str, str]]:
    """The Add / Edit Equipment rules, in the order the dialog asks them.

    Each problem is (level, field, message):
      "error"   - cannot be saved
      "warning" - saved only if the user continues
    *other_names*: the names of the other rows (duplicates are blocked).
    *max_days*: the construction period in days, or None.
    """
    problems = []
    name, src = row["name"].strip(), row["source"]

    if not name:
        problems.append(("error", "name", "Equipment Name is required."))
    elif len(name) > NAME_MAX_LEN:
        problems.append(("error", "name", f"Equipment Name must be {NAME_MAX_LEN} characters or fewer."))
    elif not _NAME_OK.fullmatch(name):
        problems.append(("error", "name",
                         "Equipment Name may use only letters, numbers, spaces and - _ / . ( )"))
    elif name.casefold() in {n.strip().casefold() for n in other_names}:
        problems.append(("error", "name", f"Equipment \"{name}\" is already in the list."))

    if src not in ENERGY_SOURCES:
        problems.append(("error", "source", "Please select an Energy Source."))

    if not row["rate"] > 0:
        problems.append(("error", "rate", "Fuel / Power Rating must be greater than zero."))
    if not 0 < row["hrs"] <= 24:
        problems.append(("error", "hrs", "Avg Hrs/Day must be greater than zero and at most 24."))
    if row["days"] < 1:
        problems.append(("error", "days", "No. of Days must be at least 1."))
    elif max_days and row["days"] > max_days:
        problems.append(("error", "days",
                         f"No. of Days ({row['days']}) is longer than the construction "
                         f"period ({max_days} days, from Bridge Data)."))

    ef = row["ef"]
    if ef < 0 or (ef == 0 and src not in _ZERO_EF_OK):
        problems.append(("error", "ef", "Emission Factor must be greater than zero."))
    elif src in EF_DEFAULTS and src != "Other" and ef != EF_DEFAULTS[src]:
        problems.append(("warning", "ef",
                         f"Emission Factor {fmt(ef)} differs from the default "
                         f"{fmt(EF_DEFAULTS[src])} for {src}."))

    if not math.isfinite(_consumption(row) * ef):
        problems.append(("error", "rate", "The calculated emissions are too large."))
    return problems


class _ActionDelegate(BaseActionDelegate):
    """Edit and Delete buttons in the Action column."""

    def __init__(self, table, owner):
        super().__init__(table)
        self._owner = owner
        self._btns = [
            (make_icon("edit"), (46, 204, 113), "edit", "Edit"),
            (make_icon("trash", color=get_token("danger")), (231, 76, 60), "delete", "Remove row"),
        ]

    def _get_btns_for_row(self, row) -> list[tuple]:
        return [(icon, hover_rgb, tooltip) for icon, hover_rgb, _, tooltip in self._btns]

    def editorEvent(self, event, model, option, index):
        if self._frozen or event.type() != QEvent.MouseButtonRelease:
            return False
        rects = self._btn_rects(option.rect, len(self._btns))
        for rect, (_, _, action, _) in zip(rects, self._btns):
            if rect.contains(event.pos()):
                if action == "edit":
                    self._owner.edit_row(index.row())
                else:
                    self._owner.delete_row(index.row())
                return True
        return False


class _EquipmentDialog(QDialog):
    """Add / Edit one machine."""

    def __init__(self, row: dict, title: str, ok_text: str, other_names=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._other_names = list(other_names)
        layout = QFormLayout(self)
        layout.setSpacing(SP2)
        layout.setContentsMargins(SP4, SP4, SP4, SP4)

        self._name = QLineEdit(row["name"])
        self._name.setMaxLength(NAME_MAX_LEN)
        self._source = QComboBox()
        self._source.addItems(ENERGY_SOURCES)
        self._source.setCurrentIndex(max(0, self._source.findText(row["source"])))

        def spin(cls, lo, hi, value, suffix):
            w = cls()
            w.setRange(lo, hi)
            if cls is QDoubleSpinBox:
                w.setDecimals(DECIMAL_PLACES)
            w.setValue(value)
            w.setSuffix(suffix)
            return w

        self._rate = spin(QDoubleSpinBox, 0.0, 1e9, row["rate"], RATE_SUFFIX.get(row["source"], " units/hr"))
        self._hrs = spin(QDoubleSpinBox, 0.0, 24.0, row["hrs"], " hrs/day")
        self._days = spin(QSpinBox, 0, 9999, row["days"], " days")
        self._ef = spin(QDoubleSpinBox, 0.0, 999.0, row["ef"], " kg CO₂e/unit")

        layout.addRow("Equipment Name:", self._name)
        layout.addRow("Energy Source:", self._source)
        layout.addRow("Fuel / Power Rating:", self._rate)
        layout.addRow("Avg Hrs/Day:", self._hrs)
        layout.addRow("No. of Days:", self._days)
        layout.addRow("Emission Factor:", self._ef)
        self._source.currentTextChanged.connect(self._on_source_changed)

        # Cancel | Add, right-aligned (as in the Material dialog)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton(ok_text)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.validate_and_accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(ok_btn)
        layout.addRow(buttons)
        self._initial = self.values()

    def validate_and_accept(self):
        """Check the row (check_equipment); errors stop, warnings ask first.
        The field with the problem gets the focus."""
        fields = {"name": self._name, "source": self._source, "rate": self._rate,
                  "hrs": self._hrs, "days": self._days, "ef": self._ef}
        problems = check_equipment(self.values(), self._other_names, _construction_days())
        for level, field, message in problems:
            fields[field].setFocus()
            if level == "error":
                QMessageBox.critical(self, "Validation Error", message)
                return
            reply = QMessageBox.warning(self, "Check Value", f"{message}\n\nContinue?",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        self.accept()

    def reject(self):
        """Cancel, X or Esc: ask before throwing away edits."""
        if self.values() != self._initial:
            reply = QMessageBox.question(self, "Discard Changes",
                                         "Discard the changes to this equipment?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        super().reject()

    def _on_source_changed(self, src: str):
        self._rate.setSuffix(RATE_SUFFIX.get(src, " units/hr"))
        self._ef.setValue(EF_DEFAULTS.get(src, 0.0))

    def values(self) -> dict:
        return {
            "name":   self._name.text().strip(),
            "source": self._source.currentText(),
            "rate":   self._rate.value(),
            "hrs":    self._hrs.value(),
            "days":   self._days.value(),
            "ef":     self._ef.value(),
        }


class _EquipmentTable(TooltipTableMixin, ColumnMinWidthMixin, QTableWidget):
    """Read-only rows (changed through the dialog); never narrower than its
    columns' minimum widths (table_style.ColumnMinWidthMixin)."""


class _DetailedTable(QWidget):
    """The Equipment card. The rows live in self._rows; the table shows them."""

    def __init__(self, on_change, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._rows: list[dict] = []
        self._frozen = False

        t = self._table = _EquipmentTable(0, len(_HEADERS))
        t.setHorizontalHeader(WordWrapHeaderView(Qt.Horizontal))
        for col, label in enumerate(_HEADERS):
            item = QTableWidgetItem(label)
            # Equipment Name sits left over its text; the rest are centred
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if col == 0 else Qt.AlignCenter)
            t.setHorizontalHeaderItem(col, item)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QTableWidget.SelectRows)
        t.setSelectionMode(QTableWidget.SingleSelection)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.cellDoubleClicked.connect(lambda row, _col: self.edit_row(row))
        fit_to_contents(t)  # every row shows; the page scrolls down

        self._action_delegate = _ActionDelegate(t, self)
        t.setItemDelegateForColumn(_ACTION_COL, self._action_delegate)
        btn_h = self._action_delegate.sizeHint(QStyleOptionViewItem(), QModelIndex()).height()
        t.verticalHeader().setMinimumSectionSize(btn_h)  # rows fit the buttons

        # widths from the header labels (assets/themes/table_style.py);
        # Action has no width rule there, so it sizes to its buttons
        apply_column_style(t)
        t.horizontalHeader().setSectionResizeMode(_ACTION_COL, QHeaderView.ResizeToContents)

        # Card: heading (title, count, total, ••• menu), table, "+ Add" row
        card = self._card = TableCard(t, "Equipment")
        card.count_rows()
        menu = QMenu(card)
        # even spacing: icon, gap, text and separator share the SP2/SP3 grid
        menu.setStyleSheet(
            f"QMenu {{ padding: {SP1}px; }}"
            f"QMenu::item {{ padding: {SP2}px {SP4}px {SP2}px {SP2}px; }}"
            f"QMenu::icon {{ padding-left: {SP3}px; }}"
            f"QMenu::separator {{ margin: {SP1}px {SP2}px; }}"
        )
        defaults_act = menu.addAction("Load defaults")
        defaults_act.triggered.connect(lambda checked=False: self.load_defaults(confirm=True))
        menu.addSeparator()
        clear_act = menu.addAction("Clear all items")
        clear_act.triggered.connect(lambda checked=False: self.clear_all())

        def _on_menu_show():  # icons follow the theme, so set them on open
            defaults_act.setIcon(make_icon("restore"))
            clear_act.setIcon(make_icon("trash", color=get_token("danger")))
            clear_act.setEnabled(bool(self._rows))
        menu.aboutToShow.connect(_on_menu_show)
        self.btn_more = card.set_menu(menu)

        self.btn_add = card.add_footer()
        self.btn_add.clicked.connect(lambda checked=False: self.add_row())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)
        self._render()

    # ── Rows ──────────────────────────────────────────────────────────────

    def _render(self):
        """Show self._rows in the table and the card, then report the total."""
        t = self._table
        _L = Qt.AlignLeft | Qt.AlignVCenter
        _R = Qt.AlignRight | Qt.AlignVCenter
        t.setRowCount(0)
        t.setRowCount(len(self._rows))
        for row, r in enumerate(self._rows):
            use = _consumption(r)
            unit = CONSUMPTION_UNIT.get(r["source"], "units")
            for col, (text, align) in enumerate((
                (r["name"], _L),
                (r["source"], _L),
                (fmt(r["rate"]), _R),
                (fmt(r["hrs"]), _R),
                (str(r["days"]), _R),
                (fmt(r["ef"]), _R),
                (f"{fmt_comma(use)} {unit}", _R),
                (fmt_comma(use * r["ef"]), _R),
                ("", _L),
            )):
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                t.setItem(row, col, item)

        t.updateGeometry()  # tell the page the table's height changed

        empty = not self._rows
        t.setVisible(not empty)  # no rows: just the heading and the Add row
        self.btn_add.setText("+  Add first equipment" if empty else "+  Add equipment")
        self._card.set_total(f"{fmt_comma(self.get_total())} kg CO₂e")
        self._on_change()

    def add_row(self):
        if self._frozen:
            return
        dlg = _EquipmentDialog(_clean_row({}), "Add Equipment", "Add",
                               [r["name"] for r in self._rows], self)
        if dlg.exec() == QDialog.Accepted:
            self._rows.append(dlg.values())
            self._render()

    def edit_row(self, row: int):
        if self._frozen or not (0 <= row < len(self._rows)):
            return
        dlg = _EquipmentDialog(self._rows[row], "Edit Equipment", "Save",
                               [r["name"] for i, r in enumerate(self._rows) if i != row], self)
        if dlg.exec() == QDialog.Accepted and dlg.values() != self._rows[row]:
            self._rows[row] = dlg.values()
            self._render()

    def delete_row(self, row: int):
        if 0 <= row < len(self._rows):
            del self._rows[row]
            self._render()

    def load_defaults(self, confirm: bool = False):
        if confirm and self._rows:
            reply = QMessageBox.question(
                self,
                "Load Defaults",
                "This will replace all current rows with the default equipment list.\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self._rows = [_clean_row(d) for d in DEFAULT_MACHINERY_DATA]
        self._render()

    def clear_all(self):
        if self._rows and confirm_clear_all(self):
            self._rows = []
            self._render()

    # ── Page interface ────────────────────────────────────────────────────

    def freeze(self, frozen: bool = True):
        self._frozen = frozen
        freeze_widgets(frozen, self.btn_add, self.btn_more)
        self._action_delegate.set_frozen(frozen)

    def get_total(self) -> float:
        return sum(_consumption(r) * r["ef"] for r in self._rows)

    def collect(self) -> dict:
        return {"rows": [dict(r) for r in self._rows]}

    def load(self, data: dict):
        self._rows = [_clean_row(d) for d in data.get("rows", [])]
        self._render()


# ── Main page ─────────────────────────────────────────────────────────────────


class MachineryEmissions(ScrollableForm):
    def __init__(self, controller=None):
        super().__init__(controller=controller, chunk_name=CHUNK)
        self._loading = False
        self._build_ui()
        self._loading = True
        self._detailed_table.load_defaults()
        self._loading = False
        self._on_totals_changed()
        if self.controller and hasattr(self.controller, "chunk_updated"):
            self.controller.chunk_updated.connect(self._on_chunk_updated)

    def _get_currency(self) -> str:
        if self.controller and self.controller.engine:
            info = self.controller.engine.fetch_chunk("general_info") or {}
            return str(info.get("currency", ""))
        return ""

    def _build_ui(self):
        f = self.form
        bold = QFont()
        bold.setBold(True)
        bold.setPointSize(FS_SECTION)

        # ── Grand total banner (top) ───────────────────────────────────────
        banner = QGroupBox()
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        self._lbl_grand_total = QLabel("<b>Total Machinery/Equipment Emissions:</b> - kg CO₂e")
        self._lbl_grand_total.setFont(bold)
        # note = QLabel(
        #     "  ⓘ  Fill either Detailed Equipment List or Lump Sum - not both."
        # )
        # note.setStyleSheet("color: gray; font-style: italic;")
        banner_layout.addWidget(self._lbl_grand_total)
        # banner_layout.addWidget(note)
        banner_layout.addStretch()
        f.addRow(banner)

        # ── Toggle ────────────────────────────────────────────────────────
        toggle_widget = QWidget()
        toggle_layout = QHBoxLayout(toggle_widget)
        toggle_layout.setContentsMargins(0, 4, 0, 4)
        self._radio_detailed = QRadioButton("Detailed Equipment List")
        self._radio_lumpsum = QRadioButton("Lump Sum")
        self._radio_detailed.setChecked(True)
        self._toggle_group = QButtonGroup(self)
        self._toggle_group.addButton(self._radio_detailed, 0)
        self._toggle_group.addButton(self._radio_lumpsum, 1)
        self._toggle_group.idToggled.connect(self._on_mode_toggled)
        toggle_layout.addWidget(QLabel("Input Method:"))
        toggle_layout.addSpacing(8)
        toggle_layout.addWidget(self._radio_detailed)
        toggle_layout.addSpacing(16)
        toggle_layout.addWidget(self._radio_lumpsum)
        toggle_layout.addStretch()
        f.addRow(toggle_widget)

        # ── Stack ─────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        # Index 0 - Detailed table
        detailed_widget = QWidget()
        detailed_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        detailed_vbox = QVBoxLayout(detailed_widget)
        detailed_vbox.setContentsMargins(0, 0, 0, 0)
        detailed_vbox.setSpacing(4)

        self._detailed_table = _DetailedTable(
            on_change=self._on_totals_changed,
        )
        detailed_vbox.addWidget(self._detailed_table)
        self._stack.addWidget(detailed_widget)

        # Index 1 - Lump Sum via build_form temp-swap
        lumpsum_widget = QWidget()
        lumpsum_layout = QFormLayout(lumpsum_widget)
        lumpsum_layout.setContentsMargins(0, 0, 0, 0)
        lumpsum_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        lumpsum_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lumpsum_layout.setFormAlignment(Qt.AlignTop | Qt.AlignLeft)
        lumpsum_layout.setVerticalSpacing(8)

        _saved = self.form
        self.form = lumpsum_layout
        build_form(self, LUMPSUM_ELEC_FIELDS)
        build_form(self, LUMPSUM_FUEL_FIELDS)
        self.form = _saved

        # Pop from _field_map - we save manually via collect_data
        # Wire valueChanged -> _on_totals_changed for live total update
        for key, default in _LUMPSUM_KEYS:
            self._field_map.pop(key, None)
            w = getattr(self, key, None)
            if w is not None:
                w.valueChanged.connect(self._on_totals_changed)

        # Set default EF values

        # Lump sum subtotal
        ls_total_row = QWidget()
        ls_total_layout = QHBoxLayout(ls_total_row)
        ls_total_layout.setContentsMargins(0, 8, 0, 4)
        self._lbl_lumpsum_total = QLabel(f"Lump Sum Subtotal: {fmt(0.0)} kg CO₂e")
        bold2 = QFont()
        bold2.setBold(True)
        self._lbl_lumpsum_total.setFont(bold2)
        ls_total_layout.addStretch()
        ls_total_layout.addWidget(self._lbl_lumpsum_total)
        lumpsum_layout.addRow(ls_total_row)

        self._stack.addWidget(lumpsum_widget)
        f.addRow(self._stack)
        self._shrink_stack_to_current()

        # ── Grand total (bottom) ───────────────────────────────────────────
        bottom_banner = QGroupBox()
        bottom_layout = QHBoxLayout(bottom_banner)
        bottom_layout.setContentsMargins(12, 8, 12, 8)
        self._lbl_grand_total_bottom = QLabel("<b>Total Machinery/Equipment Emissions:</b> - kg CO₂e")
        self._lbl_grand_total_bottom.setFont(bold)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self._lbl_grand_total_bottom)
        f.addRow(bottom_banner)

        # ── Remarks ───────────────────────────────────────────────────────
        self._remarks = RemarksEditor(
            title="Notes",
            on_change=self._on_field_changed,
        )
        f.addRow(self._remarks)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _lumpsum_elec_total(self) -> float:
        c = getattr(self, "elec_consumption_per_day", None)
        d = getattr(self, "elec_days", None)
        e = getattr(self, "elec_ef", None)
        return c.value() * d.value() * e.value() if c and d and e else 0.0

    def _lumpsum_fuel_total(self) -> float:
        c = getattr(self, "fuel_consumption_per_day", None)
        d = getattr(self, "fuel_days", None)
        e = getattr(self, "fuel_ef", None)
        return c.value() * d.value() * e.value() if c and d and e else 0.0

    def _current_mode(self) -> str:
        return "detailed" if self._radio_detailed.isChecked() else "lumpsum"

    # ── Slots ─────────────────────────────────────────────────────────────

    def _shrink_stack_to_current(self):
        """The stack is as tall as the page on show: QStackedLayout leaves
        Ignored pages out of its size, so it follows the current page as
        that page grows (no fixed cap to go stale when rows are added)."""
        idx = self._stack.currentIndex()
        for i in range(self._stack.count()):
            policy = QSizePolicy.Preferred if i == idx else QSizePolicy.Ignored
            self._stack.widget(i).setSizePolicy(policy, policy)
        self._stack.updateGeometry()

    def _on_mode_toggled(self, btn_id: int, checked: bool):
        if checked:
            self._stack.setCurrentIndex(btn_id)
            self._shrink_stack_to_current()
            self._on_totals_changed()

    def _on_totals_changed(self):
        if self._loading:
            return
        # Guard: may fire during build_form before all labels are created
        if not hasattr(self, "_lbl_grand_total_bottom"):
            return
        mode = self._current_mode()
        if mode == "detailed":
            total = self._detailed_table.get_total()
        else:
            total = self._lumpsum_elec_total() + self._lumpsum_fuel_total()
            self._lbl_lumpsum_total.setText(f"<b>Lump Sum Subtotal:</b> {fmt_comma(total)} kg CO₂e")

        text = f"<b>Total Machinery/Equipment Emissions:</b> {fmt_comma(total)} kg CO₂e"
        self._lbl_grand_total.setText(text)
        self._lbl_grand_total_bottom.setText(text)
        self._on_field_changed()

    # ── Currency ──────────────────────────────────────────────────────────

    def _apply_currency(self):
        currency = self._get_currency()
        note = f" (Currency: {currency})" if currency else ""
        self._lbl_grand_total.setToolTip(f"Total CO₂e emissions from machinery{note}")
        self._lbl_grand_total_bottom.setToolTip(
            f"Total CO₂e emissions from machinery{note}"
        )

    def _on_chunk_updated(self, chunk_name: str):
        if chunk_name == "general_info":
            self._apply_currency()

    # ── Data I/O ──────────────────────────────────────────────────────────

    def collect_data(self) -> dict:
        lumpsum = {}
        for key, default in _LUMPSUM_KEYS:
            w = getattr(self, key, None)
            if w is not None:
                lumpsum[key] = (
                    int(w.value()) if isinstance(w, QSpinBox) else float(w.value())
                )
            else:
                lumpsum[key] = default


        return {
            "mode": self._current_mode(),
            "default_days": (
                int(self.default_days.value()) if hasattr(self, "default_days") else 0
            ),
            "detailed": self._detailed_table.collect(),
            "lumpsum": lumpsum,
            "remarks": self._remarks.to_html() if hasattr(self, "_remarks") else "",
            "total_kgCO2e": round(
                (
                    self._detailed_table.get_total()
                    if self._current_mode() == "detailed"
                    else self._lumpsum_elec_total() + self._lumpsum_fuel_total()
                ),
                DECIMAL_PLACES,
            ),
        }

    def load_data(self, data: dict):
        if not data:
            return
        self._loading = True
        try:
            mode = data.get("mode", "detailed")
            self._radio_lumpsum.setChecked(mode == "lumpsum")
            self._radio_detailed.setChecked(mode != "lumpsum")
            self._stack.setCurrentIndex(1 if mode == "lumpsum" else 0)

            self._detailed_table.load(data.get("detailed", {}))

            if hasattr(self, "default_days"):
                self.default_days.blockSignals(True)
                self.default_days.setValue(int(data.get("default_days", 0)))
                self.default_days.blockSignals(False)

            ls = data.get("lumpsum", {})
            for key, default in _LUMPSUM_KEYS:
                w = getattr(self, key, None)
                if w is not None:
                    w.blockSignals(True)
                    val = ls.get(key, default)
                    w.setValue(int(val) if isinstance(w, QSpinBox) else float(val))
                    w.blockSignals(False)

            self._remarks.from_html(data.get("remarks", ""))
        finally:
            self._loading = False
        # Shrink/expand stack AFTER all rows are loaded so sizeHint is correct
        self._shrink_stack_to_current()
        self._on_totals_changed()

    # ── Base overrides ────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        # _shrink_stack_to_current() was last run in _build_ui(), before this
        # widget was ever shown/polished - the detailed table's sizeHint() can
        # be wrong at that point (e.g. an unpolished header height), capping
        # the stack too short and cramping the banners/margins around it until
        # something else (like a row-count change) reruns it. Rerun once here
        # too so the layout is correct from the very first paint, not only
        # after the user first interacts with the table.
        self._shrink_stack_to_current()

    def _on_field_changed(self):
        if self._loading:
            return
        if self.controller and self.controller.engine and self.chunk_name:
            self.controller.engine.stage_update(
                chunk_name=self.chunk_name, data=self.collect_data()
            )
        self.data_changed.emit()

    def get_data_dict(self) -> dict:
        return self.collect_data()

    def load_data_dict(self, data: dict):
        self.load_data(data)

    def refresh_from_engine(self):
        if not self.controller or not self.controller.engine:
            return
        if not self.controller.engine.is_active() or not self.chunk_name:
            return
        data = self.controller.get_chunk(self.chunk_name)
        if not data or data == self._loaded_data:
            return
        self._loaded_data = data
        self.load_data(data)
        self._apply_currency()

    def on_refresh(self):
        if not self.controller or not getattr(self.controller, "engine", None):
            return
        data = self.controller.get_chunk(CHUNK) or {}
        self.load_data(data)
        self._apply_currency()

    def validate(self) -> dict:
        data = self.collect_data()
        warnings = []
        total = data.get("total_kgCO2e", 0.0)
        if total == 0.0:
            mode = data.get("mode", "")
            if mode == "detailed":
                warnings.append(
                    "Total machinery/equipment emissions is 0 kgCO₂e - "
                    "no equipment rows have been added, or fuel consumption and operating hours are zero for all entries; add equipment details or check existing entries"
                )
            else:
                warnings.append(
                    "Total machinery/equipment emissions is 0 kgCO₂e - "
                    "both lumpsum fuel consumption and electricity consumption are zero; enter at least one positive value to calculate machinery emissions"
                )
        if data.get("mode") == "detailed":
            # the dialog's checks again, against the project as it is now
            # (the construction period may have changed since a row was added)
            rows = data["detailed"]["rows"]
            max_days = _construction_days()
            for i, r in enumerate(rows):
                others = [o["name"] for j, o in enumerate(rows) if j != i]
                errors = [msg for level, _, msg in check_equipment(r, others, max_days) if level == "error"]
                if errors:
                    warnings.append(f"Equipment \"{r['name'] or i + 1}\": {errors[0]}")
        return {"errors": [], "warnings": warnings}

    def freeze(self, frozen: bool = True):
        self._radio_detailed.setEnabled(not frozen)
        self._radio_lumpsum.setEnabled(not frozen)
        self._detailed_table.freeze(frozen)
        for key, _ in _LUMPSUM_KEYS:
            w = getattr(self, key, None)
            if w is not None:
                w.setEnabled(not frozen)
        if hasattr(self, "default_days"):
            self.default_days.setEnabled(not frozen)
        self._remarks.freeze(frozen)

    def get_data(self) -> dict:
        return {"chunk": CHUNK, "data": self.get_data_dict()}


