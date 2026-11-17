from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QTableWidgetItem,
    QStyledItemDelegate,
    QMenu,
    QWidgetAction,
    QToolTip,
)
from PySide6.QtCore import Qt, Signal, QPoint, QRectF, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.styles import font
from three_ps_lcca_gui.gui.theme import FS_DISP, FS_MD, FS_SM, FW_BOLD, FW_SEMIBOLD
from ...utils.display_format import fmt_comma, fmt_pct
from ...utils.icons import make_icon
from .items_by_tab import ItemsByTabView, TAB_NAMES
from three_ps_lcca_gui.core import start_manager as sm


# BOQ export formats: extension, badge, badge colour, title, hint
BOQ_CHOICES = [
    (".xlsx", "XLSX", "#22c55e", "Excel workbook", "Editable spreadsheet"),
    (".ods", "ODS", "#3b82f6", "OpenDocument sheet", "LibreOffice / open format"),
    (".pdf", "PDF", "#ef4444", "PDF document", "Print-ready for submission"),
]

CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}

# one colour per tab for the share bar, readable on light and dark
TAB_COLORS = {
    "str_foundation": "#22c55e",
    "str_sub_structure": "#38bdf8",
    "str_super_structure": "#a78bfa",
    "str_misc": "#f59e0b",
}


def _rgba(color, alpha):
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


class _TotalRowDelegate(QStyledItemDelegate):
    """Fills the cell background before the normal paint. The app stylesheet
    styles QTableView::item, which makes Qt ignore an item's own background."""

    def __init__(self, color, parent):
        super().__init__(parent)
        self._color = color

    def paint(self, painter, option, index):
        painter.fillRect(option.rect, self._color)
        super().paint(painter, option, index)



