"""
gui/components/outputs/lcc_plot.py

Creates an interactive matplotlib chart from LCC analysis results.
Use LCCChartWidget(results) to get a QWidget ready to embed in Qt.
"""

import matplotlib
matplotlib.use("QtAgg")

from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.theme import (
    FONT_FAMILY,
    FS_SM, FS_MD, FW_NORMAL, FW_SEMIBOLD, FW_BOLD, RADIUS_SM, SP2
)
from three_ps_lcca_gui.gui.components.utils.display_format import fmt_currency
from three_ps_lcca_gui.gui.components.utils.table_widgets import contrast_color, fit_to_contents, item_text_rect
from .plots_helper.Pie import COLORS
from .helper_functions.lcc_colors import COLORS as LCC_PALETTE
from .lcc_data import (
    _get,
    build_chart_data,
    STAGE_DEFS, stage_totals,
    BREAKDOWN_STAGES,
    CATEGORY_COLORS,
)
from .plots_helper.bar_chart import create_bar_chart

matplotlib.rcParams["font.family"] = FONT_FAMILY

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QHeaderView, QLabel, QScrollArea, QFrame,
    QSizePolicy, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QToolTip, QHBoxLayout,
)

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
except ImportError:
    from matplotlib.backends.backend_qt import FigureCanvasQTAgg

from .plots_helper.plot_utils import ChartToolbar, WheelForwarder as _ScrollForwarder
from .table_export import (
    attach_table_context_menu,
    create_table_context_menu,
    export_widget_as_image,
    copy_widget_to_clipboard,
)



class HeatmapDelegate(QStyledItemDelegate):
    """Native Qt delegate for rendering heatmap cells."""
    def __init__(self, col_maxima, currency, parent=None):
        super().__init__(parent)
        self.col_maxima = col_maxima
        self.currency = currency

    def _std_heat_color(self, intensity: float) -> QColor:
        t = max(0.0, min(1.0, intensity))
        # Light Pale Yellow (255, 255, 200) -> Deep Forest Green (34, 139, 34)
        r = 255 + int((34 - 255) * t)
        g = 255 + int((139 - 255) * t)
        b = 200 + int((34 - 200) * t)
        return QColor(r, g, b)

    def _text_on(self, bg: QColor) -> QColor:
        return contrast_color(bg)

    def paint(self, painter, option, index):
        # Index breakdown:
        # Col 0: Stage Name (slight tint)
        # Col 1-3: Economic, Environmental, Social (Heatmap)
        # Col 4: Stage Total (Neutral)
        # Last Row: Grand Total (Neutral Highlight)
        
        row_count = index.model().rowCount()
        is_total_row = (index.row() == row_count - 1)
        is_heatmap_col = (1 <= index.column() <= 3)
        is_stage_col = (index.column() == 0)
        
        # Determine background color
        if is_heatmap_col and not is_total_row:
            # Main Heatmap Area
            val = index.data(Qt.UserRole)
            col_idx = index.column() - 1
            max_val = self.col_maxima[col_idx]
            intensity = val / max_val if max_val > 0 else 0
            bg_color = self._std_heat_color(intensity)
        elif is_total_row:
            # Bottom Total Row
            bg_color = QColor(get_token("surface_mid"))
        elif is_stage_col:
            bg_data = index.data(Qt.BackgroundRole)
            if hasattr(bg_data, 'color'):
                bg_color = bg_data.color()
            elif isinstance(bg_data, QColor) and bg_data.isValid():
                bg_color = bg_data
            else:
                bg_color = QColor(get_token("window"))
        else:
            # Right Total Column (index 4)
            bg_color = QColor(get_token("surface"))

        fg_color = self._text_on(bg_color)

        painter.save()
        painter.fillRect(option.rect, bg_color)
        
        painter.setFont(option.font)
        painter.setPen(fg_color)
        
        # Draw text
        display_text = index.data(Qt.DisplayRole)
        if display_text is None:
            val = index.data(Qt.UserRole)
            if val is not None:
                display_text = fmt_currency(val, self.currency, decimals=2)
        
        if display_text:
            padding = 8
            rect = option.rect.adjusted(padding, 0, -padding, 0)
            align = Qt.AlignLeft if is_stage_col else Qt.AlignRight
            painter.drawText(rect, align | Qt.AlignVCenter, display_text)
            
        painter.restore()

    def helpEvent(self, event, view, option, index):
        if not index.isValid():
            return False

        val = index.data(Qt.UserRole)
        if val is not None:
            actual_val = val * 1_000_000
            QToolTip.showText(
                event.globalPos(),
                f"Actual Value: {self.currency} {fmt_currency(actual_val, self.currency, decimals=0, style='both')}",
            )
            return True
        else:
            txt = index.data(Qt.DisplayRole)
            if txt:
                QToolTip.showText(event.globalPos(), str(txt))
                return True
                
        return super().helpEvent(event, view, option, index)


