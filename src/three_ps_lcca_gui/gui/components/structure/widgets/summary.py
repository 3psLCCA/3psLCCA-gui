from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QMenu,
    QWidgetAction,
    QToolTip,
    QStyle,
)
from PySide6.QtCore import Qt, Signal, QPoint, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.styles import font
from three_ps_lcca_gui.gui.theme import (
    FS_DISP, FS_MD, FS_SM, FW_BOLD, FW_SEMIBOLD,
    RADIUS_SM, SP2, SP4, SP5,
)
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
    """One row of the export menu: badge and title (hint as tooltip), tick when current."""

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
            f"color: {color}; background-color: {_rgba(color, 45)}; border-radius: {RADIUS_SM}px;"
        )
        b.setFont(font(FS_SM, FW_BOLD))
        t = QLabel(title)
        t.setFont(font(FS_MD, FW_SEMIBOLD))
        t.setStyleSheet(f"color: {get_token('text')};")
        self.setToolTip(hint)
        self.tick = QLabel("✓")
        self.tick.setFont(font(FS_MD, FW_BOLD))
        self.tick.setStyleSheet(f"color: {get_token('success')};")
        row.addWidget(b)
        row.addWidget(t, 1)
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

    PAGE_NAME = "Summary"
    EMPTY_TEXT = (
        "No items yet. Add materials in the Foundation, Sub-Structure, "
        "Super-Structure and Miscellaneous tabs."
    )
    TABLE_OPTIONS = {"read_only": True}
    EXPORT_TEXT = "Export Priced BOQ"
    EXPORTING_TEXT = "Exporting…"

    export_requested = Signal(str)  # file extension, e.g. ".xlsx"
    open_requested = Signal(str, str, int)  # tab name, component, data index

    def __init__(self, controller=None):
        self._has_items = False
        self._exporting = False
        super().__init__(controller)

        # same width as the tab pages (manager.py): Qt's default side margin,
        # and the scrollbar's room kept so the cards don't change width
        side = self.style().pixelMetric(QStyle.PM_LayoutLeftMargin)
        self.layout.setContentsMargins(side, 8, side, 0)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        text, muted = get_token("text"), get_token("text_secondary")
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

        # Initial construction cost on the left, the split Export button on the right
        top = QHBoxLayout()
        total_col = QVBoxLayout()
        total_col.setSpacing(2)
        caption = QLabel("Initial Construction Cost")
        caption.setFont(font(FS_SM))
        caption.setStyleSheet(f"color: {muted};")
        self.total_lbl = QLabel()
        self.total_lbl.setFont(font(FS_DISP, FW_BOLD))
        self.total_lbl.setStyleSheet(f"color: {text};")
        total_col.addWidget(caption)
        total_col.addWidget(self.total_lbl)
        top.addLayout(total_col, 1)
        top.addWidget(self._build_export_button(), 0, Qt.AlignVCenter)
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

        # Card scrolls with the tables: put it above the table container,
        # inside the scroll area (the rebuild only clears the container)
        page = QWidget()
        page_col = QVBoxLayout(page)  # its margins frame the card and tables alike
        page_col.setSpacing(SP4)  # same gap as between the table cards
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        page_col.addWidget(card)
        page_col.addWidget(self.scroll.takeWidget())
        self.scroll.setWidget(page)

    def _build_export_button(self):
        """Split button (main.qss: #exportBtn, #exportMenuBtn): the main part
        exports in the last-used format, the arrow opens a menu to pick
        another one."""
        on_fill = get_token("text-on-primary")

        split_w = QWidget()
        split = QHBoxLayout(split_w)
        split.setContentsMargins(0, 0, 0, 0)
        split.setSpacing(0)

        self.export_btn = QPushButton()
        self.export_btn.setObjectName("exportBtn")
        self.export_btn.setCursor(Qt.PointingHandCursor)
        self.export_btn.setToolTip("Export the Bill of Quantities")
        inner = QHBoxLayout(self.export_btn)
        inner.setContentsMargins(SP5, 0, SP4, 0)
        inner.setSpacing(SP2)
        icon = QLabel()
        # at the screen's scale, so it stays sharp on 125% / 150% displays
        icon.setPixmap(make_icon("download", color=on_fill).pixmap(QSize(16, 16), self.devicePixelRatioF()))
        self._export_label = label = QLabel(self.EXPORT_TEXT)
        label.setFont(font(FS_MD, FW_SEMIBOLD))
        label.setStyleSheet(f"color: {on_fill}; background: transparent;")
        self.fmt_badge = QLabel()
        self.fmt_badge.setAlignment(Qt.AlignCenter)
        self.fmt_badge.setStyleSheet(
            f"color: {get_token('warning')}; background-color: {on_fill}; border-radius: {RADIUS_SM}px;"
            f" padding: 2px {SP2}px;"
        )
        self.fmt_badge.setFont(font(FS_SM, FW_BOLD))
        for w in (icon, label, self.fmt_badge):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            inner.addWidget(w, 0, Qt.AlignVCenter)
        self.export_btn.clicked.connect(lambda: self.export_requested.emit(self._fmt))

        self._chevrons = {n: make_icon(n, color=on_fill) for n in ("expand-more", "expand-less")}
        self.fmt_btn = QPushButton()
        self.fmt_btn.setObjectName("exportMenuBtn")
        self.fmt_btn.setIcon(self._chevrons["expand-more"])
        self.fmt_btn.setIconSize(QSize(18, 18))
        self.fmt_btn.setCursor(Qt.PointingHandCursor)
        self.fmt_btn.setToolTip("Choose the export format")
        self.fmt_btn.clicked.connect(self._show_menu)
        split.addWidget(self.export_btn)
        split.addWidget(self.fmt_btn)

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
        return split_w

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

    def _refreshed(self, rows_by_chunk):
        totals = {c: self._sum(rows) for c, rows in rows_by_chunk.items()}
        grand_total = sum(totals.values())
        cur = self._currency()  # short code, e.g. INR
        self.total_lbl.setText(f"{cur} {fmt_comma(grand_total)}".strip())

        shares = [(c, t / grand_total) for c, t in totals.items() if t > 0] if grand_total > 0 else []
        self.share_bar.set_parts([
            (f, QColor(TAB_COLORS[c]),
             f"{TAB_NAMES[c]} \u00b7 {fmt_pct(f * 100)}%<br><b>{cur} {fmt_comma(totals[c])}</b>")
            for c, f in shares
        ])
        self.legend.setText("&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;".join(
            f"<span style='color:{TAB_COLORS[c]}'>\u25a0</span>&nbsp; {TAB_NAMES[c]}"
            f"&nbsp; <b style='color:{get_token('text')}'>{fmt_pct(f * 100)}%</b>"
            for c, f in shares
        ))
        self.share_bar.setVisible(bool(shares))
        self.legend.setVisible(bool(shares))
        self._has_items = any(rows_by_chunk.values())
        self._update_export_enabled()

    def set_exporting(self, busy: bool):
        """While an export runs: button disabled and reads "Exporting…"."""
        self._exporting = busy
        self._export_label.setText(self.EXPORTING_TEXT if busy else self.EXPORT_TEXT)
        self._update_export_enabled()

    def _update_export_enabled(self):
        on = self._has_items and not self._exporting
        self.export_btn.setEnabled(on)
        self.fmt_btn.setEnabled(on)
