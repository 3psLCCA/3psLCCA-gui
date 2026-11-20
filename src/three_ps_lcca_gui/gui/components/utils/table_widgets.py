"""
Reusable table widgets shared across the application.

Exports:
    GroupedHeaderView       - two-tier grouped horizontal header
    WordWrapHeaderView      - single-tier header, no eliding (installed globally)
    BaseActionDelegate      - base for painted action-column delegates
    TooltipTableMixin       - mixin that shows cell tooltip on overflow
    TableDoubleSpinBox      - QDoubleSpinBox styled for table cells
    TableSpinBox            - QSpinBox styled for table cells
    TableLineEdit           - QLineEdit styled for table cells
    fit_to_contents         - let Qt size a table from its labels and rows
    item_text_rect          - the style's text rect for a cell (QSS padding included)
    FrozenActionColumn      - Action column pinned over a table's right edge
    TableCard               - a table in a rounded box with a heading row and "+ Add" row
"""
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyledItemDelegate,
    QStyleOptionHeader,
    QStyleOptionViewItem,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QVBoxLayout,
)
from PySide6.QtCore import Qt, QSize, QRect, QEvent, QModelIndex, Signal
from PySide6.QtGui import QPainter, QColor
from shiboken6 import isValid
from three_ps_lcca_gui.gui.assets.themes.table_style import COL_MIN_ROLE
from three_ps_lcca_gui.gui.theme import BTN_SM, SP2, SP3


# ---------------------------------------------------------------------------
# Word-wrap header (no groups) - installed globally on plain QTableWidget/View
# ---------------------------------------------------------------------------

def contrast_color(bg: QColor) -> QColor:
    """Return black or white for readable text on the given background color."""
    lum = (0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()) / 255
    return QColor("#000000") if lum > 0.55 else QColor("#ffffff")


def item_text_rect(delegate: QStyledItemDelegate, option, index) -> QRect:
    """Where the style puts a cell's text - QSS ``::item`` padding included.
    Delegates that paint their own text draw into this instead of a hand-set inset."""
    opt = QStyleOptionViewItem(option)
    delegate.initStyleOption(opt, index)
    style = opt.widget.style() if opt.widget else QApplication.style()
    return style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget)


class WordWrapHeaderView(QHeaderView):
    """Horizontal header that never elides. Qt measures and paints the
    sections; multi-line labels break at explicit "\\n"."""

    def __init__(self, orientation_or_parent=Qt.Horizontal, parent=None):
        if isinstance(orientation_or_parent, Qt.Orientation):
            orientation = orientation_or_parent
            actual_parent = parent
        else:
            orientation = Qt.Horizontal
            actual_parent = orientation_or_parent
        super().__init__(orientation, actual_parent)
        self.setTextElideMode(Qt.ElideNone)
        self.sectionResized.connect(self._on_section_resized)
        self._updating = False

    def _on_section_resized(self, logicalIndex: int, oldSize: int, newSize: int):
        if not self._updating:
            self._updating = True
            try:
                self.geometriesChanged.emit()
            finally:
                self._updating = False

    def sectionSizeFromContents(self, logicalIndex):
        # never under the column's minimum width from table_style.py
        size = super().sectionSizeFromContents(logicalIndex)
        model = self.model()
        floor = model.headerData(logicalIndex, self.orientation(), COL_MIN_ROLE) if model else None
        if floor:
            size.setWidth(max(size.width(), floor))
        return size

    def _one_line_height(self, text="X"):
        """Height of a one-line section, with the style's own padding."""
        opt = QStyleOptionHeader()
        self.initStyleOption(opt)
        opt.text = text
        return self.style().sizeFromContents(
            QStyle.CT_HeaderSection, opt, QSize(), self
        ).height()


# ---------------------------------------------------------------------------
# Two-tier grouped header
# ---------------------------------------------------------------------------

