"""
gui/components/structure/widgets/material_dialog.py
====================================================
MaterialDialog and its helper classes / functions.
Extracted from manager.py so it can be imported by other modules
(carbon_emission, recycling, etc.) without pulling in StructureManagerWidget.
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QDialog,
    QLineEdit,
    QFrame,
    QLabel,
    QMessageBox,
    QCheckBox,
    QComboBox,
    QCompleter,
    QScrollArea,
)
from PySide6.QtCore import Qt, QUrl, QStringListModel, Signal, QTimer
from PySide6.QtGui import (
    QDoubleValidator,
    QDesktopServices,
    QStandardItemModel,
    QStandardItem,
)

from ...utils.definitions import (
    _CONSTRUCTION_UNITS,
    UNIT_TO_SI,
    UNIT_DIMENSION,
    SI_BASE_UNITS,
    UNIT_DISPLAY,
)
from ...utils.display_format import fmt, fmt_comma
from ...utils.unit_resolver import (
    get_custom_units,
    load_custom_units,
    _UNIT_ALIASES as _SOR_UNIT_ALIASES,
)
from ...utils.input_fields.add_material import FIELD_DEFINITIONS
from ...utils.form_builder.form_builder import _PLACEHOLDER
from ...utils.unit_resolver import get_unit_info as _get_unit_info_impl, suggest_cf
from ...utils.doc_link import doc_inline, doc_label
from ..registry.material_catalog import list_databases
from ..registry.search_engine import MaterialSearchEngine, AdvancedSearchEngine, _component_matches

import os
import uuid as _uuid_mod

from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.theme import FS_MD, FS_MD, FS_SM

try:
    from ..registry.custom_material_db import CustomMaterialDB, CUSTOM_PREFIX
except ImportError:
    CustomMaterialDB = None
    CUSTOM_PREFIX = "custom::"

DECIMAL_PLACES_CUSTOM = 5

# ---------------------------------------------------------------------------
# Info Popup
# ---------------------------------------------------------------------------


class InfoPopup(QDialog):
    def __init__(self, field_key: str, parent=None):
        super().__init__(parent)
        defn = FIELD_DEFINITIONS.get(field_key, {})

        self.setWindowTitle(defn.get("label", field_key))
        self.setMinimumWidth(360)
        self.setMaximumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(420, 260)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title_lbl = QLabel(f"<b>{defn.get('label', field_key)}</b>")
        title_lbl.setStyleSheet(f"font-size: {FS_MD}pt;")
        layout.addWidget(title_lbl)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        doc_slug = defn.get("doc_slug", [])
        expl = defn.get("explanation", "No description available.")
        html = expl + (" " + doc_inline(doc_slug, "Read More →") if doc_slug else "")
        expl_lbl = doc_label(html)
        expl_lbl.setStyleSheet(f"font-size: {FS_MD}pt;")
        layout.addWidget(expl_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


# ---------------------------------------------------------------------------
# Shared UI helpers
# ---------------------------------------------------------------------------




def _section_header(title: str) -> QLabel:
    lbl = QLabel(f"<b>{title}</b>")
    lbl.setStyleSheet(f"font-size: {FS_MD}pt; margin-top: 4px;")
    return lbl


def _lbl(text: str, key: str = "") -> QLabel:
    slug = FIELD_DEFINITIONS.get(key, {}).get("doc_slug", []) if key else []
    if slug:
        lbl = doc_label(f'<span style="font-weight:600;font-size:{FS_SM}pt;">{text}</span> {doc_inline(slug)}')
    else:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-weight: 600; font-size: {FS_SM}pt;")
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


# ---------------------------------------------------------------------------
# CustomUnitDialog
# ---------------------------------------------------------------------------


class CustomUnitDialog(QDialog):
    # (dimension label, SI base unit code, display symbol, placeholder example, note)
    _DIMS = [
        ("Mass", "kg", "kg", "e.g. 50  (1 bag = 50 kg)", "SI base: kilogram (kg)"),
        ("Length", "m", "m", "e.g. 0.3048  (1 ft = 0.3048 m)", "SI base: meter (m)"),
        (
            "Area",
            "m2",
            "m²",
            "e.g. 25.29  (1 perch = 25.29 m²)",
            "SI base: square meter (m²)",
        ),
        (
            "Volume",
            "m3",
            "m³",
            "e.g. 0.0283  (1 cft = 0.0283 m³)",
            "SI base: cubic meter (m³)",
        ),
        (
            "Count",
            "nos",
            "nos",
            "e.g. 100  (1 bundle = 100 nos)",
            "SI base: number (nos)",
        ),
    ]

    def __init__(self, parent=None, existing_symbols: list | None = None):
        super().__init__(parent)
        self._existing_symbols = {s.lower() for s in (existing_symbols or [])}

        self.setWindowTitle("Add Custom Unit")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)

        dbl = QDoubleValidator()
        dbl.setBottom(1e-12)
        dbl.setNotation(QDoubleValidator.StandardNotation)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "Define a custom unit by selecting its dimension and providing "
            "its equivalent in the SI base unit."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: {FS_SM}pt; color: {get_token('text_secondary')};")
        layout.addWidget(desc)

        # ── Symbol + Name ─────────────────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        sym_col = QVBoxLayout()
        sym_col.setSpacing(3)
        sym_col.addWidget(_lbl("Symbol *"))
        self.symbol_in = QLineEdit()
        self.symbol_in.setPlaceholderText("e.g. bag, rft, perch")
        self.symbol_in.setMinimumHeight(32)
        sym_col.addWidget(self.symbol_in)
        row1.addLayout(sym_col, stretch=1)

        name_col = QVBoxLayout()
        name_col.setSpacing(3)
        name_col.addWidget(_lbl("Name (optional)"))
        self.name_in = QLineEdit()
        self.name_in.setPlaceholderText("e.g. Cement Bag")
        self.name_in.setMinimumHeight(32)
        name_col.addWidget(self.name_in)
        row1.addLayout(name_col, stretch=2)

        layout.addLayout(row1)

        # ── Dimension selector ────────────────────────────────────────────────
        layout.addWidget(_lbl("Dimension *"))
        self.dim_cb = QComboBox()
        self.dim_cb.setMinimumHeight(32)
        self.dim_cb.wheelEvent = lambda event: event.ignore()
        for dim_label, si_code, si_sym, _, _ in self._DIMS:
            self.dim_cb.addItem(f"{dim_label}  (SI base: {si_sym})", dim_label)
        layout.addWidget(self.dim_cb)

        # ── SI equivalent row ─────────────────────────────────────────────────
        layout.addWidget(_lbl("SI Equivalent *"))
        conv_row = QHBoxLayout()
        conv_row.setSpacing(8)
        self.conv_prefix_lbl = QLabel("1 unit  =")
        self.conv_prefix_lbl.setStyleSheet(f"color: {get_token('text_secondary')}; font-size: {FS_MD}pt;")
        conv_row.addWidget(self.conv_prefix_lbl)
        self.conv_in = QLineEdit()
        self.conv_in.setMinimumHeight(32)
        self.conv_in.setValidator(dbl)
        conv_row.addWidget(self.conv_in, stretch=1)
        self.si_sym_lbl = QLabel("kg")
        self.si_sym_lbl.setStyleSheet(
            f"background: {get_token('surface')}; color: {get_token('text_secondary')}; padding: 4px 8px; "
            f"border: 1px solid {get_token('surface_mid')}; border-radius: 4px; font-size: {FS_MD}pt;"
        )
        self.si_sym_lbl.setMinimumHeight(32)
        self.si_sym_lbl.setMinimumWidth(48)
        self.si_sym_lbl.setAlignment(Qt.AlignCenter)
        conv_row.addWidget(self.si_sym_lbl)
        layout.addLayout(conv_row)

        # ── Live preview ──────────────────────────────────────────────────────
        self.preview_lbl = QLabel("")
        self.preview_lbl.setStyleSheet(
            f"font-size: {FS_MD}pt; color: {get_token('success')}; background: {get_token('success', 'pressed')}; "
            f"padding: 6px 10px; border-radius: 4px;"
        )
        self.preview_lbl.setWordWrap(True)
        self.preview_lbl.setVisible(False)
        layout.addWidget(self.preview_lbl)

        # ── Note ──────────────────────────────────────────────────────────────
        self._note_lbl = QLabel("")
        self._note_lbl.setStyleSheet(f"font-size: {FS_SM}pt; color: {get_token('text_disabled')};")
        self._note_lbl.setWordWrap(True)
        layout.addWidget(self._note_lbl)

        layout.addStretch()

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add Unit")
        self._add_btn.setStyleSheet("font-weight: bold; padding: 6px 20px;")
        self._add_btn.setMinimumHeight(32)
        self._add_btn.clicked.connect(self._validate_and_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Wire signals ──────────────────────────────────────────────────────
        self.dim_cb.currentIndexChanged.connect(self._on_dim_changed)
        self.symbol_in.textChanged.connect(self._update_preview)
        self.conv_in.textChanged.connect(self._update_preview)

        self._on_dim_changed(0)  # initialise labels for Mass

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_dim_changed(self, idx: int):
        if idx < 0 or idx >= len(self._DIMS):
            return
        _, _, si_sym, placeholder, note = self._DIMS[idx]
        self.si_sym_lbl.setText(si_sym)
        self.conv_in.setPlaceholderText(placeholder.split("(")[0].strip())
        self._note_lbl.setText(note)
        self._update_preview()

    def _update_preview(self):
        sym = self.symbol_in.text().strip()
        raw = self.conv_in.text().strip()
        idx = self.dim_cb.currentIndex()

        # Update "1 <symbol> =" prefix
        self.conv_prefix_lbl.setText(f"1 {sym}  =" if sym else "1 unit  =")

        if not sym or not raw:
            self.preview_lbl.setVisible(False)
            return

        try:
            val = float(raw)
            if val <= 0:
                raise ValueError
        except ValueError:
            self.preview_lbl.setVisible(False)
            return

        _, _, si_sym, _, _ = self._DIMS[idx]
        self.preview_lbl.setText(f"1 {sym} = {val:g} {si_sym}")
        self.preview_lbl.setVisible(True)

    # ── Validation & output ───────────────────────────────────────────────────

    def _validate_and_accept(self):
        sym = self.symbol_in.text().strip()
        if not sym:
            QMessageBox.critical(self, "Error", "Symbol is required.")
            return

        if sym.lower() in self._existing_symbols:
            QMessageBox.critical(
                self,
                "Symbol Already Exists",
                f'"{sym}" is already defined. Choose a different symbol.',
            )
            return

        raw = self.conv_in.text().strip()
        try:
            val = float(raw)
            if val <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.critical(
                self, "Invalid Value", "SI equivalent must be a positive number."
            )
            return

        self.accept()

    def get_unit(self) -> dict:
        idx = self.dim_cb.currentIndex()
        dim_label, si_code, si_sym, _, _ = self._DIMS[max(idx, 0)]
        return {
            "symbol": self.symbol_in.text().strip(),
            "name": self.name_in.text().strip(),
            "dimension": dim_label,
            "to_si": float(self.conv_in.text()),
            "si_unit": si_code,
        }


# ---------------------------------------------------------------------------
# SOR / registry helpers
# ---------------------------------------------------------------------------


def _unit_sym(code: str) -> str:
    """
    Return the pretty display symbol for a unit code.
    Handles compound codes like 'm2-mm' → 'm²-mm' by prettifying each
    dash-separated part individually.
    """
    if not code:
        return "unit"

    code = code.replace(" ", "").strip()

    if code in UNIT_DISPLAY:
        return UNIT_DISPLAY[code]

    # Compound unit - prettify each part separated by '-'
    parts = code.split("-")
    if len(parts) > 1:
        return "-".join(UNIT_DISPLAY.get(p, p) for p in parts)

    return code


def _resolve_unit_code(sor_unit: str, combo: "QComboBox") -> int:
    """
    Find the combo index for sor_unit.  If no standard match is found and
    add_if_missing=True (default), the raw unit string is appended as a
    plain-text fallback item so compound units like 'sqm-mm' are preserved.
    """
    if not sor_unit:
        return -1
    idx = combo.findData(sor_unit)
    if idx >= 0:
        return idx
    lower = sor_unit.lower()
    idx = combo.findData(lower)
    if idx >= 0:
        return idx
    alias = _SOR_UNIT_ALIASES.get(lower)
    if alias:
        idx = combo.findData(alias)
        if idx >= 0:
            return idx
    # Unit not in the standard list - append it so it isn't silently dropped.
    combo.addItem(_unit_sym(sor_unit), sor_unit)
    return combo.count() - 1


def _list_sor_options(country: str = None) -> list[dict]:
    result = []
    try:
        raw = list_databases(country=country.strip() if country else None)
        for e in raw:
            if e.get("status") != "OK":
                continue
            region = e.get("region", "")
            result.append(
                {"db_key": e["db_key"], "region": region, "label": e["db_key"]}
            )
    except Exception as ex:
        print(f"[MaterialDialog] Could not list SOR options: {ex}")

    try:
        if CustomMaterialDB is not None:
            cdb = CustomMaterialDB()
            for db_name in cdb.list_db_names():
                result.append(
                    {
                        "db_key": f"{CUSTOM_PREFIX}{db_name}",
                        "region": "Custom",
                        "label": f"{db_name}  (Custom)",
                    }
                )
    except Exception as ex:
        print(f"[MaterialDialog] Could not list custom databases: {ex}")

    return result


def _list_sor_sheet_components(db_keys: list = None) -> list[tuple[str, str]]:
    """Return sorted [(component, sheetName), ...] pairs from loaded databases."""
    try:
        available = [
            e["db_key"]
            for e in list_databases()
            if e.get("status") == "OK" and (db_keys is None or e["db_key"] in db_keys)
        ]
        if not available:
            return []
        engine = MaterialSearchEngine(db_keys=db_keys)
        return engine.list_sheet_components()
    except Exception:
        return []


_REQUIRED_ITEM_KEYS = (
    "name",
    "unit",
    "rate",
    "rate_src",
    "carbon_emission",
    "carbon_emission_units_den",
    "conversion_factor",
    "carbon_emission_src",
)
_ITEM_DEFAULTS = {
    "rate": None,
    "rate_src": None,
    "carbon_emission": None,
    "carbon_emission_units_den": None,
    "conversion_factor": None,
    "carbon_emission_src": None,
}


def _validate_item(item: dict) -> bool:
    """
    Ensure item has all required schema keys, filling optional ones with
    'not_available' defaults rather than dropping the item entirely.
    Returns False only if the truly essential keys (name, unit) are missing.
    """
    if not item.get("name") or not item.get("unit"):
        return False
    for key, default in _ITEM_DEFAULTS.items():
        item.setdefault(key, default)
    return True


def _num(value):
    """A number from a field's text (or a number); None when blank or not a number."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def name_key(name) -> str:
    """A material name as duplicate checks compare it: case and spacing
    ignored ("  Abc   def " is "abc def"); the saved name is not changed."""
    return " ".join(str(name or "").split()).lower()


