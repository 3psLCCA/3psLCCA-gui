from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QGroupBox,
    QInputDialog,
    QMessageBox,
    QLabel,
    QFrame,
)
from PySide6.QtCore import Qt, QTimer
import time
import uuid
import datetime
import traceback

from .base_table import StructureTableWidget, _make_msgbox
from .material_dialog import MaterialDialog
from ...utils.definitions import UNIT_DISPLAY
from ...utils.validation_helpers import freeze_widgets
from ...utils.display_format import fmt, fmt_comma
from three_ps_lcca_gui.gui.styles import btn_danger
from ...utils.common_requested_data import get_chunk


# ---------------------------------------------------------------------------
# StructureManagerWidget
# ---------------------------------------------------------------------------


class StructureManagerWidget(QWidget):
    total_changed = Signal()  # emitted whenever the computed total changes
    def __init__(self, controller, chunk_name, default_components):
        super().__init__()
        self.controller = controller
        self.chunk_name = chunk_name
        self.default_components = default_components
        self.sections = {}
        self.data = {}

        self._frozen = False
        self._add_material_btns = []
        self._del_comp_btns = []

        self.main_layout = QVBoxLayout(self)

        # ── Summary bar ──────────────────────────────────────────────────
        summary_bar = QWidget()
        summary_layout = QHBoxLayout(summary_bar)
        summary_layout.setContentsMargins(4, 4, 4, 4)
        self.total_lbl = QLabel("Total: -")
        self.count_lbl = QLabel("Items: -")
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        summary_layout.addWidget(self.total_lbl)
        summary_layout.addWidget(sep)
        summary_layout.addWidget(self.count_lbl)
        summary_layout.addStretch()
        self.main_layout.addWidget(summary_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; }")

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.scroll.setWidget(self.container)
        self.main_layout.addWidget(self.scroll)

        btn_layout = QHBoxLayout()
        self.add_comp_btn = QPushButton("+ Add Component")
        self.add_comp_btn.clicked.connect(self.add_new_component)
        btn_layout.addWidget(self.add_comp_btn)
        btn_layout.addStretch()
        self.main_layout.addLayout(btn_layout)

    def on_refresh(self):
        try:
            if not self.controller or not getattr(self.controller, "engine", None):
                return

            data = self.controller.engine.fetch_chunk(self.chunk_name) or {}

            if not data and self.default_components:
                for comp in self.default_components:
                    data[comp] = []
                self.controller.engine.stage_update(
                    chunk_name=self.chunk_name, data=data
                )
                self.controller.chunk_updated.emit(self.chunk_name)

            info = self.controller.engine.fetch_chunk("general_info") or {}
            self._currency = str(info.get("project_currency", ""))
            self.data = data
            self.refresh_ui()
        except Exception as e:

            print(f"[ERROR] on_refresh crashed: {e}")
            traceback.print_exc()

    def refresh_ui(self):
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)

        self.sections = {}
        self._add_material_btns = []
        self._del_comp_btns = []
        currency = getattr(self, "_currency", "")

        for comp_name, items in self.data.items():
            self.create_section(comp_name)
            table = self.sections.get(comp_name)
            if table:
                table.set_currency(currency)
                for original_index, item in enumerate(items):
                    if not item.get("state", {}).get("in_trash", False):
                        table.add_row(item, original_index)

        self.container_layout.addStretch()
        self.container.adjustSize()
        self._update_summary()

        if getattr(self, "_frozen", False):
            self.freeze(True)

    def _update_summary(self):
        total = 0.0
        count = 0
        components = 0
        for items in self.data.values():
            comp_has_items = False
            for item in items:
                if not item.get("state", {}).get("in_trash", False):
                    v = item.get("values", {})
                    total += (v.get("quantity") or 0) * (v.get("rate") or 0)
                    count += 1
                    comp_has_items = True
            if comp_has_items:
                components += 1
        self._computed_total      = total
        self._computed_count      = count
        self._computed_components = components
        currency = getattr(self, "_currency", "")
        suffix = f" ({currency})" if currency else ""
        item_str = f"{count} item{'s' if count != 1 else ''}"
        comp_str = f"{components} component{'s' if components != 1 else ''}"
        self.total_lbl.setText(f"Total{suffix}: {fmt_comma(total)}  |  {item_str} in {comp_str}")
        self.count_lbl.hide()
        self.total_changed.emit()

    def create_section(self, name):
        group = QGroupBox(name)
        g_layout = QVBoxLayout(group)

        table = StructureTableWidget(self, name)
        self.sections[name] = table

        btn_bar = QHBoxLayout()

        add_row_btn = QPushButton(f"Add Material to {name}")
        add_row_btn.clicked.connect(lambda checked=False, n=name: self.open_dialog(n))
        freeze_widgets(self._frozen, add_row_btn)
        self._add_material_btns.append(add_row_btn)

        del_btn = QPushButton("Delete Component")
        del_btn.setObjectName("deleteButton")
        del_btn.setStyleSheet(btn_danger())
        del_btn.clicked.connect(lambda checked=False, n=name: self.delete_component(n))
        freeze_widgets(self._frozen, del_btn)
        self._del_comp_btns.append(del_btn)

        btn_bar.addWidget(add_row_btn, 1)
        btn_bar.addWidget(del_btn)

        g_layout.addWidget(table)
        g_layout.addLayout(btn_bar)
        self.container_layout.addWidget(group)

    def add_material(self, comp_name, mat_dict, is_trash=False):
        now = datetime.datetime.now().isoformat()

        values = dict(mat_dict.get("values", {}))
        meta_in = mat_dict.get("meta", {})
        state_in = mat_dict.get("state", {})

        db_original = dict(meta_in.get("db_original") or {})

        new_entry = {
            "id": str(uuid.uuid4()),
            "values": values,
            "meta": {
                "created_on": now,
                "modified_on": now,
                "source": meta_in.get("source", "manual"),
                "source_db_key": meta_in.get("source_db_key", ""),
                "db_original": db_original,
            },
            "state": {
                "in_trash": is_trash,
                "included_in_carbon_emission": state_in.get("included_in_carbon_emission", True),
                "included_in_recyclability": state_in.get("included_in_recyclability", False),
                "allow_edit_checked": state_in.get("allow_edit_checked", False),
            },
        }

        current_data = self.controller.engine.fetch_chunk(self.chunk_name) or {}
        if comp_name not in current_data:
            current_data[comp_name] = []

        current_data[comp_name].append(new_entry)
        self.controller.engine.stage_update(
            chunk_name=self.chunk_name, data=current_data
        )
        self.controller.chunk_updated.emit(self.chunk_name)
        self.save_current_state()

        if is_trash:
            self.on_refresh()
            return

        original_index = len(current_data[comp_name]) - 1
        self.data = current_data
        table = getattr(self, "sections", {}).get(comp_name)
        if table:
            table.insert_row_at_position(new_entry, original_index)
            self._update_summary()
        else:
            self.on_refresh()

    def _get_project_country(self) -> str:
        try:
            return (
                self.controller.get_chunk("general_info").get("project_country", "")
                or ""
            )
        except Exception:
            return ""

    def _get_project_sor_db(self) -> str:
        try:
            return (
                self.controller.get_chunk("general_info").get("sor_database", "") or ""
            )
        except Exception:
            return ""

    def _existing_names(self, comp_name) -> set:
        """Return lowercased active material names for comp_name."""
        data = self.controller.engine.fetch_chunk(self.chunk_name) or {}
        return {
            item.get("values", {}).get("material_name", "").strip().lower()
            for item in data.get(comp_name, [])
            if not item.get("state", {}).get("in_trash", False)
        }

    def open_dialog(self, comp_name):
        dialog = MaterialDialog(
            comp_name,
            self,
            country=self._get_project_country(),
            sor_db_key=self._get_project_sor_db(),
        )

        def _on_material_added(values):
            name = values.get("values", {}).get("material_name", "").strip()
            existing = self._existing_names(comp_name)
            # print(f"[DUP CHECK] name='{name}'  name_lower='{name.lower()}'")
            # print(f"[DUP CHECK] existing names: {existing}")
            # print(f"[DUP CHECK] match={name.lower() in existing}")
            if name.lower() in existing:
                QMessageBox.warning(
                    self,
                    "Duplicate Name",
                    f'A material named "{name}" already exists in "{comp_name}".\n'
                    "Use a different name.",
                )
                return
            self.add_material(comp_name, values)
            dialog._reset_for_next(name)

        dialog.material_added.connect(_on_material_added)
        dialog.exec()

    def open_edit_dialog(self, comp_name, original_index):
        try:
            # Always fetch fresh so the dialog reflects changes made by other pages
            # (e.g. recycling toggling included_in_recyclability) since last load.
            current_data = get_chunk(self.chunk_name)
            self.data = current_data
            items = current_data.get(comp_name, [])

            if original_index < len(items):
                item_to_edit = items[original_index]

                dialog = MaterialDialog(
                    comp_name,
                    self,
                    data=item_to_edit,
                    country=self._get_project_country(),
                    sor_db_key=self._get_project_sor_db(),
                )
                if dialog.exec():
                    new_data = dialog.get_values()
                    new_values = dict(new_data.get("values", {}))
                    new_meta = new_data.get("meta", {})
                    new_state = new_data.get("state", {})

                    new_db_original = new_meta.get("db_original")
                    item_to_edit["values"] = new_values
                    now = datetime.datetime.now().isoformat()
                    item_to_edit["meta"]["modified_on"] = now
                    item_to_edit["meta"]["source"] = new_meta.get("source", item_to_edit["meta"].get("source", "manual"))
                    if new_db_original is not None:
                        item_to_edit["meta"]["db_original"] = new_db_original
                    item_to_edit["state"]["included_in_carbon_emission"] = new_state.get("included_in_carbon_emission", True)
                    item_to_edit["state"]["included_in_recyclability"] = new_state.get("included_in_recyclability", False)
                    item_to_edit["state"]["allow_edit_checked"] = new_state.get("allow_edit_checked", False)

                    self.controller.engine.stage_update(
                        chunk_name=self.chunk_name, data=current_data
                    )
                    self.controller.chunk_updated.emit(self.chunk_name)
                    self.save_current_state()

                    def _do_edit():
                        self.data = current_data
                        table = getattr(self, "sections", {}).get(comp_name)
                        if table:
                            # Find the visual row whose col-6 UserRole matches original_index
                            visual_row = None
                            for r in range(table.rowCount()):
                                cell = table.item(r, 6)
                                if cell and cell.data(Qt.UserRole) == original_index:
                                    visual_row = r
                                    break

                            if visual_row is not None:
                                v = new_values
                                # Surgical update of cells 0-5
                                cells_updated = 0
                                for col, text in [
                                    (0, v.get("material_name", "New Item")),
                                    (1, fmt(v.get("quantity"))),
                                    (2, UNIT_DISPLAY.get(v.get("unit", "").lower(), v.get("unit", ""))),
                                    (3, fmt_comma(v.get("rate"))),
                                    (4, v.get("rate_source", "Manual")),
                                ]:
                                    it = table.item(visual_row, col)
                                    if it:
                                        it.setText(text)
                                        cells_updated += 1

                                try:
                                    rate = float(v.get("rate") or 0)
                                    qty = float(v.get("quantity") or 0)
                                    total = rate * qty
                                except (ValueError, TypeError):
                                    total = 0.0

                                it_total = table.item(visual_row, 5)
                                if it_total:
                                    it_total.setText(fmt_comma(total))
                                    cells_updated += 1

                                # If cells are missing (None), fallback to full refresh
                                if cells_updated < 6:
                                    self.on_refresh()
                                else:
                                    table.update_height()
                                    self._update_summary()
                            else:
                                self.on_refresh()
                        else:
                            self.on_refresh()

                    QTimer.singleShot(0, _do_edit)
        except Exception as e:

            print(f"[ERROR] open_edit_dialog crashed: {e}")
            traceback.print_exc()

    def toggle_trash_status(self, comp_name, data_index, should_trash):
        data = self.controller.engine.fetch_chunk(self.chunk_name) or {}
        if comp_name not in data or len(data[comp_name]) <= data_index:
            return

        item = data[comp_name][data_index]
        mat_uuid = item.get("id")
        mat_name = item.get("values", {}).get("material_name", "")

        # If trashing, warn about all pages that reference this material
        if should_trash and mat_uuid:
            state = item.get("state", {})
            impacts = []

            if state.get("included_in_carbon_emission") is True:
                impacts.append("• Carbon Emissions — this material contributes to carbon calculations")

            if state.get("included_in_recyclability") is True:
                impacts.append("• Recycling — this material is included in recyclability calculations")

            transport = self.controller.engine.fetch_chunk("transport_data") or {}
            affected_deliveries = [
                v.get("vehicle", {}).get("name", "Unnamed")
                for v in transport.get("vehicles", [])
                if not v.get("state", {}).get("in_trash", False)
                and any(
                    (m.get("uuid") if isinstance(m, dict) else m) == mat_uuid
                    for m in v.get("materials", [])
                )
            ]
            if affected_deliveries:
                impacts.append(
                    "• Transport Deliveries — referenced in: "
                    + ", ".join(affected_deliveries)
                )

            if impacts:
                reply = QMessageBox.warning(
                    self,
                    "Material Referenced in Other Pages",
                    f'"{mat_name}" is used in:\n\n'
                    + "\n".join(impacts)
                    + "\n\nMoving to trash will exclude it from all these calculations.\n\nContinue?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    return
                # Remove from deliveries and snapshot the removed entries for restore
                removed_from = []
                for v in transport.get("vehicles", []):
                    before = v.get("materials", [])
                    removed = [m for m in before if (m.get("uuid") if isinstance(m, dict) else m) == mat_uuid]
                    if removed:
                        v["materials"] = [m for m in before if m not in removed]
                        removed_from.append({"vehicle_id": v.get("id"), "entry": removed[0]})
                if removed_from:
                    self.controller.engine.stage_update(chunk_name="transport_data", data=transport)
                # Store snapshot so restore can put it back
                item.setdefault("state", {})["_transport_snapshot"] = removed_from

        if "state" not in item:
            item["state"] = {}
        item["state"]["in_trash"] = should_trash
        self.data = data

        self.controller.engine.stage_update(chunk_name=self.chunk_name, data=data)
        self.controller.chunk_updated.emit(self.chunk_name)
        self.save_current_state()

        if should_trash and mat_uuid:
            self.controller.material_trashed.emit(mat_uuid)

        def _do_refresh():
            table = self.sections.get(comp_name)
            if table:
                table.remove_row_by_index(data_index)
            self._update_summary()
            main_view = self.window().findChild(QWidget, "StructureTabView")
            if main_view:
                main_view.update_trash_count()

        QTimer.singleShot(0, _do_refresh)

    def add_new_component(self):
        dialog = QInputDialog(self)
        dialog.setWindowTitle("New Component")
        dialog.setLabelText("Enter Component Name:")
        dialog.setOkButtonText("Add")
        ok = dialog.exec()
        name = dialog.textValue()
        if ok and name.strip():
            clean_name = name.strip()
            current_data = self.controller.engine.fetch_chunk(self.chunk_name) or {}
            if any(k.lower() == clean_name.lower() for k in current_data):
                QMessageBox.warning(
                    self,
                    "Duplicate Component",
                    f'A component named "{clean_name}" already exists.',
                )
                return
            current_data[clean_name] = []
            self.controller.engine.stage_update(
                chunk_name=self.chunk_name, data=current_data
            )
            self.create_section(clean_name)
            self.save_current_state()

    def delete_component(self, name):
        current_data = self.controller.engine.fetch_chunk(self.chunk_name) or {}
        items = current_data.get(name, [])
        active_count = sum(
            1 for i in items if not i.get("state", {}).get("in_trash", False)
        )

        msg = f'Delete component "{name}"?'
        if active_count:
            msg += f"\n\n{active_count} material(s) will be moved to trash."

        box = _make_msgbox(self, QMessageBox.Warning, "Delete Component", msg)
        if box.exec() != QMessageBox.Yes:
            return

        for item in items:
            item.setdefault("state", {})["in_trash"] = True
        self.controller.engine.stage_update(chunk_name=self.chunk_name, data=current_data)
        self.controller.chunk_updated.emit(self.chunk_name)
        self.save_current_state()
        self.data = current_data
        self.refresh_ui()

        main_view = self.window().findChild(QWidget, "StructureTabView")
        if main_view:
            main_view.update_trash_count()

    def freeze(self, frozen: bool = True):
        self._frozen = frozen
        freeze_widgets(frozen, self.add_comp_btn, *self._add_material_btns, *self._del_comp_btns)
        for table in self.sections.values():
            table.freeze(frozen)

    def save_current_state(self):
        if self.controller and self.controller.engine:
            eng = self.controller.engine
            eng._last_keystroke_time = time.time()
            eng._has_unsaved_changes = True
            try:
                eng.on_dirty(True)
            except Exception:
                pass


