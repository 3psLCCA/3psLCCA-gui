"""
gui/components/outputs/comparison_page.py

Side-by-side LCCA project comparison — redesigned to match the
"Bridge Comparison — Life Cycle Cost" reference layout.

Sections (in scroll order):
  1. Header  – title + "Generate PDF Report" button
  2. Total Life Cycle Cost – one hero card per project with NPV total
  3. Across 3 Pillars of Sustainability – grouped bar chart (Eco / Env / Social)
  4. Across 3 Lifecycle Stages – grouped bar chart (Initial / Use / End-of-Life)
  5. Consolidated Comparison – flat table rows: pillars, stages, grand total
  6. Detailed Cost Item Breakdown – diverging-heatmap table

Flow:
  1. Page scans projects with fit_for_comparison=True via list_all_projects().
  2. User picks ≥2 projects, optionally sets a common analysis period.
  3. Workers re-run run_full_lcc_analysis from the cached all_data + lcc_breakdown.
  4. Results rendered in all sections above.

Reading the comparison_cache from disk without opening an engine instance keeps
other projects' locks untouched and avoids the overhead of a full engine attach.
"""

import os
import traceback
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.figure import Figure

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
except ImportError:
    from matplotlib.backends.backend_qt import FigureCanvasQTAgg

import matplotlib.colors as mcolors
from matplotlib import font_manager as _fm

from PySide6.QtCore import Qt, QSize, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPixmap, QPainter, QIcon
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QStyledItemDelegate, QApplication, QAbstractScrollArea,
    QStyleOptionHeader, QStyle,
)

from three_ps_lcca_gui.gui.themes import get_token, theme_manager
from three_ps_lcca_gui.gui.styles import font as _f, btn_primary, btn_ghost
from three_ps_lcca_gui.gui.theme import (
    SP1, SP2, SP3, SP4, SP5, SP6, SP8, SP10,
    RADIUS_SM, RADIUS_LG, RADIUS_MD,
    FS_SM, FS_SM, FS_MD, FS_DISP,
    FW_NORMAL, FW_MEDIUM, FW_SEMIBOLD, FW_BOLD,
    BTN_SM, BTN_MD, BTN_LG, FONT_FAMILY, FS_SECTION
)
from three_ps_lcca_gui.core.safechunk_engine import SafeChunkEngine, _decode, LCCA_EXT
import three_ps_lcca_gui.core.start_manager as _sm
from three_ps_lcca_core.core.main import run_full_lcc_analysis
from three_ps_lcca_gui.gui.components.utils.display_format import fmt_currency, fmt_short
from three_ps_lcca_gui.gui.components.sponsors_footer import SponsorsFooter
from .data_preparer import DataPreparer
from .helper_functions.lifecycle_summary import compute_all_summaries
from .helper_functions.lcc_colors import COLORS as LCC_PALETTE
from .lcc_data import _get, _MASTER_ROWS, BREAKDOWN_STAGES
from .lcc_plot import _VerticalTextDelegate, LCCBreakdownTable, LCCDetailsTable
from .plots_helper.plot_utils import ChartToolbar, WheelForwarder

# ── Register Ubuntu fonts for matplotlib ──────────────────────────────────────
_UBUNTU_FONT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "assets", "themes", "Ubuntu_font")
)
for _ttf in ["Ubuntu-Regular.ttf", "Ubuntu-Medium.ttf", "Ubuntu-Bold.ttf"]:
    _path = os.path.join(_UBUNTU_FONT_DIR, _ttf)
    if os.path.exists(_path):
        _fm.fontManager.addfont(_path)
matplotlib.rcParams["font.family"] = FONT_FAMILY

# ── Constants ─────────────────────────────────────────────────────────────────
CHUNK_COMPARISON = "comparison_cache"

_GUI_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ASSETS_DIR = os.path.join(_GUI_DIR, "assets")

# LOCKED stage definitions (must not be changed)
_STAGE_KEYS   = ["initial", "use", "end_of_life"]
_STAGE_LABELS = ["Initial", "Use", "End-of-Life"]
_STAGE_COLORS = [
    LCC_PALETTE.get("init_color", "#CCCCCC"),
    LCC_PALETTE.get("use_color",  "#00C49A"),
    LCC_PALETTE.get("end_color",  "#EA9E9E"),
]

# LOCKED pillar definitions (must not be changed)
_PILLAR_KEYS   = ["eco", "env", "social"]
_PILLAR_LABELS = ["Economic", "Environmental", "Social"]
_PILLAR_COLORS = [
    LCC_PALETTE.get("eco_color", "#9e9eff"),
    LCC_PALETTE.get("env_color", "#8ad400"),
    LCC_PALETTE.get("soc_color", "#ff5a2a"),
]

# Per-project distinct colors (cycles for unlimited projects)
_PROJECT_COLORS = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#CCB974", "#64B5CD", "#E377C2", "#7F7F7F", "#BCBD22",
]