def _field_text(value) -> str:
    """A stored value as field text, in full: 0 stays "0", 12.345 is not rounded."""
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value).strip()


def check_material(
    name, unit, quantity, rate, carbon_on, carbon_den, emission, conversion,
    recycle_on, scrap, recovery,
) -> list[tuple[str, str, str, str | None]]:
    """The Add Material rules, in the order the dialog asks them.

    Each problem is (level, title, message, turns_off):
      "error"   - cannot be saved
      "warning" - saved only if the user continues; *turns_off* names the
                  section ("carbon" / "recycle") that is then left out
    Shared by MaterialDialog and the Excel import, so both check the same.
    """
    problems = []
    if not str(name or "").strip():
        problems.append(("error", "Validation Error", "Material Name is required.", None))
    if not str(unit or "").strip():
        problems.append(("error", "Validation Error", "Please select a unit.", None))
    if (_num(quantity) or 0) <= 0:
        problems.append(("error", "Validation Error", "Quantity must be greater than zero.", None))

    if str(rate if rate is not None else "").strip() == "":
        problems.append(("error", "Validation Error", "Rate (unit cost) is required.", None))
    else:
        rate_val = _num(rate) or 0
        if rate_val < 0:
            problems.append(("error", "Validation Error", "Rate cannot be negative.", None))
        elif rate_val == 0:
            problems.append(("warning", "Rate",
                             "Rate (unit cost) is 0 - this material will contribute no cost.", None))

    if carbon_on:
        if not str(carbon_den or "").strip():
            problems.append(("error", "Validation Error",
                             "Please select a unit for the emission factor denominator.", None))
        ef, cf = _num(emission), _num(conversion)
        if ef is None or ef <= 0:
            problems.append(("warning", "Emission Factor",
                             "Emission factor is 0 or blank - carbon cost will be skipped.", "carbon"))
        elif cf is None or cf <= 0:
            if suggest_cf(unit or "", carbon_den or "") != 1.0:
                # different units cannot be compared without a factor
                problems.append(("error", "Validation Error",
                                 "Conversion factor is required when the material unit "
                                 "and the carbon unit differ.", None))
            else:
                problems.append(("warning", "Conversion Factor",
                                 "Conversion factor is 0 or blank - carbon cost will be skipped.", "carbon"))
        else:
            _, mat_dim = _get_unit_info_impl(unit or "")
            _, den_dim = _get_unit_info_impl(carbon_den or "")
            if mat_dim != den_dim and abs(cf - 1.0) < 1e-6:
                problems.append(("warning", "Check Conversion Factor",
                                 f"Unit mismatch: material is {mat_dim}, carbon unit is {den_dim}.\n"
                                 "Conversion factor is 1.0 - is this correct?", None))

    if recycle_on:
        scrap_val, recovery_val = _num(scrap), _num(recovery)
        if (recovery_val or 0) > 100:
            problems.append(("error", "Validation Error", "Recovery percentage cannot exceed 100%.", None))
        scrap_none = scrap_val is None or scrap_val <= 0
        recovery_none = recovery_val is None or recovery_val <= 0
        if scrap_none and recovery_none:
            detail = (
                "Both scrap rate and recovery percentage are blank"
                if scrap_val is None and recovery_val is None
                else "Both scrap rate and recovery percentage are zero or blank"
            )
            problems.append(("warning", "Recyclability",
                             f"{detail} - recyclability will be excluded.", "recycle"))
    return problems


def build_excel_snapshot(values_dict: dict) -> dict:
    """
    Build a complete snapshot from an Excel-imported values_dict.
    Captures all parsed fields to ensure 100% data parity for audit logs.
    Blank strings are normalized to None so db_original stays consistent
    with the values dict.
    """
    snapshot = {}
    for k, v in values_dict.items():
        if k.startswith("_"):
            continue
        snapshot[k] = None if (isinstance(v, str) and v.strip() == "") else v
    snapshot["action"] = "excel"
    return snapshot


def convert_sor_item_to_material(dict_b: dict) -> dict:
    """
    Convert a raw SOR/database item (dict_b) into a fully structured material
    entry ready for storage.  The returned dict follows the canonical
    {id, values, meta, state} schema.

    Consumed by the dialog autofill pipeline (future step).
    """
    def _valid(val):
        return val not in (None, "", 0, 0.0)

    carbon_eligible = all(
        _valid(dict_b.get(k))
        for k in ("carbon_emission", "carbon_emission_units_den", "conversion_factor")
    )

    raw_key = dict_b.get("db_key") or ""
    is_custom = raw_key.startswith("custom::")
    source = "custom_db" if is_custom else "db"
    source_db_key = raw_key.removeprefix("custom::")

    values = {
        "material_name": dict_b.get("name", ""),
        "quantity": None,
        "unit": dict_b.get("unit"),
        "unit_to_si": 1.0,
        "rate": dict_b.get("rate") if _valid(dict_b.get("rate")) else None,
        "rate_source": dict_b.get("rate_src", "") if _valid(dict_b.get("rate_src")) else "",
        "carbon_emission": dict_b.get("carbon_emission") if _valid(dict_b.get("carbon_emission")) else None,
        "carbon_unit": (
            f"kgCO₂e/{dict_b.get('carbon_emission_units_den')}"
            if _valid(dict_b.get("carbon_emission_units_den"))
            else None
        ),
        "carbon_emission_src": dict_b.get("carbon_emission_src", "") if _valid(dict_b.get("carbon_emission_src")) else "",
        "conversion_factor": dict_b.get("conversion_factor") if _valid(dict_b.get("conversion_factor")) else None,
        "scrap_rate": None,
        "post_demolition_recovery_percentage": None,
    }
    state = {
        "in_trash": False,
        "included_in_carbon_emission": carbon_eligible,
        "included_in_recyclability": False,
        "allow_edit_checked": False,
    }
    db_original = {
        **dict_b,
        "action": "custom_db" if is_custom else "internal_db",
        "db_key": raw_key,
    }
    return {
        "id": str(_uuid_mod.uuid4()),
        "values": values,
        "meta": {
            "source": source,
            "source_db_key": source_db_key,
            "db_original": db_original,
            "defaults": {"values": dict(values), "state": dict(state)},
        },
        "state": state,
    }


