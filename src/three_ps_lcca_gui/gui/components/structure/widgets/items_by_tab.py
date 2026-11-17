"""Shared base for the Trash and Summary tabs: one table per structure tab,
with a Component column, built from the items that match SHOW_TRASHED."""

import json

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
)
from three_ps_lcca_gui.gui.themes import get_token
from .base_table import StructureTableWidget

# chunk id -> tab name, in tab order
TAB_NAMES = {
    "str_foundation": "Foundation",
    "str_sub_structure": "Sub-Structure",
    "str_super_structure": "Super-Structure",
    "str_misc": "Miscellaneous",
}


class _RowScope:
    """Manager for one tab's table. The table holds rows of several
    components, so each row stores a key into self.rows, which gives the
    row's (component, data index); clicks are sent on to the view with those."""

    def __init__(self, view, chunk_id):
        self._view = view
        self._chunk_id = chunk_id
        self.rows = []  # key -> (comp_name, data_index)

    def toggle_trash_status(self, _table_name, key, should_trash):
        self._view.toggle_trash_status(self._chunk_id, *self.rows[key], should_trash)

    def permanent_delete(self, _table_name, key):
        self._view.permanent_delete(self._chunk_id, *self.rows[key])

    def open_edit_dialog(self, _table_name, key):
        self._view.open_item(self._chunk_id, *self.rows[key])


class ItemsByTabView(QWidget):
    """Subclasses set the class attributes below, fill self.header_row, and
    may override _setup_table() and _refreshed()."""

    SHOW_TRASHED = False      # list trashed items (Trash) or active ones (Summary)
    TITLE = "{tab}"           # title above each table
    EMPTY_TEXT = ""
    TABLE_OPTIONS = {}        # extra StructureTableWidget arguments

    def __init__(self, controller=None):
        super().__init__()
        self.controller = controller
        self._built_sig = None  # _signature() of what is currently shown
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 8, 0, 0)

        self.header_row = QHBoxLayout()
        self.layout.addLayout(self.header_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.scroll.setWidget(self.container)
        self.layout.addWidget(self.scroll)

        self.chunks = list(TAB_NAMES)

    def _rows(self, chunk_id):
        """(comp_name, data_index, item) of every listed item in chunk_id."""
        data = self.controller.engine.fetch_chunk(chunk_id) or {}
        return [
            (comp_name, idx, item)
            for comp_name, items in data.items()
            for idx, item in enumerate(items)
            if item.get("state", {}).get("in_trash", False) == self.SHOW_TRASHED
        ]

    def _signature(self):
        """Snapshot of the listed items, used to skip rebuilding an unchanged view."""
        if not self.controller or not self.controller.engine:
            return None
        return [
            (chunk_id, comp_name, idx,
             json.dumps(item.get("values", {}), sort_keys=True, default=str))
            for chunk_id in self.chunks
            for comp_name, idx, item in self._rows(chunk_id)
        ]

    def _setup_table(self, table):
        """Hook: adjust a new table before rows are added."""

    def _table_filled(self, table, rows):
        """Hook: called after a table's rows are added, with its _rows() list."""

    def _refreshed(self, rows_by_chunk):
        """Hook: called after a rebuild with {chunk_id: _rows(chunk_id)}."""

    def on_refresh(self, force=False):
        """Clears the view and re-populates it, one table per tab.

        Building the tables is slow, so the rebuild is skipped when the items
        are the same as last time, unless force=True.
        """
        sig = self._signature()
        if not force and sig is not None and sig == self._built_sig:
            return
        self._built_sig = sig

        for i in reversed(range(self.container_layout.count())):
            widget = self.container_layout.takeAt(i).widget()
            if widget:
                widget.deleteLater()

        if not self.controller or not self.controller.engine:
            return

        rows_by_chunk = {chunk_id: self._rows(chunk_id) for chunk_id in self.chunks}
        for chunk_id, rows in rows_by_chunk.items():
            if not rows:
                continue
            tab_name = TAB_NAMES.get(chunk_id, chunk_id)

            # Title, then the table (it has its own border)
            group = QWidget()
            g_layout = QVBoxLayout(group)
            g_layout.setContentsMargins(0, 0, 0, 12)
            title = QLabel(self.TITLE.format(tab=tab_name))
            title.setObjectName("componentTitle")
            g_layout.addWidget(title)

            scope = _RowScope(self, chunk_id)
            table = StructureTableWidget(scope, tab_name, show_component=True, **self.TABLE_OPTIONS)
            self._setup_table(table)
            for comp_name, idx, item in rows:
                table.add_row(item, len(scope.rows), comp_name)
                scope.rows.append((comp_name, idx))
            self._table_filled(table, rows)
            g_layout.addWidget(table)
            self.container_layout.addWidget(group)

        if not any(rows_by_chunk.values()):
            empty_lbl = QLabel(self.EMPTY_TEXT)
            empty_lbl.setStyleSheet(f"color: {get_token('text_disabled')}; font-style: italic;")
            self.container_layout.addWidget(empty_lbl)

        self._refreshed(rows_by_chunk)

        # Force items to the top
        self.container_layout.addStretch()
        self.container.adjustSize()