class _StageLabelDelegate(QStyledItemDelegate):
    """Paints col-0 stage cells with explicit background and centered text."""

    def paint(self, painter, option, index):
        bg = index.data(Qt.BackgroundRole)
        bg_color = bg.color() if hasattr(bg, 'color') else None
        painter.save()
        if bg_color and bg_color.isValid():
            painter.fillRect(option.rect, bg_color)
            painter.setPen(contrast_color(bg_color))
        else:
            painter.fillRect(option.rect, option.palette.base())
        font = index.data(Qt.FontRole)
        if font:
            painter.setFont(font)
        text = index.data(Qt.DisplayRole) or ""
        painter.drawText(item_text_rect(self, option, index),
                         Qt.AlignCenter | Qt.TextWordWrap, str(text))
        painter.restore()


class LCCDetailsTable(QWidget):
    """Stage × pillar cost summary table."""

    def __init__(self, results: dict, currency: str = "INR", parent=None):
        super().__init__(parent)
        self._currency = currency

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.table = QTableWidget()
        self.table.setItemDelegateForColumn(0, _StageLabelDelegate(self.table))
        self.table.setColumnCount(5)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)

        headers = [
            "Stage",
            f"Economic\n({currency})",
            f"Environmental\n({currency})",
            f"Social\n({currency})",
            f"Stage Total\n({currency})"
        ]
        self.table.setHorizontalHeaderLabels(headers)
        _hdr_bg = [None, LCC_PALETTE["eco_color"], LCC_PALETTE["env_color"], LCC_PALETTE["soc_color"], None]
        for col, hex_color in enumerate(_hdr_bg):
            if hex_color:
                item = self.table.horizontalHeaderItem(col)
                if item:
                    item.setBackground(QColor(hex_color))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.table.setWordWrap(True)
        fit_to_contents(self.table)

        self._build_data(results)

        attach_table_context_menu(self.table, title="Consolidated Stage Summary", default_filename="stage_cost_summary.svg")

        lay.addWidget(self.table)

    def export_as_image(self, file_path: str | None = None, parent=None, format: str = "svg"):
        """Export the table as an SVG vector or PNG/JPEG image."""
        return export_widget_as_image(
            self.table,
            title="Consolidated Stage Summary",
            default_filename=file_path or "stage_cost_summary.svg",
            parent=parent or self,
            format=format,
        )

    def copy_to_clipboard(self):
        return copy_widget_to_clipboard(self.table)

    def _build_data(self, results: dict):
        rows = []
        grand = [0.0] * 4
        _recon_vals = None

        for stage_label, result_key, cat_keys in STAGE_DEFS:
            totals = stage_totals(results, result_key, cat_keys)
            if not totals:
                continue

            vals = [
                totals.get("Economic", 0.0),
                totals.get("Environmental", 0.0),
                totals.get("Social", 0.0),
            ]
            vals.append(sum(vals))

            if result_key == "reconstruction":
                _recon_vals = vals
                continue

            if result_key == "end_of_life" and _recon_vals is not None:
                vals = [vals[i] + _recon_vals[i] for i in range(4)]

            rows.append((stage_label, result_key, vals))
            for i, v in enumerate(vals):
                grand[i] += v

        self.table.setRowCount(len(rows) + 1)

        f_base = QFont(FONT_FAMILY, FS_MD, FW_SEMIBOLD)
        f_bold = QFont(FONT_FAMILY, FS_MD, FW_BOLD)

        _stage_bg = {
            "initial_stage": LCC_PALETTE["init_color"],
            "use_stage":     LCC_PALETTE["use_color"],
            "end_of_life":   LCC_PALETTE["end_color"],
        }

        for r_idx, (label, key, vals) in enumerate(rows):
            item = QTableWidgetItem(label)
            item.setFont(f_base)
            if key in _stage_bg:
                item.setBackground(QColor(_stage_bg[key]))
            self.table.setItem(r_idx, 0, item)

            for c_idx, v in enumerate(vals):
                it = QTableWidgetItem(fmt_currency(v, self._currency, decimals=2))
                it.setFont(f_base)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.TextWordWrap)
                self.table.setItem(r_idx, c_idx + 1, it)

        # Grand Total Row
        tr_idx = len(rows)
        gt_item = QTableWidgetItem("Total")
        gt_item.setFont(f_bold)
        gt_item.setBackground(QColor(get_token("surface_mid")))
        self.table.setItem(tr_idx, 0, gt_item)

        for c_idx, v in enumerate(grand):
            it = QTableWidgetItem(fmt_currency(v, self._currency, decimals=2))
            it.setFont(f_bold)
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.TextWordWrap)
            it.setBackground(QColor(get_token("surface_mid")))
            self.table.setItem(tr_idx, c_idx + 1, it)