def _load_material_suggestions(db_keys: list = None, comp_name: str = None, sheet_name: str = None) -> dict:
    if db_keys is not None:
        regular_keys = [k for k in db_keys if not k.startswith("custom::")]
        custom_names = [
            k[len("custom::") :] for k in db_keys if k.startswith("custom::")
        ]
        load_all_custom = False
    else:
        regular_keys = None
        custom_names = []
        load_all_custom = True

    result = {}
    comp_lower = comp_name.strip().lower() if comp_name else None

    skip_regular = db_keys is not None and not regular_keys
    if not skip_regular:
        try:
            _available = [
                e["db_key"]
                for e in list_databases()
                if e.get("status") == "OK"
                and (regular_keys is None or e["db_key"] in regular_keys)
            ]
            if not _available:
                skip_regular = True
        except Exception:
            skip_regular = True

    if not skip_regular:
        try:
            engine = MaterialSearchEngine(db_keys=regular_keys)

            if comp_lower:
                for item in engine._iter_items(category=sheet_name, component=comp_lower):
                    if not _validate_item(item):
                        print(
                            f"[MaterialDialog] Skipping item with missing schema keys: {item.get('name', '<unnamed>')}"
                        )
                        continue
                    name = item.get("name", "").strip()
                    if name:
                        result[name] = item
                if not result:
                    for item in engine._iter_items():
                        if not _validate_item(item):
                            continue
                        name = item.get("name", "").strip()
                        if name:
                            result[name] = item
            else:
                for item in engine._iter_items(category=sheet_name):
                    if not _validate_item(item):
                        print(
                            f"[MaterialDialog] Skipping item with missing schema keys: {item.get('name', '<unnamed>')}"
                        )
                        continue
                    name = item.get("name", "").strip()
                    if name:
                        result[name] = item
        except Exception as e:
            print(f"[MaterialDialog] Could not load material suggestions: {e}")

    if load_all_custom or custom_names:
        try:
            cdb = CustomMaterialDB()
            names_to_load = cdb.list_db_names() if load_all_custom else custom_names
            for db_name in names_to_load:
                for item in cdb.get_items(db_name):
                    if not _validate_item(item):
                        print(
                            f"[MaterialDialog] Skipping custom item with missing schema keys: {item.get('name', '<unnamed>')}"
                        )
                        continue
                    name = item.get("name", "").strip()
                    if not name:
                        continue
                    if comp_lower:
                        if not _component_matches(item.get("component"), comp_lower):
                            continue
                    result[name] = item
        except Exception as e:
            print(f"[MaterialDialog] Could not load custom material suggestions: {e}")

    return result


# ---------------------------------------------------------------------------
# _SaveToCustomDBDialog
# ---------------------------------------------------------------------------


