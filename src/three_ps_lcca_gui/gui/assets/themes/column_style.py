"""column_style.py - per-column widths for Qt tables, by column id (like a CSS class).
Minimum widths come from theme.py (COL_W_*, COL_PAD_X).

QSS cannot size one column, so this module does that job next to your .qss.

    from column_style import apply_column_style
    apply_column_style(table)                    # ids come from the header labels
    apply_column_style(table, {5: "carbon"})     # a label that means two things

What every styled table does
  1. each column has a MINIMUM width (its id's rule) and grows with its contents,
     never below the minimum;
  2. a stretch column (default id "name") takes the spare width when the table is wide;
  3. when columns do not fit, the TABLE scrolls sideways (the page does not, the
     table never forces its parent wider);
  4. the user can still drag any column wider, but not below its minimum; dragged
     widths survive data changes and can be saved/restored (export_widths / import_widths).

How it works: all sections stay Interactive (so the user keeps control). One small
controller object per table recomputes widths when the data, the table size, the font
or the header labels change, coalesced through a 0 ms timer. Nothing is measured per row:
content width comes from QTableView.sizeHintForColumn (sampled, see `precision`).

Ids and labels
  A header label is matched without line breaks, a trailing "(...)" or " *", ignoring
  case: "Rate (INR)" and "Rate *" both match "rate". Hidden and blank columns are skipped.
  A label with no id gives a warning: register_labels("rate", "My label") or use overrides.

Public functions
  rules / labels   register_column, register_labels, load_rules, column_id
  apply            apply_column_style, refit, rescan, reset_widths
  per table        set_min_width, set_stretch, set_column_id, column_floor, column_ids
  visibility       hide_columns, show_columns, pin_last_column, pinned_view, is_pinned
  scrolling        confine_horizontal_scroll (only the table scrolls in x, never its parent)
  persistence      export_widths, import_widths, save_widths, restore_widths
  diagnostics      describe, check
"""
from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette, QTextDocument, QTextOption
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QScrollArea, QSizePolicy, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QTableView)

__all__ = [
    "ColumnRule", "WrapAnywhereDelegate", "register_column", "register_labels", "load_rules", "column_id",
    "apply_column_style", "refit", "rescan", "reset_widths",
    "set_min_width", "set_stretch", "set_column_id", "column_floor", "column_ids",
    "hide_columns", "show_columns", "pin_last_column", "pinned_view", "is_pinned", "confine_horizontal_scroll",
    "export_widths", "import_widths", "save_widths", "restore_widths",
    "describe", "check",
]

from three_ps_lcca_gui.gui.theme import (
    COL_PAD_X, COL_W_AMOUNT, COL_W_CARBON, COL_W_CARBON_SRC, COL_W_CARBON_UNIT, COL_W_COMPONENT,
    COL_W_DATETIME, COL_W_FACTOR, COL_W_NAME, COL_W_NOTE, COL_W_PERCENT, COL_W_QUANTITY,
    COL_W_RATE, COL_W_RATE_SRC, COL_W_SRC_ID, COL_W_UNIT,
)

PAD_X = COL_PAD_X     # default horizontal cell padding (px, each side)


# ------------------------------------------------------------------------------------
# Rules: column id -> minimum width
# ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnRule:
    min_width: int                  # content width in px; padding is added on top
    pad_x: int = PAD_X              # padding on each side
    stretch: bool = False           # takes the table's spare width
    max_width: int | None = None    # cap for content-driven growth (a user drag can exceed it)

    @property
    def floor(self) -> int:
        """Smallest section width: content width plus padding on both sides."""
        return self.min_width + 2 * self.pad_x