# Hatch patterns to distinguish projects using the same stage/pillar colors
_PROJECT_HATCHES = [
    "",       # Solid fill
    "///",    # Diagonal hatch
    "...",    # Dotted
    "xxx",    # Cross hatch
    "\\\\\\", # Reverse diagonal
    "+++",    # Plus / grid hatch
    "ooo",    # Circles
    "---",    # Horizontal lines
    "|||",    # Vertical lines
    "***",    # Stars
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fmt_date(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str[:19])
    except (ValueError, TypeError):
        return dt_str[:10] if dt_str else ""
    now  = datetime.now()
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 60:       return "Just now"
    if secs < 3600:     return f"{secs // 60}m ago"
    if secs < 86400:    return f"{secs // 3600}h ago"
    if secs < 172800:   return "Yesterday"
    if secs < 604800:   return f"{secs // 86400} days ago"
    fmt = "%b %d" if dt.year == now.year else "%b %d, %Y"
    return dt.strftime(fmt)


def _read_cache_from_disk(base_dir: Path, project_id: str) -> dict:
    chunk_path = base_dir / project_id / "chunks" / f"{CHUNK_COMPARISON}{LCCA_EXT}"
    if not chunk_path.exists():
        return {}
    try:
        return _decode(chunk_path.read_bytes())
    except Exception:
        return {}


def _fmt_M(val: float, currency: str) -> str:
    """Format value as 'X.XXM' style for chart bar labels."""
    try:
        v = abs(float(val)) / 1_000_000
        return f"{v:.2f}M"
    except Exception:
        return ""


def _safe_float(v) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _fmt_million(val: float) -> str:
    """Format a value as 'X.XX million' matching the inspiration card style."""
    try:
        return f"{abs(float(val)) / 1_000_000:.2f} million"
    except Exception:
        return "—"


def _make_circle_icon(hex_color: str, size: int = 10) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(hex_color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pix)


# ──────────────────────────────────────────────────────────────────────────────
# Background worker – one per project
# ──────────────────────────────────────────────────────────────────────────────

class _ComparisonWorker(QThread):
    finished = Signal(str, object)   # (project_id, results_dict)
    errored  = Signal(str, str)      # (project_id, error_message)

    def __init__(self, project_id: str, all_data: dict,
                 lcc_breakdown: dict, analysis_period: int):
        super().__init__()
        self._project_id    = project_id
        self._all_data      = all_data
        self._lcc_breakdown = lcc_breakdown
        self._ap            = analysis_period
        self._cancel        = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            if self._cancel:
                return
            is_global, data_obj = DataPreparer.prepare_data_object(self._all_data, self._ap)
            if self._cancel:
                return
            wpi = None
            if not is_global:
                wpi = DataPreparer.prepare_wpi_object(self._all_data)
            if self._cancel:
                return
            results = run_full_lcc_analysis(
                data_obj, self._lcc_breakdown, wpi=wpi, debug=True
            )
            self.finished.emit(self._project_id, results)
        except Exception as exc:
            self.errored.emit(self._project_id, str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Shared divider
# ──────────────────────────────────────────────────────────────────────────────

def _make_divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {get_token('surface_mid')}; border: none;")
    return line


# ──────────────────────────────────────────────────────────────────────────────
# Section header (title + optional subtitle)
# ──────────────────────────────────────────────────────────────────────────────

def _section_header(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(SP2)

    t = QLabel(title)
    t.setFont(_f(FS_SECTION, FW_BOLD))
    t.setStyleSheet(f"color: {get_token('text')};")
    v.addWidget(t)

    if subtitle:
        s = QLabel(subtitle)
        s.setFont(_f(FS_SM, FW_NORMAL))
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {get_token('text_secondary')};")
        v.addWidget(s)
    return w



# ──────────────────────────────────────────────────────────────────────────────
# Section 1 – Hero KPI cards (Total Life Cycle Cost)
# ──────────────────────────────────────────────────────────────────────────────


class _HeroCardsSection(QWidget):
    """One hero card per project: filled color pill + project name, big value, currency sub-label.
    The lowest-cost project receives a green 'Lowest cost' badge alongside its pill.
    """

    def __init__(self, pids, names, summaries, caches, currency, parent=None):
        super().__init__(parent)
        self._build(pids, names, summaries, caches, currency)

    def _build(self, pids, names, summaries, caches, currency):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP4)

        root.addWidget(_section_header(
            "Total Life Cycle Cost",
            "Total life cycle cost across all three pillars for each project under comparison."
        ))

        # ── Compute totals ────────────────────────────────────────────────────
        totals: dict[str, float] = {}
        for pid in pids:
            sw = summaries[pid]["stagewise"]
            totals[pid] = sum(sw.values())

        best_pid = min(totals, key=totals.get) if len(pids) > 1 else None

        # ── Card row (one per project) ────────────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(SP4)
        cards_row.setContentsMargins(0, 0, 0, 0)

        for i, pid in enumerate(pids):
            name    = names[i]
            total   = totals[pid]
            is_best = (pid == best_pid)

            # Lowest-cost card: 2px success border; others: 1px surface_mid
            border_color = get_token("success") if is_best else get_token("surface_mid")
            border_width = "2px" if is_best else "1px"

            card = QFrame()
            card.setObjectName("heroCardMain")
            card.setStyleSheet(
                f"QFrame#heroCardMain {{ background: {get_token('base')}; "
                f"border: {border_width} solid {border_color}; "
                f"border-radius: {RADIUS_LG}px; }}"
            )
            card_v = QVBoxLayout(card)
            card_v.setContentsMargins(SP4, SP3, SP4, SP4)
            card_v.setSpacing(SP1)

            # Line 1 — project name, wraps if needed
            name_lbl = QLabel(name)
            name_lbl.setFont(_f(FS_SM, FW_SEMIBOLD))
            name_lbl.setStyleSheet(f"color: {get_token('text_secondary')}; background: transparent;")
            name_lbl.setWordWrap(True)
            card_v.addWidget(name_lbl)

            # Line 2 — big value
            val_lbl = QLabel(_fmt_million(total))
            val_lbl.setFont(_f(FS_DISP, FW_BOLD))
            val_lbl.setStyleSheet(f"color: {get_token('text')}; background: transparent;")
            card_v.addWidget(val_lbl)

            # Line 3 — currency
            cur_lbl = QLabel(currency)
            cur_lbl.setFont(_f(FS_SM, FW_NORMAL))
            cur_lbl.setStyleSheet(
                f"color: {get_token('text_secondary')}; background: transparent;"
            )
            card_v.addWidget(cur_lbl)

            cards_row.addWidget(card, 1)

        root.addLayout(cards_row)






# ──────────────────────────────────────────────────────────────────────────────
# Shared grouped bar chart widget
# ──────────────────────────────────────────────────────────────────────────────

class _GroupedBarChart(QWidget):
    """
    Interactive grouped bar chart with smart annotator, hover tooltips,
    active series highlight, and responsive toolbar.

    groups       – list of group labels (x-axis groups)
    group_data   – list of dicts: {name, color, values=[one per group]}
    title        – chart title
    ylabel       – y-axis label
    group_colors – optional list of hex colors, one per group (e.g. from LCC_PALETTE)
    currency     – project currency code for formatted tooltips and smart callouts
    """

    def __init__(self, groups, group_data, title, ylabel, group_colors=None, currency="", parent=None):
        super().__init__(parent)
        self._groups        = groups
        self._group_data    = group_data
        self._title         = title
        self._ylabel        = ylabel
        self._group_colors  = group_colors
        self._currency      = currency
        self._fig           = None
        self.canvas         = None
        self._all_bar_items = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP2)
        self._build()
        theme_manager().theme_changed.connect(self._rebuild)

    def _rebuild(self):
        if self._fig:
            self._fig.clear()
            self._fig = None
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._build()

    def _build(self):
        text_color = get_token("text")
        text_sec   = get_token("text_secondary")
        bg_color   = get_token("base")    # match card container, not page background
        mid_color  = get_token("surface_mid")
        primary_c  = get_token("primary")

        n_groups   = len(self._groups)
        n_series   = len(self._group_data)
        bar_w      = 0.70 / max(1, n_series)
        x          = np.arange(n_groups)

        fig_w = max(6.0, n_groups * max(2.2, n_series * 0.75))
        fig = Figure(figsize=(fig_w, 4.4))
        fig.patch.set_facecolor(bg_color)
        ax = fig.add_subplot(111)
        ax.set_facecolor(bg_color)
        self._fig = fig
        self.ax = ax

        self._all_bar_items = []
        legend_patches = []
        border_color = get_token("text")

        # Pre-compute totals per project
        proj_totals = [sum(_safe_float(v) for v in s["values"]) for s in self._group_data]

        # Pre-compute group minimums (lowest positive value in each group)
        group_mins = []
        for g in range(n_groups):
            g_vals = [_safe_float(s["values"][g]) for s in self._group_data]
            pos_vals = [v for v in g_vals if v > 0]
            group_mins.append(min(pos_vals) if pos_vals else 0.0)

        all_scaled_vals = []

        for i, series in enumerate(self._group_data):
            raw_vals    = np.array([_safe_float(v) for v in series["values"]])
            scaled_vals = raw_vals / 1_000_000.0
            all_scaled_vals.extend(scaled_vals)
            offset = (i - (n_series - 1) / 2) * bar_w
            hatch  = _PROJECT_HATCHES[i % len(_PROJECT_HATCHES)]

            if self._group_colors and len(self._group_colors) == n_groups:
                bar_colors = [self._group_colors[g] for g in range(n_groups)]
                swatch_bg  = get_token("surface")
            else:
                color = series.get("color", _PROJECT_COLORS[i % len(_PROJECT_COLORS)])
                bar_colors = color
                swatch_bg  = color

            bars = ax.bar(x + offset, scaled_vals, bar_w, color=bar_colors,
                          edgecolor=border_color, hatch=hatch, linewidth=0.8, zorder=3)

            for g, (bar, raw_v, s_val) in enumerate(zip(bars, raw_vals, scaled_vals)):
                self._all_bar_items.append({
                    "patch": bar,
                    "series_idx": i,
                    "group_idx": g,
                    "project_name": series["name"],
                    "group_name": self._groups[g],
                    "raw_val": raw_v,
                    "scaled_val": s_val,
                    "proj_total": proj_totals[i],
                    "is_lowest": (len(self._group_data) > 1 and group_mins[g] > 0 and abs(raw_v - group_mins[g]) < 1e-3),
                    "min_val": group_mins[g],
                    "edgecolor": border_color,
                    "hatch": hatch,
                })

            legend_patches.append(
                mpatches.Patch(
                    facecolor=swatch_bg,
                    edgecolor=border_color,
                    hatch=hatch,
                    linewidth=0.8,
                    label=series["name"],
                )
            )

        # Smart Bar-Top Labels & Y-Axis Headroom
        max_v = max(all_scaled_vals) if all_scaled_vals else 1.0
        min_v = min(all_scaled_vals) if all_scaled_vals else 0.0
        total_span = max(max_v - min_v, 1.0)
        pad = total_span * 0.18

        for item in self._all_bar_items:
            bar = item["patch"]
            val = item["scaled_val"]
            bx  = bar.get_x() + bar.get_width() / 2.0
            val_str = f"{val:.2f}M"

            if val >= total_span * 0.08:
                ax.text(
                    bx, val + pad * 0.03,
                    val_str,
                    ha="center", va="bottom",
                    fontsize=FS_SM, fontweight="bold",
                    color=text_color, fontfamily=FONT_FAMILY,
                    zorder=4,
                )
            elif val > 0:
                ax.annotate(
                    val_str,
                    xy=(bx, val),
                    xytext=(bx, val + pad * 0.25),
                    ha="center", va="bottom",
                    fontsize=FS_SM, fontweight="bold", color=text_color,
                    bbox=dict(boxstyle="round,pad=0.2,rounding_size=0.2",
                              fc=bg_color, ec=mid_color, lw=0.6, alpha=0.9),
                    arrowprops=dict(arrowstyle="-", color=mid_color, lw=0.6),
                    clip_on=False, zorder=5,
                )
            elif val < 0:
                ax.text(
                    bx, val - pad * 0.04,
                    val_str,
                    ha="center", va="top",
                    fontsize=FS_SM, fontweight="bold",
                    color=text_color, fontfamily=FONT_FAMILY,
                    zorder=4,
                )

        ax.set_xticks(x)
        ax.set_xticklabels(self._groups, color=text_color,
                           fontsize=FS_SM, fontweight="bold", fontfamily=FONT_FAMILY)
        ax.set_ylabel(self._ylabel, color=text_color, fontsize=FS_SM, fontfamily=FONT_FAMILY)
        ax.tick_params(colors=text_color, labelsize=FS_SM)

        y_bottom = min(0.0, min_v) - (pad * 0.2 if min_v < 0 else 0)
        y_top    = max(0.0, max_v) + pad
        ax.set_ylim(y_bottom, y_top)

        for spine in ax.spines.values():
            spine.set_color(mid_color)
        ax.yaxis.grid(True, color=mid_color, linewidth=0.5, alpha=0.5)
        ax.set_axisbelow(True)

        if min_v < 0:
            ax.axhline(0, color=mid_color, linewidth=0.8, linestyle="--", zorder=2)

        # Legend
        self._legend = ax.legend(
            handles=legend_patches, fontsize=FS_SM, facecolor=bg_color,
            labelcolor=text_color, framealpha=0.0,
            edgecolor="none", loc="upper center",
            bbox_to_anchor=(0.5, -0.12), ncol=max(1, min(n_series, 4))
        )

        # Smart Hover Annotation (Floating Tooltip)
        self.annot = ax.annotate(
            "", xy=(0, 0), xytext=(20, 20), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.6,rounding_size=0.3",
                      fc=bg_color, ec=primary_c, lw=1.2, alpha=0.96),
            arrowprops=dict(arrowstyle="->", color=primary_c, lw=1.2, connectionstyle="arc3,rad=0.05"),
            zorder=20, color=text_color, fontsize=FS_SM, fontfamily=FONT_FAMILY,
        )
        self.annot.set_visible(False)

        fig.tight_layout(pad=1.5)

        # Canvas with WheelForwarder
        self.canvas = FigureCanvasQTAgg(fig)
        self.canvas.setMinimumHeight(320)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.canvas.installEventFilter(WheelForwarder(self))

        # Event connections
        fig.canvas.mpl_connect("motion_notify_event", self._hover)
        fig.canvas.mpl_connect("figure_leave_event", lambda event: self._reset_highlight())

        # Footer Frame with hint and toolbar
        footer = QFrame()
        footer.setStyleSheet(
            f"border: none; border-top: 1px solid {mid_color}; background: transparent; padding-top: 2px;"
        )
        footer_l = QHBoxLayout(footer)
        footer_l.setContentsMargins(0, 4, 0, 0)
        footer_l.setSpacing(SP2)

        footer_hint = QLabel("Hover on bars to inspect breakdown")
        footer_hint.setFont(_f(FS_SM))
        footer_hint.setStyleSheet(f"color: {text_sec}; border: none; background: transparent;")
        footer_l.addWidget(footer_hint)
        footer_l.addStretch()

        toolbar = ChartToolbar(self.canvas, self)
        footer_l.addWidget(toolbar)

        self.layout().addWidget(self.canvas)
        self.layout().addWidget(footer)

    def _hover(self, event):
        if not hasattr(self, "annot") or not hasattr(self, "_all_bar_items"):
            return

        if event.inaxes != self.ax:
            self._reset_highlight()
            return

        hit_item = None
        for item in self._all_bar_items:
            patch = item["patch"]
            if patch.contains(event)[0]:
                hit_item = item
                break

        if hit_item:
            hit_series = hit_item["series_idx"]
            primary_c = get_token("primary")

            for item in self._all_bar_items:
                p = item["patch"]
                if item is hit_item:
                    p.set_alpha(1.0)
                    p.set_linewidth(2.0)
                    p.set_edgecolor(primary_c)
                elif item["series_idx"] == hit_series:
                    p.set_alpha(0.85)
                    p.set_linewidth(0.8)
                    p.set_edgecolor(item["edgecolor"])
                else:
                    p.set_alpha(0.25)
                    p.set_linewidth(0.8)
                    p.set_edgecolor(item["edgecolor"])

            self._set_legend_alpha(hit_series)

            # Build smart annotation text
            val_m     = hit_item["scaled_val"]
            raw_val   = hit_item["raw_val"]
            proj_tot  = hit_item["proj_total"]
            pct_str   = f" ({raw_val / proj_tot * 100:.1f}%)" if proj_tot > 0 else ""

            curr = self._currency
            curr_tag = f" {curr}" if curr else ""
            fmt_exact = fmt_currency(raw_val, curr, decimals=2, style="comma") if curr else f"{raw_val:,.2f}"

            lines = [
                f"{hit_item['project_name']}",
                f"{hit_item['group_name']}: {val_m:.2f}M{curr_tag}{pct_str}",
                f"Exact: {fmt_exact}",
            ]

            if hit_item["is_lowest"]:
                lines.append("Lowest cost in this category")
            elif len(self._group_data) > 1 and hit_item["min_val"] > 0:
                min_m = hit_item["min_val"] / 1_000_000.0
                delta_pct = ((raw_val - hit_item["min_val"]) / hit_item["min_val"]) * 100
                lines.append(f"+{delta_pct:.1f}% vs lowest ({min_m:.2f}M)")

            self.annot.set_text("\n".join(lines))

            # Smart tooltip placement
            patch = hit_item["patch"]
            bx = patch.get_x() + patch.get_width() / 2.0
            by = patch.get_height()
            self.annot.xy = (bx, by)

            x_min, x_max = self.ax.get_xlim()
            y_min, y_max = self.ax.get_ylim()

            dx = -160 if bx > (x_min + x_max) * 0.6 else 20
            dy = -70 if by > (y_min + y_max) * 0.75 else 20
            self.annot.set_position((dx, dy))

            self.annot.set_visible(True)
        else:
            self._reset_highlight()

        if hasattr(self, "canvas") and self.canvas:
            self.canvas.draw_idle()

    def _reset_highlight(self):
        if not hasattr(self, "_all_bar_items"):
            return
        changed = False
        if hasattr(self, "annot") and self.annot.get_visible():
            self.annot.set_visible(False)
            changed = True

        for item in self._all_bar_items:
            p = item["patch"]
            if p.get_alpha() != 1.0 or p.get_linewidth() != 0.8:
                p.set_alpha(1.0)
                p.set_linewidth(0.8)
                p.set_edgecolor(item["edgecolor"])
                changed = True

        self._set_legend_alpha(-1)
        if changed and hasattr(self, "canvas") and self.canvas:
            self.canvas.draw_idle()

    def _set_legend_alpha(self, hit_series_idx: int):
        if not hasattr(self, "_legend") or not self._legend:
            return
        handles = getattr(self._legend, "legend_handles", getattr(self._legend, "legendHandles", []))
        texts = self._legend.get_texts()
        for i, (handle, text) in enumerate(zip(handles, texts)):
            a = 1.0 if (hit_series_idx == -1 or i == hit_series_idx) else 0.25
            handle.set_alpha(a)
            text.set_alpha(a)