# ---------------------------------------------------------------------------
# Detailed breakdown table
# ---------------------------------------------------------------------------

class _VerticalTextDelegate(QStyledItemDelegate):
    """Renders cell text rotated 90° counter-clockwise for the stage column."""

    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)
        bg = index.data(Qt.BackgroundRole)
        if bg:
            c = bg.color() if hasattr(bg, "color") else QColor(bg)
            painter.fillRect(option.rect, c)

        text = (index.data(Qt.DisplayRole) or "").replace("\n", " ")
        font = index.data(Qt.FontRole)
        if font:
            painter.setFont(font)
        fg = index.data(Qt.ForegroundRole)
        painter.setPen(fg.color() if (fg and hasattr(fg, "color")) else option.palette.text().color())

        rect = item_text_rect(self, option, index)
        if option.rect.height() < 55:
            painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, text)
        else:
            painter.translate(
                option.rect.x() + option.rect.width() / 2,
                option.rect.y() + option.rect.height() / 2,
            )
            painter.rotate(-90)

            # the style's text rect, turned with the painter
            text_rect = QRect(
                -rect.height() // 2,
                -rect.width() // 2,
                rect.height(),
                rect.width(),
            )
            painter.drawText(text_rect, Qt.AlignCenter, text)
        painter.restore()

    def sizeHint(self, option, index):
        # Rotated text: one text line (style padding included) sets the width;
        # the stage span gives the height
        base = super().sizeHint(option, index)
        return QSize(base.height(), base.height())



class _ColorDelegate(QStyledItemDelegate):
    """Paints cell background from BackgroundRole brush, ignoring QSS overrides.
    This is the only reliable way to force per-item colors in a dark-themed Qt app."""

    def paint(self, painter, option, index):
        painter.save()
        # Fill background from the item's BackgroundRole brush
        bg = index.data(Qt.BackgroundRole)
        if bg:
            color = bg.color() if hasattr(bg, 'color') else QColor(bg)
            painter.fillRect(option.rect, color)
        else:
            painter.fillRect(option.rect, option.palette.base())

        # Draw text with ForegroundRole color
        fg = index.data(Qt.ForegroundRole)
        text_color = fg.color() if fg and hasattr(fg, 'color') else QColor(get_token("text"))
        painter.setPen(text_color)

        text = index.data(Qt.DisplayRole) or ""
        align = index.data(Qt.TextAlignmentRole)
        if align is None:
            align = Qt.AlignLeft | Qt.AlignVCenter

        padding = 6
        text_rect = option.rect.adjusted(padding, 0, -padding, 0)
        painter.drawText(text_rect, int(align), text)
        painter.restore()

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return base