# Content widths (px) from theme.py (COL_W_*). Action has no floor: its buttons
# (the delegate's sizeHint) set its width.
RULES: dict[str, ColumnRule] = {
    "name":        ColumnRule(COL_W_NAME, stretch=True),
    "component":   ColumnRule(COL_W_COMPONENT),
    "unit":        ColumnRule(COL_W_UNIT),
    "carbon_unit": ColumnRule(COL_W_CARBON_UNIT),
    "src_id":      ColumnRule(COL_W_SRC_ID),
    "rate_src":    ColumnRule(COL_W_RATE_SRC),
    "carbon_src":  ColumnRule(COL_W_CARBON_SRC),
    "rate":        ColumnRule(COL_W_RATE),
    "carbon":      ColumnRule(COL_W_CARBON),
    "factor":      ColumnRule(COL_W_FACTOR),
    "amount":      ColumnRule(COL_W_AMOUNT),
    "quantity":    ColumnRule(COL_W_QUANTITY),
    "percent":     ColumnRule(COL_W_PERCENT),
    "note":        ColumnRule(COL_W_NOTE),
    "datetime":    ColumnRule(COL_W_DATETIME),
    "action":      ColumnRule(0),
    "misc":        ColumnRule(0),
}

_LABELS = {
    "name":        ["Work name", "Material", "Name", "Equipment Name", "Vehicle Type",
                    "Metric", "Cost Item", "Label"],
    "component":   ["Component", "Category", "Stage", "Hour Category", "Energy Source"],
    "unit":        ["Unit"],
    "carbon_unit": ["Carbon Unit"],
    "src_id":      ["ID"],
    "rate_src":    ["Source", "Rate Source"],
    "carbon_src":  ["Carbon EF Source"],
    "rate":        ["Rate", "Scrap Rate"],
    "carbon":      ["Carbon EF", "EF", "Emission Factor", "kg Factor", "kg / unit"],
    "factor":      ["Conversion Factor", "Fuel / Power Rating", "Power to weight ratio"],
    "amount":      ["Amount", "Total Emissions", "Emissions", "Emission", "Recovered Value",
                    "Economic", "Environmental", "Social", "Stage Total"],
    "quantity":    ["Quantity", "Recyclable Quantity", "Vehicles / Day", "Consumption",
                    "No. of Days", "Avg Hrs/Day", "Trips"],
    "percent":     ["Recyclability %", "Recovery %", "Accident", "Traffic Proportion",
                    "Relative Cost"],
    "note":        ["Warning", "Warnings", "Issues", "Reason", "Notes", "Details"],
    "datetime":    ["Date & Time", "Saved At", "Timestamp"],
    "action":      ["Action"],
    "misc":        ["Size", "File", "Event"],
}


def _normalize(label: object) -> str:
    """'Rate (INR)', 'Rate *', 'Scrap Rate\\n(per unit)' -> 'rate', 'rate', 'scrap rate'."""
    text = " ".join(str(label or "").split())
    while True:
        new = re.sub(r"\s*\([^()]*\)\s*$", "", text).rstrip(" *").strip()
        if new == text:
            return text.lower()
        text = new


LABELS: dict[str, str] = {_normalize(lbl): cid for cid, lbls in _LABELS.items() for lbl in lbls}


def register_column(col_id: str, min_width: int, *, pad_x: int = PAD_X, stretch: bool = False,
                    max_width: int | None = None, labels: Iterable[str] = ()) -> None:
    """Add or replace a column id (global). `labels` are header labels that map to it."""
    RULES[col_id] = ColumnRule(min_width, pad_x, stretch, max_width)
    register_labels(col_id, *labels)


def register_labels(col_id: str, *labels: str) -> None:
    """Map header labels to an existing id."""
    if col_id not in RULES:
        raise KeyError(f"unknown column id {col_id!r}; register_column() it first")
    for lbl in labels:
        LABELS[_normalize(lbl)] = col_id


def load_rules(widths: Mapping[str, "int | tuple[int, int]"], *, pad_x: int = PAD_X) -> None:
    """Bulk-set minimum widths, e.g. from a theme module:
    load_rules({"name": 151, "rate": 60, "action": (58, 8)})   # (width, pad_x)."""
    for cid, spec in widths.items():
        w, pad = (spec if isinstance(spec, tuple) else (spec, pad_x))
        old = RULES.get(cid)
        RULES[cid] = replace(old, min_width=w, pad_x=pad) if old else ColumnRule(w, pad)


def column_id(label: object) -> str | None:
    """The id a header label maps to, or None."""
    return LABELS.get(_normalize(label))