def _make_chart_card(title: str, subtitle: str, chart_widget: QWidget) -> QWidget:
    """Wrap a chart in a light rounded card with a title and subtitle."""
    card = QFrame()
    card.setObjectName("chartCard")
    card.setStyleSheet(
        f"#chartCard {{ background: {get_token('base')}; "
        f"border: 1px solid {get_token('surface_mid')}; "
        f"border-radius: {RADIUS_LG}px; }}"
    )
    cv = QVBoxLayout(card)
    cv.setContentsMargins(SP4, SP3, SP4, SP4)
    cv.setSpacing(SP2)

    t = QLabel(title)
    t.setFont(_f(FS_MD, FW_SEMIBOLD))
    t.setStyleSheet(f"color: {get_token('text')};")
    cv.addWidget(t)

    if subtitle:
        s = QLabel(subtitle)
        s.setFont(_f(FS_SM, FW_NORMAL))
        s.setStyleSheet(f"color: {get_token('text_secondary')};")
        cv.addWidget(s)

    cv.addWidget(chart_widget)
    return card


# ──────────────────────────────────────────────────────────────────────────────
# Section 2 – Pillar grouped bar chart
# ──────────────────────────────────────────────────────────────────────────────

class _PillarChartSection(QWidget):
    def __init__(self, pids, names, summaries, currency, parent=None):
        super().__init__(parent)
        self._build(pids, names, summaries, currency)

    def _build(self, pids, names, summaries, currency):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP3)

        root.addWidget(_section_header(
            "Across 3 Pillars of Sustainability",
            "Compares Economic, Environmental, and Social cost contribution across projects, "
            "so the pillar driving the highest burden for each option is easy to spot."
        ))

        # Build series: one series per project (bars within each pillar group)
        group_data = []
        for i, (pid, name) in enumerate(zip(pids, names)):
            pt = summaries[pid]["pillar_totals"]
            group_data.append({
                "name":   name,
                "values": [pt.get("eco", 0), pt.get("env", 0), pt.get("social", 0)],
            })

        chart = _GroupedBarChart(
            groups=_PILLAR_LABELS,
            group_data=group_data,
            title="Pillar cost comparison",
            ylabel=f"Cost  (Million {currency})",
            group_colors=_PILLAR_COLORS,
            currency=currency,
        )

        card = _make_chart_card(
            "Pillar cost comparison",
            f"All values in {currency} (millions)",
            chart,
        )
        root.addWidget(card)


