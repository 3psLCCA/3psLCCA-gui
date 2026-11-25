from three_ps_lcca_gui.gui.themes import get_token
from PySide6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)
from PySide6.QtCore import Qt, QEvent, QModelIndex, QTimer
from ...utils.definitions import UNIT_DISPLAY
from ...utils.display_format import fmt, fmt_comma
from ...utils.icons import make_icon
from ...utils.table_widgets import (
    GroupedHeaderView,
    BaseActionDelegate,
    TooltipTableMixin,
    TableCard,
    fit_to_contents,
)
from three_ps_lcca_gui.gui.assets.themes.column_style import (
    apply_column_style,
    pin_last_column,
    pinned_view,
    refit,
)



def _make_msgbox(parent, icon, title, text):
    """QMessageBox styled to match the app theme background."""
    box = QMessageBox(icon, title, text, QMessageBox.Yes | QMessageBox.No, parent)
    box.setDefaultButton(QMessageBox.No)
    box.setStyleSheet(
        f"QMessageBox {{ background-color: {get_token('base')}; color: {get_token('text')}; }}"
        f"QLabel {{ color: {get_token('text')}; }}"
    )
    return box


class _CellDelegate(QStyledItemDelegate):
    """Shows the unit after the quantity (col 2 stays hidden) and reads work
    names saved with line breaks (e.g. from Excel) as one line."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.column() == 0:
            option.text = " ".join(option.text.split())
        elif index.column() == 1:
            unit = index.siblingAtColumn(2).data() or ""
            if unit:
                option.text = f"{option.text} {unit}"


# ---------------------------------------------------------------------------
# Action column delegate - paints icon buttons directly, no QWidget overhead
# ---------------------------------------------------------------------------


class _ActionDelegate(BaseActionDelegate):
    """Paints circular icon buttons in the Action column and handles clicks."""

    BTN_GAP = 8

    def __init__(self, table, manager, component_name, is_trash_view):
        super().__init__(table)
        self._manager = manager
        self._component = component_name
        self._trash_view = is_trash_view
        self._icon_size = 16  # base default (80% of the 28 px button) is too heavy here

        if not is_trash_view:
            self._btns = [
                (make_icon("edit"), (46, 204, 113), "edit", "Edit"),
                (
                    make_icon("trash", color=get_token("danger")),
                    (231, 76, 60),
                    "trash",
                    "Move to trash",
                ),
            ]
        else:
            self._btns = [
                (make_icon("restore"), (46, 204, 113), "restore", "Restore"),
                (
                    make_icon("trash", color=get_token("danger")),
                    (192, 57, 43),
                    "delete",
                    "Permanently delete",
                ),
            ]

    def _action_col(self) -> int:
        return 6  # col 7 (Component) comes after it in the model

    def _get_btns_for_row(self, row) -> list[tuple]:
        return [
            (icon, hover_rgb, tooltip) for icon, hover_rgb, _, tooltip in self._btns
        ]

    def editorEvent(self, event, model, option, index):
        if self._frozen:
            return False
        if event.type() == QEvent.MouseButtonRelease:
            original_index = index.data(Qt.UserRole)
            rects = self._btn_rects(option.rect, len(self._btns))
            for i, (_, _, action, *__) in enumerate(self._btns):
                if rects[i].contains(event.pos()):
                    if action == "edit":
                        self._manager.open_edit_dialog(self._component, original_index)
                    elif action == "trash":
                        self._confirm_trash(original_index)
                    elif action == "restore":
                        self._manager.toggle_trash_status(
                            self._component, original_index, False
                        )
                    elif action == "delete":
                        self._confirm_delete(original_index)
                    return True
        return False

    def _confirm_trash(self, original_index):
        box = _make_msgbox(self._table, QMessageBox.Warning, "Move to Trash", "Move this item to trash?")
        if box.exec() == QMessageBox.Yes:
            self._manager.toggle_trash_status(self._component, original_index, True)

    def _confirm_delete(self, original_index):
        box = _make_msgbox(self._table, QMessageBox.Critical, "Permanent Delete", "Remove this item? This cannot be undone.")
        if box.exec() == QMessageBox.Yes:
            self._manager.permanent_delete(self._component, original_index)


# ---------------------------------------------------------------------------
# Structure table
# ---------------------------------------------------------------------------


class StructureTableWidget(TooltipTableMixin, QTableWidget):
    _GROUPS = []

    def __init__(self, parent_manager, component_name, is_trash_view=False, read_only=False,
                 show_component=False, title=None, framed=True):
        super().__init__()
        self._framed = framed  # False: an outer card draws the border
        self._read_only = read_only
        self.manager = parent_manager
        self.component_name = component_name
        self.title = title or component_name
        self.is_trash_view = is_trash_view
        self._frozen = False

        self.setHorizontalHeader(GroupedHeaderView(groups=self._GROUPS))
        self.setItemDelegate(_CellDelegate(self))
        self.currency = ""

        # cols 0-5 values (2 hidden, painted inside 1), col 6 Action (buttons;
        # also stores the item's index), col 7 Component (Summary/Trash only,
        # shown first).
        self.setColumnCount(8)
        _L = Qt.AlignLeft | Qt.AlignVCenter
        _headers = [
            "Work name",   # 0
            "Quantity",    # 1
            "Unit",        # 2  hidden - painted after the quantity
            "Rate",        # 3
            "Source",      # 4
            "Amount",      # 5
            "Action",      # 6  buttons, pinned to the right edge
            "Component",   # 7  hidden unless show_component
        ]
        for col, label in enumerate(_headers):
            item = QTableWidgetItem(label)
            # Work name and Component sit left over their text; the rest are centred
            item.setTextAlignment(_L if col in (0, 7) else Qt.AlignCenter)
            self.setHorizontalHeaderItem(col, item)

        self.setColumnHidden(2, True)
        self.setColumnHidden(6, read_only)  # read-only: no buttons
        self.setColumnHidden(7, not show_component)
        if show_component:
            self.horizontalHeader().moveSection(7, 0)

        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        fit_to_contents(self)  # every row shows; the page scrolls down

        # Action buttons: paint and handle clicks in col 6
        self._action_delegate = _ActionDelegate(
            self, parent_manager, component_name, is_trash_view
        )
        self.setItemDelegateForColumn(6, self._action_delegate)
        if not read_only:  # rows fit the buttons
            btn_h = self._action_delegate.sizeHint(QStyleOptionViewItem(), QModelIndex()).height()
            self.verticalHeader().setMinimumSectionSize(btn_h)

        # widths from the header labels (assets/themes/column_style.py); the
        # table scrolls sideways itself, with Action pinned to its right edge.
        # break_long_words off: _CellDelegate paints the Work name column.
        apply_column_style(self, break_long_words=False)
        if not read_only:
            pin_last_column(self)
            self._action_delegate.track(pinned_view(self))

        # heading row (title, count, total) lives in a TableCard - see card()
        self._card = None
        self._card_pending = False
        for sig in (self.model().rowsInserted, self.model().rowsRemoved, self.model().dataChanged):
            sig.connect(self._schedule_card)
        # the hidden unit cell is painted inside Quantity - repaint on any change
        self.model().dataChanged.connect(self.viewport().update)

        if not self.is_trash_view:
            self.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self.update_height()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def card(self) -> TableCard:
        """This table in a TableCard whose heading row shows the title, the
        item count and the total (kept up to date as rows change)."""
        if self._card is None:
            self._card = TableCard(self, self.title)
            self._refresh_card()
        return self._card

    def _schedule_card(self, *_):
        """Recount once after a batch of row changes, not once per cell."""
        if self._card is not None and not self._card_pending:
            self._card_pending = True
            QTimer.singleShot(0, self, self._refresh_card)

    def _refresh_card(self):
        """Count and sum the item rows (those with col 6 data) into the card."""
        self._card_pending = False
        if self._card is None:
            return
        count, total = 0, 0.0
        for r in range(self.rowCount()):
            cell = self.item(r, 6)
            if cell is None or cell.data(Qt.UserRole) is None:
                continue  # no stored item index
            count += 1
            amount = self.item(r, 5)
            try:
                total += float(amount.text().replace(",", "")) if amount else 0.0
            except ValueError:
                pass
        self._card.set_count(f"{count} item" + ("" if count == 1 else "s") if count else "No materials yet")
        cur = f" {self.currency}" if self.currency else ""
        self._card.set_total(fmt_comma(total) + cur)

    def _on_cell_double_clicked(self, row, column):
        if self._frozen:
            return
        cell = self.item(row, 6)
        if cell is None:
            return
        self.manager.open_edit_dialog(self.component_name, cell.data(Qt.UserRole))

    def set_currency(self, code: str):
        self.currency = code or ""
        self._refresh_card()
        suffix = f" ({code})" if code else ""
        for col, base in ((3, "Rate"), (5, "Amount")):
            item = self.horizontalHeaderItem(col)
            if item:
                item.setText(base + suffix)

    def update_height(self):
        """Re-fit columns, rows and the pinned Action column to the rows now."""
        refit(self)
        self.updateGeometry()

    def _schedule_layout(self):
        """Grow to the rows; column_style re-fits the columns on its own."""
        self.updateGeometry()

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def add_row(self, item_data, original_index, component=""):
        self.blockSignals(True)
        row = self.rowCount()
        self.insertRow(row)

        v = item_data.get("values", {})

        self.setItem(row, 0, QTableWidgetItem(v.get("material_name", "New Item")))

        qty_item = QTableWidgetItem(fmt(v.get("quantity")))
        qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(row, 1, qty_item)

        unit = v.get("unit", "")
        unit = UNIT_DISPLAY.get(unit.lower(), unit) if unit else unit
        self.setItem(row, 2, QTableWidgetItem(unit))

        rate_item = QTableWidgetItem(fmt_comma(v.get("rate")))
        rate_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(row, 3, rate_item)

        self.setItem(row, 4, QTableWidgetItem(v.get("rate_source", "Manual")))

        try:
            rate = float(v.get("rate") or 0)
            qty = float(v.get("quantity") or 0)
            total = rate * qty
        except (ValueError, TypeError):
            total = 0.0

        total_item = QTableWidgetItem(fmt_comma(total))
        total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(row, 5, total_item)

        # Col 6: Action buttons; stores original_index for the clicks
        action_item = QTableWidgetItem()
        action_item.setData(Qt.UserRole, original_index)
        action_item.setFlags(Qt.ItemIsEnabled)
        self.setItem(row, 6, action_item)

        # Col 7: the component name (shown in Summary / Trash only)
        self.setItem(row, 7, QTableWidgetItem(component))

        self.blockSignals(False)
        self._schedule_layout()

    def insert_row_at_position(self, item_data: dict, original_index: int):
        """Insert a row at the correct sorted position (by original_index)."""
        pos = self.rowCount()
        for r in range(self.rowCount()):
            cell = self.item(r, 6)
            if cell:
                idx = cell.data(Qt.UserRole)
                if isinstance(idx, int) and idx > original_index:
                    pos = r
                    break

        self.blockSignals(True)
        self.insertRow(pos)

        v = item_data.get("values", {})

        self.setItem(pos, 0, QTableWidgetItem(v.get("material_name", "New Item")))

        qty_item = QTableWidgetItem(fmt(v.get("quantity", 0)))
        qty_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(pos, 1, qty_item)

        unit = v.get("unit", "")
        unit = UNIT_DISPLAY.get(unit.lower(), unit) if unit else unit
        self.setItem(pos, 2, QTableWidgetItem(unit))

        rate_item = QTableWidgetItem(fmt_comma(v.get("rate", 0)))
        rate_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(pos, 3, rate_item)

        self.setItem(pos, 4, QTableWidgetItem(v.get("rate_source", "Manual")))

        try:
            rate = float(v.get("rate", 0) or 0)
            qty = float(v.get("quantity", 0) or 0)
            total = rate * qty
        except (ValueError, TypeError):
            total = 0.0

        total_item = QTableWidgetItem(fmt_comma(total))
        total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setItem(pos, 5, total_item)

        action_item = QTableWidgetItem()
        action_item.setData(Qt.UserRole, original_index)
        action_item.setFlags(Qt.ItemIsEnabled)
        self.setItem(pos, 6, action_item)

        self.setItem(pos, 7, QTableWidgetItem())

        self.blockSignals(False)
        self._schedule_layout()

    def remove_row_by_index(self, original_index: int, reindex: bool = False):
        """Remove the row whose col-6 UserRole matches original_index.

        reindex=True: decrement stored indices > original_index after removal
        (needed after permanent delete, which shifts the data array).
        """
        found = None
        for row in range(self.rowCount()):
            item = self.item(row, 6)
            if item and item.data(Qt.UserRole) == original_index:
                found = row
                break
        if found is None:
            return
        self.removeRow(found)
        if reindex:
            for row in range(self.rowCount()):
                cell = self.item(row, 6)
                if cell:
                    idx = cell.data(Qt.UserRole)
                    if isinstance(idx, int) and idx > original_index:
                        cell.setData(Qt.UserRole, idx - 1)
        self._schedule_layout()

    # ------------------------------------------------------------------
    # Freeze / unfreeze
    # ------------------------------------------------------------------

    def freeze(self, frozen: bool = True):
        self._frozen = frozen
        self._action_delegate.set_frozen(frozen)