class _RelativeBarDelegate(QStyledItemDelegate):
    """Relative Cost cell: a bar for the row's value inside the style's content
    rect (QSS padding included). Credits grow left of the zero line, costs right."""

    _INSET_Y = 3  # bar clear of the row lines

    def __init__(self, pos_max: float, neg_max: float, parent=None):
        super().__init__(parent)
        self._pos_max = pos_max
        self._neg_max = neg_max

    def paint(self, painter, option, index):
        # Cell background (the row tint) through the style
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)

        value = index.data(Qt.UserRole)
        color = index.data(Qt.UserRole + 1)
        if not value or not color:
            return
        r = item_text_rect(self, option, index).adjusted(0, self._INSET_Y, 0, -self._INSET_Y)
        span = (self._pos_max + self._neg_max) or 1.0
        zero_x = r.left() + round(r.width() * self._neg_max / span)
        w = max(1, round(r.width() * abs(value) / span))
        x = zero_x - w if value < 0 else zero_x
        painter.fillRect(QRect(x, r.top(), w, r.height()), QColor(color))


class LCCBreakdownTable(QWidget):
    """Detailed row-by-row LCC cost breakdown: a pillar legend above a table.

    Columns: Stage | Cost Item | Value | Relative Cost

    Qt sizes everything: the Stage and Value columns fit their contents, Cost
    Item (word-wrapped) and Relative Cost share the rest, and rows fit their text.
    Hover shows the full label, the value to 4 decimals, or the bar's value.
    """

    # Colors from lcc_colors.py (single source of truth for this widget)
    _PILLAR_COLORS = {
        "economic":      LCC_PALETTE["eco_color"],
        "environmental": LCC_PALETTE["env_color"],
        "social":        LCC_PALETTE["soc_color"],
    }
    _STAGE_COLORS = {
        "initial_stage":   LCC_PALETTE["init_color"],
        "use_stage":       LCC_PALETTE["use_color"],
        "end_of_life":     LCC_PALETTE["end_color"],
        "reconstruction":  LCC_PALETTE.get("recon_color", "#B0BEC5"),
    }
    _CELL_TEXT = "#1a1a1a"  # cells are always light tints

    def __init__(self, results: dict, currency: str = "INR",
                 stage_labels: dict | None = None,
                 row_labels: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self._currency = currency
        self._stage_labels = stage_labels or {}  # result_key → custom stage name
        self._row_labels   = row_labels   or {}  # cost key   → custom row label
        self._rows = []          # list of (pillar, label, value, stage_color)
        self._stage_blocks = []  # list of (label, color_hex, start, end)
        self._build(results)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP2)
        lay.addWidget(self._make_legend())
        self.table = self._make_table()
        lay.addWidget(self.table)
        lay.addStretch(1)  # spare height goes below the table

    # ── data ──────────────────────────────────────────────────────────────────

    def _build(self, results: dict):
        row_idx = 0
        _pillar_order = {"economic": 0, "environmental": 1, "social": 2}
        _buffered_recon = None  # buffer reconstruction rows to fold into end_of_life

        for stage_def in BREAKDOWN_STAGES:
            result_key = stage_def["result_key"]
            stage_data = results.get(result_key, {})

            if stage_def.get("optional") and not isinstance(stage_data.get("economic"), dict):
                continue

            stage_rows = []
            for cat, key, label in stage_def["rows"]:
                val = stage_data.get(cat, {}).get(key)
                if val is not None:
                    # Scrap value is stored as a positive cost, so negate it for display/totaling as a credit
                    if key == "total_scrap_value":
                        val = -float(val)
                    stage_rows.append((cat, label, float(val)))
            if not stage_rows:
                continue
            if stage_def.get("optional") and all(v == 0.0 for _, _, v in stage_rows):
                continue

            stage_rows.sort(key=lambda r: _pillar_order.get(r[0], 9))
            stage_color = self._STAGE_COLORS.get(result_key, stage_def["stage_color"])

            if result_key == "reconstruction":
                # Buffer to fold into end_of_life block as a sub-section
                _buffered_recon = stage_rows
                continue
            start = row_idx
            if result_key == "end_of_life" and _buffered_recon is not None:
                for cat, label, value in _buffered_recon:
                    self._rows.append((cat, f"Reconstruction | {label}", value, stage_color))
                    row_idx += 1
            for cat, label, value in stage_rows:
                self._rows.append((cat, label, value, stage_color))
                row_idx += 1
            self._stage_blocks.append((
                self._stage_labels.get(result_key, stage_def["label"].replace("\n", " ")),
                stage_color,
                start,
                row_idx - 1,
            ))

    # ── widgets ───────────────────────────────────────────────────────────────

    @staticmethod
    def _tint(hex_color: str) -> QColor:
        """The light shade of a pillar/stage color used behind cell text."""
        c = QColor(hex_color)
        return QColor(min(255, c.red() * 25 // 100 + 191),
                      min(255, c.green() * 25 // 100 + 191),
                      min(255, c.blue() * 25 // 100 + 191))

    def _make_legend(self) -> QLabel:
        swatches = "&nbsp;&nbsp;&nbsp;&nbsp;".join(
            f'<span style="color:{color}">&#9632;</span>&nbsp;{pillar.capitalize()}'
            for pillar, color in self._PILLAR_COLORS.items()
        )
        legend = QLabel(swatches)
        legend.setTextFormat(Qt.RichText)
        legend.setFont(QFont(FONT_FAMILY, FS_MD, FW_NORMAL))
        return legend

    def _make_table(self) -> QTableWidget:
        t = QTableWidget(len(self._rows), 4)
        t.setHorizontalHeaderLabels(
            ["Stage", "Cost Item", f"Value ({self._currency})", "Relative Cost"])
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionMode(QTableWidget.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        t.setWordWrap(True)

        # Stage and Value fit their contents; Cost Item and the bars share the rest
        h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        h.setStretchLastSection(False)

        values = [r[2] for r in self._rows]
        pos_max = max([v for v in values if v > 0], default=0.0)
        neg_max = max([-v for v in values if v < 0], default=0.0)
        t.setItemDelegateForColumn(0, _VerticalTextDelegate(t))
        t.setItemDelegateForColumn(3, _RelativeBarDelegate(pos_max, neg_max, t))

        dark = QColor(self._CELL_TEXT)
        f_row = QFont(FONT_FAMILY, FS_MD, FW_NORMAL)
        f_val = QFont(FONT_FAMILY, FS_MD, FW_SEMIBOLD)
        f_stage = QFont(FONT_FAMILY, FS_MD, FW_BOLD)

        def cell(text, font, bg, tip="", align=Qt.AlignLeft | Qt.AlignVCenter):
            it = QTableWidgetItem(text)
            it.setFont(font)
            it.setBackground(bg)
            it.setForeground(dark)
            it.setTextAlignment(align)
            if tip:
                it.setToolTip(tip)
            return it

        for r, (cat, label, value, _stage_color) in enumerate(self._rows):
            bg = self._tint(self._PILLAR_COLORS.get(cat, "#888888"))
            t.setItem(r, 1, cell(label, f_row, bg, tip=label))
            t.setItem(r, 2, cell(
                fmt_currency(value, self._currency, decimals=2), f_val, bg,
                tip=f"{fmt_currency(value, self._currency, decimals=4)} {self._currency}",
                align=Qt.AlignRight | Qt.AlignVCenter))
            bar = cell("", f_row, bg,
                       tip=f"{fmt_currency(value, self._currency, decimals=2)} {self._currency}")
            bar.setData(Qt.UserRole, value)
            bar.setData(Qt.UserRole + 1, self._PILLAR_COLORS.get(cat, "#888888"))
            t.setItem(r, 3, bar)

        for label, color, start, end in self._stage_blocks:
            t.setItem(start, 0, cell(label, f_stage, self._tint(color), tip=label,
                                     align=Qt.AlignCenter))
            if end > start:
                t.setSpan(start, 0, end - start + 1, 1)

        fit_to_contents(t)
        return t

    # ── export ────────────────────────────────────────────────────────────────

    def export_as_image(self, file_path: str | None = None, parent=None, format: str = "svg"):
        """Export the detailed table as an SVG vector (Option 4) or PNG/JPEG image."""
        return export_widget_as_image(
            self,
            title="Detailed Cost Breakdown",
            default_filename=file_path or "detailed_cost_breakdown.svg",
            parent=parent or self,
            format=format,
        )

    def copy_to_clipboard(self):
        return copy_widget_to_clipboard(self)

    def contextMenuEvent(self, event):
        menu = create_table_context_menu(self, title="Detailed Cost Breakdown", default_filename="detailed_cost_breakdown.svg")
        menu.exec(event.globalPos())

    @classmethod
    def in_scroll(cls, results: dict, currency: str = "INR",
                  stage_labels: dict | None = None,
                  row_labels: dict | None = None,
                  parent=None) -> QScrollArea:
        chart = cls(results, currency, stage_labels=stage_labels, row_labels=row_labels)
        scroll = QScrollArea(parent)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(chart)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Don't let the inner scroll area force the outer page wider
        scroll.setMinimumWidth(0)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return scroll


# ---------------------------------------------------------------------------
# Public widget
# ---------------------------------------------------------------------------

class _ScrollForwarder(QObject):
    """Forward wheel events from the canvas to the nearest parent QScrollArea."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            parent = obj.parent()
            while parent is not None:
                if isinstance(parent, QScrollArea):
                    QApplication.sendEvent(parent.verticalScrollBar(), event)
                    return True
                parent = parent.parent()
        return False


class LCCChartWidget(QWidget):
    """
    Interactive LCC bar chart widget.
    Includes a navigation toolbar (zoom / pan / save) and hover tooltips.
    """

    def __init__(self, results: dict, currency: str = "INR", parent=None):
        super().__init__(parent)
        self._currency = currency

        # Use theme colors for the graph
        text_color = get_token("text")
        bg_color   = get_token("window")

        self._values, self._labels, stage_info = build_chart_data(results)
        fig, self._bars = create_bar_chart(
            self._values, self._labels, stage_info, text_color, bg_color, currency=currency
        )

        self._canvas = FigureCanvasQTAgg(fig)
        self._canvas.setMinimumHeight(480)
        self._canvas.setMaximumHeight(600)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._scroll_forwarder = _ScrollForwarder(self)
        self._canvas.installEventFilter(self._scroll_forwarder)
        toolbar = _ChartToolbar(self._canvas, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self._canvas)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # ── Hover annotation ──────────────────────────────────────────────
        ax = fig.axes[0]
        self._annot = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(14, 14),
            textcoords="offset points",
            bbox=dict(
                boxstyle="round,pad=0.5",
                fc=bg_color,
                ec="#aaaaaa",
                alpha=0.95,
                linewidth=1,
            ),
            fontsize=FS_SM,
            fontfamily=FONT_FAMILY,
            color=text_color,
            zorder=10,
        )
        self._annot.set_visible(False)

        self._canvas.mpl_connect("motion_notify_event", self._on_hover)
        self._canvas.mpl_connect("axes_leave_event",    self._on_leave)

    def sizeHint(self):
        # toolbar ≈ 36px + canvas minimum 480px
        return QSize(super().sizeHint().width(), 520)

    # ── Hover handlers ────────────────────────────────────────────────────

    def _on_hover(self, event):
        if event.inaxes is None:
            self._set_annot_visible(False)
            return

        for bar, label, val in zip(self._bars, self._labels, self._values):
            if bar.contains(event)[0]:
                x = bar.get_x() + bar.get_width() / 2
                self._annot.xy = (x, val)
                inr_val = val * 1_000_000
                sign = "−" if val < 0 else ""
                self._annot.set_text(
                    f"{label}\n"
                    f"{self._currency} {sign}{fmt_currency(abs(inr_val), self._currency, decimals=0, style='both')}\n"
                    f"({sign}{fmt_currency(abs(val), self._currency, decimals=4)} Million {self._currency})"
                )
                self._set_annot_visible(True)
                return

        self._set_annot_visible(False)

    def _on_leave(self, event):
        self._set_annot_visible(False)

    def _set_annot_visible(self, visible: bool):
        if self._annot.get_visible() != visible:
            self._annot.set_visible(visible)
            self._canvas.draw_idle()


# Keep backward-compatible alias for any existing call sites
def create_lcc_figure(results: dict):
    palette = QApplication.instance().palette()
    text_color = palette.windowText().color().name()
    bg_color   = palette.window().color().name()
    values, labels, stage_info = build_chart_data(results)
    fig, _ = create_bar_chart(values, labels, stage_info, text_color, bg_color)
    return fig