# ──────────────────────────────────────────────────────────────────────────────
# Section 3 – Stage grouped bar chart
# ──────────────────────────────────────────────────────────────────────────────

class _StageChartSection(QWidget):
    def __init__(self, pids, names, summaries, currency, parent=None):
        super().__init__(parent)
        self._build(pids, names, summaries, currency)

    def _build(self, pids, names, summaries, currency):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP3)

        root.addWidget(_section_header(
            "Across 3 Lifecycle Stages",
            "Compares Initial, Use, and End-of-Life cost across projects to identify "
            "which phase carries the most weight for each option."
        ))

        group_data = []
        for i, (pid, name) in enumerate(zip(pids, names)):
            sw = summaries[pid]["stagewise"]
            group_data.append({
                "name":   name,
                "values": [sw.get("initial", 0), sw.get("use", 0), sw.get("end_of_life", 0)],
            })

        chart = _GroupedBarChart(
            groups=_STAGE_LABELS,
            group_data=group_data,
            title="Stage cost comparison",
            ylabel=f"Cost  (Million {currency})",
            group_colors=_STAGE_COLORS,
            currency=currency,
        )

        card = _make_chart_card(
            "Stage cost comparison",
            f"All values in {currency} (millions)",
            chart,
        )
        root.addWidget(card)


# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# Shared Word-Wrap Horizontal Header
# ──────────────────────────────────────────────────────────────────────────────
from three_ps_lcca_gui.gui.components.utils.table_widgets import WordWrapHeaderView
_WordWrapHeaderView = WordWrapHeaderView




# ──────────────────────────────────────────────────────────────────────────────
# Section 4 – Consolidated comparison table
# ──────────────────────────────────────────────────────────────────────────────