# ------------------------------------------------------------------------------------
# Delegate: wrap text, and break inside a word only when a single word is wider than the
# column (CSS overflow-wrap: anywhere). Qt's default delegate never breaks inside a word, so a
# long unbroken string (a file name, an id) is clipped instead of wrapped.
# ------------------------------------------------------------------------------------
class WrapAnywhereDelegate(QStyledItemDelegate):
    """Plain-text wrapping delegate. It ignores QSS item padding (uses the style's default
    text margin) and rich text; use it for name/description columns."""
    V_MARGIN = 3

    def _margin(self, opt):
        return opt.widget.style().pixelMetric(QStyle.PM_FocusFrameHMargin, opt, opt.widget) + 1 \
            if opt.widget else 4

    def _doc(self, opt, width):
        doc = QTextDocument()
        doc.setDefaultFont(opt.font); doc.setDocumentMargin(0)
        o = QTextOption(); o.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        o.setAlignment(opt.displayAlignment)
        doc.setDefaultTextOption(o); doc.setPlainText(opt.text); doc.setTextWidth(max(width, 1))
        return doc

    def sizeHint(self, option, index):
        opt = QStyleOptionViewItem(option); self.initStyleOption(opt, index)
        view = self.parent()
        width = view.columnWidth(index.column()) if view is not None else option.rect.width()
        h = self._doc(opt, width - 2 * self._margin(opt)).size().height()
        return QSize(width, int(h + 0.99) + 2 * self.V_MARGIN)

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option); self.initStyleOption(opt, index)
        text, opt.text = opt.text, ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)   # background, selection
        opt.text = text
        m = self._margin(opt)
        rect = opt.rect.adjusted(m, self.V_MARGIN, -m, -self.V_MARGIN)
        doc = self._doc(opt, rect.width())
        role = QPalette.HighlightedText if opt.state & QStyle.State_Selected else QPalette.Text
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.Text, opt.palette.color(QPalette.Active, role))
        painter.save()
        painter.setClipRect(opt.rect)
        painter.translate(rect.left(), rect.top() + max(0, (rect.height() - doc.size().height()) / 2))
        doc.documentLayout().draw(painter, ctx)
        painter.restore()