class GroupedHeaderView(WordWrapHeaderView):
    """Word-wrap header with spanning group labels on the top tier and
    individual column labels on the bottom tier.

    Args:
        groups: list of (start_col, span, label)
    Columns NOT in any group span the full height with their label centred.
    """

    def __init__(self, groups=(), parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._groups    = list(groups)
        self._col_group: dict[int, tuple] = {}
        for start, span, label in self._groups:
            for c in range(start, start + span):
                self._col_group[c] = (start, span, label)

    def _group_tier_height(self):
        return max((self._one_line_height(label) for *_, label in self._groups),
                   default=0)

    def sizeHint(self):
        # Qt measures each label (style padding included); a grouped
        # column's label sits under its group label
        s = super().sizeHint()
        if not self.model():
            return s
        tier = self._group_tier_height()
        h = max((self.sectionSizeFromContents(i).height()
                 + (tier if i in self._col_group else 0)
                 for i in range(self.count()) if not self.isSectionHidden(i)),
                default=0)
        return QSize(s.width(), max(s.height(), h))

    def paintSection(self, painter, rect, logical_index):
        if self._groups and logical_index in self._col_group:
            top    = self._group_tier_height()
            bottom = QRect(rect.x(), rect.y() + top, rect.width(), rect.height() - top)
            painter.save()
            painter.setClipRect(bottom)
            super().paintSection(painter, bottom, logical_index)
            painter.restore()
            return
        # Non-grouped column: spans full height — delegate to Qt's C++ pipeline.
        # super().paintSection() is Fusion-safe: it calls drawControl(CE_Header)
        # with opt.text set correctly, so the pen is always valid.
        painter.save()
        painter.setClipRect(rect)
        super().paintSection(painter, rect, logical_index)
        painter.restore()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._groups:
            return
        painter = QPainter(self.viewport())
        top = self._group_tier_height()
        for start, span, label in self._groups:
            x       = self.sectionViewportPosition(start)
            total_w = sum(self.sectionSize(start + i) for i in range(span))
            group_rect = QRect(x, 0, total_w, top)
            opt = QStyleOptionHeader()
            self.initStyleOption(opt)
            opt.rect             = group_rect
            opt.section          = start
            opt.text             = label
            opt.textAlignment    = Qt.AlignCenter | Qt.AlignVCenter
            opt.position         = QStyleOptionHeader.Middle
            opt.selectedPosition = QStyleOptionHeader.NotAdjacent
            # Isolate each style call so painter state (clip, pen, brush) left
            # behind by QStyleSheetStyle cannot leak into the next group label.
            painter.save()
            self.style().drawControl(
                self.style().ControlElement.CE_Header, opt, painter, self
            )
            painter.restore()
        painter.end()


# ---------------------------------------------------------------------------
# Base action delegate
# ---------------------------------------------------------------------------

class BaseActionDelegate(QStyledItemDelegate):
    """Paints circular icon buttons in a table's last (action) column.
    No QWidget/QHBoxLayout - eliminates jitter and background bleed.

    Subclasses must implement:
        _get_btns_for_row(row) → list of (QIcon, hover_rgb_tuple)

    Class attributes to override per subclass:
        BTN_SIZE  - button diameter in px  (default 28)
        BTN_GAP   - gap between buttons px (default 6)
        BTN_PAD   - clear space around the button strip (default 6)
        MAX_BTNS  - most buttons in a row; sizes the column (default 2)

    The strip is the cell's decoration as far as the style knows, so the
    style sizes and places it - QSS ``::item`` padding included.
    """

    BTN_SIZE = 28
    BTN_GAP  = 6
    BTN_PAD  = 6
    MAX_BTNS = 2

    def __init__(self, table):
        super().__init__(table)
        self._table     = table
        self._frozen    = False
        self._hovered   = (-1, -1)   # (row, btn_index)
        self._icon_size = int(self.BTN_SIZE * 0.8)
        self._views     = []         # views painting with this delegate (hover)
        self.track(table)

    def track(self, view):
        """Also follow the mouse over another view that paints these buttons,
        e.g. the pinned copy of the column (column_style.pinned_view)."""
        if view is None or view in self._views:
            return
        self._views.append(view)
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    def _get_btns_for_row(self, row) -> list[tuple]:
        """Return list of (QIcon, hover_rgb) for buttons in this row."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _action_col(self) -> int:
        return self._table.columnCount() - 1

    def _strip_option(self, rect: QRect | None = None) -> QStyleOptionViewItem:
        """A view-item option whose decoration is the widest button strip."""
        opt = QStyleOptionViewItem()
        opt.initFrom(self._table)
        opt.widget = self._table
        if rect is not None:
            opt.rect = rect
        opt.features = QStyleOptionViewItem.HasDecoration
        opt.decorationPosition = QStyleOptionViewItem.Left
        opt.decorationAlignment = Qt.AlignLeft | Qt.AlignVCenter
        n, pad = self.MAX_BTNS, self.BTN_PAD
        opt.decorationSize = QSize(n * self.BTN_SIZE + (n - 1) * self.BTN_GAP + 2 * pad,
                                   self.BTN_SIZE + 2 * pad)
        return opt

    def sizeHint(self, option, index):
        # The style's cell size for the button strip
        style = self._table.style()
        return style.sizeFromContents(QStyle.CT_ItemViewItem, self._strip_option(),
                                      QSize(), self._table)

    def _btn_rects(self, cell_rect: QRect, n: int) -> list[QRect]:
        """Return n QRects left-aligned where the style puts the strip."""
        style = self._table.style()
        strip = style.subElementRect(QStyle.SE_ItemViewItemDecoration,
                                     self._strip_option(cell_rect), self._table)
        x = strip.x() + self.BTN_PAD
        y = strip.y() + (strip.height() - self.BTN_SIZE) // 2
        return [
            QRect(x + i * (self.BTN_SIZE + self.BTN_GAP), y, self.BTN_SIZE, self.BTN_SIZE)
            for i in range(n)
        ]

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paint(self, painter, option, index):
        # Standard cell background only; the buttons replace the cell text.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else self._table.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)

        btns = self._get_btns_for_row(index.row())
        if not btns:
            return
        painter.save()
        if self._frozen:
            painter.setOpacity(0.35)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

        row       = index.row()
        btn_rects = self._btn_rects(option.rect, len(btns))
        icon_size = self._icon_size

        for i, (icon, hover_rgb, *_) in enumerate(btns):
            br = btn_rects[i]
            if not self._frozen and self._hovered == (row, i):
                painter.setBrush(QColor(*hover_rgb, 40))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(br)
            offset    = (br.width() - icon_size) // 2
            icon_rect = QRect(br.x() + offset, br.y() + offset, icon_size, icon_size)
            icon.paint(painter, icon_rect, Qt.AlignCenter)

        painter.restore()

    # ------------------------------------------------------------------
    # Mouse events - hover tracking
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        try:
            view = next((v for v in self._views if v.viewport() is obj), None)
        except RuntimeError:
            return False
        if view is None:
            return False

        action_col = self._action_col()
        if event.type() == QEvent.MouseMove:
            pos   = event.pos()
            index = view.indexAt(pos)
            if index.isValid() and index.column() == action_col:
                btns = self._get_btns_for_row(index.row())
                for i, br in enumerate(
                    self._btn_rects(view.visualRect(index), len(btns))
                ):
                    if br.contains(pos):
                        self._set_hovered(index.row(), i)
                        tooltip = btns[i][2] if len(btns[i]) > 2 else ""
                        if tooltip:
                            QToolTip.showText(event.globalPos(), tooltip)
                        else:
                            QToolTip.hideText()
                        return False
            self._set_hovered(-1, -1)
            QToolTip.hideText()
        elif event.type() == QEvent.Leave:
            self._set_hovered(-1, -1)
            QToolTip.hideText()

        return False

    def _set_hovered(self, row, btn):
        new = (row, btn)
        if self._hovered == new:
            return
        old, self._hovered = self._hovered, new
        action_col = self._action_col()
        for view in self._views:
            try:
                for r, _ in (old, new):
                    if r >= 0:
                        view.viewport().update(view.visualRect(
                            view.model().index(r, action_col)
                        ))
            except RuntimeError:  # view already deleted
                pass

    def set_frozen(self, frozen: bool):
        self._frozen = frozen
        for view in self._views:
            view.viewport().update()


# ---------------------------------------------------------------------------
# Tooltip mixin for QTableWidget subclasses
# ---------------------------------------------------------------------------

class TooltipTableMixin:
    """Mixin for QTableWidget: always shows a tooltip with the full cell text,
    and enables word wrap + ElideNone so text is never silently cut off.
    The last column (action column) is always skipped.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideNone)

    def viewportEvent(self, event):
        if event.type() == QEvent.ToolTip:
            index      = self.indexAt(event.pos())
            action_col = self.columnCount() - 1
            if index.isValid() and index.column() != action_col:
                item = self.item(index.row(), index.column())
                if item and item.text():
                    QToolTip.showText(event.globalPos(), item.text())
                    return True
            QToolTip.hideText()
        return super().viewportEvent(event)


