from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QMessageBox,
    QPushButton,
)
from PySide6.QtCore import QTimer
from three_ps_lcca_gui.gui.themes import get_token
from .base_table import _make_msgbox
from .items_by_tab import ItemsByTabView, TAB_NAMES


class TrashTabWidget(ItemsByTabView):
    """
    Lists every item whose state['in_trash'] is True, one table per tab,
    with Restore / Delete actions.
    """

    SHOW_TRASHED = True
    TITLE = "Deleted from: {tab}"
    EMPTY_TEXT = "No items in Trash Bin."
    TABLE_OPTIONS = {"is_trash_view": True}

    def __init__(self, controller=None):
        super().__init__(controller)

        header = QLabel(
            "<b>Trash Bin</b><br>Items here are excluded from all calculations."
        )
        header.setStyleSheet(f"color: {get_token('text_secondary')}; margin-bottom: 10px;")
        self.delete_all_btn = QPushButton("Delete All")
        self.delete_all_btn.setStyleSheet(
            f"QPushButton {{ background-color: {get_token('danger')}; color: white; }}"
            f"QPushButton:disabled {{ background-color: {get_token('danger', 'disabled')}; color: white; }}"
        )
        self.delete_all_btn.clicked.connect(self._delete_all)
        self.header_row.addWidget(header, 1)
        self.header_row.addWidget(self.delete_all_btn)

    def _delete_all(self):
        box = _make_msgbox(
            self, QMessageBox.Critical,
            "Delete All",
            "Permanently delete all items in trash? This cannot be undone.",
        )
        if box.exec() != QMessageBox.Yes:
            return

        if not self.controller or not self.controller.engine:
            return

        for chunk_id in self.chunks:
            data = self.controller.get_fresh_chunk(chunk_id) or {}
            changed = False
            for comp_name in list(data.keys()):
                before = len(data[comp_name])
                data[comp_name] = [
                    item for item in data[comp_name]
                    if not item.get("state", {}).get("in_trash", False)
                ]
                if len(data[comp_name]) != before:
                    changed = True
            if changed:
                self.controller.save_chunk_data(chunk_id, data)

        self.on_refresh()
        main_view = self.window().findChild(QWidget, "StructureTabView")
        if main_view:
            main_view.update_trash_count()

    def _refreshed(self, rows_by_chunk):
        self.delete_all_btn.setEnabled(any(rows_by_chunk.values()))

    def permanent_delete(self, chunk_id, comp_name, data_index):
        """Permanently remove a trashed item of comp_name in chunk_id."""
        data = self.controller.get_fresh_chunk(chunk_id) or {}
        items = data.get(comp_name, [])
        if data_index >= len(items) or not items[data_index].get("state", {}).get("in_trash", False):
            return

        del items[data_index]
        self.controller.save_chunk_data(chunk_id, data)

        def _do():
            self.on_refresh()  # row keys shift after a delete, so rebuild
            main_view = self.window().findChild(QWidget, "StructureTabView")
            if main_view:
                main_view.update_trash_count()

        QTimer.singleShot(0, _do)

    def toggle_trash_status(self, chunk_id, comp_name, data_index, should_trash):
        """
        Restores (should_trash=False) or re-trashes (should_trash=True) the
        item of comp_name in chunk_id.
        """
        data = self.controller.get_fresh_chunk(chunk_id) or {}
        items = data.get(comp_name, [])
        if data_index >= len(items):
            return
        item = items[data_index]
        if item.get("state", {}).get("in_trash", False) == should_trash:
            return  # already in the wanted state: stale row, leave it alone

        # Before restoring, check for an active item with the same name.
        if not should_trash:
            restoring_name = (
                item.get("values", {}).get("material_name", "").strip().lower()
            )
            active_names = {
                it.get("values", {}).get("material_name", "").strip().lower()
                for it in items
                if not it.get("state", {}).get("in_trash", False)
            }
            if restoring_name and restoring_name in active_names:
                QMessageBox.warning(
                    self,
                    "Name Conflict",
                    f'A material named "{item.get("values", {}).get("material_name", "")}" '
                    f'already exists in "{TAB_NAMES.get(chunk_id, chunk_id)} › {comp_name}".\n\n'
                    "Remove or rename the existing material before restoring this one.",
                )
                return

        item.setdefault("state", {})["in_trash"] = should_trash
        if not should_trash:
            item["state"].pop("_transport_snapshot", None)

        self.controller.save_chunk_data(chunk_id, data)

        # When restoring, clear is_deleted from the component registry
        if not should_trash:
            try:
                registry = self.controller.engine.fetch_chunk("str_component_registry") or {}
                comp_meta = registry.get(chunk_id, {}).get(comp_name, {})
                if comp_meta.get("is_deleted", False):
                    comp_meta["is_deleted"] = False
                    self.controller.engine.stage_update(
                        chunk_name="str_component_registry", data=registry
                    )
            except Exception:
                pass

        def _do(ci=chunk_id, cn=comp_name, di=data_index,
                st=should_trash, d=data, idata=item):
            self.on_refresh()

            main_view = self.window().findChild(QWidget, "StructureTabView")
            if main_view:
                if not st:
                    _CHUNK_TAB = {
                        "str_foundation":     main_view.foundation_tab,
                        "str_sub_structure":  main_view.substructure_tab,
                        "str_super_structure": main_view.superstructure_tab,
                        "str_misc":           main_view.misc_tab,
                    }
                    active_tab = _CHUNK_TAB.get(ci)
                    section_table = active_tab.sections.get(cn) if active_tab else None
                    if section_table:
                        section_table.insert_row_at_position(idata, di)
                        active_tab.data = d
                        active_tab._update_summary()
                    elif active_tab:
                        main_view.refresh_tab_by_chunk(ci)
                main_view.update_trash_count()

        QTimer.singleShot(0, _do)