# ------------------------------------------------------------------------------------
# Controller: one per table
# ------------------------------------------------------------------------------------
class _Controller(QObject):
    def __init__(self, table: QTableView, overrides, *, wrap_names, wrap_rows_limit, sideways,
                 break_long_words=True):
        super().__init__(table)
        self.table = table
        self.overrides: dict[int, str] = dict(overrides or {})
        self.rules: dict[str, ColumnRule] = dict(RULES)     # per-table copy: tweaks do not leak
        self.floor_override: dict[int, int] = {}            # col -> floor px (set_min_width(int))
        self.user: dict[int, int] = {}                      # col -> width the user dragged to
        self.ids: dict[int, str | None] = {}
        self.wrap_names, self.wrap_rows_limit = wrap_names, wrap_rows_limit
        self.break_long_words = break_long_words and wrap_names
        self._wrap_delegate = WrapAnywhereDelegate(table)
        self._delegated: set[int] = set()
        self._busy = False
        self._model = None
        self._stretch_sig = None
        self.pin: _Pin | None = None
        self.confine = False

        self._timer = QTimer(self); self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.relayout)
        self._rows_timer = QTimer(self); self._rows_timer.setSingleShot(True)
        self._rows_timer.timeout.connect(self._fit_rows)

        hh = table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(16)
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.sectionResized.connect(self._on_section_resized)
        if sideways:
            table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.confine = True
            self.apply_confinement(ancestors=True)
        if wrap_names:
            table.setWordWrap(True)
        table.viewport().installEventFilter(self)
        table.installEventFilter(self)
        self.bind_model()
        self.rescan()

    def apply_confinement(self, ancestors: bool):
        t = self.table
        sp = t.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Ignored)      # its size hint never asks its layout for width
        t.setSizePolicy(sp)
        t.setMinimumWidth(0)
        if ancestors:
            w = t.parentWidget()
            while w is not None:
                if isinstance(w, QScrollArea):
                    w.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                    w.setWidgetResizable(True)           # the page is exactly as wide as the window
                w = w.parentWidget()

    # ---- model + events -----------------------------------------------------------
    def bind_model(self):
        m = self.table.model()
        if m is self._model:
            return
        self._model = m
        if m is None:
            return
        for sig in (m.modelReset, m.rowsInserted, m.rowsRemoved, m.dataChanged, m.layoutChanged,
                    m.columnsInserted, m.columnsRemoved):
            sig.connect(self.schedule)
        m.headerDataChanged.connect(self._on_header_changed)

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if (obj is self.table.viewport() and t == QEvent.Resize) or \
               (obj is self.table and t in (QEvent.FontChange, QEvent.StyleChange, QEvent.Show)):
                if self.pin and t in (QEvent.Resize, QEvent.Show):
                    self.pin.sync()     # move it now, so it never paints one frame at the old edge
                self.schedule()
            if self.confine and obj is self.table and t == QEvent.Show:
                # a table is usually styled before it has a parent: reach the page's
                # scroll areas once it is placed and shown
                self.apply_confinement(ancestors=True)
            if self.confine and obj is self.table.viewport() and t == QEvent.Wheel:
                d = ev.angleDelta()
                if d.x() != 0 and abs(d.x()) >= abs(d.y()):
                    # sideways wheel / shift+wheel: the table takes it even at its ends, so it
                    # never leaks to a parent scroll area
                    bar = self.table.horizontalScrollBar()
                    bar.setValue(bar.value() - d.x() // 2 if d.y() == 0 else bar.value() - d.y() // 2)
                    ev.accept()
                    return True
        except RuntimeError:            # the table is being destroyed
            pass
        return False

    def schedule(self, *_):
        if not self._timer.isActive():
            self._timer.start(0)

    def _on_header_changed(self, orientation, *_):
        if orientation == Qt.Horizontal:
            self.rescan()

    # ---- ids / rules ----------------------------------------------------------------
    def rescan(self):
        """Re-read header labels and (re)resolve every column's id."""
        self.bind_model()
        t, m = self.table, self.table.model()
        self.ids.clear()
        if m is None:
            return
        for col in range(m.columnCount()):
            if col in self.overrides:
                cid = self.overrides[col]
                if cid not in self.rules:
                    raise KeyError(f"override for column {col}: unknown column id {cid!r}")
                self.ids[col] = cid
                continue
            label = m.headerData(col, t.horizontalHeader().orientation())
            key = _normalize(label)
            if not key or t.isColumnHidden(col):          # blank placeholder / hidden: skipped
                self.ids[col] = None
                continue
            cid = LABELS.get(key)
            if cid is None:
                warnings.warn(f"column_style: header {str(label)!r} (column {col} of "
                              f"{type(t).__name__}) has no id - register_labels(id, label) "
                              f"or pass it in overrides", stacklevel=4)
            self.ids[col] = cid
        self._install_delegates()
        self.schedule()

    def _install_delegates(self):
        """Wrap-anywhere delegate on stretch columns that still use the table's default one."""
        t = self.table
        for col in self._delegated:                        # undo for columns that are no longer stretch
            r = self.rule(col)
            if not (r and r.stretch) and t.itemDelegateForColumn(col) is self._wrap_delegate:
                t.setItemDelegateForColumn(col, None)
        self._delegated = {c for c in self._delegated if t.itemDelegateForColumn(c) is self._wrap_delegate}
        if not self.break_long_words:
            return
        for col in self.ids:
            r = self.rule(col)
            if r and r.stretch and t.itemDelegateForColumn(col) is None:
                t.setItemDelegateForColumn(col, self._wrap_delegate)
                self._delegated.add(col)

    def rule(self, col: int) -> ColumnRule | None:
        cid = self.ids.get(col)
        return self.rules.get(cid) if cid else None

    def floor(self, col: int) -> int:
        if col in self.floor_override:
            return self.floor_override[col]
        r = self.rule(col)
        return r.floor if r else 0

    # ---- layout -----------------------------------------------------------------------
    def relayout(self):
        t, hh = self.table, self.table.horizontalHeader()
        if t.model() is None or self._busy:
            return
        self.bind_model()
        cols = [c for c in range(hh.count()) if not hh.isSectionHidden(c)]
        base: dict[int, int] = {}
        for c in cols:
            r, floor = self.rule(c), self.floor(c)
            if c in self.user:
                w = self.user[c]
            elif r and r.stretch:
                w = floor                       # a wrapping column never drives the width
            else:
                w = max(hh.sectionSizeHint(c), t.sizeHintForColumn(c))
                if r and r.max_width:
                    w = min(w, r.max_width + 2 * r.pad_x)
            base[c] = max(w, floor)

        stretch = [c for c in cols if (self.rule(c) and self.rule(c).stretch)]
        spare = t.viewport().width() - sum(base.values())
        if stretch and spare > 0:
            share, extra = divmod(spare, len(stretch))
            for i, c in enumerate(stretch):
                base[c] += share + (extra if i == 0 else 0)

        self._busy = True
        try:
            for c, w in base.items():
                if hh.sectionSize(c) != w:
                    hh.resizeSection(c, w)
        finally:
            self._busy = False

        if self.pin:
            self.pin.sync()
        sig = (tuple(base[c] for c in stretch), t.model().rowCount())
        if self.wrap_names and sig != self._stretch_sig:
            self._stretch_sig = sig
            self._rows_timer.start(20)

    def _fit_rows(self):
        t = self.table
        if t.wordWrap() and t.model() is not None and t.model().rowCount() <= self.wrap_rows_limit:
            t.resizeRowsToContents()

    def _on_section_resized(self, col, _old, new):
        # hiding a column reports a resize to 0 (before it is marked hidden) and
        # showing it a resize from 0; a drag never reaches 0 (minimum section 16):
        # neither is the user's, and widening a hiding section leaves a gap
        if self._busy or new == 0 or _old == 0:
            return
        floor = self.floor(col)
        if new < floor:
            self._busy = True
            self.table.horizontalHeader().resizeSection(col, floor)
            self._busy = False
            new = floor
        self.user[col] = new
        self.schedule()


# ------------------------------------------------------------------------------------
# Pinned last column: a second view showing only the last visible column, floating on the
# right edge. It shares the model, selection model and delegate, so selection, hover and
# painting match; the real column scrolls underneath it.
# ------------------------------------------------------------------------------------
class _Pin(QObject):
    ROW_SYNC_LIMIT = 5000      # above this many rows, per-row heights are not copied

    def __init__(self, ctrl: _Controller, min_beside: int, separator: str | None):
        t = ctrl.table
        super().__init__(t)
        self.ctrl, self.min_beside = ctrl, min_beside
        self._syncing = False
        ov = self.view = QTableView(t)
        ov.setObjectName("columnStylePinned")
        ov.setFrameShape(QTableView.NoFrame)
        ov.verticalHeader().hide()
        ov.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        ov.horizontalHeader().setHighlightSections(False)
        ov.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ov.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if separator:
            ov.setStyleSheet(f"QTableView#columnStylePinned {{ border-left: 1px solid {separator}; }}")
        self.bind()
        t.verticalScrollBar().valueChanged.connect(self._scroll_from_table)
        ov.verticalScrollBar().valueChanged.connect(self._scroll_from_overlay)
        t.verticalHeader().sectionResized.connect(self._row_resized)
        self.sync()

    def bind(self):
        """(Re)attach to the table's model, selection and delegate; mirror its look."""
        t, ov = self.ctrl.table, self.view
        if t.model() is None:
            return
        if ov.model() is not t.model():
            ov.setModel(t.model())
        if ov.selectionModel() is not t.selectionModel():
            ov.setSelectionModel(t.selectionModel())
        ov.setItemDelegate(t.itemDelegate())
        ov.setSelectionBehavior(t.selectionBehavior()); ov.setSelectionMode(t.selectionMode())
        ov.setEditTriggers(t.editTriggers())
        ov.setAlternatingRowColors(t.alternatingRowColors())
        ov.setShowGrid(t.showGrid()); ov.setWordWrap(t.wordWrap())
        ov.setTextElideMode(t.textElideMode()); ov.setVerticalScrollMode(t.verticalScrollMode())
        ov.setHorizontalScrollMode(t.horizontalScrollMode())
        ov.horizontalHeader().setSectionsClickable(t.horizontalHeader().sectionsClickable())

    def sync(self):
        t, ov = self.ctrl.table, self.view
        m, hh = t.model(), t.horizontalHeader()
        if m is None:
            return
        self.bind()
        # last column on screen (visual order: a column may have been moved)
        vis = [hh.logicalIndex(v) for v in range(hh.count())
               if not hh.isSectionHidden(hh.logicalIndex(v))]
        if not vis:
            ov.hide(); return
        last = vis[-1]
        for c in range(m.columnCount()):
            ov.setColumnHidden(c, c != last)
        if ov.itemDelegateForColumn(last) is not t.itemDelegateForColumn(last):
            ov.setItemDelegateForColumn(last, t.itemDelegateForColumn(last))   # e.g. buttons
        w = hh.sectionSize(last)
        ov.horizontalHeader().resizeSection(last, w)
        ov.horizontalHeader().setFixedHeight(hh.height())   # level with the table's titles
        vh = t.verticalHeader()
        ov.verticalHeader().setDefaultSectionSize(vh.defaultSectionSize())
        if m.rowCount() <= self.ROW_SYNC_LIMIT:
            for r in range(m.rowCount()):
                if ov.rowHeight(r) != t.rowHeight(r):
                    ov.setRowHeight(r, t.rowHeight(r))
        vp = t.viewport()
        floating = vp.width() >= w + self.min_beside
        ov.setVisible(floating)
        if floating:
            ov.setGeometry(vp.x() + vp.width() - w, vp.y() - hh.height(), w, vp.height() + hh.height())
            ov.raise_()
            self._scroll_from_table(t.verticalScrollBar().value())

    def _row_resized(self, row, _old, new):
        if self.view.model() is not None and row < self.view.model().rowCount() \
                and self.view.rowHeight(row) != new:
            self.view.setRowHeight(row, new)

    def _scroll_from_table(self, value):
        if not self._syncing and self.view.verticalScrollBar().value() != value:
            self._syncing = True
            self.view.verticalScrollBar().setValue(value)
            self._syncing = False

    def _scroll_from_overlay(self, value):          # mouse wheel over the pinned column
        if not self._syncing:
            self._syncing = True
            self.ctrl.table.verticalScrollBar().setValue(value)
            self._syncing = False

    def remove(self):
        self.view.hide(); self.view.deleteLater(); self.deleteLater()


# ------------------------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------------------------
def apply_column_style(table: QTableView, overrides: Mapping[int, str] | None = None, *,
                       wrap_names: bool = True, wrap_rows_limit: int = 2000,
                       precision: int | None = None, sideways: bool = True,
                       break_long_words: bool = True) -> _Controller:
    """Style `table` once, after its headers are set (QTableWidget or QTableView + model).

    overrides         {column index: column id} for ambiguous or unknown labels; they win.
    wrap_names        word-wrap the table and fit row heights to the stretch column's width.
    wrap_rows_limit   above this many rows, row heights are NOT refitted (cost grows with rows).
    precision         rows sampled for content width (QHeaderView.resizeContentsPrecision).
    sideways          table scrolls sideways itself, per pixel.
    break_long_words  stretch columns use WrapAnywhereDelegate, so a long unbroken string wraps
                      instead of being clipped (a column with its own delegate is left alone).
    Calling it again on the same table updates its overrides and re-resolves the ids."""
    ctrl = table.findChild(_Controller)
    if ctrl is None:
        ctrl = _Controller(table, overrides, wrap_names=wrap_names,
                           wrap_rows_limit=wrap_rows_limit, sideways=sideways,
                           break_long_words=break_long_words)
    else:
        ctrl.overrides.update(overrides or {})
        ctrl.rescan()
    if precision is not None:
        table.horizontalHeader().setResizeContentsPrecision(precision)
    return ctrl


def _ctrl(table) -> _Controller:
    c = table.findChild(_Controller)
    if c is None:
        raise RuntimeError("apply_column_style(table) has not been called for this table")
    return c


def confine_horizontal_scroll(table: QTableView, on: bool = True, *, ancestors: bool = True) -> None:
    """Only the table scrolls in x, never its parent. (apply_column_style does this by default.)

    - the table's horizontal size policy becomes Ignored and its minimum width 0, so a wide set
      of columns cannot make a layout, splitter or dialog wider;
    - ancestors=True: every QScrollArea above it gets no horizontal scrollbar and
      widgetResizable=True, so the page is exactly as wide as the window;
    - sideways wheel / shift+wheel over the table is consumed by the table even when it is at
      its left or right end (it does not chain to a parent scroll area).
    Call it again after you re-parent the table. on=False only stops the wheel capture."""
    c = _ctrl(table)
    c.confine = on
    if on:
        c.apply_confinement(ancestors)


def refit(table: QTableView) -> None:
    """Recompute widths now (e.g. after setModel, a theme or font change)."""
    c = _ctrl(table); c.bind_model(); c._timer.stop(); c.relayout()


def rescan(table: QTableView) -> None:
    """Re-read header labels after you changed them (also happens on headerDataChanged)."""
    _ctrl(table).rescan()


def reset_widths(table: QTableView) -> None:
    """Forget every width the user dragged; go back to minimum / content / spare."""
    c = _ctrl(table); c.user.clear(); c.relayout()


def _col(table, which) -> int:
    """Column index from an index or a column id (first visible column with that id)."""
    c = _ctrl(table)
    if isinstance(which, int):
        return which
    for col, cid in c.ids.items():
        if cid == which:
            return col
    raise KeyError(f"no column with id {which!r} in this table")


def set_min_width(table: QTableView, which: "int | str", content_px: int) -> None:
    """Change a minimum for THIS table only. `which` is a column index (that column) or a
    column id (every column with that id). content_px excludes padding."""
    c = _ctrl(table)
    if isinstance(which, int):
        r = c.rule(which)
        c.floor_override[which] = content_px + 2 * (r.pad_x if r else PAD_X)
    else:
        if which not in c.rules:
            raise KeyError(f"unknown column id {which!r}")
        c.rules[which] = replace(c.rules[which], min_width=content_px)
        for col, cid in c.ids.items():
            if cid == which:
                c.floor_override.pop(col, None)
    c.relayout()


def set_stretch(table: QTableView, col_id: str, on: bool = True) -> None:
    """Make columns with this id take (or stop taking) the spare width, for this table only."""
    c = _ctrl(table)
    c.rules[col_id] = replace(c.rules[col_id], stretch=on)
    c._install_delegates(); c.relayout()


def set_column_id(table: QTableView, col: int, col_id: str) -> None:
    """Give one column an id (same as an override, but after apply_column_style)."""
    c = _ctrl(table)
    if col_id not in c.rules:
        raise KeyError(f"unknown column id {col_id!r}")
    c.overrides[col] = col_id
    c.rescan()


def column_floor(table: QTableView, which: "int | str") -> int:
    """Smallest width (px, with padding) a column may have."""
    return _ctrl(table).floor(_col(table, which))


def column_ids(table: QTableView) -> dict[int, str | None]:
    """{column index: id or None} as resolved from the header labels."""
    return dict(_ctrl(table).ids)


def hide_columns(table: QTableView, *ids: str) -> None:
    """Hide every column with one of these ids (e.g. hide_columns(t, "note", "datetime"))."""
    c = _ctrl(table)
    for col, cid in c.ids.items():
        if cid in ids:
            table.setColumnHidden(col, True)
    c.schedule()


def show_columns(table: QTableView, *ids: str) -> None:
    """Show hidden columns with these ids again."""
    c = _ctrl(table)
    for col, cid in c.ids.items():
        if cid in ids:
            table.setColumnHidden(col, False)
    c.schedule()


# ---- persistence: user-dragged widths, keyed by header label (survives column reorder) ----
def export_widths(table: QTableView) -> dict[str, int]:
    c = _ctrl(table)
    m = table.model()
    out = {}
    for col, w in c.user.items():
        key = _normalize(m.headerData(col, table.horizontalHeader().orientation()))
        if key:
            out[key] = w
    return out


def import_widths(table: QTableView, widths: Mapping[str, int]) -> None:
    """Apply saved widths. Labels that no longer exist are ignored; a width below the
    column's minimum is raised to the minimum."""
    c = _ctrl(table)
    m = table.model()
    by_label = {_normalize(m.headerData(col, table.horizontalHeader().orientation())): col
                for col in range(m.columnCount())}
    for key, w in widths.items():
        col = by_label.get(key)
        if col is not None and isinstance(w, int):
            c.user[col] = max(w, c.floor(col))
    c.relayout()


def save_widths(table: QTableView, settings, key: str) -> None:
    """Store export_widths() as JSON in a QSettings."""
    settings.setValue(key, json.dumps(export_widths(table)))


def restore_widths(table: QTableView, settings, key: str) -> None:
    raw = settings.value(key, "")
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        data = {}
    if isinstance(data, dict):
        import_widths(table, data)


# ---- pinned last column ---------------------------------------------------------------------
def pin_last_column(table: QTableView, on: bool = True, *, min_beside: int = 90,
                    separator: str | None = None) -> None:
    """Keep the last visible column (usually "Action") on the table's right edge while the
    other columns scroll sideways underneath it. At the end of the scroll it sits exactly on
    the real column, so it never covers another column.

    min_beside   when less than this many px of other columns would be visible next to it,
                 the pin stops floating and the column scrolls like any other.
    separator    colour of a 1 px line on its left edge, e.g. "#ddd" (or draw it in your QSS).
    Limits: cell widgets (setCellWidget / setIndexWidget) and per-column delegates are not
    mirrored in the pinned copy; persistent editors work through the shared delegate.
    Call refit(table) after replacing the model or the delegate."""
    c = _ctrl(table)
    if on and c.pin is None:
        c.pin = _Pin(c, min_beside, separator)
    elif on:
        c.pin.min_beside = min_beside
        c.pin.sync()
    elif c.pin is not None:
        c.pin.remove(); c.pin = None


def pinned_view(table: QTableView) -> QTableView | None:
    """The floating copy of the last column (e.g. to track hover on it), or None."""
    c = _ctrl(table)
    return c.pin.view if c.pin is not None else None


def is_pinned(table: QTableView) -> bool:
    """True while a pinned last column exists AND is currently floating (visible)."""
    c = _ctrl(table)
    return c.pin is not None and c.pin.view.isVisible()


# ---- diagnostics --------------------------------------------------------------------------
def describe(table: QTableView) -> str:
    """A text table of every column: label, id, floor, current width, state."""
    c, hh, m = _ctrl(table), table.horizontalHeader(), table.model()
    lines = [f"{'col':>3}  {'label':<22} {'id':<12} {'floor':>5} {'width':>5}  state"]
    for col in range(hh.count()):
        label = str(m.headerData(col, hh.orientation()) or "").replace("\n", " ")
        state = "hidden" if hh.isSectionHidden(col) else ""
        if col in c.user:
            state = (state + " dragged").strip()
        r = c.rule(col)
        if r and r.stretch:
            state = (state + " stretch").strip()
        lines.append(f"{col:>3}  {label:<22.22} {str(c.ids.get(col)):<12} "
                     f"{c.floor(col):>5} {hh.sectionSize(col):>5}  {state}")
    return "\n".join(lines)


def check(table: QTableView) -> list[str]:
    """Problems found in the table's column setup (empty list = fine)."""
    c, hh, m = _ctrl(table), table.horizontalHeader(), table.model()
    problems = []
    for col in range(hh.count()):
        if hh.isSectionHidden(col):
            continue
        label = m.headerData(col, hh.orientation())
        if c.ids.get(col) is None and _normalize(label):
            problems.append(f"column {col} {str(label)!r}: no id (register_labels or overrides)")
        if hh.sectionSize(col) < c.floor(col):
            problems.append(f"column {col} {str(label)!r}: width {hh.sectionSize(col)} is below "
                            f"its minimum {c.floor(col)}")
        if hh.sectionResizeMode(col) != QHeaderView.Interactive:
            problems.append(f"column {col} {str(label)!r}: resize mode was changed away from "
                            f"Interactive; the minimum is no longer enforced")
    ids = [c.ids.get(col) for col in range(hh.count()) if not hh.isSectionHidden(col)]
    stretch = [i for i in ids if i and c.rules[i].stretch]
    if not stretch:
        problems.append("no visible stretch column: spare width stays empty on the right")
    return problems