# ---------------------------------------------------------------------------
# Compact spin boxes for use inside QTableWidget cells
# ---------------------------------------------------------------------------


class _FitEditorMixin:
    """Force the inner editor to fill the spin box (minus a small side margin).
    On some Qt/PySide builds the style-sheet edit-field rect collapses to ~0 px
    when the up/down buttons are zero-width, leaving the text invisible."""

    _EDITOR_MARGIN = 4

    def _fit_editor(self):
        m = self._EDITOR_MARGIN
        self.lineEdit().setGeometry(self.rect().adjusted(m, 0, -m, 0))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_editor()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_editor()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.StyleChange, QEvent.FontChange):
            self._fit_editor()


class TableDoubleSpinBox(_FitEditorMixin, QDoubleSpinBox):
    """QDoubleSpinBox subclass for table cells.
    Named differently so main.qss compact rules apply instead of the
    standard form-control padding/min-height rules.
    """


class TableSpinBox(_FitEditorMixin, QSpinBox):
    """QSpinBox subclass for table cells. Same rationale as TableDoubleSpinBox."""


class TableLineEdit(QLineEdit):
    """QLineEdit subclass for table cells. Same rationale as TableDoubleSpinBox."""




# ---------------------------------------------------------------------------
# Content sizing
# ---------------------------------------------------------------------------