class _ShareBar(QWidget):
    """Thin bar split into each tab's share of the grand total. Hovering a
    segment outlines it and shows its name, share and amount."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(12)
        self.setMouseTracking(True)
        self._parts = []  # (fraction, QColor, tooltip)
        self._hover = -1

    def set_parts(self, parts):
        self._parts = parts
        self._hover = -1
        self.update()

    def _segments(self):
        x, w = 0.0, self.width()
        for frac, _, _ in self._parts:
            seg = frac * w
            yield QRectF(x + 1, 2, max(seg - 4, 3), self.height() - 4)
            x += seg

    def mouseMoveEvent(self, event):
        pos = event.position()
        hit = next((i for i, r in enumerate(self._segments())
                    if r.left() - 2 <= pos.x() <= r.right() + 2), -1)
        if hit != self._hover:
            self._hover = hit
            self.update()
        if hit >= 0:
            QToolTip.showText(event.globalPosition().toPoint(), self._parts[hit][2], self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, _event):
        self._hover = -1
        QToolTip.hideText()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i, (r, (_, color, _)) in enumerate(zip(self._segments(), self._parts)):
            p.setPen(QPen(QColor(get_token("text")), 1.5) if i == self._hover else Qt.NoPen)
            p.setBrush(color)
            rect = r.adjusted(-1.5, -1.5, 1.5, 1.5) if i == self._hover else r
            p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.end()


class _FormatRow(QFrame):
    """One row of the export menu: badge, title and hint, tick when current."""

    def __init__(self, badge, color, title, hint, on_click):
        super().__init__()
        self._on_click = on_click
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("fmtRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 12, 8)
        row.setSpacing(12)
        b = QLabel(badge)
        b.setAlignment(Qt.AlignCenter)
        b.setFixedSize(38, 20)
        b.setStyleSheet(
            f"color: {color}; background-color: {_rgba(color, 45)}; border-radius: 4px;"
        )
        b.setFont(font(FS_SM, FW_BOLD))
        texts = QVBoxLayout()
        texts.setSpacing(1)
        t = QLabel(title)
        t.setFont(font(FS_MD, FW_SEMIBOLD))
        t.setStyleSheet(f"color: {get_token('text')};")
        h = QLabel(hint)
        h.setFont(font(FS_SM))
        h.setStyleSheet(f"color: {get_token('text_secondary')};")
        texts.addWidget(t)
        texts.addWidget(h)
        self.tick = QLabel("✓")
        self.tick.setFont(font(FS_MD, FW_BOLD))
        self.tick.setStyleSheet(f"color: {get_token('success')};")
        row.addWidget(b)
        row.addLayout(texts, 1)
        row.addWidget(self.tick)

    def set_current(self, on):
        self.tick.setVisible(on)
        bg = _rgba(get_token("success"), 30) if on else "transparent"
        self.setStyleSheet(
            f"#fmtRow {{ background-color: {bg}; border-radius: 8px; }}"
            f"#fmtRow:hover {{ background-color: {_rgba(get_token('text'), 18)}; }}"
            "#fmtRow QLabel { background: transparent; }"
        )

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self._on_click()


class StructureSummaryWidget(ItemsByTabView):
    """
    Read-only list of every active (not trashed) item, one table per tab,
    with the grand total and an Export BOQ button.
    """

    EMPTY_TEXT = (
        "No items yet. Add materials in the Foundation, Sub-Structure, "
        "Super-Structure and Miscellaneous tabs."
    )
    TABLE_OPTIONS = {"read_only": True}

    export_requested = Signal(str)  # file extension, e.g. ".xlsx"
    open_requested = Signal(str, str, int)  # tab name, component, data index

    def __init__(self, controller=None):
        super().__init__(controller)

        text, muted = get_token("text"), get_token("text_secondary")
        self.header_row.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("summaryCard")
        card.setStyleSheet(
            f"#summaryCard {{ background-color: {get_token('surface')};"
            f" border: 1px solid {get_token('surface_mid')}; border-radius: 12px; }}"
            "#summaryCard QLabel { background: transparent; border: none; }"
        )
        card_col = QVBoxLayout(card)
        card_col.setContentsMargins(20, 18, 20, 18)
        card_col.setSpacing(0)

        # Grand total on the left, the split Export button on the right
        top = QHBoxLayout()
        total_col = QVBoxLayout()
        total_col.setSpacing(2)
        caption = QLabel("Grand total")
        caption.setFont(font(FS_SM))
        caption.setStyleSheet(f"color: {muted};")
        self.total_lbl = QLabel()
        self.total_lbl.setFont(font(FS_DISP, FW_BOLD))
        self.total_lbl.setStyleSheet(f"color: {text};")
        total_col.addWidget(caption)
        total_col.addWidget(self.total_lbl)
        top.addLayout(total_col, 1)
        top.addLayout(self._build_export_button(), 0)
        card_col.addLayout(top)
        card_col.addSpacing(14)

        # Each tab's share of the total, across the full card width
        self.share_bar = _ShareBar()
        self.legend = QLabel()
        self.legend.setFont(font(FS_SM))
        self.legend.setStyleSheet(f"color: {muted};")
        card_col.addWidget(self.share_bar)
        card_col.addSpacing(8)
        card_col.addWidget(self.legend)

        self.header_row.addWidget(card)

    def _build_export_button(self):
        """Split button: the main part exports in the last-used format,
        the arrow opens a menu to pick another one."""
        base = get_token("base")
        green = QColor(get_token("success"))
        if QColor(base).lightness() > 128:  # light theme: white text needs a darker green
            green = green.darker(135)
        btn_css = (
            f"QPushButton {{ background-color: {green.name()}; color: {base}; border: none;"
            f" border-radius: 0px; }}"
            f"QPushButton:hover {{ background-color: {green.lighter(112).name()}; }}"
            f"QPushButton:disabled {{ background-color: {get_token('success', 'disabled')}; }}"
        )

        self.export_btn = QPushButton()
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setToolTip("Export the Bill of Quantities")
        self.export_btn.setStyleSheet(
            btn_css + "QPushButton { border-top-left-radius: 8px; border-bottom-left-radius: 8px; }"
        )
        inner = QHBoxLayout(self.export_btn)
        inner.setContentsMargins(18, 0, 12, 0)
        inner.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(make_icon("download", color=base).pixmap(18, 18))
        label = QLabel("Export BOQ")
        label.setFont(font(FS_MD, FW_BOLD))
        label.setStyleSheet(f"color: {base};")
        self.fmt_badge = QLabel()
        self.fmt_badge.setAlignment(Qt.AlignCenter)
        self.fmt_badge.setFixedHeight(20)
        self.fmt_badge.setStyleSheet(
            f"color: {base}; background-color: rgba(0, 0, 0, 60); border-radius: 4px;"
            " padding: 0px 6px;"
        )
        self.fmt_badge.setFont(font(FS_SM, FW_BOLD))
        for w in (icon, label, self.fmt_badge):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            inner.addWidget(w, 0, Qt.AlignVCenter)
        self.export_btn.setFixedHeight(40)
        self.export_btn.clicked.connect(lambda: self.export_requested.emit(self._fmt))

        self._chevrons = {n: make_icon(n, color=base) for n in ("expand-more", "expand-less")}
        self.fmt_btn = QPushButton()
        self.fmt_btn.setIcon(self._chevrons["expand-more"])
        self.fmt_btn.setIconSize(QSize(22, 22))
        self.fmt_btn.setCursor(Qt.PointingHandCursor)
        self.fmt_btn.setToolTip("Choose the export format")
        self.fmt_btn.setFixedSize(44, 40)
        self.fmt_btn.setStyleSheet(
            btn_css + "QPushButton { border-top-right-radius: 8px; border-bottom-right-radius: 8px;"
            f" border-left: 1px solid {green.darker(125).name()}; }}"
        )
        self.fmt_btn.clicked.connect(self._show_menu)

        # Format menu: "EXPORT AS", one row per format, a footer note
        self._menu = QMenu(self)
        self._menu.setWindowFlags(self._menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self._menu.setAttribute(Qt.WA_TranslucentBackground)
        self._menu.setStyleSheet(
            f"QMenu {{ background-color: {get_token('surface')}; border: 1px solid {get_token('surface_mid')};"
            f" border-radius: 10px; padding: 6px; }}"
        )
        panel = QWidget()
        panel.setObjectName("fmtPanel")
        panel.setStyleSheet("#fmtPanel { background: transparent; }")  # one colour: the menu's
        col = QVBoxLayout(panel)
        col.setContentsMargins(4, 6, 4, 4)
        col.setSpacing(2)
        cap = QLabel("EXPORT AS")
        cap.setFont(font(FS_SM, FW_SEMIBOLD))
        cap.setStyleSheet(f"color: {get_token('text_secondary')}; letter-spacing: 1px; padding: 0 8px 6px 8px;")
        col.addWidget(cap)
        self._fmt_rows = {}
        for ext, badge, color, title, hint in BOQ_CHOICES:
            row = _FormatRow(badge, color, title, hint, lambda e=ext: self._export_as(e))
            self._fmt_rows[ext] = row
            col.addWidget(row)
        note = QLabel("The main button uses your last format.")
        note.setFont(font(FS_SM))
        note.setStyleSheet(f"color: {get_token('text_secondary')}; padding: 8px 8px 2px 8px;")
        col.addWidget(note)
        panel.setMinimumWidth(240)
        act = QWidgetAction(self._menu)
        act.setDefaultWidget(panel)
        self._menu.addAction(act)

        try:
            saved = sm.get_pref("boq_format")
        except Exception:
            saved = ""
        self._set_fmt(saved if saved in self._fmt_rows else ".xlsx")

        split = QHBoxLayout()
        split.setSpacing(0)
        split.setAlignment(Qt.AlignVCenter)
        split.addWidget(self.export_btn)
        split.addWidget(self.fmt_btn)
        return split

    def _show_menu(self):
        """Open the format menu right-aligned under the split button."""
        w = self._menu.sizeHint().width()
        pos = self.fmt_btn.mapToGlobal(QPoint(self.fmt_btn.width() - w, self.fmt_btn.height() + 6))
        self.fmt_btn.setIcon(self._chevrons["expand-less"])
        self._menu.exec(pos)
        self.fmt_btn.setIcon(self._chevrons["expand-more"])

    def _set_fmt(self, ext):
        self._fmt = ext
        for e, row in self._fmt_rows.items():
            row.set_current(e == ext)
        self.fmt_badge.setText(next(c[1] for c in BOQ_CHOICES if c[0] == ext))
        self.export_btn.setMinimumWidth(self.export_btn.layout().sizeHint().width())

    def _export_as(self, ext):
        """Menu pick: remember the format for the main button, then export."""
        self._menu.close()
        self._set_fmt(ext)
        try:
            sm.set_pref("boq_format", ext)
        except Exception:
            pass
        self.export_requested.emit(ext)

    def showEvent(self, event):
        super().showEvent(event)
        self.on_refresh()

    def _currency(self):
        info = self.controller.engine.fetch_chunk("general_info") or {}
        return str(info.get("project_currency", ""))

    def _signature(self):
        sig = super()._signature()
        return None if sig is None else [self._currency(), *sig]

    def _setup_table(self, table):
        table.set_currency(self._currency())

    def open_item(self, chunk_id, comp_name, data_index):
        self.open_requested.emit(TAB_NAMES.get(chunk_id, chunk_id), comp_name, data_index)

    @staticmethod
    def _sum(rows):
        total = 0.0
        for _, _, item in rows:
            v = item.get("values", {})
            try:
                total += float(v.get("rate") or 0) * float(v.get("quantity") or 0)
            except (ValueError, TypeError):
                pass
        return total

    def _table_filled(self, table, rows):
        """Append a bold, non-selectable Total row. It has no col 6 data,
        so double-click ignores it."""
        row = table.rowCount()
        table.insertRow(row)
        table.setRowHeight(row, table.rowHeight(0))
        bold = QFont(table.font())
        bold.setBold(True)
        bg = QColor(get_token("surface_mid"))
        table.setItemDelegateForRow(row, _TotalRowDelegate(bg, table))
        # label in Component (col 7, shown first), amount in Total (col 5)
        cells = {7: "Total", 5: fmt_comma(self._sum(rows))}
        for col in range(table.columnCount()):
            if col == 6:  # hidden data column: left empty so double-click skips the row
                continue
            item = QTableWidgetItem(cells.get(col, ""))
            item.setFlags(Qt.ItemIsEnabled)
            item.setFont(bold)
            if col == 5:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, col, item)
        table.update_height()

    def _refreshed(self, rows_by_chunk):
        totals = {c: self._sum(rows) for c, rows in rows_by_chunk.items()}
        grand_total = sum(totals.values())
        sym = CURRENCY_SYMBOLS.get(self._currency(), "")
        self.total_lbl.setText(sym + fmt_comma(grand_total))

        shares = [(c, t / grand_total) for c, t in totals.items() if t > 0] if grand_total > 0 else []
        self.share_bar.set_parts([
            (f, QColor(TAB_COLORS[c]),
             f"{TAB_NAMES[c]} \u00b7 {fmt_pct(f * 100)}%<br><b>{sym}{fmt_comma(totals[c])}</b>")
            for c, f in shares
        ])
        self.legend.setText("&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;".join(
            f"<span style='color:{TAB_COLORS[c]}'>\u25a0</span>&nbsp; {TAB_NAMES[c]}"
            f"&nbsp; <b style='color:{get_token('text')}'>{fmt_pct(f * 100)}%</b>"
            for c, f in shares
        ))
        self.share_bar.setVisible(bool(shares))
        self.legend.setVisible(bool(shares))
        has_items = any(rows_by_chunk.values())
        self.export_btn.setEnabled(has_items)
        self.fmt_btn.setEnabled(has_items)
