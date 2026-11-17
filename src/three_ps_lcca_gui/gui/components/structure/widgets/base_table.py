from three_ps_lcca_gui.gui.themes import get_token, theme_manager
from PySide6.QtWidgets import (
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSizePolicy,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QWidget,
)
from PySide6.QtCore import Qt, QSize, QEvent, QRect, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QFontMetricsF, QPainter, QPainterPath
from ...utils.definitions import UNIT_DISPLAY
from ...utils.display_format import fmt, fmt_comma
from ...utils.icons import make_icon
from ...utils.table_widgets import (
    GroupedHeaderView,
    WordWrapHeaderView,
    BaseActionDelegate,
    TooltipTableMixin,
)
from three_ps_lcca_gui.gui.theme import BTN_SM, FS_MD, FS_SM, FW_BOLD, FW_SEMIBOLD, SP2, SP3


_HDR_FONT = QFont("Ubuntu", FS_SM, FW_SEMIBOLD)
_HDR_H = 32  # one-line column titles
_CAP_H = 44  # heading row above the column titles

_ACTION_W = 80  # fixed Action column width


def _make_msgbox(parent, icon, title, text):
    """QMessageBox styled to match the app theme background."""
    box = QMessageBox(icon, title, text, QMessageBox.Yes | QMessageBox.No, parent)
    box.setDefaultButton(QMessageBox.No)
    box.setStyleSheet(
        f"QMessageBox {{ background-color: {get_token('base')}; color: {get_token('text')}; }}"
        f"QLabel {{ color: {get_token('text')}; }}"
    )
    return box
_ROW_H = 40  # row height - 6 px clearance top + bottom around 28 px button
_READ_ONLY_ROW_H = 34  # no action buttons to fit


_MUTED_COLS = (4, 7)  # Source, Component
_AMOUNT_COL = 5
_RADIUS = 8  # card corners


def _muted() -> QColor:
    """Text blended 40 % toward the background - visibly grey in every theme."""
    t, b = QColor(get_token("text")), QColor(get_token("base"))
    return QColor(*(round(b + 0.6 * (a - b)) for a, b in (
        (t.red(), b.red()), (t.green(), b.green()), (t.blue(), b.blue()))))


def _band() -> QColor:
    """Base nudged 4 % toward text - the heading row's slightly lighter fill."""
    t, b = QColor(get_token("text")), QColor(get_token("base"))
    return QColor(*(round(b + 0.04 * (a - b)) for a, b in (
        (t.red(), b.red()), (t.green(), b.green()), (t.blue(), b.blue()))))


def _divider(painter, option):
    """Thin line under a row, except where the card border already closes it."""
    rect = option.rect
    w = option.widget
    table = getattr(w, "_parent_table", w)
    vp = w.viewport() if w else None
    if getattr(table, "_framed", True) and vp is not None and rect.bottom() >= vp.height() - 1:
        return
    painter.save()
    painter.setPen(QColor(get_token("surface_mid")))
    painter.drawLine(rect.bottomLeft(), rect.bottomRight())
    painter.restore()


class _CellDelegate(QStyledItemDelegate):
    """Muted Component and Source, bold Amount, the unit as a muted suffix
    on Quantity (col 2 stays hidden), and a line under each row.
    Work name wraps and the row grows to fit; other columns stay one line."""

    def sizeHint(self, option, index):
        if index.column() != 0:
            return QSize(0, 0)  # one line - the row's minimum height covers it
        fm = QFontMetrics(option.font)
        w = max(1, option.rect.width() - 2 * SP3)
        text = " ".join((index.data() or "").split())  # same as paint
        h = fm.boundingRect(QRect(0, 0, w, 100000), Qt.TextWordWrap, text).height()
        return QSize(w, h + SP3)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text, opt.text = opt.text, ""
        # background, hover and selection only - the text is drawn below
        opt.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        col = index.column()
        rect = opt.rect.adjusted(SP3, 0, -SP3, 0)
        muted = _muted()
        painter.save()
        f = QFont(opt.font)
        if col == _AMOUNT_COL:
            f.setWeight(QFont.Weight(FW_SEMIBOLD))
        painter.setFont(f)
        fm = painter.fontMetrics()
        if col == 1:
            unit = index.siblingAtColumn(2).data() or ""
            if unit:
                painter.setPen(muted)
                painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, unit)
                rect = rect.adjusted(0, 0, -fm.horizontalAdvance(" " + unit), 0)
        painter.setPen(muted if col in _MUTED_COLS else QColor(get_token("text")))
        if col == 0:
            # names saved with line breaks (e.g. from Excel) read as one line
            text = " ".join(text.split())
            painter.drawText(rect, opt.displayAlignment | Qt.TextWordWrap, text)
        else:
            painter.drawText(rect, opt.displayAlignment, fm.elidedText(text, Qt.ElideRight, rect.width()))
        painter.restore()
        _divider(painter, option)