def fit_to_contents(table):
    """Let Qt size a table from its labels and rows: every row shows (the
    page scrolls, not the table) and rows grow with wrapped text."""
    table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
    table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)


# ---------------------------------------------------------------------------
# Floating Action column
# ---------------------------------------------------------------------------


class FrozenActionColumn(QTableWidget):
    """One-column "Action" table pinned over the right edge of a main table.

    Follows Qt's Frozen Column pattern: the overlay is a child of the main
    table and is kept in step with it through signals, so it never scrolls
    sideways and its rows always line up.

    - Vertical scrolling is linked both ways.
    - Row heights follow the main table's ``sectionResized`` signal.
    - The header height follows the main header's ``geometriesChanged``.

    The width is Qt's: the wider of the header label and the delegate's
    buttons, both measured by the style. ``widthChanged`` tells the main
    table, which keeps that much free on the right (a placeholder column
    and/or ``setViewportMargins``) so no value sits under the overlay. Its
    rows are never shorter than the action delegate's buttons.
    """

    widthChanged = Signal(int)

    def __init__(self, parent_table: QTableWidget, title: str = "Action"):
        super().__init__(parent_table)
        self.setObjectName("actionColumn")  # main.qss: #actionColumn
        self._parent_table = parent_table
        self._width = 0

        # Set the header here: main.py's filter swaps a plain header later,
        # after reposition() has fixed its height, which left the Action
        # header and rows out of line with the main table.
        self.setHorizontalHeader(WordWrapHeaderView(Qt.Horizontal))
        self.setColumnCount(1)
        hdr_item = QTableWidgetItem(title)
        hdr_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        self.setHorizontalHeaderItem(0, hdr_item)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setFrameShape(QTableWidget.NoFrame)

        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        main_bar, own_bar = parent_table.verticalScrollBar(), self.verticalScrollBar()
        main_bar.valueChanged.connect(own_bar.setValue)
        own_bar.valueChanged.connect(main_bar.setValue)
        parent_table.verticalHeader().sectionResized.connect(self._on_row_resized)
        parent_table.horizontalHeader().geometriesChanged.connect(self._on_header_changed)

    def setItemDelegateForColumn(self, column, delegate):
        super().setItemDelegateForColumn(column, delegate)
        # main-table rows must fit the buttons this delegate paints
        btn_h = delegate.sizeHint(QStyleOptionViewItem(), QModelIndex()).height()
        self._parent_table.verticalHeader().setMinimumSectionSize(btn_h)
        self.update_width()

    # ---- rows ----------------------------------------------------------
    def _on_row_resized(self, row: int, _old: int, new: int):
        if row < self.rowCount():
            self.setRowHeight(row, new)

    def sync_row_heights(self):
        p = self._parent_table
        for r in range(min(self.rowCount(), p.rowCount())):
            self.setRowHeight(r, p.rowHeight(r))

    def add_row(self, data=None):
        """Append a row; ``data`` (default: the row index) goes in UserRole."""
        row = self.rowCount()
        self.insertRow(row)
        p = self._parent_table
        if row < p.rowCount():
            self.setRowHeight(row, p.rowHeight(row))
        item = QTableWidgetItem()
        item.setData(Qt.UserRole, row if data is None else data)
        item.setFlags(Qt.ItemIsEnabled)
        self.setItem(row, 0, item)

    def clear_rows(self):
        self.setRowCount(0)

    # ---- geometry ------------------------------------------------------
    def _on_header_changed(self):
        # The header still emits while the main table is being deleted.
        if isValid(self) and isValid(self._parent_table):
            self.reposition()

    def update_width(self) -> int:
        """Take Qt's width for the column; tell the main table if it changed."""
        d = self.itemDelegateForColumn(0)
        btn_w = d.sizeHint(QStyleOptionViewItem(), QModelIndex()).width() if d else 0
        w = max(self.horizontalHeader().sectionSizeFromContents(0).width(), btn_w)
        if w != self._width:
            self._width = w
            self.widthChanged.emit(w)
        return w

    def reposition(self):
        """Sit on the right edge, header level with the main header."""
        self.update_width()
        p = self._parent_table
        hdr_h = p.horizontalHeader().height()
        self.horizontalHeader().setFixedHeight(hdr_h)
        vp = p.viewport()
        # a floating child sits outside any layout, so it is placed by hand;
        # contentsRect is Qt's area inside the table's frame and QSS margin
        self.setGeometry(p.contentsRect().right() + 1 - self._width, vp.y() - hdr_h,
                         self._width, vp.height() + hdr_h)
        self.raise_()


