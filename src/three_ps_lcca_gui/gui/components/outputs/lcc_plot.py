"""
gui/components/outputs/lcc_plot.py

Results tables: LCCDetailsTable (stage x pillar summary) and
LCCBreakdownTable (itemized cost breakdown).
"""

from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.theme import (
    FONT_FAMILY,
    FS_MD, FW_NORMAL, FW_SEMIBOLD, FW_BOLD, SP2, ACCENT_W
)
from three_ps_lcca_gui.gui.components.utils.display_format import fmt_currency
from three_ps_lcca_gui.gui.components.utils.table_widgets import (
    WordWrapHeaderView, contrast_color, fit_to_contents, item_text_rect,
)
from .helper_functions.lcc_colors import COLORS as LCC_PALETTE
from .lcc_data import (
    STAGE_DEFS, stage_totals,
    BREAKDOWN_STAGES,
)

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication, QHeaderView, QLabel, QScrollArea, QFrame,
    QSizePolicy, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .table_export import (
    attach_table_context_menu,
    create_table_context_menu,
    export_widget_as_image,
    copy_widget_to_clipboard,
)

_STAGE_COLOR_ROLE = Qt.UserRole + 1  # hex of a stage cell's strip


class _StageLabelDelegate(QStyledItemDelegate):
    """Paints col-0 stage cells: stage-coloured strip on the left, centered text."""

    def paint(self, painter, option, index):
        bg = index.data(Qt.BackgroundRole)
        bg_color = bg.color() if hasattr(bg, 'color') else None
        painter.save()
        if bg_color and bg_color.isValid():
            painter.fillRect(option.rect, bg_color)
            painter.setPen(contrast_color(bg_color))
        else:
            painter.fillRect(option.rect, option.palette.base())
            painter.setPen(option.palette.text().color())
        stage = index.data(_STAGE_COLOR_ROLE)
        if stage:
            r = option.rect
            painter.fillRect(QRect(r.x(), r.y(), ACCENT_W, r.height()), QColor(stage))
        font = index.data(Qt.FontRole)
        if font:
            painter.setFont(font)
        text = index.data(Qt.DisplayRole) or ""
        painter.drawText(item_text_rect(self, option, index),
                         Qt.AlignCenter | Qt.TextWordWrap, str(text))
        painter.restore()


class _PillarHeaderView(WordWrapHeaderView):
    """Header that paints a pillar-coloured strip along the top of a section."""

    def __init__(self, colors: dict, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._colors = colors  # {logical column: hex}

    def paintSection(self, painter, rect, logical_index):
        painter.save()
        super().paintSection(painter, rect, logical_index)
        painter.restore()
        color = self._colors.get(logical_index)
        if color:
            painter.fillRect(QRect(rect.x(), rect.y(), rect.width(), ACCENT_W), QColor(color))


class LCCDetailsTable(QWidget):
    """Stage × pillar cost summary table."""

    def __init__(self, results: dict, currency: str = "INR", parent=None):
        super().__init__(parent)
        self._currency = currency

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.table = QTableWidget()
        self.table.setObjectName("consolidatedTable")  # main.qss
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
        self.table.setHorizontalHeader(_PillarHeaderView({
            1: LCC_PALETTE["eco_color"],
            2: LCC_PALETTE["env_color"],
            3: LCC_PALETTE["soc_color"],
        }, self.table))
        self.table.setHorizontalHeaderLabels(headers)
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
                item.setData(_STAGE_COLOR_ROLE, _stage_bg[key])
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
        t.setObjectName("itemizedTable")  # main.qss
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