class _Caption(QWidget):
    """Heading row at the top of the card: title, item count and total.
    Counts and sums the table's own item rows (those with col 6 data)."""

    def __init__(self, table):
        super().__init__(table)
        self._table = table
        self.menu_btn = None

    def set_menu(self, menu):
        btn = QToolButton(self)
        btn.setText("•••")
        btn.setToolTip("More actions")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setFixedSize(BTN_SM, BTN_SM)
        btn.setMenu(menu)
        self.menu_btn = btn
        self.apply_style()
        self._place_btn()
        btn.show()
        return btn

    def apply_style(self):
        if self.menu_btn:
            self.menu_btn.setStyleSheet(
                f"QToolButton {{ border: none; border-radius: {SP2 - 2}px; background: transparent;"
                f" color: {_muted().name()}; font-size: {FS_SM}pt; font-weight: {FW_BOLD}; padding: 0px; }}"
                f"QToolButton:hover, QToolButton:pressed {{ background: {get_token('surface_mid')};"
                f" color: {get_token('text')}; }}"
                f"QToolButton::menu-indicator {{ image: none; width: 0px; }}"
            )

    def _place_btn(self):
        if self.menu_btn:
            b = self.menu_btn
            b.move(self.width() - SP2 - b.width(), (self.height() - b.height()) // 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_btn()

    def showEvent(self, event):
        super().showEvent(event)
        self._place_btn()

    def paintEvent(self, event):
        t = self._table
        count, total = 0, 0.0
        for r in range(t.rowCount()):
            cell = t.item(r, 6)
            if cell is None or cell.data(Qt.UserRole) is None:
                continue  # no stored item index
            count += 1
            amount = t.item(r, 5)
            try:
                total += float(amount.text().replace(",", "")) if amount else 0.0
            except ValueError:
                pass

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # lighter band, top corners rounded to sit inside the card border
        r, w, h = _RADIUS - 1, self.width(), self.height()
        band = QPainterPath()
        band.moveTo(0, h)
        band.lineTo(0, r)
        band.quadTo(0, 0, r, 0)
        band.lineTo(w - r, 0)
        band.quadTo(w, 0, w, r)
        band.lineTo(w, h)
        band.closeSubpath()
        p.fillPath(band, _band())
        rect = self.rect().adjusted(SP3, 0, -SP3, 0)
        if self.menu_btn:  # keep the total clear of the menu button (placed by _place_btn)
            rect.setRight(self.width() - SP2 - self.menu_btn.width() - SP2)
        bold = QFont(t.font())
        bold.setPointSize(FS_MD)
        bold.setWeight(QFont.Weight(FW_BOLD))
        p.setFont(bold)
        p.setPen(QColor(get_token("text")))
        small = QFont(t.font())
        small.setPointSize(FS_SM)
        cur = f" {t.currency}" if t.currency else ""
        cur_w = QFontMetrics(small).horizontalAdvance(cur)
        amount = fmt_comma(total)
        p.drawText(rect.adjusted(0, 0, -cur_w, 0), Qt.AlignRight | Qt.AlignVCenter, amount)
        room = rect.width() - cur_w - p.fontMetrics().horizontalAdvance(amount) - SP3
        p.save()
        p.setFont(small)
        p.setPen(_muted())
        p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, cur)
        p.restore()

        count_text = "  ·  " + (f"{count} item" + ("" if count == 1 else "s") if count else "No materials yet")
        # QFontMetrics rounds down; elidedText measures fractionally - use the true width
        title_w = min(int(QFontMetricsF(p.font()).horizontalAdvance(t.title)) + 1, max(0, room - QFontMetrics(small).horizontalAdvance(count_text)))
        p.drawText(rect.adjusted(0, 0, -(rect.width() - title_w), 0), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(t.title, Qt.ElideRight, title_w))
        p.setFont(small)
        p.setPen(_muted())
        p.drawText(rect.adjusted(title_w, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(count_text, Qt.ElideRight, max(0, room - title_w)))


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

    def _get_btns_for_row(self, row) -> list[tuple]:
        return [
            (icon, hover_rgb, tooltip) for icon, hover_rgb, _, tooltip in self._btns
        ]

    def sizeHint(self, option, index):
        return QSize(_ACTION_W, _ROW_H)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        _divider(painter, option)

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
# Frozen Action overlay - single-column widget pinned to the right edge
# ---------------------------------------------------------------------------


class _FrozenActionTable(QTableWidget):
    """
    Action column pinned over the right edge of StructureTableWidget.
    _layout_columns keeps _ACTION_W px free on the right (col 7, or a
    narrower layout in show_component mode), so no value sits under it.
    """

    def __init__(self, parent_table: "StructureTableWidget"):
        super().__init__(parent_table)
        self._parent_table = parent_table

        # Use WordWrapHeaderView (not the plain default QHeaderView) so this
        # header is exempt from the app-wide _TableHeaderWordWrapFilter, which
        # asynchronously (QTimer.singleShot(0, ...)) replaces the header of any
        # QTableWidget/QTableView that isn't already a GroupedHeaderView or
        # WordWrapHeaderView. That swap runs fully decoupled from reposition()/
        # resizeEvent()/showEvent(), so if it ever landed on the plain header
        # this widget used before, nothing here would know to resync afterward.
        self.setHorizontalHeader(WordWrapHeaderView(Qt.Horizontal, font=_HDR_FONT))

        self.setColumnCount(1)
        hdr_item = QTableWidgetItem("Action")
        hdr_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        self.setHorizontalHeaderItem(0, hdr_item)
        self.horizontalHeader().setFont(_HDR_FONT)

        self.setFixedWidth(_ACTION_W)
        self.setShowGrid(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setFrameShape(QTableWidget.NoFrame)
        self.apply_style()

        self.viewport().setStyleSheet("background-color: transparent;")

        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(_ROW_H)
        self.verticalHeader().setMinimumSectionSize(_ROW_H)

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        self.setColumnWidth(0, _ACTION_W)

        # Sync vertical scroll with the main table
        parent_table.verticalScrollBar().valueChanged.connect(
            self.verticalScrollBar().setValue
        )

    def apply_style(self):
        self.setStyleSheet(
            f"QTableWidget {{ background-color: {get_token('base')}; border: none;"
            f" border-bottom-right-radius: {_RADIUS - 1}px; }}"
        )

    def sync_row_heights(self):
        for r in range(self.rowCount()):
            self.setRowHeight(r, self._parent_table.rowHeight(r))

    def add_row(self, original_index: int):
        row = self.rowCount()
        self.insertRow(row)
        self.setRowHeight(row, _ROW_H)
        item = QTableWidgetItem()
        item.setData(Qt.UserRole, original_index)
        item.setFlags(Qt.ItemIsEnabled)
        self.setItem(row, 0, item)

    def reposition(self):
        """
        Sit flush against the right edge of the parent widget, aligned with
        the top of the header.  Match the grouped header height exactly so
        row 0 lines up with the main table's first data row.
        """
        p = self._parent_table
        main_hdr_h = p.horizontalHeader().height() - _CAP_H  # titles only

        # Force overlay header to same height as the two-tier grouped header
        self.horizontalHeader().setFixedHeight(main_hdr_h)

        # x: flush right edge of parent widget
        # y: top of header = viewport top minus header height
        vp = p.viewport()
        x = p.width() - p.frameWidth() - _ACTION_W  # inside the card border
        y = vp.y() - main_hdr_h
        self.move(x, y)

        # Use the summed *row* heights rather than p.viewport().height() - the
        # viewport's own geometry only catches up with a newly-grown row (e.g.
        # from word-wrap in resizeRowsToContents()) after another layout pass,
        # leaving the overlay briefly shorter than its actual header+row content
        # in the meantime. Row heights themselves are already up to date here,
        # since resizeEvent() calls resizeRowsToContents() before reposition().
        rows_h = sum(p.rowHeight(r) for r in range(p.rowCount()))
        self.setFixedHeight(rows_h + main_hdr_h)


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
        self._row_h = _READ_ONLY_ROW_H if read_only else _ROW_H

        self.setHorizontalHeader(GroupedHeaderView(groups=self._GROUPS, font=_HDR_FONT))
        # the heading row sits over the top _CAP_H px of the header
        self.horizontalHeader().setObjectName("structHdr")
        self.horizontalHeader().setFixedHeight(_CAP_H + _HDR_H)
        self.setShowGrid(False)
        self.setItemDelegate(_CellDelegate(self))
        self.viewport().setStyleSheet("background-color: transparent;")
        self.currency = ""
        self._layout_pending = False

        # cols 0-5 visible (2 hidden, painted inside 1), col 6 hidden (data/delegate
        # only), col 7 blank space under the Action overlay or the Component name.
        self.setColumnCount(8)
        _L = Qt.AlignLeft | Qt.AlignVCenter
        _headers = [
            "Work name",   # 0
            "Quantity",    # 1
            "Unit",        # 2  hidden - painted after the quantity
            "Rate",        # 3
            "Source",      # 4
            "Amount",      # 5
            "Action",      # 6  hidden - data/delegate only
            "",            # 7  blank under the Action overlay, or Component
        ]
        for col, label in enumerate(_headers):
            item = QTableWidgetItem(label)
            # numeric columns: align the header with its right-aligned values
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter if col in (1, 3, 5) else _L)
            self.setHorizontalHeaderItem(col, item)

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(False)
        hdr.setMinimumSectionSize(60)
        self.setColumnWidth(3, 110)
        self.setColumnHidden(2, True)
        hdr.setSectionResizeMode(6, QHeaderView.Fixed)
        self.setColumnWidth(6, 0)
        self.setColumnHidden(6, True)
        hdr.setSectionResizeMode(7, QHeaderView.Fixed)
        self.setColumnWidth(7, _ACTION_W)

        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.verticalHeader().setMinimumSectionSize(self._row_h)
        self.verticalHeader().setDefaultSectionSize(self._row_h)
        self.verticalHeader().setVisible(False)

        # Delegate on hidden col 6 (stores original_index, handles clicks)
        self._action_delegate = _ActionDelegate(
            self, parent_manager, component_name, is_trash_view
        )
        self.setItemDelegateForColumn(6, self._action_delegate)

        # Frozen overlay
        self._frozen_col = _FrozenActionTable(self)
        self._frozen_action_delegate = _ActionDelegate(
            self._frozen_col, parent_manager, component_name, is_trash_view
        )
        self._frozen_col.setItemDelegateForColumn(0, self._frozen_action_delegate)
        self._frozen_col.show()

        self._caption = _Caption(self)
        for sig in (self.model().rowsInserted, self.model().rowsRemoved, self.model().dataChanged):
            sig.connect(self._caption.update)
        # the hidden unit cell is painted inside Quantity - repaint on any change
        self.model().dataChanged.connect(self.viewport().update)

        self.apply_style()
        theme_manager().theme_changed.connect(self.apply_style)


        self._show_component = show_component
        if show_component:  # col 7 holds the component name, shown first
            self.horizontalHeaderItem(7).setText("Component")
            hdr.setSectionResizeMode(7, QHeaderView.Interactive)
            hdr.moveSection(7, 0)

        if not self.is_trash_view:
            self.cellDoubleClicked.connect(self._on_cell_double_clicked)

        self.update_height()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def apply_style(self):
        # Plain one-line titles: muted, no fill, a line underneath. Also
        # reaches the frozen Action overlay's header, a child widget.
        self.setStyleSheet(
            (f"StructureTableWidget {{ background-color: {get_token('base')};"
             f" border: 1px solid {get_token('surface_mid')}; border-radius: {_RADIUS}px; }}"
             if self._framed else
             "StructureTableWidget { background-color: transparent; border: none; }")
            + f"QHeaderView {{ background-color: transparent; }}"
            f"QHeaderView::section {{ background-color: transparent;"
            f" color: {_muted().name()}; font-weight: {FW_SEMIBOLD};"
            f" border: none; border-bottom: 1px solid {get_token('surface_mid')};"
            f" border-radius: 0px; padding: 0px {SP3}px; }}"
            f"QHeaderView#structHdr::section {{ padding-top: {_CAP_H}px; }}"
        )
        self._frozen_col.apply_style()
        self._caption.apply_style()
        self.viewport().update()
        self._caption.update()

    def _on_cell_double_clicked(self, row, column):
        if self._frozen:
            return
        cell = self.item(row, 6)
        if cell is None:
            return
        self.manager.open_edit_dialog(self.component_name, cell.data(Qt.UserRole))

    def set_menu(self, menu):
        """Add a "more actions" button to the heading row; returns it."""
        return self._caption.set_menu(menu)

    def set_currency(self, code: str):
        self.currency = code or ""
        self._caption.update()
        suffix = f" ({code})" if code else ""
        for col, base in ((3, "Rate"), (5, "Amount")):
            item = self.horizontalHeaderItem(col)
            if item:
                item.setText(base + suffix)

    def sizeHint(self):
        header_h = self.horizontalHeader().height() or 56
        rows_h = sum(self.rowHeight(r) for r in range(self.rowCount()))
        # _layout_columns turns the sideways scrollbar on only when columns overflow
        sb_h = (self.horizontalScrollBar().sizeHint().height()
                if self.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded else 0)
        return QSize(super().sizeHint().width(), header_h + rows_h + 2 + sb_h)

    def minimumSizeHint(self):
        return self.sizeHint()

    def update_height(self):
        """Re-fit columns and height to the current values, right now."""
        self._layout_columns()

    def _schedule_layout(self):
        """Re-fit once after a batch of row changes, not once per row."""
        self.updateGeometry()
        if not self._layout_pending:
            self._layout_pending = True
            QTimer.singleShot(0, self, self._run_pending_layout)

    def _run_pending_layout(self):
        if self._layout_pending:
            self._layout_columns()

    # ------------------------------------------------------------------
    # Row management
    # ------------------------------------------------------------------

    def add_row(self, item_data, original_index, component=""):
        self.blockSignals(True)
        row = self.rowCount()
        self.insertRow(row)
        self.setRowHeight(row, self._row_h)

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

        # Col 6: hidden, stores original_index for delegate click handling
        action_item = QTableWidgetItem()
        action_item.setData(Qt.UserRole, original_index)
        action_item.setFlags(Qt.ItemIsEnabled)
        self.setItem(row, 6, action_item)

        # Col 7: blank under the Action overlay, or the component name
        self.setItem(row, 7, QTableWidgetItem(component))

        # Mirror in frozen overlay
        self._frozen_col.add_row(original_index)

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
        self.setRowHeight(pos, self._row_h)

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

        frozen_item = QTableWidgetItem()
        frozen_item.setData(Qt.UserRole, original_index)
        frozen_item.setFlags(Qt.ItemIsEnabled)
        self._frozen_col.insertRow(pos)
        self._frozen_col.setRowHeight(pos, _ROW_H)
        self._frozen_col.setItem(pos, 0, frozen_item)

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
        self._frozen_col.removeRow(found)
        if reindex:
            for row in range(self.rowCount()):
                for tbl, col in ((self, 6), (self._frozen_col, 0)):
                    cell = tbl.item(row, col)
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
        self._frozen_action_delegate.set_frozen(frozen)

    # ------------------------------------------------------------------
    # Layout / resize
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_columns()

    def _layout_columns(self):
        self._layout_pending = False
        empty = self.rowCount() == 0
        self.horizontalHeader().setFixedHeight(_CAP_H if empty else _CAP_H + _HDR_H)
        self._frozen_col.setVisible(not (empty or self._read_only))
        vp_w = self.viewport().width()

        ratios = {
            0: 0.38,  # Work name
            1: 0.14,  # Quantity + unit
            3: 0.13,  # Rate
            4: 0.15,  # Source
            5: 0.20,  # Amount
        }
        mins = {0: 180, 1: 100, 3: 60, 4: 80, 5: 90}
        if self._show_component:  # share Work name's space with the Component column
            ratios[0], ratios[7], mins[7] = 0.24, 0.16, 100
            ratios[3], ratios[4] = 0.14, 0.12  # room for the "(INR)" suffix
            if not self._frozen_col.isHidden():
                # col 7 no longer pads the right edge, so keep Amount clear of the overlay
                vp_w -= _ACTION_W
        else:
            vp_w -= _ACTION_W  # col 7 is the placeholder under the Action overlay
        # never narrower than the column title or its widest value, in the
        # fonts they are drawn with - narrow screens scroll instead
        hdr_font = QFont(self.horizontalHeader().font())
        hdr_font.setWeight(QFont.Weight(FW_SEMIBOLD))
        hdr_fm = QFontMetrics(hdr_font)
        cell_fm = QFontMetrics(self.font())
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight(FW_SEMIBOLD))
        bold_fm = QFontMetrics(bold)
        for c in mins:
            need = hdr_fm.horizontalAdvance(self.horizontalHeaderItem(c).text())
            if c != 0:  # Work name may elide - it has a tooltip
                fm = bold_fm if c == _AMOUNT_COL else cell_fm
                for r in range(self.rowCount()):
                    item = self.item(r, c)
                    text = item.text() if item else ""
                    if c == 1 and self.item(r, 2):  # unit painted after the quantity
                        text += "  " + self.item(r, 2).text()
                    need = max(need, fm.horizontalAdvance(text))
            mins[c] = max(mins[c], need + 2 * SP3 + 4)

        col_widths = {c: max(mins[c], int(vp_w * r)) for c, r in ratios.items()}

        used = sum(col_widths.values())
        if used > vp_w:
            # Too narrow for proportional layout - scale down to mins, enable scroll
            scale = vp_w / used
            col_widths = {
                c: max(mins[c], int(w * scale)) for c, w in col_widths.items()
            }

        # Amount takes the rounding leftover (not Stretch: that ignores its minimum)
        col_widths[5] += max(0, vp_w - sum(col_widths.values()))

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
            if sum(col_widths.values()) > vp_w
            else Qt.ScrollBarAlwaysOff
        )

        hdr = self.horizontalHeader()
        hdr.blockSignals(True)
        for col, width in col_widths.items():
            self.setColumnWidth(col, width)
        hdr.blockSignals(False)
        self.updateGeometries()  # signals were blocked - refresh the scroll range
        self.viewport().update()
        self.resizeRowsToContents()
        self.updateGeometry()  # scrollbar may have come or gone - refit the height

        self._frozen_col.reposition()
        self._frozen_col.sync_row_heights()
        self._place_caption()

    def _place_caption(self):
        fw = self.frameWidth()
        self._caption.setGeometry(fw, fw, self.width() - 2 * fw, _CAP_H)
        self._caption.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._frozen_col.reposition()
        self._place_caption()


