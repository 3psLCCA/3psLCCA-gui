import math
import datetime
import time
from three_ps_lcca_gui.gui.themes import get_token
# load form_builder before validation_helpers: they import each other
from ...utils.form_builder import form_builder  # noqa: F401

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QGridLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QScrollArea,
    QMessageBox,
    QMenu,
)
from PySide6.QtCore import Qt, QTimer

from .transport_dialog import TransportDialog
from ...utils.definitions import STRUCTURE_CHUNKS, UNIT_DIMENSION
from ...utils.fab_button import FabButton
from ...utils.table_widgets import (
    TableCard, TooltipTableMixin, WordWrapHeaderView, fit_to_contents,
)
from three_ps_lcca_gui.gui.assets.themes.column_style import (
    apply_column_style,
)
from three_ps_lcca_gui.gui.styles import font
from three_ps_lcca_gui.gui.theme import SP1, SP2, SP3, SP4, FS_MD, FS_SECTION, FW_BOLD
from ...utils.display_format import fmt, fmt_comma
from ...utils.icons import make_icon, make_icon_btn
from ...utils.validation_helpers import freeze_widgets


class _TransportEmissionsTable(TooltipTableMixin, QTableWidget):
    """Transport table with a WordWrapHeaderView installed at construction time.

    The global _TableHeaderWordWrapFilter would also install one (deferred), and
    skips tables that already have it. Note: blank headings in installer builds
    were NOT caused by that deferred swap; see WordWrapHeaderView.paintSection
    and devtools/dev_notes_log/3psLCCA_blank_table_headers_fix.md.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        hdr = WordWrapHeaderView(Qt.Horizontal, parent=self)
        self.setHorizontalHeader(hdr)
        hdr.show()
        fit_to_contents(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _named_label(text: str, name: str) -> QLabel:
    """QLabel styled from main.qss through its object name."""
    lbl = QLabel(text)
    lbl.setObjectName(name)
    return lbl


def _stat_grid(pairs: list) -> tuple:
    """Grid of muted labels over bold values, one column per pair.

    Returns (QGridLayout, [value QLabel, ...]) so callers can update values.
    """
    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(2)
    values = []
    for col, (label, value) in enumerate(pairs):
        grid.addWidget(_named_label(label, "statLabel"), 0, col)
        val = _named_label(value, "statValue")
        grid.addWidget(val, 1, col)
        grid.setColumnStretch(col, 1)
        values.append(val)
    return grid, values


# ---------------------------------------------------------------------------
# Material lookup - scan all structure chunks by UUID
# ---------------------------------------------------------------------------


def _build_material_index(engine) -> dict:
    """
    Returns dict: {uuid: (item, category, chunk_id, comp_name)}
    Scans all structure chunks once per refresh.
    """
    index = {}
    for chunk_id, category in STRUCTURE_CHUNKS:
        data = engine.fetch_chunk(chunk_id) or {}
        for comp_name, items in data.items():
            for item in items:
                mat_id = item.get("id")
                if mat_id:
                    index[mat_id] = (item, category, chunk_id, comp_name)
    return index


# ---------------------------------------------------------------------------
# Emission calculation
# ---------------------------------------------------------------------------


def calc_vehicle_emission(entry: dict, mat_index: dict) -> tuple:
    """
    Returns (total_emission, material_results, warnings)

    material_results: list of dicts with per-material breakdown
    warnings:         list of warning strings
    """
    v = entry.get("vehicle", {})
    r = entry.get("route", {})
    uuids = entry.get("materials", [])

    cap = float(v.get("capacity", 0) or 0)
    gross_wt = float(v.get("gross_weight", 0) or 0)
    empty_wt = float(v.get("empty_weight", max(0.0, gross_wt - cap)) or 0)
    dist = float(r.get("distance_km", 0) or 0)
    ef = float(v.get("emission_factor", 0) or 0)

    total_emission = 0.0
    material_results = []
    warnings = []

    if cap <= 0:
        warnings.append("The payload capacity of the vehicle is 0. Make sure that the vehicle data is correct.")
        return 0.0, [], warnings

    if dist <= 0:
        warnings.append("The distance is 0 km. The emission is 0 kgCO₂e.")

    if ef <= 0:
        warnings.append("The emission factor is 0. The emission is 0 kgCO₂e.")

    for mat_entry in uuids:
        # materials is now [{uuid, kg_factor}]
        mat_uuid = mat_entry.get("uuid") if isinstance(mat_entry, dict) else mat_entry
        kg_factor = (
            mat_entry.get("kg_factor", 1.0) if isinstance(mat_entry, dict) else 1.0
        )

        if mat_uuid not in mat_index:
            material_results.append(
                {
                    "uuid": mat_uuid,
                    "name": "Unknown",
                    "status": "removed",
                    "emission": 0.0,
                    "warning": "⚠ Not in Construction Works Data",
                }
            )
            warnings.append(f"Material {mat_uuid[:8]}… is not in Construction Works Data.")
            continue

        item, category, chunk_id, comp_name = mat_index[mat_uuid]

        if item.get("state", {}).get("in_trash", False):
            material_results.append(
                {
                    "uuid": mat_uuid,
                    "name": item.get("values", {}).get("material_name", ""),
                    "category": category,
                    "status": "trashed",
                    "emission": 0.0,
                }
            )
            continue

        val = item.get("values", {})
        qty = float(val.get("quantity") or 0)
        unit = val.get("unit", "")
        name = val.get("material_name", "")

        # Use kg_factor from transport entry (not structure conv factor)
        qty_kg = qty * kg_factor
        qty_t = qty_kg / 1000.0
        trips = math.ceil(qty_t / cap) if cap > 0 else 0

        # Loaded trip: gross_weight × dist × trips × EF
        # Empty return: empty_weight × dist × trips × EF
        emission = (gross_wt + empty_wt) * trips * dist * ef

        warns = []
        if qty <= 0:
            warns.append("⚠ The quantity is 0.")
        if qty_kg <= 0 and qty > 0:
            warns.append("⚠ The weight is 0 kg. Make sure that the kg factor is correct.")
        if trips > 1000:
            warns.append(f"⚠ The number of trips ({trips:,}) is high.")
        is_mass = UNIT_DIMENSION.get(unit.lower()) == "Mass"
        if not is_mass and abs(kg_factor - 1.0) < 1e-6:
            warns.append(f"⚠ The kg factor is 1 kg/{unit}. Make sure that this value is correct.")

        warn = " | ".join(warns)
        if trips > 1000:
            warnings.append(f"{name}: The number of trips ({trips:,}) is high. Make sure that the quantity and the vehicle capacity are correct.")

        material_results.append(
            {
                "uuid": mat_uuid,
                "name": name,
                "category": category,
                "unit": unit,
                "qty": qty,
                "kg_factor": kg_factor,
                "qty_kg": qty_kg,
                "trips": trips,
                "emission": emission,
                "status": "ok",
                "warning": warn,  # ← this
            }
        )

        total_emission += emission

    return total_emission, material_results, warnings


# ---------------------------------------------------------------------------
# Vehicle Card Widget
# ---------------------------------------------------------------------------


class VehicleCard(TableCard):
    """One delivery, laid out like the structure table cards:

        name  ·  origin · km  ----------  emission  [•••]
        warning callout                 (if any)
        material table
        "Edit delivery" row

    The vehicle specs are the tooltip of the heading.
    """

    def __init__(
        self,
        entry: dict,
        mat_results: list,
        warnings: list,
        total_emission: float,
        on_edit,
        on_trash,
        frozen: bool = False,
        parent=None,
    ):
        v = entry.get("vehicle", {})
        r = entry.get("route", {})
        table = self._build_table(mat_results)
        super().__init__(table, title=(v.get("name") or "").strip() or "Delivery", parent=parent)

        route = [p for p in ((r.get("origin") or "").strip(), f"{fmt_comma(r.get('distance_km', 0))} km") if p]
        self.set_count("  ·  ".join(route))
        self.set_total(f"{fmt_comma(total_emission)} kgCO₂e")

        gross = v.get("gross_weight", 0)
        cap = v.get("capacity", 0)
        empty = v.get("empty_weight", max(0.0, gross - cap))
        specs = (
            f"Capacity {fmt_comma(cap)} t  ·  Gross {fmt_comma(gross)} t  ·  "
            f"Empty {fmt_comma(empty)} t  ·  EF {fmt(v.get('emission_factor', 0))} kgCO₂e/t-km"
        )
        self.title_lbl.setToolTip(specs)
        self.count_lbl.setToolTip(specs)

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ padding: {SP1}px; }}"
            f"QMenu::item {{ padding: {SP2}px {SP4}px {SP2}px {SP2}px; }}"
            f"QMenu::icon {{ padding-left: {SP3}px; }}"
            f"QMenu::separator {{ margin: {SP1}px {SP2}px; }}"
        )
        edit_act = menu.addAction(make_icon("edit"), "Edit delivery")
        edit_act.triggered.connect(on_edit)
        menu.addSeparator()
        trash_act = menu.addAction(make_icon("trash", color=get_token("danger")), "Remove delivery")
        trash_act.triggered.connect(on_trash)
        freeze_widgets(frozen, self.set_menu(menu))

        apply_column_style(table)

        # warnings (delivery and per material) sit between the heading and the table
        row_warnings = [
            f"{m.get('name') or 'Material'}: {w.replace('⚠', '').strip()}"
            for m in mat_results
            for w in (m.get("warning") or "").split(" | ")
            if w and "trips" not in w  # high trip counts are in `warnings` already
        ]
        all_warnings = list(warnings) + row_warnings
        if all_warnings:
            warn_box = QFrame()
            warn_box.setObjectName("warnBox")
            warn_layout = QHBoxLayout(warn_box)
            warn_layout.setContentsMargins(10, 8, 10, 8)
            warn_layout.setSpacing(8)
            warn_layout.addWidget(_named_label("!", "warnIcon"), 0, Qt.AlignTop)
            warn_text = _named_label("\n".join(all_warnings), "warnText")
            warn_text.setWordWrap(True)
            warn_layout.addWidget(warn_text, 1)
            extra = QVBoxLayout()
            extra.setContentsMargins(SP3, SP2, SP3, 0)
            extra.addWidget(warn_box)
            self.layout().insertLayout(1, extra)

        table.setVisible(bool(mat_results))
        footer = self.add_footer("Edit delivery")
        footer.clicked.connect(on_edit)
        freeze_widgets(frozen, footer)

    @staticmethod
    def _build_table(mat_results: list) -> QTableWidget:
        table = _TransportEmissionsTable()
        _L = Qt.AlignLeft  | Qt.AlignVCenter
        _R = Qt.AlignRight | Qt.AlignVCenter
        headers = [
            ("Material",  _L),
            ("Category",  _L),
            ("kg Factor", _R),
            ("Quantity",  _R),
            ("Trips",     _R),
            ("Emission (kgCO₂e)", _R),  # unit here, numbers only in the rows
        ]
        table.setColumnCount(len(headers))
        for col, (label, align) in enumerate(headers):
            item = QTableWidgetItem(label)
            item.setTextAlignment(align)
            table.setHorizontalHeaderItem(col, item)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.verticalHeader().setVisible(False)

        item = VehicleCard._item
        for mat in mat_results:
            row = table.rowCount()
            table.insertRow(row)
            name = mat.get("name", "")
            if mat.get("status", "ok") == "ok":
                unit = mat.get("unit", "")
                kf = fmt_comma(mat.get("kg_factor", 1))
                cells = [
                    (name, _L),
                    (mat.get("category", ""), _L),
                    (f"{kf} kg/{unit}" if unit else kf, _R),
                    (f"{fmt_comma(mat.get('qty_kg', 0))} kg", _R),
                    (f"{mat.get('trips', 0):,}", _R),
                    (fmt_comma(mat.get("emission", 0)), _R),
                ]
            else:
                label = "in Trash" if mat.get("status") == "trashed" else "removed"
                cells = [(f"{name} ({label})", _L), (mat.get("category", ""), _L)] + [("-", _R)] * 4
            for col, (text, align) in enumerate(cells):
                table.setItem(row, col, item(text, align))
        return table

    @staticmethod
    def _item(text="", align=None) -> QTableWidgetItem:
        it = QTableWidgetItem(text)
        it.setFlags(Qt.ItemIsEnabled)
        if align:
            it.setTextAlignment(align)
        return it


# ---------------------------------------------------------------------------
# TransportEmissions - main widget
# ---------------------------------------------------------------------------


class TransportEmissions(QWidget):
    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self.setObjectName("TransportEmissions")

        self._frozen = False
        self._loaded = False
        if controller and hasattr(controller, "project_loaded"):
            controller.project_loaded.connect(self._on_project_reloaded)
        if controller and hasattr(controller, "chunk_updated"):
            _WATCHED = {"str_foundation", "str_sub_structure", "str_super_structure", "str_misc", "transport_data"}
            controller.chunk_updated.connect(
                lambda name: QTimer.singleShot(0, self.on_refresh) if name in _WATCHED else None
            )

        # Laid out like a Construction Works tab (structure/widgets/manager.py):
        # heading row, then cards, in a scroll area, with a floating "+".
        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # keep the scrollbar's room so cards don't change width when it appears
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setSpacing(SP4)
        scroll.setWidget(page)
        outer.addWidget(scroll)

        # ── Heading row: title, delivery count, total ────────────────────
        head = QHBoxLayout()
        head.setContentsMargins(SP1, SP2, SP1, SP1)
        head.setSpacing(SP3)
        title = QLabel("Transportation")
        title.setFont(font(FS_SECTION, FW_BOLD))
        self.vehicle_lbl = _named_label("", "statLabel")
        self.vehicle_lbl.setFont(font(FS_MD))
        self.total_lbl = QLabel()
        self.total_lbl.setFont(font(FS_SECTION, FW_BOLD))
        head.addWidget(title, 0, Qt.AlignBottom)
        head.addWidget(self.vehicle_lbl, 0, Qt.AlignBottom)
        head.addStretch()
        head.addWidget(self.total_lbl, 0, Qt.AlignBottom)
        page_layout.addLayout(head)

        # ── Category totals card ─────────────────────────────────────────
        summary = QFrame()
        summary.setObjectName("transportSummary")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(SP4, SP3, SP4, SP3)
        cats, (
            self.foundation_lbl,
            self.sub_lbl,
            self.super_lbl,
            self.misc_lbl,
        ) = _stat_grid([
            ("Foundation", "- kgCO₂e"),
            ("Sub-Structure", "- kgCO₂e"),
            ("Super-Structure", "- kgCO₂e"),
            ("Misc", "- kgCO₂e"),
        ])
        summary_layout.addLayout(cats)
        page_layout.addWidget(summary)

        # ── Delivery cards (rebuilt by on_refresh) ───────────────────────
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(SP4)
        page_layout.addWidget(self.container, 1)
        # room under the last card so the floating button doesn't cover it
        page_layout.addSpacing(64)

        # Floating "+" (expands to "+ Add Delivery" on hover)
        self.add_btn = FabButton("+ Add Delivery", self)
        self.add_btn.clicked.connect(self._open_add_dialog)

    # ── Refresh ──────────────────────────────────────────────────────────

    def on_refresh(self):
        if not self.controller or not getattr(self.controller, "engine", None):
            return

        # Clear cards
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        data = self.controller.engine.fetch_chunk("transport_data") or {}
        vehicles = data.get("vehicles", [])

        mat_index = _build_material_index(self.controller.engine)

        # Auto-clean stale material references (trashed or permanently deleted)
        dirty = False
        for entry in vehicles:
            if entry.get("state", {}).get("in_trash", False):
                continue
            clean = []
            for m in entry.get("materials", []):
                uuid = m.get("uuid") if isinstance(m, dict) else m
                item_data = mat_index.get(uuid)
                if item_data and not item_data[0].get("state", {}).get("in_trash", False):
                    clean.append(m)
                else:
                    dirty = True
            entry["materials"] = clean
        if dirty:
            self.controller.engine.stage_update(chunk_name="transport_data", data=data)

        total_emission = 0.0
        cat_totals = {label: 0.0 for _, label in STRUCTURE_CHUNKS}
        active_count = 0

        for entry in vehicles:
            if entry.get("state", {}).get("in_trash", False):
                continue

            active_count += 1
            emission, mat_results, warnings = calc_vehicle_emission(entry, mat_index)
            total_emission += emission

            # Category breakdown
            for mat in mat_results:
                if mat.get("status") == "ok":
                    cat = mat.get("category", "")
                    if cat in cat_totals:
                        cat_totals[cat] += mat.get("emission", 0)

            entry_id = entry.get("id")
            card = VehicleCard(
                entry=entry,
                mat_results=mat_results,
                warnings=warnings,
                total_emission=emission,
                on_edit=lambda _, eid=entry_id: self._open_edit_dialog(eid),
                on_trash=lambda _, eid=entry_id: self._trash_vehicle(eid),
                frozen=self._frozen,
            )
            self.container_layout.addWidget(card)

        self.container_layout.addStretch()

        # Update summary
        self.total_lbl.setText(f"{fmt_comma(total_emission)} kgCO₂e")
        self.vehicle_lbl.setText(
            f"{active_count} deliver" + ("y" if active_count == 1 else "ies")
        )
        for lbl, cat in (
            (self.foundation_lbl, "Foundation"),
            (self.sub_lbl, "Sub-Structure"),
            (self.super_lbl, "Super-Structure"),
            (self.misc_lbl, "Misc"),
        ):
            lbl.setText(f"{fmt_comma(cat_totals.get(cat, 0))} kgCO₂e")

    # ── Actions ──────────────────────────────────────────────────────────

    def _get_assigned_uuids(self, exclude_entry_id: str = None) -> set:
        data = self.controller.engine.fetch_chunk("transport_data") or {}
        vehicles = data.get("vehicles", [])
        assigned = set()
        for entry in vehicles:
            if entry.get("state", {}).get("in_trash", False):
                continue
            if entry.get("id") == exclude_entry_id:
                continue
            for m in entry.get("materials", []):
                if isinstance(m, dict):
                    assigned.add(m.get("uuid"))
                else:
                    assigned.add(m)  # fallback for plain uuid strings
        return assigned

    def _write_back_kg_factors(self, entry: dict):
        """
        Persist kg_factor for non-mass materials back into each material's
        values dict (transport_kg_factor key) so the next delivery dialog
        pre-fills the factor automatically.
        """
        for m in entry.get("materials", []):
            if not isinstance(m, dict):
                continue
            uid = m.get("uuid")
            kf  = m.get("kg_factor", 0.0)
            if not uid or not kf:
                continue
            for chunk_id, _ in STRUCTURE_CHUNKS:
                chunk_data = self.controller.engine.fetch_chunk(chunk_id) or {}
                changed = False
                for comp_items in chunk_data.values():
                    for item in comp_items:
                        if item.get("id") == uid:
                            item.setdefault("values", {})["transport_kg_factor"] = kf
                            changed = True
                if changed:
                    self.controller.engine.stage_update(chunk_name=chunk_id, data=chunk_data)
                    break

    def _open_add_dialog(self):
        assigned = self._get_assigned_uuids()
        dialog = TransportDialog(self.controller, assigned, parent=self)
        if dialog.exec():
            entry = dialog.get_vehicle_entry()
            self._write_back_kg_factors(entry)
            data = self.controller.engine.fetch_chunk("transport_data") or {}
            data.setdefault("vehicles", []).append(entry)
            self.controller.engine.stage_update(chunk_name="transport_data", data=data)
            self._mark_dirty()
            QTimer.singleShot(0, self.on_refresh)

    def _open_edit_dialog(self, entry_id: str):
        data = self.controller.engine.fetch_chunk("transport_data") or {}
        vehicles = data.get("vehicles", [])
        entry = next((v for v in vehicles if v.get("id") == entry_id), None)
        if not entry:
            return

        assigned = self._get_assigned_uuids(exclude_entry_id=entry_id)
        dialog = TransportDialog(self.controller, assigned, data=entry, parent=self)
        if dialog.exec():
            updated = dialog.get_vehicle_entry()
            self._write_back_kg_factors(updated)
            vehicles = [updated if v.get("id") == entry_id else v for v in vehicles]
            data["vehicles"] = vehicles
            self.controller.engine.stage_update(chunk_name="transport_data", data=data)
            self._mark_dirty()
            QTimer.singleShot(0, self.on_refresh)

    def _trash_vehicle(self, entry_id: str):
        confirm = QMessageBox.question(
            self,
            "Remove Delivery",
            "Remove this delivery? You can then add its materials to a different delivery.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        data = self.controller.engine.fetch_chunk("transport_data") or {}
        vehicles = data.get("vehicles", [])
        for v in vehicles:
            if v.get("id") == entry_id:
                v.setdefault("state", {})["in_trash"] = True
                v.setdefault("meta", {})["updated_at"] = datetime.datetime.now().isoformat()
                break

        data["vehicles"] = vehicles
        self.controller.engine.stage_update(chunk_name="transport_data", data=data)
        self._mark_dirty()
        QTimer.singleShot(0, self.on_refresh)

    def _mark_dirty(self):
        if self.controller and self.controller.engine:
            eng = self.controller.engine
            eng._last_keystroke_time = time.time()
            eng._has_unsaved_changes = True
            try:
                eng.on_dirty(True)
            except Exception as e:
                print(f"[TransportEmissions] _mark_dirty: {e}")

    def _compute(self) -> dict:
        """
        Core calculation logic shared by on_refresh(), validate(), and get_data().
        Returns raw computed data without touching any UI.
        """
        cat_totals = {label: 0.0 for _, label in STRUCTURE_CHUNKS}
        entries = []
        all_warnings = []
        total_emission = 0.0
        active_count = 0

        if not self.controller or not getattr(self.controller, "engine", None):
            return {
                "total_emission": 0.0,
                "cat_totals": cat_totals,
                "active_count": 0,
                "entries": [],
                "all_warnings": [],
            }

        data = self.controller.engine.fetch_chunk("transport_data") or {}
        vehicles = data.get("vehicles", [])
        mat_index = _build_material_index(self.controller.engine)

        for entry in vehicles:
            if entry.get("state", {}).get("in_trash", False):
                continue
            active_count += 1
            emission, mat_results, warnings = calc_vehicle_emission(entry, mat_index)
            total_emission += emission
            for mat in mat_results:
                if mat.get("status") == "ok":
                    cat = mat.get("category", "")
                    if cat in cat_totals:
                        cat_totals[cat] += mat.get("emission", 0)
            all_warnings.extend(warnings)
            entries.append({
                "entry": entry,
                "emission": emission,
                "mat_results": mat_results,
                "warnings": warnings,
            })

        return {
            "total_emission": total_emission,
            "cat_totals": cat_totals,
            "active_count": active_count,
            "entries": entries,
            "all_warnings": all_warnings,
        }

    def validate(self) -> dict:
        result = self._compute()
        warnings = []

        if result["active_count"] == 0:
            warnings.append(
                "There are no deliveries. Add a delivery in the Transportation Emissions tab."
            )
        elif result["total_emission"] == 0.0:
            warnings.append(
                "The total transport emission is 0 kgCO₂e. Make sure that the distance, "
                "payload and emission factor of each delivery are correct."
            )

        if result["all_warnings"]:
            for w in result["all_warnings"]:
                warnings.append(w)

        return {"errors": [], "warnings": warnings}

    def get_data(self) -> dict:
        result = self._compute()
        entries_out = [
            {
                "vehicle_name": e["entry"].get("vehicle", {}).get("name", ""),
                "from-to": e["entry"].get("route", {}).get("origin", ""),
                "distance_km": e["entry"].get("route", {}).get("distance_km", 0),
                "emission_kgCO2e": e["emission"],
                "materials": e["mat_results"],
            }
            for e in result["entries"]
        ]
        return {
            "chunk": "transport_emissions_data",
            "data": {
                "entries": entries_out,
                "cat_totals": result["cat_totals"],
                "total_kgCO2e": result["total_emission"],
                "active_vehicle_count": result["active_count"],
            },
        }

    def freeze(self, frozen: bool = True):
        self._frozen = frozen
        freeze_widgets(frozen, self.add_btn)
        self.on_refresh()  # rebuild cards with updated button states

    def showEvent(self, event):
        super().showEvent(event)
        if not self._loaded:
            self.on_refresh()
            self._loaded = True

    def _on_project_reloaded(self):
        self._loaded = False
        if self.isVisible():
            self.on_refresh()
            self._loaded = True