class _SaveToCustomDBDialog(QDialog):
    def __init__(self, existing_db_names: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save to Custom Database")
        self.setMinimumWidth(360)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        layout.addWidget(
            QLabel(
                "Select an existing database or type a new name\n"
                "(e.g. biharSOR-2026, MyMaterials):"
            )
        )

        self.db_combo = QComboBox()
        self.db_combo.setEditable(True)
        self.db_combo.setMinimumHeight(32)
        self.db_combo.addItems(existing_db_names)
        self.db_combo.setCurrentIndex(-1)
        if self.db_combo.lineEdit():
            self.db_combo.lineEdit().setPlaceholderText("e.g. biharSOR-2026")
        layout.addWidget(self.db_combo)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setDefault(True)
        save_btn.setMinimumHeight(32)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_save(self):
        if not self.selected_name():
            QMessageBox.warning(self, "Missing Name", "Enter a database name to continue.")
            return
        self.accept()

    def selected_name(self) -> str:
        return self.db_combo.currentText().strip()


# ---------------------------------------------------------------------------
# Migration helper - moves custom units embedded in old project data → DB
# ---------------------------------------------------------------------------


def _migrate_embedded_custom_units(values: dict) -> None:
    """If *values* contains a legacy '_custom_units' list (old per-material
    storage), save any unknown symbols to the global DB and refresh the cache.
    Safe to call on every dialog open; does nothing when no legacy data exists.
    """
    raw = values.get("_custom_units") or values.get("_custom_unit")
    if not raw:
        return
    units = [raw] if isinstance(raw, dict) else list(raw)
    if not units:
        return

    known = {c["symbol"] for c in get_custom_units()}
    new_units = [u for u in units if u.get("symbol") and u["symbol"] not in known]
    if not new_units:
        return

    try:
        if CustomMaterialDB is None:
            raise ImportError("custom_material_db not available")
        cdb = CustomMaterialDB()
        for u in new_units:
            cdb.save_custom_unit(u)
        load_custom_units()  # refresh global cache
    except Exception as exc:
        print(f"[MaterialDialog] Custom unit migration failed: {exc}")


# ---------------------------------------------------------------------------
# MaterialDialog
# ---------------------------------------------------------------------------


class MaterialDialog(QDialog):
    _CUSTOM_CODE = "__custom__"
    _NO_SUGGESTIONS_CODE = "__no_suggestions__"

    material_added = Signal(dict)

    def __init__(
        self,
        comp_name: str,
        parent=None,
        data: dict = None,
        emissions_only: bool = False,
        recyclability_only: bool = False,
        country: str = None,
        sor_db_key: str = None,
        search_cat: dict = None,
        show_sor_info: bool = True,  # False: no "Suggestions from" row (Excel import)
    ):
        super().__init__(parent)
        self.is_edit = data is not None
        self.emissions_only = emissions_only
        self.recyclability_only = recyclability_only
        self._comp_name = comp_name
        self._search_cat = search_cat  # {"component": ..., "sheet": ...} or None
        self._sor_item = None
        self._sor_filled_name = None  # name that triggered the last autofill
        self._sor_filling = False
        self._pre_allow_edit_source = None  # saved when "Allow editing" is checked
        self._sor_carbon_available = True  # False when SOR has no carbon data
        self._db_original = {}  # immutable snapshot of DB values at suggestion time

        mat_name = (
            data.get("values", {}).get("material_name", "") if data else ""
        ) or comp_name
        if recyclability_only:
            self.setWindowTitle(f"Edit Recyclability - {mat_name}")
        elif emissions_only:
            self.setWindowTitle(f"Edit Emission Data - {mat_name}")
        elif self.is_edit:
            self.setWindowTitle(f"Edit Material - {comp_name}")
        else:
            self.setWindowTitle(f"Add Material - {comp_name}")
        self.setMinimumWidth(680)
        self.resize(720, 640)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        v = data.get("values", {}) if self.is_edit else {}
        s = data.get("state", {}) if self.is_edit else {}
        # The snapshot saved when this material was first added. Its "action"
        # (internal_db, custom_db, excel) is where the material came from;
        # no snapshot means it was typed in by hand.
        _meta = data.get("meta", {}) if data else {}
        self._meta = _meta
        self._db_original = _meta.get("db_original") or {}
        _origin = self._db_original.get("action", "")

        # Migrate any custom units embedded in old project data → global DB
        _migrate_embedded_custom_units(v)

        dbl = QDoubleValidator()
        dbl.setBottom(0.0)
        dbl.setNotation(QDoubleValidator.StandardNotation)
        dbl.setDecimals(DECIMAL_PLACES_CUSTOM)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(20, 16, 20, 12)
        root.setSpacing(10)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        # SOR database is selected project-wide (General Info → Project Settings).
        self.sor_cb = None
        self._sor_db_key = (sor_db_key or "").strip()

        # ── Active SOR info label ─────────────────────────────────────────
        if show_sor_info and not (emissions_only or recyclability_only):
            sor_info_row = QHBoxLayout()
            sor_info_row.setContentsMargins(0, 0, 0, 0)
            sor_info_row.setSpacing(4)
            sor_info_row.addWidget(QLabel("Suggestions from:"))

            if not self._sor_db_key:
                # Not configured at all
                _sor_text  = "─  not set  (configure in Project Settings)"
                _sor_style = (
                    f"font-size: {FS_SM}pt; color: {get_token('text_secondary')};"
                    f" font-style: italic;"
                )
            else:
                # Check if the key actually exists in the registry / custom DB
                _is_custom = self._sor_db_key.startswith("custom::")
                if _is_custom:
                    try:
                        _cdb_name = self._sor_db_key[len("custom::"):]
                        _db_valid = (
                            CustomMaterialDB is not None
                            and _cdb_name in CustomMaterialDB().list_db_names()
                        )
                    except Exception:
                        _db_valid = False
                else:
                    try:
                        _db_valid = any(
                            e.get("db_key") == self._sor_db_key
                            and e.get("status") == "OK"
                            for e in list_databases()
                        )
                    except Exception:
                        _db_valid = False

                if _db_valid:
                    _sor_text  = self._sor_db_key
                    _sor_style = (
                        f"font-size: {FS_SM}pt; color: {get_token('text_secondary')};"
                        f" font-style: italic;"
                    )
                else:
                    _sor_text  = f"⚠  \"{self._sor_db_key}\"  —  database not found"
                    _sor_style = (
                        f"font-size: {FS_SM}pt; color: {get_token('danger')};"
                        f" font-weight: 600;"
                    )

            sor_val_lbl = QLabel(_sor_text)
            sor_val_lbl.setStyleSheet(_sor_style)
            sor_val_lbl.setWordWrap(True)
            sor_info_row.addWidget(sor_val_lbl, stretch=1)
            root.addLayout(sor_info_row)

        # ── Sub-category filter ───────────────────────────────────────────
        self.type_filter_cb = None
        if self._sor_db_key and not (emissions_only or recyclability_only):
            sub_row = QHBoxLayout()
            sub_row.setContentsMargins(0, 0, 0, 0)
            sub_row.setSpacing(8)
            sub_lbl = QLabel("Search Category:")
            sub_lbl.setStyleSheet(f"font-size: {FS_SM}pt; color: {get_token('text_secondary')};")
            sub_row.addWidget(sub_lbl)
            self.type_filter_cb = QComboBox()
            self.type_filter_cb.setMinimumHeight(26)
            self.type_filter_cb.wheelEvent = lambda event: event.ignore()
            sub_row.addWidget(self.type_filter_cb, stretch=1)
            root.addLayout(sub_row)
            self._populate_type_filter(search_cat=self._search_cat or {"component": comp_name})
            self.type_filter_cb.currentIndexChanged.connect(
                self._on_type_filter_changed
            )

        # ── Material Name (Always visible) ────────────────────────────────
        root.addWidget(_lbl("Material Name *", "material_name"))
        self.name_in = QLineEdit(v.get("material_name", ""))
        self.name_in.setPlaceholderText(
            "e.g. Ready-mix Concrete M25  (Type ? to browse all)"
        )
        self.name_in.setMinimumHeight(32)
        root.addWidget(self.name_in)

        # ── Item ID (Always visible) ──────────────────────────────────────
        root.addWidget(_lbl("Item ID / SOR Code"))
        _id_val = v.get("src_id") or _meta.get("db_original", {}).get("src_id", "")
        self.id_in = QLineEdit(str(_id_val) if _id_val else "")
        self.id_in.setPlaceholderText("e.g. 12.01 (Leave blank for manual)")
        self.id_in.setMinimumHeight(32)
        root.addWidget(self.id_in)

        # ── Completer ─────────────────────────────────────────────────────
        self._suggestions = {}
        self._active_completer = None
        self._skip_suggestions = False
        self._ui_ready = False
        self._user_edited_snapshot = {}  # saved when user unchecks "Allow editing"
        self._reload_suggestions()
        self.name_in.textEdited.connect(self._on_name_search_changed)
        if self.sor_cb:
            self.sor_cb.currentIndexChanged.connect(self._on_sor_changed)

        self._skip_btn = None

        # ── Allow-edit checkbox ───────────────────────────────────────────
        self._allow_edit_chk = QCheckBox("Allow editing DB-filled values")
        self._allow_edit_chk.setEnabled(False)
        self._allow_edit_chk.toggled.connect(self._on_allow_edit_toggled)
        root.addWidget(self._allow_edit_chk)

        # ── Quantity + Unit ───────────────────────────────────────────────
        qty_unit_row = QHBoxLayout()
        qty_unit_row.setSpacing(12)

        qty_col = QVBoxLayout()
        qty_col.setSpacing(3)
        qty_col.addWidget(_lbl("Quantity *", "quantity"))
        self.qty_in = QLineEdit(_field_text(v.get("quantity")))
        self.qty_in.setPlaceholderText("e.g. 100")
        self.qty_in.setMinimumHeight(32)
        self.qty_in.setValidator(dbl)
        qty_col.addWidget(self.qty_in)
        qty_unit_row.addLayout(qty_col, stretch=1)

        unit_col = QVBoxLayout()
        unit_col.setSpacing(3)
        unit_col.addWidget(_lbl("Unit *", "unit"))
        current_unit = v.get("unit", _PLACEHOLDER)
        self.unit_in = self._build_unit_dropdown(current_unit, None)
        self.unit_in.wheelEvent = lambda event: event.ignore()
        self.unit_in.currentIndexChanged.connect(self._on_unit_combobox_changed)
        unit_col.addWidget(self.unit_in)
        qty_unit_row.addLayout(unit_col, stretch=2)

        root.addLayout(qty_unit_row)

        # ── Rate + Rate Source ────────────────────────────────────────────
        rate_row = QHBoxLayout()
        rate_row.setSpacing(12)

        rate_col = QVBoxLayout()
        rate_col.setSpacing(3)
        rate_col.addWidget(_lbl("Rate (Unit Cost) *", "rate"))
        self.rate_in = QLineEdit(_field_text(v.get("rate")))
        self.rate_in.setPlaceholderText("e.g. 4500")
        self.rate_in.setMinimumHeight(32)
        self.rate_in.setValidator(dbl)
        rate_col.addWidget(self.rate_in)
        rate_row.addLayout(rate_col, stretch=1)

        src_col = QVBoxLayout()
        src_col.setSpacing(3)
        src_col.addWidget(_lbl("Rate Source", "rate_source"))
        # Store original source so it can be restored when "Allow editing" is unchecked
        self._original_source = v.get("rate_source", "")
        self.src_in = QLineEdit(self._original_source)
        self.src_in.setPlaceholderText("e.g. DSR 2023, Market Rate")
        self.src_in.setMinimumHeight(32)
        src_col.addWidget(self.src_in)
        rate_row.addLayout(src_col, stretch=2)

        root.addLayout(rate_row)

        # ── Carbon Emission ───────────────────────────────────────────────
        root.addWidget(_divider())

        carbon_hdr = QHBoxLayout()
        carbon_title = QLabel("Carbon Emission Factor")
        carbon_title.setStyleSheet(f"font-weight: 600; font-size: {FS_MD}pt;")
        carbon_hdr.addWidget(carbon_title)
        carbon_hdr.addStretch()
        self.carbon_chk = QCheckBox("Include")

        # Authoritative check: DB/excel source with no carbon data disables the checkbox,
        # BUT only when allow_edit is not already enabled (user may have unlocked it).
        _is_db_source = _origin in ("internal_db", "excel")
        _values_carbon = v.get("carbon_emission")
        _allow_edit_saved = s.get("allow_edit_checked", False)
        _db_has_no_carbon = _is_db_source and _values_carbon in MaterialDialog._DB_NA and not _allow_edit_saved

        _carbon_state = s.get("included_in_carbon_emission", True)
        if _db_has_no_carbon:
            self.carbon_chk.setChecked(False)
            self.carbon_chk.setEnabled(False)
            self._sor_carbon_available = False
        elif _carbon_state is None:
            self.carbon_chk.setChecked(False)
            self.carbon_chk.setEnabled(False)
            self._sor_carbon_available = False
        elif _carbon_state is False and self.is_edit:
            # Old project format: infer if False meant "no carbon" or "user unchecked".
            _db_carbon = self._db_original.get("carbon_emission")
            if _is_db_source and _db_carbon in MaterialDialog._DB_NA:
                self.carbon_chk.setChecked(False)
                self.carbon_chk.setEnabled(False)
                self._sor_carbon_available = False
            else:
                self.carbon_chk.setChecked(False)  # explicit user choice
        else:
            self.carbon_chk.setChecked(bool(_carbon_state))
        carbon_hdr.addWidget(self.carbon_chk)
        root.addLayout(carbon_hdr)

        self.carbon_container = QWidget()
        cl = QVBoxLayout(self.carbon_container)
        cl.setContentsMargins(0, 4, 0, 0)
        cl.setSpacing(8)

        ef_row = QHBoxLayout()
        ef_row.setSpacing(12)

        ef_col = QVBoxLayout()
        ef_col.setSpacing(3)
        ef_col.addWidget(_lbl("Emission (kgCO₂e)", "carbon_emission"))
        self.carbon_em_in = QLineEdit(_field_text(v.get("carbon_emission")))
        self.carbon_em_in.setPlaceholderText("e.g. 0.179")
        self.carbon_em_in.setMinimumHeight(32)
        self.carbon_em_in.setValidator(dbl)
        ef_col.addWidget(self.carbon_em_in)
        ef_row.addLayout(ef_col, stretch=1)

        denom_col = QVBoxLayout()
        denom_col.setSpacing(3)
        denom_col.addWidget(_lbl("Per Unit", "carbon_unit"))
        self.carbon_denom_cb = QComboBox()
        self.carbon_denom_cb.setMinimumHeight(32)
        self.carbon_denom_cb.wheelEvent = lambda event: event.ignore()
        self.carbon_denom_cb.setModel(self._build_full_unit_model())

        existing_carbon_unit = v.get("carbon_unit") or ""
        if existing_carbon_unit and "/" in existing_carbon_unit:
            saved_denom = existing_carbon_unit.split("/")[-1].strip()
            didx = _resolve_unit_code(saved_denom, self.carbon_denom_cb)
            if didx >= 0:
                self.carbon_denom_cb.setCurrentIndex(didx)
        elif self._sor_carbon_available:
            didx = self.carbon_denom_cb.findData(current_unit)
            if didx >= 0:
                self.carbon_denom_cb.setCurrentIndex(didx)

        denom_col.addWidget(self.carbon_denom_cb)
        ef_row.addLayout(denom_col, stretch=1)

        src_col = QVBoxLayout()
        src_col.setSpacing(3)
        src_col.addWidget(_lbl("Source", "carbon_emission_src"))
        self._original_carbon_src = v.get("carbon_emission_src", "")
        self.carbon_src_in = QLineEdit(self._original_carbon_src)
        self.carbon_src_in.setPlaceholderText("e.g. ICE v3.0, IPCC")
        self.carbon_src_in.setMinimumHeight(32)
        src_col.addWidget(self.carbon_src_in)
        ef_row.addLayout(src_col, stretch=1)

        cl.addLayout(ef_row)

        self.cf_row_widget = QWidget()
        cf_inner = QVBoxLayout(self.cf_row_widget)
        cf_inner.setContentsMargins(0, 0, 0, 0)
        cf_inner.setSpacing(3)

        self.cf_row_lbl = _lbl("Conversion Factor", "conversion_factor")
        cf_inner.addWidget(self.cf_row_lbl)

        cf_input_row = QHBoxLayout()
        cf_input_row.setSpacing(6)
        self.cf_prefix_lbl = QLabel("1 unit =")
        self.cf_prefix_lbl.setStyleSheet(f"color: {get_token('text_secondary')}; font-size: {FS_MD}pt;")
        cf_input_row.addWidget(self.cf_prefix_lbl)

        self.conv_factor_in = QLineEdit(_field_text(v.get("conversion_factor")))
        self.conv_factor_in.setPlaceholderText("e.g. 2400")
        self.conv_factor_in.setMinimumHeight(32)
        self.conv_factor_in.setMaximumWidth(120)
        self.conv_factor_in.setValidator(dbl)
        cf_input_row.addWidget(self.conv_factor_in)

        self.cf_suffix_lbl = QLabel("unit")
        self.cf_suffix_lbl.setStyleSheet(f"color: {get_token('text_secondary')}; font-size: {FS_MD}pt;")
        cf_input_row.addWidget(self.cf_suffix_lbl)

        self.cf_status_lbl = QLabel("")
        self.cf_status_lbl.setStyleSheet(f"font-size: {FS_SM}pt; color: {get_token('text_disabled')};")
        cf_input_row.addWidget(self.cf_status_lbl)
        cf_input_row.addStretch()
        cf_inner.addLayout(cf_input_row)

        cl.addWidget(self.cf_row_widget)

        self.formula_lbl = QLabel("")
        self.formula_lbl.setWordWrap(True)
        self.formula_lbl.setStyleSheet(f"font-size: {FS_SM}pt; color: {get_token('text_secondary')};")
        self.formula_lbl.setVisible(False)
        cl.addWidget(self.formula_lbl)

        root.addWidget(self.carbon_container)

        # ── Recyclability ─────────────────────────────────────────────────
        root.addWidget(_divider())

        recycle_hdr = QHBoxLayout()
        recycle_title = QLabel("Recyclability")
        recycle_title.setStyleSheet(f"font-weight: 600; font-size: {FS_MD}pt;")
        recycle_hdr.addWidget(recycle_title)
        recycle_hdr.addStretch()
        self.recycle_chk = QCheckBox("Include")
        self.recycle_chk.setChecked(s.get("included_in_recyclability", False))
        recycle_hdr.addWidget(self.recycle_chk)
        root.addLayout(recycle_hdr)

        self.recycle_container = QWidget()
        rl = QHBoxLayout(self.recycle_container)
        rl.setContentsMargins(0, 4, 0, 0)
        rl.setSpacing(12)

        scrap_col = QVBoxLayout()
        scrap_col.setSpacing(3)
        scrap_col.addWidget(_lbl("Scrap Rate (unit cost)", "scrap_rate"))
        self.scrap_in = QLineEdit(_field_text(v.get("scrap_rate")))
        self.scrap_in.setPlaceholderText("e.g. 50")
        self.scrap_in.setMinimumHeight(32)
        self.scrap_in.setValidator(dbl)
        scrap_col.addWidget(self.scrap_in)
        rl.addLayout(scrap_col, stretch=1)

        recov_col = QVBoxLayout()
        recov_col.setSpacing(3)
        recov_col.addWidget(_lbl("Recovery after Demolition (%)", "post_demolition_recovery_percentage"))
        self.recycling_perc_in = QLineEdit(
            _field_text(v.get("post_demolition_recovery_percentage")))
        self.recycling_perc_in.setPlaceholderText("e.g. 90")
        self.recycling_perc_in.setMinimumHeight(32)
        perc_v = QDoubleValidator(0.0, 100.0, DECIMAL_PLACES_CUSTOM)
        perc_v.setNotation(QDoubleValidator.StandardNotation)
        self.recycling_perc_in.setValidator(perc_v)
        recov_col.addWidget(self.recycling_perc_in)
        rl.addLayout(recov_col, stretch=1)

        root.addWidget(self.recycle_container)

        root.addStretch()

        # ── Button bar ────────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setObjectName("btn_bar")
        btn_bar.setStyleSheet(
            f"#btn_bar {{ border-top: 1px solid {get_token('surface_mid')}; }}"
        )
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(20, 10, 20, 10)
        btn_layout.setSpacing(8)

        self.custom_db_btn = QPushButton("Save to Custom DB…")
        self.custom_db_btn.setMinimumHeight(34)
        self.custom_db_btn.setMinimumWidth(150)
        self.custom_db_btn.setToolTip(
            "Save this material to a user-created custom database"
        )
        self.custom_db_btn.clicked.connect(self._on_save_to_custom_db)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setMinimumHeight(34)
        self.cancel_btn.setMinimumWidth(90)
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton(
            "Update Changes" if self.is_edit else "Add to Table"
        )
        self.save_btn.setMinimumHeight(34)
        self.save_btn.setMinimumWidth(120)
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.validate_and_accept)

        btn_layout.addWidget(self.custom_db_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        outer.addWidget(btn_bar)

        # ── Disable save/db buttons when project is locked ────────────────
        # Walk up the parent chain to find the ProjectWindow._frozen flag.
        # Works regardless of which module opens this dialog.
        _w, _frozen = parent, False
        while _w is not None:
            if hasattr(_w, "_frozen"):
                _frozen = bool(_w._frozen)
                break
            _w = _w.parent() if callable(getattr(_w, "parent", None)) else None
        if _frozen:
            # Buttons
            self.custom_db_btn.setEnabled(False)
            self.save_btn.setEnabled(False)

            # Text inputs → read-only
            for _w in (
                self.name_in,
                self.qty_in,
                self.rate_in,
                self.src_in,
                self.carbon_em_in,
                self.conv_factor_in,
                self.scrap_in,
                self.recycling_perc_in,
            ):
                _w.setReadOnly(True)

            # Dropdowns and checkboxes → disabled
            for _w in (
                self.unit_in,
                self.carbon_denom_cb,
                self._allow_edit_chk,
                self.carbon_chk,
                self.recycle_chk,
            ):
                _w.setEnabled(False)

            # Optional widgets (may be None)
            if self.sor_cb:
                self.sor_cb.setEnabled(False)
            if self.type_filter_cb:
                self.type_filter_cb.setEnabled(False)

        # ── Freeze fields for emissions_only / recyclability_only modes ───
        if emissions_only:
            for w in (
                self.name_in,
                self.qty_in,
                self.rate_in,
                self.src_in,
                self.scrap_in,
                self.recycling_perc_in,
            ):
                w.setReadOnly(True)
            self.unit_in.setEnabled(False)
            self.recycle_chk.setEnabled(False)
            self.save_btn.setText("Save Emission Data")
        elif recyclability_only:
            for w in (
                self.name_in,
                self.qty_in,
                self.rate_in,
                self.src_in,
                self.carbon_em_in,
                self.carbon_src_in,
                self.conv_factor_in,
            ):
                w.setReadOnly(True)
            self.unit_in.setEnabled(False)
            self.carbon_chk.setEnabled(False)
            self.carbon_denom_cb.setEnabled(False)
            self.save_btn.setText("Save Recyclability Data")

        # ── Wire signals ──────────────────────────────────────────────────
        self.carbon_chk.toggled.connect(self.carbon_container.setVisible)
        self.recycle_chk.toggled.connect(self.recycle_container.setVisible)
        self.carbon_container.setVisible(self.carbon_chk.isChecked())
        self.recycle_container.setVisible(self.recycle_chk.isChecked())

        self.carbon_denom_cb.currentIndexChanged.connect(
            self._on_denom_combobox_changed
        )
        self.carbon_em_in.textChanged.connect(self._update_formula_preview)
        self.conv_factor_in.textChanged.connect(self._update_formula_preview)
        self.qty_in.textChanged.connect(self._update_formula_preview)

        self._update_cf()
        self._ui_ready = True

        # ── Re-apply DB lock when editing a previously SOR-filled material ──
        if self.is_edit and _origin in ("internal_db", "custom_db", "excel"):
            self._sor_item = self._db_original
            self._sor_filled_name = v.get("material_name", "")  # no re-autofill on open
            if _origin == "excel":
                self._allow_edit_chk.setText("Allow editing Excel-imported values")
            self._allow_edit_chk.setEnabled(True)
            # Restore checkbox + lock state directly from what was saved
            saved_allow_edit = s.get("allow_edit_checked", False)
            self._allow_edit_chk.blockSignals(True)
            self._allow_edit_chk.setChecked(saved_allow_edit)
            self._allow_edit_chk.blockSignals(False)
            self._lock_autofilled_fields(not saved_allow_edit)
            if saved_allow_edit and not self.recyclability_only:
                self._sor_carbon_available = True
                self.carbon_chk.setEnabled(True)
            # emissions_only mode must be able to edit carbon fields regardless of lock state
            if self.emissions_only:
                self.carbon_em_in.setReadOnly(False)
                self.carbon_denom_cb.setEnabled(True)
                self.carbon_src_in.setReadOnly(False)

    # ── SOR / suggestion helpers ──────────────────────────────────────────

    def _reload_suggestions(self):
        if not self._sor_db_key or self._sor_db_key == self._NO_SUGGESTIONS_CODE:
            self._suggestions = {}
            self.name_in.setCompleter(None)
            self._active_completer = None
            return

        db_keys = [self._sor_db_key]

        comp_filter  = None
        sheet_filter = None
        if self.type_filter_cb is not None:
            filter_data = self.type_filter_cb.currentData()
            if isinstance(filter_data, dict):
                comp_filter  = filter_data.get("component")
                sheet_filter = filter_data.get("sheet")
            # None means "All components" — no filter
        else:
            comp_filter = self._comp_name

        self._suggestions = _load_material_suggestions(
            db_keys=db_keys, comp_name=comp_filter, sheet_name=sheet_filter
        )

        # Stamp a _searchable_name temp key on every item: "Name  |  ID" when an
        # ID exists, otherwise just "Name". This is the single display + lookup key
        # used by the completer — no separate mapping dict needed.
        for name, item in self._suggestions.items():
            raw_id = item.get("src_id")
            src_id = str(raw_id).strip() if raw_id not in (None, "", 0, 0.0) else ""
            item["_searchable_name"] = f"{name}  |  {src_id}" if src_id else name

        if self._suggestions:
            if self._active_completer is None:
                self._active_completer = QCompleter(self)
                self._active_completer.setCompletionMode(
                    QCompleter.UnfilteredPopupCompletion
                )
                self._active_completer.setCaseSensitivity(Qt.CaseInsensitive)
                self._active_completer.setMaxVisibleItems(10)

                popup = self._active_completer.popup()
                popup.setStyleSheet(
                    f"QListView {{"
                    f"  background: {get_token('base')};"
                    f"  border: 1px solid {get_token('surface_mid')};"
                    f"  border-radius: 8px;"
                    f"  padding: 4px 0;"
                    f"  outline: none;"
                    f"}}"
                    f"QListView::item {{"
                    f"  padding: 6px 12px;"
                    f"  color: {get_token('text')};"
                    f"  border: none;"
                    f"  border-radius: 4px;"
                    f"  margin: 1px 6px;"
                    f"  min-height: 22px;"
                    f"}}"
                    f"QListView::item:hover {{"
                    f"  background: {get_token('surface')};"
                    f"}}"
                    f"QListView::item:selected {{"
                    f"  background: {get_token('surface_pressed')};"
                    f"  color: {get_token('text')};"
                    f"}}"
                )

                self._active_completer.activated.connect(self._on_suggestion_selected)
                self.name_in.setCompleter(self._active_completer)
            # Re-filter with current text whenever suggestions are reloaded
            self._on_name_search_changed(self.name_in.text())
        else:
            self.name_in.setCompleter(None)
            self._active_completer = None

    def _on_name_search_changed(self, text: str):
        """
        Filter completer suggestions using order-independent token matching.

        Each item carries a _searchable_name temp key: "Name  |  ID" when the
        item has an ID, otherwise just "Name". The completer displays and passes
        back this string; _on_suggestion_selected resolves it to the real name.

        Special token: "?" → show all suggestions.
        """
        if not self._suggestions:
            return
        q = text.strip()

        # ── Exact name match → autofill (add mode only) ───────────────────────
        _q_lower = q.lower()
        _exact_key = next(
            (k for k in self._suggestions if k.lower() == _q_lower), None
        ) if not self._skip_suggestions and q != self._sor_filled_name else None
        if _exact_key is not None:
            if self._ui_ready and not self.is_edit:
                self._on_suggestion_selected(self._suggestions[_exact_key]["_searchable_name"])
            return

        # Name no longer matches the autofilled suggestion → clear stale DB values.
        if self._ui_ready and self._sor_item is not None and q != self._sor_filled_name:
            if not (self.is_edit or self._db_original.get("action") == "excel"):
                self._reset_sor_state()
        if self._active_completer is None:
            return

        # ── Normal search: match _searchable_name (covers both name and ID) ───
        if not q or q == "?":
            filtered = sorted(item["_searchable_name"] for item in self._suggestions.values())
        else:
            filtered = sorted(
                item["_searchable_name"]
                for name, item in self._suggestions.items()
                if AdvancedSearchEngine.is_match(q, item["_searchable_name"])
            )
        self._active_completer.setModel(QStringListModel(filtered))
        if filtered and (q == "?" or q):
            self._active_completer.complete()

    def _reset_sor_state(self):
        """Clear DB-autofilled values when the user edits the name away from a suggestion."""
        self._sor_filling = True
        try:
            self.id_in.clear()
            self.rate_in.clear()
            self.src_in.clear()
            self.carbon_em_in.clear()
            self.conv_factor_in.clear()
            self.carbon_chk.setEnabled(True)
        finally:
            self._sor_filling = False
        self._sor_item = None
        self._sor_filled_name = None
        self._db_original = {}
        self._user_edited_snapshot = {}
        self._lock_autofilled_fields(False)
        self._allow_edit_chk.blockSignals(True)
        self._allow_edit_chk.setChecked(False)
        self._allow_edit_chk.blockSignals(False)
        self._allow_edit_chk.setEnabled(False)
        self._sor_carbon_available = True
        self.carbon_chk.setEnabled(True)
        self._update_cf()

    def _populate_type_filter(self, search_cat: dict = None, preselect_str: str = None):
        """
        Populate the type filter combo.

        search_cat  — {"component": ..., "sheet": ...} from the component registry.
                      Exact match on both fields first; falls back to component-only
                      match; falls back to index 0 (All components) if nothing found.
        preselect_str — plain component name string used when switching databases.
        """
        db_keys = None
        if self._sor_db_key and self._sor_db_key != self._NO_SUGGESTIONS_CODE:
            db_keys = [self._sor_db_key]

        pairs = _list_sor_sheet_components(db_keys=db_keys)

        self.type_filter_cb.blockSignals(True)
        self.type_filter_cb.clear()
        self.type_filter_cb.addItem("All components", None)
        for comp, sheet in pairs:
            self.type_filter_cb.addItem(f"{comp}  |  {sheet}", {"component": comp, "sheet": sheet})

        # Determine what to look for
        want_comp  = None
        want_sheet = None
        if search_cat and isinstance(search_cat, dict):
            want_comp  = (search_cat.get("component") or "").strip().lower()
            want_sheet = (search_cat.get("sheet")     or "").strip().lower()
        elif preselect_str:
            want_comp = preselect_str.strip().lower()

        best_idx        = 0
        comp_only_match = 0

        if want_comp:
            for i in range(1, self.type_filter_cb.count()):
                d = self.type_filter_cb.itemData(i) or {}
                c = d.get("component", "").lower()
                s = d.get("sheet",     "").lower()
                if c == want_comp:
                    if want_sheet and s == want_sheet:
                        best_idx = i
                        break           # exact match — nothing better
                    elif not comp_only_match:
                        comp_only_match = i  # remember first comp-only hit
            if best_idx == 0:
                best_idx = comp_only_match  # use comp-only if no exact; 0 = All components

        self.type_filter_cb.setCurrentIndex(best_idx)
        self.type_filter_cb.blockSignals(False)

    def _on_sor_changed(self):
        if self.sor_cb and self.sor_cb.currentData() == self._NO_SUGGESTIONS_CODE:
            if self.type_filter_cb is not None:
                self.type_filter_cb.setEnabled(False)
            self._on_skip_suggestion()
            return
        if self.type_filter_cb is not None:
            self.type_filter_cb.setEnabled(True)
            current_data = self.type_filter_cb.currentData()
            if isinstance(current_data, dict):
                preselect_str = current_data.get("component") or self._comp_name
            else:
                preselect_str = self._comp_name
            self._populate_type_filter(preselect_str=preselect_str)
        self._restore_suggestions()

    def _on_type_filter_changed(self):
        self._restore_suggestions()

    def _restore_suggestions(self):
        """Re-enable the suggestion system (called when the user switches database/type filter)."""
        self._skip_suggestions = False
        self._reload_suggestions()
        if self._skip_btn is not None:
            self._skip_btn.setVisible(True)

    def _on_skip_suggestion(self):
        """User chose to enter all fields manually - bypass the suggestion system."""
        self._skip_suggestions = True
        self._reset_sor_state()
        self.name_in.setCompleter(None)
        self._active_completer = None
        if self._skip_btn is not None:
            self._skip_btn.setVisible(False)

    def _lock_autofilled_fields(self, lock: bool):
        # qty_in is always freely editable; everything else is DB-filled.
        self.unit_in.setEnabled(not lock)
        self.id_in.setReadOnly(lock)
        self.rate_in.setReadOnly(lock)
        self.src_in.setReadOnly(lock)
        self.carbon_em_in.setReadOnly(lock)
        self.carbon_denom_cb.setEnabled(not lock)
        self.carbon_src_in.setReadOnly(lock)
        self.conv_factor_in.setReadOnly(lock)
        # An Excel row's name, quantity and recycling also came from the
        # file, so the Excel lock covers every input.
        # (The emissions/recyclability-only dialogs keep their own read-only set.)
        if self._db_original.get("action") == "excel" and not (
            self.emissions_only or self.recyclability_only
        ):
            self.name_in.setReadOnly(lock)
            self.qty_in.setReadOnly(lock)
            self.scrap_in.setReadOnly(lock)
            self.recycling_perc_in.setReadOnly(lock)
            self.carbon_chk.setEnabled(not lock)
            self.recycle_chk.setEnabled(not lock)

    def _on_allow_edit_toggled(self, checked: bool):
        """Unlock autofilled fields when checked; restore values and re-lock when unchecked."""
        if checked:
            if self._user_edited_snapshot:
                # Restore previously saved user edits instead of blanking the fields
                self._sor_filling = True
                try:
                    snap = self._user_edited_snapshot
                    self.id_in.setText(snap.get("src_id", ""))
                    self.rate_in.setText(snap.get("rate", ""))
                    if snap.get("unit_idx", -1) >= 0:
                        self.unit_in.setCurrentIndex(snap["unit_idx"])
                    self.src_in.setText(snap.get("src", ""))
                    self.carbon_em_in.setText(snap.get("carbon_em", ""))
                    if snap.get("carbon_denom_idx", -1) >= 0:
                        self.carbon_denom_cb.setCurrentIndex(snap["carbon_denom_idx"])
                    self.carbon_src_in.setText(snap.get("carbon_src", ""))
                    self.conv_factor_in.setText(snap.get("conv_factor", ""))
                    self.carbon_chk.setChecked(snap.get("carbon_chk", False))
                    self.recycle_chk.setChecked(snap.get("recycle_chk", False))
                finally:
                    self._sor_filling = False
            else:
                # First time allowing edit - only clear source attribution fields
                self._sor_filling = True
                self.src_in.clear()
                self.carbon_src_in.clear()
                self._sor_filling = False
            self._sor_carbon_available = True
            self.carbon_chk.setEnabled(True)
        else:
            _restore_source = self._sor_item or (self._db_original if self._db_original else None)
            if _restore_source is not None:
                # Snapshot all current user-edited values before overwriting with DB values
                self._user_edited_snapshot = {
                    "src_id": self.id_in.text(),
                    "rate": self.rate_in.text(),
                    "unit_idx": self.unit_in.currentIndex(),
                    "src": self.src_in.text(),
                    "carbon_em": self.carbon_em_in.text(),
                    "carbon_denom_idx": self.carbon_denom_cb.currentIndex(),
                    "carbon_src": self.carbon_src_in.text(),
                    "conv_factor": self.conv_factor_in.text(),
                    "carbon_chk": self.carbon_chk.isChecked(),
                    "recycle_chk": self.recycle_chk.isChecked(),
                }
                # Restore all values from the DB suggestion that was selected
                self._sor_filling = True
                try:
                    item = _restore_source
                    self.id_in.setText(str(item.get("src_id", "") or ""))

                    unit = item.get("unit", "")
                    if unit:
                        idx = _resolve_unit_code(unit, self.unit_in)
                        if idx >= 0:
                            self.unit_in.setCurrentIndex(idx)

                    self.rate_in.setText(_field_text(item.get("rate")))

                    src = item.get("rate_src", "")
                    self.src_in.setText(
                        str(src) if src not in ("", None) else ""
                    )

                    carbon_src = item.get("carbon_emission_src", "")
                    self.carbon_src_in.setText(
                        str(carbon_src)
                        if carbon_src not in ("", None)
                        else ""
                    )

                    carbon = item.get("carbon_emission")
                    denom = item.get("carbon_emission_units_den")
                    carbon_available = carbon not in ("", None) and denom not in ("", None)
                    self._sor_carbon_available = carbon_available
                    if carbon_available:
                        self.carbon_em_in.setText(_field_text(carbon))
                        didx = _resolve_unit_code(denom, self.carbon_denom_cb)
                        if didx >= 0:
                            self.carbon_denom_cb.setCurrentIndex(didx)
                    else:
                        self.carbon_em_in.setText("")
                        self.carbon_denom_cb.setCurrentIndex(
                            self.carbon_denom_cb.findData(_PLACEHOLDER)
                        )
                    self._sor_carbon_available = carbon_available
                    self.carbon_chk.setChecked(carbon_available)
                    self.carbon_chk.setEnabled(carbon_available)

                    cf = item.get("conversion_factor")
                    self.conv_factor_in.setText(
                        "" if cf in (0, 0.0) else _field_text(cf)
                    )

                    self.recycle_chk.setChecked(False)
                    self.recycle_chk.setEnabled(True)

                    if item.get("action") == "excel":
                        # every value came from the file: put all of them back
                        self.name_in.setText(item.get("name") or "")
                        self.qty_in.setText(item.get("quantity") or "")
                        scrap = item.get("scrap_rate") or ""
                        recovery = item.get("recovery_pct") or ""
                        self.scrap_in.setText(scrap)
                        self.recycling_perc_in.setText(recovery)
                        self.recycle_chk.setChecked(bool(scrap or recovery))
                finally:
                    self._sor_filling = False
                self._update_cf()
            else:
                # No DB suggestion - restore the sources saved at check time, or the originals
                restore_src = getattr(self, "_pre_allow_edit_source", None)
                if restore_src is None:
                    restore_src = self._original_source
                restore_carbon_src = getattr(self, "_pre_allow_edit_carbon_src", None)
                if restore_carbon_src is None:
                    restore_carbon_src = self._original_carbon_src
                self._sor_filling = True
                if restore_src:
                    self.src_in.setText(restore_src)
                if restore_carbon_src:
                    self.carbon_src_in.setText(restore_carbon_src)
                self._sor_filling = False

        self._lock_autofilled_fields(not checked)

    def _on_save_to_custom_db(self):
        if not self.name_in.text().strip():
            QMessageBox.warning(
                self,
                "Missing Name",
                "A material name is required before saving.",
            )
            return

        try:
            if CustomMaterialDB is None:
                raise ImportError("custom_material_db not available")
            cdb = CustomMaterialDB()
            existing = cdb.list_db_names()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not open custom database:\n{e}")
            return

        dlg = _SaveToCustomDBDialog(existing, parent=self)
        if not dlg.exec():
            return

        db_name = dlg.selected_name()
        try:
            cdb.save_material(db_name, self.get_values())
            QMessageBox.information(
                self,
                "Saved",
                f"Material saved to '{db_name}'.\n"
                f"It will appear in suggestions next time you open this dialog.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", str(e))

    # ── Suggestion auto-fill ──────────────────────────────────────────────

    def _on_suggestion_selected(self, display: str):
        # display is item["_searchable_name"] — resolve back to the real name key.
        name, item = next(
            ((n, it) for n, it in self._suggestions.items()
             if it.get("_searchable_name") == display),
            (None, None),
        )
        if item is None:
            return

        # New suggestion - discard any snapshot from a previous suggestion's edit session
        self.id_in.setText(str(item.get("src_id", "") or ""))
        self._user_edited_snapshot = {}
        self._sor_filling = True
        try:
            # Write the plain name into the field while _sor_filling suppresses
            # field-change signals — prevents _reset_sor_state firing mid-autofill.
            self._sor_filled_name = name
            self.name_in.setText(name)
            unit = item.get("unit", "")
            unit_filled = bool(unit)
            if unit_filled:
                idx = _resolve_unit_code(unit, self.unit_in)
                if idx >= 0:
                    self.unit_in.setCurrentIndex(idx)

            rate = item.get("rate", "")
            rate_filled = rate not in ("", None)
            if rate_filled:
                self.rate_in.setText(fmt(rate))

            src = item.get("rate_src", "")
            src_filled = src not in ("", None)
            if src_filled:
                self.src_in.setText(str(src))

            carbon = item.get("carbon_emission")
            denom = item.get("carbon_emission_units_den")
            carbon_available = carbon not in ("", None) and denom not in ("", None)
            self._sor_carbon_available = carbon_available

            if carbon_available:
                self.carbon_em_in.setText(fmt(carbon))
                didx = _resolve_unit_code(denom, self.carbon_denom_cb)
                if didx >= 0:
                    self.carbon_denom_cb.setCurrentIndex(didx)
            else:
                self.carbon_em_in.setText("")
                self.carbon_denom_cb.setCurrentIndex(
                    self.carbon_denom_cb.findData(_PLACEHOLDER)
                )
            self.carbon_chk.setChecked(carbon_available)
            self.carbon_chk.setEnabled(carbon_available)

            carbon_src = item.get("carbon_emission_src", "")
            self.carbon_src_in.setText(
                str(carbon_src) if carbon_src not in ("", None) else ""
            )

            cf = item.get("conversion_factor")
            if cf not in ("", None, 0, 0.0):
                self.conv_factor_in.setText(fmt(cf))
            else:
                self.conv_factor_in.setText("")

            self.recycle_chk.setChecked(False)
            self.recycle_chk.setEnabled(True)

            self._sor_item = item
            self._sor_filled_name = name

            # Snapshot original DB values (written once; never overwritten on re-open).
            # Store the full item so every field is available for modification detection.
            if not self._db_original:
                _db_key = item.get("db_key", "") or self._sor_db_key
                _action = (
                    "custom_db" if _db_key.startswith("custom::") else "internal_db"
                )
                self._db_original = {
                    **item,
                    "action": _action,
                    "db_key": _db_key,
                }

        finally:
            self._sor_filling = False

        self._update_cf()

        self._allow_edit_chk.blockSignals(True)
        self._allow_edit_chk.setChecked(False)
        self._allow_edit_chk.blockSignals(False)
        self._allow_edit_chk.setEnabled(True)
        self._lock_autofilled_fields(True)

    # ── Unit model helpers ────────────────────────────────────────────────

    def _build_full_unit_model(self) -> QStandardItemModel:
        model = QStandardItemModel()

        placeholder = QStandardItem("─ Select unit ─")
        placeholder.setData(_PLACEHOLDER, Qt.UserRole)
        model.appendRow(placeholder)

        for dim, units in _CONSTRUCTION_UNITS.units.items():
            sep = QStandardItem(f"── {dim} ──")
            sep.setFlags(Qt.ItemFlag(0))
            model.appendRow(sep)
            for code, info in units.items():
                si_val = UNIT_TO_SI.get(code)
                si_unit_code = SI_BASE_UNITS.get(dim, "")
                sym = (
                    _unit_sym(code)
                    if code in UNIT_DISPLAY
                    else info["name"].split(",")[0].strip()
                )
                si_sym = _unit_sym(si_unit_code)
                short_name = info["name"].split(",")[-1].strip()
                item = QStandardItem(f"{sym} ({short_name})")
                item.setData(code, Qt.UserRole)
                tooltip = (
                    f"1 {sym} = {si_val:g} {si_sym}  |  Example: {info['example']}"
                    if si_val is not None and si_val != 1.0
                    else f"SI base unit  |  Example: {info['example']}"
                )
                item.setData(tooltip, Qt.ToolTipRole)
                model.appendRow(item)

        _global_custom = get_custom_units()
        if _global_custom:
            sep_c = QStandardItem("── Custom ──")
            sep_c.setFlags(Qt.ItemFlag(0))
            model.appendRow(sep_c)
            for cu in _global_custom:
                display = (
                    f"{cu['symbol']} - {cu['name']}" if cu.get("name") else cu["symbol"]
                )
                item = QStandardItem(display)
                item.setData(cu["symbol"], Qt.UserRole)
                item.setData(
                    f"Custom: 1 {cu['symbol']} = {cu['to_si']:g} {cu.get('si_unit', '')}  |  {cu.get('dimension', '')}",
                    Qt.ToolTipRole,
                )
                model.appendRow(item)

        sep2 = QStandardItem("──────────────")
        sep2.setFlags(Qt.ItemFlag(0))
        model.appendRow(sep2)
        add_item = QStandardItem("+ Add Custom Unit...")
        add_item.setData(self._CUSTOM_CODE, Qt.UserRole)
        model.appendRow(add_item)

        return model

    def _build_unit_dropdown(self, current_unit: str, _=None) -> QComboBox:
        cb = QComboBox()
        cb.setMinimumHeight(30)
        cb.setModel(self._build_full_unit_model())
        # aliases (cum, rmt, MT...) and unknown units resolve like DB units do
        idx = _resolve_unit_code(current_unit, cb)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        return cb

    def _get_unit_info(self, code: str):
        return _get_unit_info_impl(code)

    _DB_NA = frozenset({"", None})

    def _compute_modified_fields(self) -> list:
        """
        Compare current dialog values against the immutable DB snapshot.
        Returns a list of field names whose values differ from the DB original.
        Empty list means either no DB source or no changes made.
        """
        orig = self._db_original
        if not orig:
            return []

        modified = []

        # Unit
        orig_unit = orig.get("unit", "")
        if orig_unit and self.unit_in.currentData() != orig_unit:
            modified.append("unit")

        # Rate
        orig_rate = orig.get("rate", "")
        if orig_rate not in self._DB_NA:
            try:
                if abs(float(self.rate_in.text() or 0) - float(orig_rate)) > 1e-9:
                    modified.append("rate")
            except (ValueError, TypeError):
                pass

        # Carbon emission factor
        orig_em = orig.get("carbon_emission", "")
        if orig_em not in self._DB_NA:
            try:
                if abs(float(self.carbon_em_in.text() or 0) - float(orig_em)) > 1e-9:
                    modified.append("carbon_emission")
            except (ValueError, TypeError):
                pass

        # Carbon denominator unit
        orig_denom = orig.get("carbon_emission_units_den", "")
        if orig_denom not in self._DB_NA:
            if self.carbon_denom_cb.currentData() != orig_denom:
                modified.append("carbon_emission_units_den")

        # Conversion factor
        orig_cf = orig.get("conversion_factor", "")
        if orig_cf not in self._DB_NA and orig_cf not in (0, 0.0):
            try:
                if abs(float(self.conv_factor_in.text() or 0) - float(orig_cf)) > 1e-9:
                    modified.append("conversion_factor")
            except (ValueError, TypeError):
                pass

        return modified

    def _rebuild_unit_models(self, mat_sel: str = None, denom_sel: str = None):
        self.unit_in.blockSignals(True)
        self.carbon_denom_cb.blockSignals(True)

        self.unit_in.setModel(self._build_full_unit_model())
        self.carbon_denom_cb.setModel(self._build_full_unit_model())

        if mat_sel:
            idx = self.unit_in.findData(mat_sel)
            if idx >= 0:
                self.unit_in.setCurrentIndex(idx)
        if denom_sel:
            idx = self.carbon_denom_cb.findData(denom_sel)
            if idx >= 0:
                self.carbon_denom_cb.setCurrentIndex(idx)

        self.unit_in.blockSignals(False)
        self.carbon_denom_cb.blockSignals(False)

    def _add_custom_unit(self, triggering_cb: QComboBox):
        prev_mat = self.unit_in.currentData()
        prev_denom = self.carbon_denom_cb.currentData()

        existing_syms = list(UNIT_TO_SI.keys()) + [
            c["symbol"] for c in get_custom_units()
        ]
        dialog = CustomUnitDialog(self, existing_symbols=existing_syms)
        if dialog.exec():
            cu = dialog.get_unit()
            # Persist to DB and refresh the global cache so all open dialogs see it
            try:
                if CustomMaterialDB is not None:
                    CustomMaterialDB().save_custom_unit(cu)
                load_custom_units()
            except Exception as exc:
                print(f"[MaterialDialog] Could not save custom unit: {exc}")
            new_sym = cu["symbol"]
            mat_sel = (
                new_sym
                if triggering_cb is self.unit_in
                else (prev_mat if prev_mat != self._CUSTOM_CODE else new_sym)
            )
            denom_sel = (
                new_sym
                if triggering_cb is self.carbon_denom_cb
                else (prev_denom if prev_denom != self._CUSTOM_CODE else new_sym)
            )
            self._rebuild_unit_models(mat_sel=mat_sel, denom_sel=denom_sel)
        else:
            prev = prev_mat if triggering_cb is self.unit_in else prev_denom
            restore = prev if (prev and prev != self._CUSTOM_CODE) else None
            triggering_cb.blockSignals(True)
            if restore:
                idx = triggering_cb.findData(restore)
                if idx >= 0:
                    triggering_cb.setCurrentIndex(idx)
            triggering_cb.blockSignals(False)

        self._update_cf()

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_unit_combobox_changed(self):
        code = self.unit_in.currentData()
        if code in (_PLACEHOLDER, None):
            return
        if code == self._CUSTOM_CODE:
            self._add_custom_unit(self.unit_in)
            return
        if code:
            self.carbon_denom_cb.blockSignals(True)
            didx = self.carbon_denom_cb.findData(code)
            if didx >= 0:
                self.carbon_denom_cb.setCurrentIndex(didx)
            self.carbon_denom_cb.blockSignals(False)
        self._update_cf()

    def _on_denom_combobox_changed(self):
        code = self.carbon_denom_cb.currentData()
        if code in (_PLACEHOLDER, None):
            return
        if code == self._CUSTOM_CODE:
            self._add_custom_unit(self.carbon_denom_cb)
            return
        self._update_cf()

    # ── Auto conversion factor ────────────────────────────────────────────

    def _update_cf(self):
        mat_code = self.unit_in.currentData() or ""
        denom_code = self.carbon_denom_cb.currentData() or ""
        mat_sym = _unit_sym(mat_code)
        denom_sym = _unit_sym(denom_code)

        mat_si, mat_dim = self._get_unit_info(mat_code)
        denom_si, denom_dim = self._get_unit_info(denom_code)

        if mat_code == denom_code:
            self._auto_cf = "1"
            self.conv_factor_in.setText("1")
            self.cf_row_widget.setVisible(False)
        elif mat_si is not None and denom_si is not None and mat_dim == denom_dim:
            suggested = f"{mat_si / denom_si:g}"
            self._auto_cf = suggested
            self.conv_factor_in.setText(suggested)
            self.cf_row_widget.setVisible(True)
            self.cf_prefix_lbl.setText(f"1 {mat_sym} =")
            self.cf_suffix_lbl.setText(denom_sym)
            self.cf_status_lbl.setText("(suggested - you can change this)")
        else:
            # Clear the field only if it still holds a previously auto-written value
            if self.conv_factor_in.text() == getattr(self, "_auto_cf", None):
                self.conv_factor_in.clear()
            self._auto_cf = None
            self.cf_row_widget.setVisible(True)
            self.cf_prefix_lbl.setText(f"1 {mat_sym} =")
            self.cf_suffix_lbl.setText(denom_sym)
            if mat_dim and denom_dim:
                self.cf_status_lbl.setText(f"e.g. density for {mat_dim} → {denom_dim}")
            else:
                self.cf_status_lbl.setText("")

        self._update_formula_preview()

    # ── Formula preview ───────────────────────────────────────────────────

    def _update_formula_preview(self):
        try:
            qty = float(self.qty_in.text() or 0)
            ef = float(self.carbon_em_in.text() or 0)
            cf = float(self.conv_factor_in.text() or 0)

            mat_code = self.unit_in.currentData() or ""
            mat_sym = _unit_sym(mat_code)
            denom_code = self.carbon_denom_cb.currentData() or ""
            denom_sym = _unit_sym(denom_code)

            if qty > 0 and ef > 0 and cf > 0:
                total = qty * cf * ef
                if cf == 1.0:
                    self.formula_lbl.setText(
                        f"{qty:g} {mat_sym}  ×  {ef:g} kgCO₂e/{denom_sym}"
                        f"  =  {fmt_comma(total)} kgCO₂e"
                    )
                else:
                    self.formula_lbl.setText(
                        f"{qty:g} {mat_sym}  ×  {cf:g}  ×  {ef:g} kgCO₂e/{denom_sym}"
                        f"  =  {fmt_comma(total)} kgCO₂e"
                    )
                self.formula_lbl.setVisible(True)
            else:
                self.formula_lbl.setVisible(False)
        except (ValueError, ZeroDivisionError):
            self.formula_lbl.setVisible(False)

    # ── Validation ────────────────────────────────────────────────────────

    def validate_and_accept(self):
        unit = self.unit_in.currentData()
        den = self.carbon_denom_cb.currentData()
        problems = check_material(
            name=self.name_in.text(),
            unit="" if unit == _PLACEHOLDER else unit,
            quantity=self.qty_in.text(),
            rate=self.rate_in.text(),
            carbon_on=self.carbon_chk.isChecked(),
            carbon_den="" if den == _PLACEHOLDER else den,
            emission=self.carbon_em_in.text(),
            conversion=self.conv_factor_in.text(),
            recycle_on=self.recycle_chk.isChecked(),
            scrap=self.scrap_in.text(),
            recovery=self.recycling_perc_in.text(),
        )
        for level, title, message, turns_off in problems:
            if level == "error":
                QMessageBox.critical(self, title, message)
                return
            reply = QMessageBox.warning(
                self, title, f"{message}\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return
            if turns_off == "carbon":
                self.carbon_chk.setChecked(False)
            elif turns_off == "recycle":
                self.recycle_chk.setChecked(False)

        if self.is_edit:
            self.accept()
        else:
            self.material_added.emit(self.get_values())

    def _reset_for_next(self, added_name: str = ""):
        success_color = get_token("success")
        self.save_btn.setText("✓ Added")
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(
            f"QPushButton {{ background: {success_color}; color: #ffffff;}}"
        )

        def _restore():
            self.save_btn.setText("Add to Table")
            self.save_btn.setStyleSheet("")
            self.save_btn.setEnabled(True)
            self._skip_suggestions = True
            self.name_in.clear()
            self.qty_in.clear()
            self.rate_in.clear()
            self.src_in.clear()
            self._skip_suggestions = False
            self.name_in.setFocus()

        QTimer.singleShot(800, _restore)

    # ── Output ────────────────────────────────────────────────────────────

    def _source(self) -> tuple:
        """(meta source, source_db_key): where the material came from.
        Whether it was changed since is worked out from db_original when the
        report is made (material_flags.material_flag)."""
        action = self._db_original.get("action", "")
        raw_key = self._db_original.get("db_key", "")
        if action == "excel":
            return "excel", ""
        if action == "internal_db":
            return "db", raw_key
        if action == "custom_db":
            return "custom_db", raw_key.removeprefix("custom::")
        return "manual", ""

    def get_values(self) -> dict:
        """Return material data as {values, meta, state}.

        Consumed by:
          manager.add_material() / open_edit_dialog()
          material_emissions._open_emission_edit()
          recycling.main._open_recyclability_edit()
          custom_material_db.save_material()
        """
        _raw_unit = self.unit_in.currentData() or ""
        actual_unit = "" if _raw_unit == _PLACEHOLDER else _raw_unit
        unit_to_si, _ = self._get_unit_info(actual_unit)

        carbon_on = self.carbon_chk.isChecked()
        recycle_on = self.recycle_chk.isChecked()

        source, source_db_key = self._source()

        _src_id   = self.id_in.text().strip() or None
        _rate_src = self.src_in.text().strip() or None
        _c_src    = self.carbon_src_in.text().strip() or None
        _cf_text  = self.conv_factor_in.text().strip()
        _em_text  = self.carbon_em_in.text().strip()
        _carbon_denom = self.carbon_denom_cb.currentData()

        return {
            "values": {
                "src_id": _src_id,
                "material_name": self.name_in.text().strip(),
                "quantity": float(self.qty_in.text() or 0),
                "unit": actual_unit,
                "unit_to_si": unit_to_si or 1.0,
                "rate": float(self.rate_in.text()) if self.rate_in.text().strip() else None,
                "rate_source": _rate_src,
                "carbon_emission": (
                    float(_em_text) if carbon_on and _em_text else None
                ),
                "carbon_unit": (
                    f"kgCO₂e/{_carbon_denom}"
                    if carbon_on and _carbon_denom not in (_PLACEHOLDER, None, "")
                    else None
                ),
                "carbon_emission_src": _c_src if carbon_on else None,
                "conversion_factor": float(_cf_text) if _cf_text else None,
                "scrap_rate": (
                    float(self.scrap_in.text()) if recycle_on and self.scrap_in.text().strip() else None
                ),
                "post_demolition_recovery_percentage": (
                    float(self.recycling_perc_in.text()) if recycle_on and self.recycling_perc_in.text().strip() else None
                ),
            },
            "meta": {
                "source": source,
                "source_db_key": source_db_key,
                "db_original": self._db_original,
            },
            "state": {
                "included_in_carbon_emission": (
                    True if carbon_on
                    else (None if not self._sor_carbon_available else False)
                ),
                "included_in_recyclability": recycle_on,
                "allow_edit_checked": self._allow_edit_chk.isChecked(),
            },
        }

    # ── Window close / Escape ─────────────────────────────────────────────

    def closeEvent(self, event):
        """X button on the title bar - always treated as Cancel."""
        self.reject()
        event.accept()

    def keyPressEvent(self, event):
        """Escape → Cancel. Enter/Return → trigger the default button only if
        focus is not on a text field (prevents accidental submission)."""
        if event.key() == Qt.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            focused = self.focusWidget()
            if isinstance(focused, QLineEdit):
                event.ignore()  # let the line-edit handle it, don't submit
            else:
                self.save_btn.click()
        else:
            super().keyPressEvent(event)