class _ConsolidatedTable(QWidget):
    """
    Flat table: rows = pillars + stages + grand total.
    Best (lowest) value per row highlighted in green.
    Non-best values show a '+X%' delta label.
    """

    def __init__(self, pids, names, summaries, caches, currency, parent=None):
        super().__init__(parent)
        self._build(pids, names, summaries, caches, currency)

    def _build(self, pids, names, summaries, caches, currency):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP3)

        root.addWidget(_section_header(
            "Consolidated Comparison",
            "A single view of every pillar and stage across projects. "
            "The lowest value in each row is highlighted, so the best-performing "
            "option per metric is immediate."
        ))

        # ── Build row definitions ─────────────────────────────────────────────
        def _ptotal(pid):
            sw = summaries[pid]["stagewise"]
            return sum(sw.values())

        pillar_rows = [
            ("Pillars", None, None),
            ("Economic",       lambda p: summaries[p]["pillar_totals"]["eco"],      True,  "eco_color"),
            ("Environmental",  lambda p: summaries[p]["pillar_totals"]["env"],      True,  "env_color"),
            ("Social",         lambda p: summaries[p]["pillar_totals"]["social"],   True,  "soc_color"),
        ]
        stage_rows = [
            ("Stages", None, None),
            ("Initial",        lambda p: summaries[p]["stagewise"]["initial"],      True,  "init_color"),
            ("Use",            lambda p: summaries[p]["stagewise"]["use"],          True,  "use_color"),
            ("End-of-Life",    lambda p: summaries[p]["stagewise"]["end_of_life"],  True,  "end_color"),
        ]
        total_row = [
            ("Total Life Cycle Cost", _ptotal, True, None),
        ]
        all_rows = pillar_rows + stage_rows + total_row

        n_cols = len(pids)
        n_rows = len(all_rows)

        table = QTableWidget(n_rows, n_cols + 1)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(True)
        table.setAlternatingRowColors(False)
        table.setWordWrap(True)
        table.setFont(_f(FS_MD, FW_NORMAL))
        table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setStyleSheet(
            f"""
            QTableWidget {{
                background: {get_token('base')};
                border: 1px solid {get_token('surface_mid')};
                border-radius: {RADIUS_LG}px;
                gridline-color: {get_token('surface_mid')};
            }}
            QHeaderView::section {{
                background: {get_token('surface_mid')};
                color: {get_token('text')};
                font-size: {FS_SM}pt;
                font-weight: {FW_SEMIBOLD};
                padding: {SP2}px {SP3}px;
                border: none;
                border-bottom: 1px solid {get_token('surface_mid')};
            }}
            """
        )

        # Headers
        table.setHorizontalHeader(WordWrapHeaderView(Qt.Horizontal, parent=table))
        table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        table.horizontalHeader().setFont(_f(FS_SM, FW_SEMIBOLD))
        table.horizontalHeader().setMinimumSectionSize(90)
        table.setHorizontalHeaderItem(0, QTableWidgetItem("Metric"))
        for ci, name in enumerate(names):
            table.setHorizontalHeaderItem(ci + 1, QTableWidgetItem(name))

        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for ci in range(1, n_cols + 1):
            table.horizontalHeader().setSectionResizeMode(ci, QHeaderView.Stretch)

        # Fill rows
        for row_idx, row_def in enumerate(all_rows):
            label = row_def[0]
            fn    = row_def[1]
            is_cost = row_def[2] if len(row_def) > 2 else False
            color_key = row_def[3] if len(row_def) > 3 else None

            is_group_header = (fn is None)
            is_total = (label == "Total Life Cycle Cost")

            # Row background
            if is_group_header:
                row_bg = get_token("surface_mid")
            elif is_total:
                row_bg = get_token("surface_mid")
            elif row_idx % 2 == 0:
                row_bg = "transparent"
            else:
                row_bg = get_token("surface")

            # Metric cell
            metric_item = QTableWidgetItem(label)
            metric_item.setFont(_f(FS_MD, FW_BOLD if is_total else (FW_BOLD if is_group_header else FW_NORMAL)))
            metric_item.setForeground(QColor(get_token("text") if (is_group_header or is_total) else get_token("text")))
            metric_item.setBackground(QColor(row_bg if row_bg != "transparent" else get_token("base")))

            # Pillar dot prefix
            if color_key and not is_group_header:
                dot_color = LCC_PALETTE.get(color_key, "#888888")
                metric_item.setText(f"  {label}")
                metric_item.setIcon(_make_circle_icon(dot_color, 8))

            table.setItem(row_idx, 0, metric_item)

            if is_group_header:
                table.setSpan(row_idx, 0, 1, n_cols + 1)
                for ci in range(n_cols):
                    blank = QTableWidgetItem("")
                    blank.setBackground(QColor(row_bg))
                    table.setItem(row_idx, ci + 1, blank)
                continue

            # Compute values
            values = {}
            for pid in pids:
                try:
                    values[pid] = float(fn(pid))
                except Exception:
                    values[pid] = 0.0

            best_pid = None
            if is_cost and len(pids) > 1:
                numeric = {p: v for p, v in values.items() if isinstance(v, float)}
                if numeric:
                    best_pid = min(numeric, key=numeric.get)

            for ci, pid in enumerate(pids):
                val      = values[pid]
                is_best  = (pid == best_pid)
                best_val = values.get(best_pid, 0.0) if best_pid else 0.0

                # Use standard comma currency formatter with 2 decimals
                cell_text = fmt_currency(val, currency, decimals=2, style="comma")

                if is_cost and best_pid and pid != best_pid and best_val > 0:
                    delta = ((val - best_val) / best_val) * 100
                    sign  = "+" if delta >= 0 else ""
                    cell_text = f"{cell_text}  ({sign}{delta:.0f}%)"

                item = QTableWidgetItem(cell_text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setFont(_f(FS_MD, FW_BOLD if is_total else FW_NORMAL))

                if is_best and is_cost:
                    item.setForeground(QColor(get_token("success")))
                    _sc = QColor(get_token("success"))
                    _sc.setAlpha(38)   # ≈ 15 % opacity — visible tint without overpowering
                    item.setBackground(_sc)
                else:
                    item.setForeground(QColor(get_token("text")))
                    item.setBackground(QColor(row_bg if row_bg != "transparent" else get_token("base")))

                table.setItem(row_idx, ci + 1, item)

        root.addWidget(table)


# ──────────────────────────────────────────────────────────────────────────────
# Section 5 – Detailed Cost Item Breakdown (diverging heatmap)
# ──────────────────────────────────────────────────────────────────────────────

# Row definitions for detailed breakdown, grouped by stage
_DETAIL_ROWS = [
    # (stage_result_key, category, result_key, display_label, is_credit)
]
for _sk, _cat, _key, _lbl in _MASTER_ROWS:
    _DETAIL_ROWS.append((_sk, _cat, _key, _lbl, _key == "total_scrap_value"))

# Stage grouping for display headers (reconstruction is folded into End-of-Life, matching outputs_page)
_DETAIL_STAGE_GROUPS = [
    ("initial_stage", "Initial Stage Costs", LCC_PALETTE.get("init_color", "#CCCCCC")),
    ("use_stage",     "Use Stage Costs",     LCC_PALETTE.get("use_color",  "#00C49A")),
    ("end_of_life",   "End-of-Life Stage",   LCC_PALETTE.get("end_color",  "#EA9E9E")),
]


def _lerp_color(c1: tuple, c2: tuple, t: float) -> QColor:
    """Linear interpolation between two (r,g,b) tuples."""
    t = max(0.0, min(1.0, t))
    r = int(c1[0] + (c2[0] - c1[0]) * t)
    g = int(c1[1] + (c2[1] - c1[1]) * t)
    b = int(c1[2] + (c2[2] - c1[2]) * t)
    return QColor(r, g, b)


def _contrast(bg: QColor) -> QColor:
    """Return black or white depending on background luminance."""
    lum = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return QColor(30, 30, 30) if lum > 140 else QColor(240, 240, 240)


# Option 1 Multi-Hue Scale: Green (Profit) ◄— White (0) —► Gold ➔ Orange ➔ Red ➔ Deep Purple (Peak)
_SCALE_GREEN = (0x1b, 0x78, 0x37)   # rich green (#1b7837) — profit / savings / credit

_WARM_COST_STOPS = [
    (0.00, (255, 255, 255)),  # White (0 cost)
    (0.25, (246, 194, 62)),   # #f6c23e Warm Gold (Low cost)
    (0.50, (230, 126, 34)),   # #e67e22 Vibrant Orange (Moderate cost)
    (0.75, (192, 57, 43)),    # #c0392b Crimson Red (High cost)
    (1.00, (91, 20, 111)),    # #5b146f Deep Purple (Peak cost)
]


def _warm_cost_color(t: float) -> QColor:
    """Interpolate along the warm cost progression for t in [0.0, 1.0]."""
    t = max(0.0, min(1.0, float(t)))
    for i in range(len(_WARM_COST_STOPS) - 1):
        t0, c0 = _WARM_COST_STOPS[i]
        t1, c1 = _WARM_COST_STOPS[i + 1]
        if t0 <= t <= t1:
            local_t = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return _lerp_color(c0, c1, local_t)
    return QColor(*_WARM_COST_STOPS[-1][1])


class _HeatmapDelegate(QStyledItemDelegate):
    """
    Multi-Hue Warm diverging scale:
      Green                                   (negative) → profit / savings / credit
      White                                   (zero)     → neutral base / zero cost
      Gold ➔ Orange ➔ Crimson ➔ Deep Purple   (positive) → multi-hue cost brackets
    Text foreground automatically adapts contrast across all hues.
    """

    def __init__(self, col_pos_max: dict | float, col_neg_max: dict | float = None, parent=None):
        super().__init__(parent)
        self._col_pos_max = col_pos_max
        self._col_neg_max = col_neg_max if col_neg_max is not None else col_pos_max

    def _get_max(self, m, col_idx):
        if isinstance(m, dict):
            return m.get(col_idx, 0.0) or 1.0
        return float(m) if (m is not None and float(m) > 0) else 1.0

    def paint(self, painter, option, index):
        val = index.data(Qt.UserRole)
        col_idx = index.column()
        white_rgb = (255, 255, 255)
        white_color = QColor(255, 255, 255)

        if isinstance(val, (int, float)):
            if val < -0.001:
                # Profit / savings / credit (green)
                neg_m = self._get_max(self._col_neg_max, col_idx)
                intensity = min((abs(val) / neg_m) ** 0.5, 1.0)
                bg = _lerp_color(white_rgb, _SCALE_GREEN, intensity)
            elif val > 0.001:
                # Progressive cost: White ➔ Gold ➔ Orange ➔ Red ➔ Purple
                pos_m = self._get_max(self._col_pos_max, col_idx)
                intensity = min((val / pos_m) ** 0.5, 1.0)
                bg = _warm_cost_color(intensity)
            else:
                bg = white_color

        if bg is None:
            bg_data = index.data(Qt.BackgroundRole)
            bg = bg_data.color() if (bg_data and hasattr(bg_data, "color")) else bg_base

        painter.save()
        painter.fillRect(option.rect, bg)

        txt = str(index.data(Qt.DisplayRole) or "")
        fg  = _contrast(bg)
        painter.setPen(fg)
        fnt = index.data(Qt.FontRole)
        if fnt:
            painter.setFont(fnt)
        painter.drawText(
            option.rect.adjusted(SP2, 0, -SP2, 0),
            Qt.AlignRight | Qt.AlignVCenter,
            txt,
        )
        painter.restore()


class _ItemTickDelegate(QStyledItemDelegate):
    """Draws a vertical colored tick on the left edge of each cost item indicating its pillar."""

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QSize(base.width() + 18, max(28, base.height() + 4))

    def paint(self, painter, option, index):
        painter.save()
        bg = index.data(Qt.BackgroundRole)
        if bg:
            c = bg.color() if hasattr(bg, "color") else QColor(bg)
            painter.fillRect(option.rect, c)
        else:
            painter.fillRect(option.rect, QColor(get_token("base")))

        tick_color_hex = index.data(Qt.UserRole + 1)
        if tick_color_hex:
            painter.fillRect(
                option.rect.left() + 4,
                option.rect.top() + 4,
                4,
                option.rect.height() - 8,
                QColor(tick_color_hex),
            )

        txt = str(index.data(Qt.DisplayRole) or "")
        fnt = index.data(Qt.FontRole)
        fg  = index.data(Qt.ForegroundRole)
        c_fg = fg.color() if (fg and hasattr(fg, "color")) else QColor(get_token("text"))
        if fnt:
            painter.setFont(fnt)
        painter.setPen(c_fg)
        text_rect = option.rect.adjusted(14, 2, -4, -2) if tick_color_hex else option.rect.adjusted(8, 2, -4, -2)
        painter.drawText(text_rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, txt)
        painter.restore()


class _DetailedBreakdownSection(QWidget):
    """
    Detailed cost item breakdown table reusing the LCCBreakdownTable structure:
    - Top pillar legend (Economic, Environmental, Social)
    - Col 0: Stage column with vertical text and stage color background (_VerticalTextDelegate)
    - Col 1: Cost Item with pillar color tick indicator
    - Cols 2+: Comparison projects using diverging heat map instead of bars
    """

    def __init__(self, pids, names, results, currency, parent=None):
        super().__init__(parent)
        self._build(pids, names, results, currency)

    def _build(self, pids, names, results, currency):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP3)

        root.addWidget(_section_header(
            "Detailed Cost Item Breakdown",
            "Itemized breakdown across lifecycle stages. Values are rendered with a diverging "
            "heat map — green indicates credits/savings, while gold to purple indicates increasing costs."
        ))

        # ── Pillar legend (reused from LCCBreakdownTable) ─────────────────────
        leg_row = QHBoxLayout()
        leg_row.setSpacing(SP4)
        for pillar, hex_color in [
            ("Economic",      LCC_PALETTE.get("eco_color", "#9e9eff")),
            ("Environmental", LCC_PALETTE.get("env_color", "#8ad400")),
            ("Social",        LCC_PALETTE.get("soc_color", "#ff5a2a")),
        ]:
            item_box = QWidget()
            ib_l = QHBoxLayout(item_box)
            ib_l.setContentsMargins(0, 0, 0, 0)
            ib_l.setSpacing(SP1)
            sw = QFrame()
            sw.setFixedSize(14, 14)
            sw.setStyleSheet(f"background: {hex_color}; border-radius: 2px;")
            lbl = QLabel(pillar)
            lbl.setFont(_f(FS_SM, FW_MEDIUM))
            lbl.setStyleSheet(f"color: {get_token('text')};")
            ib_l.addWidget(sw)
            ib_l.addWidget(lbl)
            leg_row.addWidget(item_box)
        leg_row.addStretch()
        root.addLayout(leg_row)

        # ── Group items by stage ──────────────────────────────────────────────
        stage_groups = []  # list of (stage_label, stage_color, items)
        for sk, stage_label, stage_color in _DETAIL_STAGE_GROUPS:
            stage_items = []

            # Reconstruction is folded into End-of-Life Stage (matching outputs_page & LCCBreakdownTable)
            if sk == "end_of_life":
                recon_rows = [(cat, key, f"Reconstruction | {lbl}", is_credit)
                              for s, cat, key, lbl, is_credit in _DETAIL_ROWS
                              if s == "reconstruction"]
                for cat, key, lbl, is_credit in recon_rows:
                    pid_vals = {}
                    for pid in pids:
                        raw = _get(results.get(pid, {}), "reconstruction", cat, key)
                        pid_vals[pid] = -_safe_float(raw) if is_credit else _safe_float(raw)
                    if all(abs(v) < 0.01 for v in pid_vals.values()):
                        continue
                    stage_items.append((lbl, pid_vals, is_credit, cat))

            items_for_stage = [(cat, key, lbl, is_credit)
                               for s, cat, key, lbl, is_credit in _DETAIL_ROWS
                               if s == sk]
            for cat, key, lbl, is_credit in items_for_stage:
                pid_vals = {}
                for pid in pids:
                    raw = _get(results.get(pid, {}), sk, cat, key)
                    pid_vals[pid] = -_safe_float(raw) if is_credit else _safe_float(raw)
                if all(abs(v) < 0.01 for v in pid_vals.values()):
                    continue
                stage_items.append((lbl, pid_vals, is_credit, cat))

            if stage_items:
                stage_groups.append((stage_label, stage_color, stage_items))

        if not stage_groups:
            root.addWidget(QLabel("No detailed breakdown available."))
            return

        total_rows = sum(len(items) for _, _, items in stage_groups)
        n_cols     = len(pids)

        table = QTableWidget(total_rows, n_cols + 2)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setStyleSheet(
            f"""
            QTableWidget {{
                background: {get_token('base')};
                border: 1px solid {get_token('surface_mid')};
                border-radius: {RADIUS_LG}px;
            }}
            QTableWidget::item:selected {{
                background: transparent;
            }}
            QHeaderView::section {{
                background: {get_token('surface_mid')};
                color: {get_token('text')};
                font-size: {FS_SM}pt;
                font-weight: {FW_SEMIBOLD};
                padding: {SP2}px {SP3}px;
                border: none;
                border-bottom: 1px solid {get_token('surface_mid')};
            }}
            """
        )

        table.setWordWrap(True)
        table.setShowGrid(True)
        table.setFont(_f(FS_MD, FW_NORMAL))
        table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Headers
        table.setHorizontalHeader(WordWrapHeaderView(Qt.Horizontal, parent=table))
        table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        table.horizontalHeader().setFont(_f(FS_SM, FW_SEMIBOLD))
        table.horizontalHeader().setMinimumSectionSize(90)
        table.setHorizontalHeaderItem(0, QTableWidgetItem("Stage"))
        table.setHorizontalHeaderItem(1, QTableWidgetItem("Cost Item"))
        for ci, name in enumerate(names):
            table.setHorizontalHeaderItem(ci + 2, QTableWidgetItem(name))

        table.horizontalHeader().setVisible(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for ci in range(n_cols):
            table.horizontalHeader().setSectionResizeMode(ci + 2, QHeaderView.Stretch)

        # Compute per-column positive max and negative max (for heatmap normalization)
        col_pos_max: dict[int, float] = {}
        col_neg_max: dict[int, float] = {}
        for _, _, stage_items in stage_groups:
            for lbl, pid_vals, _, _ in stage_items:
                for ci, pid in enumerate(pids):
                    v = pid_vals.get(pid, 0.0)
                    col_idx = ci + 2
                    if v > 0:
                        col_pos_max[col_idx] = max(col_pos_max.get(col_idx, 0.0), v)
                    elif v < 0:
                        col_neg_max[col_idx] = max(col_neg_max.get(col_idx, 0.0), abs(v))

        # Overall max across all projects so comparisons across projects share the same visual scale
        global_pos_max = max(col_pos_max.values()) if col_pos_max else 1.0
        global_neg_max = max(col_neg_max.values()) if col_neg_max else 1.0

        # Delegates
        table.setItemDelegateForColumn(0, _VerticalTextDelegate(table))
        table.setItemDelegateForColumn(1, _ItemTickDelegate(table))
        delegate = _HeatmapDelegate(global_pos_max, global_neg_max, parent=table)
        for ci in range(n_cols):
            table.setItemDelegateForColumn(ci + 2, delegate)

        # Fill table and setSpan for Stage column
        curr_row = 0
        for stage_label, stage_color, stage_items in stage_groups:
            count = len(stage_items)
            if count > 1:
                table.setSpan(curr_row, 0, count, 1)

            sc = QColor(stage_color)
            stage_tint = QColor(
                min(255, sc.red()   * 25 // 100 + 191),
                min(255, sc.green() * 25 // 100 + 191),
                min(255, sc.blue()  * 25 // 100 + 191),
            )
            stage_cell = QTableWidgetItem(stage_label)
            stage_cell.setFont(_f(FS_MD, FW_BOLD))
            stage_cell.setBackground(stage_tint)
            stage_cell.setForeground(_contrast(stage_tint))
            stage_cell.setTextAlignment(Qt.AlignCenter)
            table.setItem(curr_row, 0, stage_cell)

            for idx, (lbl, pid_vals, is_credit, cat) in enumerate(stage_items):
                r = curr_row + idx

                label_item = QTableWidgetItem(lbl)
                label_item.setToolTip(lbl)
                label_item.setFont(_f(FS_MD, FW_NORMAL))
                label_item.setForeground(QColor(get_token("text")))
                label_item.setBackground(QColor(get_token("base")))

                cat_lower = str(cat).lower()
                pillar_col = (
                    LCC_PALETTE.get("eco_color") if "eco" in cat_lower
                    else LCC_PALETTE.get("env_color") if "env" in cat_lower
                    else LCC_PALETTE.get("soc_color") if "soc" in cat_lower
                    else None
                )
                if pillar_col:
                    label_item.setData(Qt.UserRole + 1, pillar_col)
                table.setItem(r, 1, label_item)

                for ci, pid in enumerate(pids):
                    val = pid_vals.get(pid, 0.0)
                    display = _fmt_detail_val(val, currency)
                    v_item = QTableWidgetItem(display)
                    v_item.setData(Qt.UserRole, val)
                    v_item.setToolTip(f"{currency} {fmt_currency(val, currency, decimals=2, style='comma')}")
                    v_item.setFont(_f(FS_MD, FW_NORMAL))
                    v_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(r, ci + 2, v_item)

            curr_row += count

        # Legend (placed above table for immediate visual reference)
        legend = _DetailLegend()
        root.addWidget(legend)
        root.addWidget(table)


def _fmt_detail_val(val, currency: str) -> str:
    """Format a detail value with exact precision and comma digit grouping.
    Guards against non-numeric input — returns '0' safely.
    """
    val = _safe_float(val)
    if abs(val) < 0.001:
        return "0"
    d = 0 if float(val).is_integer() else 2
    return fmt_currency(val, currency, decimals=d, style="comma")


class _DetailLegend(QWidget):
    """Continuous gradient bar legend for Option 1 Multi-Hue Warm heatmap."""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, SP1, 0, SP2)
        root.setSpacing(SP2)

        _green_hex  = "#{:02x}{:02x}{:02x}".format(*_SCALE_GREEN)
        _border     = get_token("surface_mid")
        _sec_text   = get_token("text_secondary")

        # Top row: Gradient bar with boundary labels
        row = QHBoxLayout()
        row.setSpacing(SP3)

        lbl_scale = QLabel("Heat Map Scale:")
        lbl_scale.setFont(_f(FS_SM, FW_SEMIBOLD))
        lbl_scale.setStyleSheet(f"color: {get_token('text')};")
        row.addWidget(lbl_scale)

        lbl_profit = QLabel("◄ (Profit / Savings)")
        lbl_profit.setFont(_f(FS_SM, FW_SEMIBOLD))
        lbl_profit.setStyleSheet(f"color: {_green_hex};")
        row.addWidget(lbl_profit)

        _purple_hex = "#{:02x}{:02x}{:02x}".format(*_WARM_COST_STOPS[-1][1])
        grad_bar = QFrame()
        grad_bar.setFixedHeight(12)
        grad_bar.setFixedWidth(260)
        grad_bar.setStyleSheet(f"""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {_green_hex},
                stop:0.35 #a6d96a,
                stop:0.50 #ffffff,
                stop:0.62 #f6c23e,
                stop:0.75 #e67e22,
                stop:0.88 #c0392b,
                stop:1.00 {_purple_hex});
            border: 1px solid {_border};
            border-radius: {RADIUS_SM}px;
        """)
        row.addWidget(grad_bar)

        # lbl_cost = QLabel("Gold ➔ Orange ➔ Red ➔ Purple (Peak) ►")
        lbl_cost = QLabel("(Peak) ►")
        lbl_cost.setFont(_f(FS_SM, FW_SEMIBOLD))
        lbl_cost.setStyleSheet(f"color: {_purple_hex};")
        row.addWidget(lbl_cost)

        zero_lbl = QLabel("(White = 0)")
        zero_lbl.setFont(_f(FS_SM, FW_NORMAL))
        zero_lbl.setStyleSheet(f"color: {_sec_text};")
        row.addWidget(zero_lbl)

        row.addStretch()
        root.addLayout(row)

        # Bottom row: Clear descriptive note
        note = QLabel(
            "Green denotes profit / savings / credit, white denotes zero cost, "
            "and costs scale through gold (low), orange (moderate), red (high), and deep purple (peak cost)."
        )
        note.setFont(_f(FS_SM, FW_NORMAL))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {_sec_text};")
        root.addWidget(note)



# ──────────────────────────────────────────────────────────────────────────────
# Main result window
# ──────────────────────────────────────────────────────────────────────────────

class ComparisonResultWindow(QWidget):
    """
    Opened by ComparisonPickerPanel when the user confirms a group.
    Runs workers, shows full redesigned comparison report.
    """

    def __init__(self, pids: list, names: list, caches: dict,
                 override_ap: int, parent=None):
        super().__init__(parent, Qt.Window)
        label = "  ·  ".join(sorted(names))
        self.setWindowTitle(f"Bridge Comparison — Life Cycle Cost")
        self.setMinimumSize(800, 600)

        self._pids        = pids
        self._names       = names
        self._caches      = caches
        self._override_ap = override_ap
        self._results:  dict = {}
        self._errors:   dict = {}
        self._pending:  set  = set()
        self._workers:  dict = {}
        self._currency = caches[pids[0]].get("currency", "INR") if pids else "INR"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._body        = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(SP8, SP6, SP8, SP8)
        self._body_layout.setSpacing(SP6)
        scroll.setWidget(self._body)
        outer.addWidget(scroll)

        self._show_running()
        self._start_workers()
        theme_manager().theme_changed.connect(self._on_theme)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _clear_body(self):
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_theme(self):
        """Rebuild the result body on theme change so all QLabel/table colours update.
        Chart widgets handle their own rebuild via theme_manager().theme_changed internally.
        """
        if self._results:
            QTimer.singleShot(0, self._show_results)
        elif not self._pending:
            # No results and no pending workers → idle/error state; just clear
            pass


    # ── running state ─────────────────────────────────────────────────────────

    def _show_running(self):
        self._clear_body()
        self._progress_status: dict = {}

        hdr = QLabel("Running Analysis…")
        hdr.setFont(_f(FS_SECTION, FW_BOLD))
        hdr.setStyleSheet(f"color: {get_token('text')};")
        self._body_layout.addWidget(hdr)

        for pid, name in zip(self._pids, self._names):
            row   = QWidget()
            row_h = QHBoxLayout(row)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(SP3)

            name_lbl = QLabel(name)
            name_lbl.setFont(_f(FS_MD, FW_MEDIUM))
            name_lbl.setFixedWidth(220)
            row_h.addWidget(name_lbl)

            bar = QProgressBar()
            bar.setRange(0, 0)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            row_h.addWidget(bar, 1)

            status = QLabel("Running…")
            status.setFont(_f(FS_SM))
            status.setStyleSheet(f"color: {get_token('text_secondary')};")
            status.setFixedWidth(70)
            row_h.addWidget(status)

            self._progress_status[pid] = status
            self._body_layout.addWidget(row)

        self._body_layout.addStretch()

    # ── workers ───────────────────────────────────────────────────────────────

    def _start_workers(self):
        self._pending = set(self._pids)
        for pid in self._pids:
            cache = self._caches[pid]
            ap    = self._override_ap if self._override_ap > 0 \
                    else cache.get("analysis_period", 50)
            worker = _ComparisonWorker(
                pid, cache.get("all_data", {}), cache.get("lcc_breakdown", {}), ap
            )
            worker.finished.connect(self._on_finished)
            worker.errored.connect(self._on_errored)
            self._workers[pid] = worker
            worker.start()

    def _on_finished(self, pid: str, results: dict):
        self._results[pid] = results
        self._pending.discard(pid)
        if pid in self._progress_status:
            self._progress_status[pid].setText("Done")
            self._progress_status[pid].setStyleSheet(f"color: {get_token('success')};")
        if not self._pending:
            self._drain_workers()
            QTimer.singleShot(0, self._show_results)

    def _on_errored(self, pid: str, error: str):
        self._errors[pid]  = error
        self._pending.discard(pid)
        if pid in self._progress_status:
            self._progress_status[pid].setText("Failed")
            self._progress_status[pid].setStyleSheet(f"color: {get_token('danger')};")
        if not self._pending:
            self._drain_workers()
            QTimer.singleShot(0, self._show_results)

    def _drain_workers(self):
        for worker in self._workers.values():
            worker.wait()
        self._workers.clear()

    # ── result rendering ──────────────────────────────────────────────────────

    def _show_results(self):
        self._clear_body()

        # Error banners
        for pid, err in self._errors.items():
            idx  = self._pids.index(pid)
            name = self._names[idx]
            err_lbl = QLabel(f"⚠  {name}: {err}")
            err_lbl.setFont(_f(FS_SM))
            err_lbl.setWordWrap(True)
            err_lbl.setStyleSheet(
                f"color: {get_token('danger')}; "
                f"background: transparent; padding: {SP2}px 0;"
            )
            self._body_layout.addWidget(err_lbl)

        if not self._results:
            self._body_layout.addWidget(QLabel("All analyses failed — no results to display."))
            self._body_layout.addStretch()
            return

        pids  = [p for p in self._pids  if p in self._results]
        names = [self._names[self._pids.index(p)] for p in pids]
        caches_sub = {p: self._caches[p] for p in pids}

        summaries = {p: compute_all_summaries(self._results[p]) for p in pids}

        # ── Page Header ───────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Bridge Comparison — Life Cycle Cost")
        title.setFont(_f(FS_DISP, FW_BOLD))
        title.setStyleSheet(f"color: {get_token('text')};")
        hdr_row.addWidget(title)
        hdr_row.addStretch()

        pdf_btn = QPushButton("Generate PDF Report")
        pdf_btn.setFixedHeight(BTN_MD)
        pdf_btn.setStyleSheet(btn_primary())
        pdf_btn.setFont(_f(FS_MD, FW_SEMIBOLD))
        pdf_btn.setCursor(Qt.PointingHandCursor)
        hdr_row.addWidget(pdf_btn)

        hdr_w = QWidget()
        hdr_w.setLayout(hdr_row)
        self._body_layout.addWidget(hdr_w)

        # ── Metadata breadcrumb strip (H1) ────────────────────────────────────
        # "ProjectA  ·  ProjectB  ·  INR"  — names already carry AP info
        _meta_text = "  ·  ".join(names) + "  ·  " + self._currency
        meta_lbl = QLabel(_meta_text)
        meta_lbl.setFont(_f(FS_SM, FW_NORMAL))
        meta_lbl.setWordWrap(True)
        meta_lbl.setStyleSheet(f"color: {get_token('text_secondary')};")
        self._body_layout.addWidget(meta_lbl)

        self._body_layout.addWidget(_make_divider())

        # ── Section 1: Hero KPI cards ──────────────────────────────────────
        self._body_layout.addWidget(
            _HeroCardsSection(pids, names, summaries, caches_sub, self._currency)
        )
        self._body_layout.addWidget(_make_divider())

        # ── Section 2: Pillar chart ────────────────────────────────────────
        self._body_layout.addWidget(
            _PillarChartSection(pids, names, summaries, self._currency)
        )
        self._body_layout.addWidget(_make_divider())

        # ── Section 3: Stage chart ─────────────────────────────────────────
        self._body_layout.addWidget(
            _StageChartSection(pids, names, summaries, self._currency)
        )
        self._body_layout.addWidget(_make_divider())

        # ── Section 4: Consolidated table ─────────────────────────────────
        self._body_layout.addWidget(
            _ConsolidatedTable(pids, names, summaries, caches_sub, self._currency)
        )
        self._body_layout.addWidget(_make_divider())

        # ── Section 5: Detailed breakdown ─────────────────────────────────
        self._body_layout.addWidget(
            _DetailedBreakdownSection(pids, names, self._results, self._currency)
        )

        self._body_layout.addStretch()


# ──────────────────────────────────────────────────────────────────────────────
# Picker stub (no-op shell kept for API compatibility)
# ──────────────────────────────────────────────────────────────────────────────

class ComparisonPickerPanel(QWidget):
    def __init__(self, manager=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._open_windows = {}

    def is_in_active_comparison(self, pid: str) -> bool:
        return False

    def refresh(self):
        pass

    def soft_refresh(self):
        pass

    def preselect_project(self, pid: str):
        pass


ComparisonPage = ComparisonPickerPanel