# ---------------------------------------------------------------------------
# Table card - heading row, table, "+ Add" row in one rounded box
# ---------------------------------------------------------------------------


class TableCard(QFrame):
    """A table in a rounded box (main.qss: #tableCard):

        heading row   title  ·  count  ----------  total  [•••]
        the table
        "+ Add" row   (optional, add_footer)

    The heading row is ordinary labels in a layout, outside the table, so
    the table's columns and Action overlay never run through it. The owner
    fills in the count and total with set_count / set_total.
    """

    def __init__(self, table, title="", parent=None):
        super().__init__(parent)
        self.setObjectName("tableCard")
        # height = its contents' (sizeHint): a scroll area gives a widget only
        # its minimum, which squeezed the "+ Add" row down to its padding
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.table = table
        self.menu_btn = None
        self.footer = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)  # inside the 1 px border
        lay.setSpacing(0)

        self._head = QHBoxLayout()
        self._head.setContentsMargins(SP3, SP2, SP2, 0)
        self._head.setSpacing(SP2)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("cardTitle")
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("cardCount")
        self.total_lbl = QLabel()
        self.total_lbl.setObjectName("cardTotal")
        self._head.addWidget(self.title_lbl)
        self._head.addWidget(self.count_lbl)
        self._head.addStretch(1)
        self._head.addWidget(self.total_lbl)

        lay.addLayout(self._head)
        lay.addWidget(table)

    def set_title(self, text: str):
        self.title_lbl.setText(text)

    def set_count(self, text: str):
        self.count_lbl.setText(f"·  {text}" if text else "")

    def set_total(self, text: str):
        self.total_lbl.setText(text)

    def count_rows(self, noun: str = "item"):
        """Show the table's row count ("3 items") and keep it up to date."""
        def refresh(*_):
            n = self.table.rowCount()
            self.set_count(f"{n} {noun}" + ("" if n == 1 else "s"))
        model = self.table.model()
        model.rowsInserted.connect(refresh)
        model.rowsRemoved.connect(refresh)
        refresh()

    def set_menu(self, menu) -> QToolButton:
        """Add a "more actions" button at the end of the heading row; returns it."""
        btn = QToolButton()
        btn.setText("•••")
        btn.setToolTip("More actions")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setFixedSize(BTN_SM, BTN_SM)
        btn.setMenu(menu)
        self._head.addWidget(btn)
        self.menu_btn = btn
        return btn

    def add_footer(self, text: str = "") -> QPushButton:
        """Add the "+ Add ..." row under the table; returns the button."""
        btn = QPushButton(text)
        btn.setObjectName("cardFooter")
        btn.setCursor(Qt.PointingHandCursor)
        self.layout().addWidget(btn)
        self.footer = btn
        return btn
