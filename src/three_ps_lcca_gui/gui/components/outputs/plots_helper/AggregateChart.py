"""
gui/components/outputs/plots_helper/AggregateChart.py

Two-view bar chart widget:
  Default  - Stage-wise bars  (Initial / Use+Rec / End-of-Life, solid colours)
  Checkbox - Pillar-wise bars (stacked Economic / Environmental / Social per stage)
"""

import os
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from matplotlib import font_manager as _fm

matplotlib.use("QtAgg")

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
except ImportError:
    from matplotlib.backends.backend_qt import FigureCanvasQTAgg

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QFrame,
    QScrollArea,
)

from three_ps_lcca_gui.gui.theme import (
    FONT_FAMILY,
    FS_XS, FS_SM, FS_BASE, FS_MD, FS_LG, FS_XL, FS_SUBHEAD, FS_DISP,
    FW_NORMAL, FW_MEDIUM, FW_SEMIBOLD, FW_BOLD,
    SP1, SP2, SP3, SP4, SP5, SP6, RADIUS_SM, RADIUS_MD, RADIUS_LG, RADIUS_XL,
)
from three_ps_lcca_gui.gui.themes import get_token
from three_ps_lcca_gui.gui.styles import font as _f
from three_ps_lcca_gui.gui.components.utils.display_format import fmt_currency
from ..helper_functions.lifecycle_summary import compute_all_summaries
from ..helper_functions.ratio_helper import format_ratio_string
from ..helper_functions.lcc_colors import COLORS as LCC_COLORS
from .plot_utils import register_ubuntu_fonts, WheelForwarder, ChartToolbar, currency_note

# ── Register Ubuntu fonts ────────────────────────────────────────────────────
register_ubuntu_fonts()
matplotlib.rcParams["font.family"] = FONT_FAMILY

# ─────────────────────────────────────────────────────────────────────────────
# COLORS
# ─────────────────────────────────────────────────────────────────────────────

STAGE_COLORS = {
    "Initial":     "#CCCCCC",
    "Use":         "#00C49A",
    "End-of-Life": "#EA9E9E",
}

PILLAR_COLORS = {
    "Economic":      LCC_COLORS["eco_color"],
    "Environmental": LCC_COLORS["env_color"],
    "Social":        LCC_COLORS["soc_color"],
}

# ─────────────────────────────────────────────────────────────────────────────
# DATA HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_stage_data(results: dict) -> list:
    """[(label, raw_value, color), ...]- one entry per stage."""
    st = compute_all_summaries(results).get("stagewise", {})
    mapping = [
        ("initial",     "Initial",     STAGE_COLORS["Initial"]),
        ("use",         "Use",         STAGE_COLORS["Use"]),
        ("end_of_life", "End-of-Life", STAGE_COLORS["End-of-Life"]),
    ]
    return [(label, st.get(key, 0), color)
            for key, label, color in mapping if st.get(key, 0) != 0]


def _build_pillar_total_data(results: dict) -> list:
    """[(label, raw_value, color), ...]- one bar per pillar total (negatives included)."""
    pt = compute_all_summaries(results).get("pillar_totals", {})
    rows = [
        ("Economic",      pt.get("eco",    0), PILLAR_COLORS["Economic"]),
        ("Environmental", pt.get("env",    0), PILLAR_COLORS["Environmental"]),
        ("Social",        pt.get("social", 0), PILLAR_COLORS["Social"]),
    ]
    return [(l, v, c) for l, v, c in rows if v != 0]


def _build_pillar_data(results: dict) -> list:
    """[{"stage": label, "pillars": [(name, raw_value), ...]}, ...]- pillar stacked."""
    pw = compute_all_summaries(results).get("pillar_wise", {})
    mapping = [
        ("initial",     "Initial"),
        ("use",         "Use"),
        ("end_of_life", "End-of-Life"),
    ]
    data = []
    for key, label in mapping:
        p = pw.get(key, {})
        if not p or all(v == 0 for v in p.values()):
            continue
        data.append({
            "stage": label,
            "pillars": [
                ("Economic",      p.get("eco",    0)),
                ("Environmental", p.get("env",    0)),
                ("Social",        p.get("social", 0)),
            ],
        })
    return data


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

class _BasePlotter:
    def __init__(self, currency: str):
        self.currency = currency
        self.fig = Figure(figsize=(8, 5))
        self.fig.patch.set_alpha(0.0)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor("none")
        self.fig.subplots_adjust(left=0.09, right=0.96, bottom=0.12, top=0.88)
        self.fig.canvas.mpl_connect("motion_notify_event", self._hover)

    def _hover(self, event):
        if event.inaxes != self.ax or not hasattr(self, "annot"):
            return
        
        info = self._get_hover_info(event)
        if info:
            text, xy = info
            self.annot.set_text(text)
            self.annot.xy = xy
            self.annot.set_visible(True)
        else:
            self.annot.set_visible(False)
        self.fig.canvas.draw_idle()

    def _get_hover_info(self, event):
        """To be implemented by subclasses. Returns (text, xy) or None."""
        return None

    def _setup_spines(self, gc):
        for s in self.ax.spines.values():
            s.set_visible(False)
        for spine in ("left", "bottom"):
            self.ax.spines[spine].set_visible(True)
            self.ax.spines[spine].set_edgecolor(gc)
            self.ax.spines[spine].set_linewidth(1.0)

    def _setup_annotation(self, tc):
        self.annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(15, 15), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.5", fc=get_token("base"),
                      ec=get_token("surface_mid"), alpha=0.95),
            zorder=10, fontweight="bold", color=tc, fontsize=8,
        )
        self.annot.set_visible(False)

    def _make_legend(self, handles, title, tc):
        leg = self.ax.legend(
            handles=handles,
            loc="upper right", ncol=len(handles),
            frameon=False, fontsize=8.5, labelcolor=tc,
        )

    def _setup_axes_style(self, tc, gc, x, xlabels, ylabel=""):
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(xlabels, fontweight="bold", color=tc, fontsize=9.5)
        self.ax.tick_params(axis="x", colors=tc, length=0)
        self.ax.tick_params(axis="y", colors=get_token("text_secondary"), labelsize=8.5, length=3)
        self.ax.yaxis.grid(True, linestyle="-", alpha=0.3, color=gc)
        self.ax.set_axisbelow(True)

    def _setup_y_formatter(self):
        self.ax.yaxis.set_major_formatter(
            matplotlib.ticker.FuncFormatter(
                lambda v, _: fmt_currency(v, self.currency, decimals=0, style="short", use_short_suffix=True)
            )
        )


# ─────────────────────────────────────────────────────────────────────────────
# CHART 0 - Stage-wise bars  (default)
# ─────────────────────────────────────────────────────────────────────────────

class StageBarPlotter(_BasePlotter):
    def __init__(self, data: list, currency: str = "INR"):
        super().__init__(currency)
        self.labels     = [d[0] for d in data]
        self.raw_values = [d[1] for d in data]
        self.values     = [float(v) for v in self.raw_values]
        self.colors     = [d[2] for d in data]
        self._patches: list = []

    def _get_hover_info(self, event):
        if not self._patches:
            return None
        for i, p in enumerate(self._patches):
            if p is not None and p.contains(event)[0]:
                text = (
                    f"{self.labels[i]}\n"
                    f"{fmt_currency(self.raw_values[i], self.currency, decimals=2, style='short', use_short_suffix=True)}"
                )
                return text, (event.xdata, event.ydata)
        return None

    def setup_plot(self):
        tc = get_token("text")
        gc = get_token("surface_mid")
        x  = np.arange(len(self.labels)) * 0.85

        bars = self.ax.bar(x, self.values, color=self.colors, edgecolor="none", width=0.45, zorder=3)
        self._patches = bars.patches

        max_v = max(self.values) if self.values else 1.0
        min_v = min(self.values) if self.values else 0.0
        total_span = max(max_v - min_v, 1.0)
        pad   = total_span * 0.15
        for i, raw in enumerate(self.raw_values):
            val = self.values[i]
            val_str = fmt_currency(raw, self.currency, decimals=2, style="short", use_short_suffix=True).title()
            if val >= total_span * 0.08:
                self.ax.text(x[i], val + pad * 0.05, val_str,
                    ha="center", va="bottom", fontsize=10, fontweight="bold", color=tc, zorder=4)
            elif val > 0:
                # Smart callout for small stage bar
                self.ax.annotate(
                    val_str,
                    xy=(x[i], val),
                    xytext=(x[i], val + pad * 0.5),
                    ha="center", va="bottom",
                    fontsize=9, fontweight="bold", color=tc,
                    bbox=dict(boxstyle="round,pad=0.25", fc=get_token("surface"),
                              ec=get_token("surface_mid"), lw=1.0, alpha=0.95),
                    arrowprops=dict(arrowstyle="-", color=get_token("surface_mid"), lw=1.0),
                    clip_on=False, zorder=5,
                )
            elif val < 0:
                self.ax.text(x[i], val - pad * 0.05, val_str,
                    ha="center", va="top", fontsize=10, fontweight="bold", color=tc, zorder=4)

        self._setup_axes_style(tc, gc, x, self.labels)
        self._setup_y_formatter()
        if self.values:
            self.ax.set_ylim(min(0, min_v) - pad * 0.2, max(0, max_v) + pad)

        self._setup_spines(gc)
        self._setup_annotation(tc)
        return self.fig


# ─────────────────────────────────────────────────────────────────────────────
# CHART 1 - Pillar-wise stacked bars
# ─────────────────────────────────────────────────────────────────────────────

class SustainabilityBarPlotter(_BasePlotter):
    def __init__(self, data: list, currency: str = "INR"):
        super().__init__(currency)
        self.data       = data
        self.stages     = [d["stage"] for d in data]
        self.categories = ["Economic", "Environmental", "Social"]
        self.raw_values = {
            cat: [next((p[1] for p in d["pillars"] if p[0] == cat), 0) for d in data]
            for cat in self.categories
        }
        self.values = {
            cat: [float(v) for v in self.raw_values[cat]]
            for cat in self.categories
        }

    def _get_hover_info(self, event):
        for patch in self.ax.patches:
            if patch.contains(event)[0]:
                for cat in self.categories:
                    if np.allclose(patch.get_facecolor()[:3],
                                   matplotlib.colors.to_rgb(PILLAR_COLORS[cat])):
                        x_pos     = patch.get_x() + patch.get_width() / 2
                        stage_idx = int(round(x_pos / 0.85))
                        if 0 <= stage_idx < len(self.stages):
                            raw = self.raw_values[cat][stage_idx]
                            text = (
                                f"{self.stages[stage_idx]} — {cat}\n"
                                f"{fmt_currency(raw, self.currency, decimals=2, style='short', use_short_suffix=True)}"
                            )
                            return text, (event.xdata, event.ydata)
        return None

    def setup_plot(self):
        tc  = get_token("text")
        gc  = get_token("surface_mid")
        x   = np.arange(len(self.stages)) * 0.85
        pos_bottom = np.zeros(len(self.stages))
        neg_bottom = np.zeros(len(self.stages))

        # Stacking order: Economic -> Social -> Environmental
        draw_order = ["Economic", "Social", "Environmental"]

        # Pre-compute total span across all categories
        for cat in draw_order:
            vals = np.array(self.values[cat])
            pos_bottom += np.where(vals > 0, vals, 0.0)
            neg_bottom += np.where(vals < 0, vals, 0.0)

        y_max = max(pos_bottom) if pos_bottom.any() else 1.0
        y_min = min(neg_bottom) if neg_bottom.any() else 0.0
        total_span = max(y_max - y_min, 1.0)
        pad = total_span * 0.15

        # Reset trackers for actual bar rendering
        pos_bottom = np.zeros(len(self.stages))
        neg_bottom = np.zeros(len(self.stages))

        for cat in draw_order:
            vals     = np.array(self.values[cat])
            pos_vals = np.where(vals > 0, vals, 0.0)
            neg_vals = np.where(vals < 0, vals, 0.0)
            if pos_vals.any():
                seg_bot = pos_bottom.copy()
                self.ax.bar(x, pos_vals, bottom=pos_bottom,
                    color=PILLAR_COLORS[cat], edgecolor="none", width=0.45, zorder=3)
                pos_bottom += pos_vals
                # Show value inside segment only if tall enough relative to total span (> 10% of chart)
                for i, (v, b) in enumerate(zip(pos_vals, seg_bot)):
                    if v >= 0.10 * total_span and pos_bottom[i] >= 0.15 * total_span:
                        seg_text = fmt_currency(v, self.currency, decimals=2, style="short", use_short_suffix=True).title()
                        self.ax.text(
                            x[i], b + v / 2, seg_text,
                            ha="center", va="center", fontsize=8.5, fontweight="bold",
                            color="white", clip_on=True, zorder=4,
                        )
            if neg_vals.any():
                seg_bot = neg_bottom.copy()
                self.ax.bar(x, neg_vals, bottom=neg_bottom,
                    color=PILLAR_COLORS[cat], edgecolor="none", width=0.45, zorder=3)
                neg_bottom += neg_vals
                for i, (v, b) in enumerate(zip(neg_vals, seg_bot)):
                    if abs(v) >= 0.10 * total_span:
                        seg_text = fmt_currency(v, self.currency, decimals=2, style="short", use_short_suffix=True).title()
                        self.ax.text(
                            x[i], b + v / 2, seg_text,
                            ha="center", va="center", fontsize=8.5, fontweight="bold",
                            color="white", clip_on=True, zorder=4,
                        )

        # Smart Annotator for Bar Totals
        for i in range(len(self.stages)):
            pos_v = pos_bottom[i]
            neg_v = neg_bottom[i]
            net_v = pos_v + neg_v

            # If bar is tall (>= 8% of chart span)
            if pos_v >= total_span * 0.08:
                tot_str = fmt_currency(pos_v, self.currency, decimals=2, style="short", use_short_suffix=True).title()
                self.ax.text(x[i], pos_v + pad * 0.05, tot_str,
                    ha="center", va="bottom", fontsize=10, fontweight="bold", color=tc, zorder=4)
            elif net_v != 0:
                # Smart Callout with leader line for tiny bar (prevents overlapping numbers)
                val_str = fmt_currency(net_v, self.currency, decimals=2, style="short", use_short_suffix=True).title()
                self.ax.annotate(
                    val_str,
                    xy=(x[i], max(pos_v, 0)),
                    xytext=(x[i], max(pos_v, 0) + pad * 0.5),
                    ha="center", va="bottom",
                    fontsize=9, fontweight="bold", color=tc,
                    bbox=dict(boxstyle="round,pad=0.25", fc=get_token("surface"),
                              ec=get_token("surface_mid"), lw=1.0, alpha=0.95),
                    arrowprops=dict(arrowstyle="-", color=get_token("surface_mid"), lw=1.0),
                    clip_on=False, zorder=5,
                )

        self._setup_axes_style(tc, gc, x, self.stages)
        self._setup_y_formatter()
        self.ax.set_ylim(min(0, y_min) - pad * 0.2, max(0, y_max) + pad)

        self._setup_spines(gc)
        self._setup_annotation(tc)
        self._make_legend(
            [Patch(facecolor=PILLAR_COLORS[cat], label=cat) for cat in self.categories],
            "Sustainability Pillars", tc,
        )
        return self.fig


# ─────────────────────────────────────────────────────────────────────────────
# CHART 2 - Pillar x-axis, stage-stacked bars  (Pie.py breakdown view)
# ─────────────────────────────────────────────────────────────────────────────

def _lbl_color(hex_color: str) -> str:
    """White text on dark/saturated bars, dark text on light bars."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return "#333333" if (0.299*r + 0.587*g + 0.114*b) / 255 > 0.58 else "white"


class PillarBreakdownBarPlotter(_BasePlotter):
    """Bars per pillar (Eco / Env / Soc) stacked by life cycle stage."""

    def __init__(self, data: list, currency: str = "INR"):
        super().__init__(currency)
        self.stages     = [d["stage"] for d in data]
        self.categories = ["Economic", "Environmental", "Social"]
        # pillar → {stage → raw_value}
        self.raw_values: dict[str, dict[str, float]] = {cat: {} for cat in self.categories}
        for d in data:
            for name, raw_val in d["pillars"]:
                self.raw_values[name][d["stage"]] = raw_val

    def _get_hover_info(self, event):
        for patch in self.ax.patches:
            if patch.contains(event)[0]:
                for stage in self.stages:
                    color = STAGE_COLORS.get(stage, "#AAAAAA")
                    if np.allclose(patch.get_facecolor()[:3], matplotlib.colors.to_rgb(color)[:3]):
                        x_pos   = patch.get_x() + patch.get_width() / 2
                        cat_idx = int(round(x_pos / 0.75))
                        if 0 <= cat_idx < len(self.categories):
                            cat = self.categories[cat_idx]
                            raw = self.raw_values[cat].get(stage, 0.0)
                            if raw != 0.0:
                                text = (
                                    f"{cat}\n"
                                    f"{stage}: {fmt_currency(raw, self.currency, decimals=0, style='short')}"
                                )
                                return text, (event.xdata, event.ydata)
        return None

    def setup_plot(self):
        tc  = get_token("text")
        gc  = get_token("surface_mid")
        x   = np.arange(len(self.categories)) * 0.85

        pos_bottom = np.zeros(len(self.categories))
        neg_bottom = np.zeros(len(self.categories))

        # Pre-compute total span
        for stage in self.stages:
            stage_vals = np.array([self.raw_values[cat].get(stage, 0.0) for cat in self.categories])
            pos_bottom += np.where(stage_vals > 0, stage_vals, 0.0)
            neg_bottom += np.where(stage_vals < 0, stage_vals, 0.0)

        y_max = float(np.max(pos_bottom)) if pos_bottom.any() else 1.0
        y_min = float(np.min(neg_bottom)) if neg_bottom.any() else 0.0
        total_span = max(y_max - y_min, 1.0)
        pad = total_span * 0.15

        pos_bottom = np.zeros(len(self.categories))
        neg_bottom = np.zeros(len(self.categories))

        for stage in self.stages:
            color      = STAGE_COLORS.get(stage, "#AAAAAA")
            lc         = _lbl_color(color)
            stage_vals = np.array([self.raw_values[cat].get(stage, 0.0) for cat in self.categories])
            pos_vals   = np.where(stage_vals > 0, stage_vals, 0.0)
            neg_vals   = np.where(stage_vals < 0, stage_vals, 0.0)

            if pos_vals.any():
                seg_bot = pos_bottom.copy()
                self.ax.bar(x, pos_vals, bottom=pos_bottom, color=color, edgecolor="none", width=0.45, zorder=3)
                pos_bottom += pos_vals
                for i, (v, b) in enumerate(zip(pos_vals, seg_bot)):
                    if v >= 0.10 * total_span and pos_bottom[i] >= 0.15 * total_span:
                        seg_text = fmt_currency(v, self.currency, decimals=2, style="short", use_short_suffix=True).title()
                        self.ax.text(
                            x[i], b + v / 2, seg_text,
                            ha="center", va="center", fontsize=8.5, fontweight="bold",
                            color=lc, clip_on=True, zorder=4,
                        )
            if neg_vals.any():
                seg_bot = neg_bottom.copy()
                self.ax.bar(x, neg_vals, bottom=neg_bottom, color=color, edgecolor="none", width=0.45, zorder=3)
                neg_bottom += neg_vals
                for i, (v, b) in enumerate(zip(neg_vals, seg_bot)):
                    if abs(v) >= 0.10 * total_span:
                        seg_text = fmt_currency(v, self.currency, decimals=2, style="short", use_short_suffix=True).title()
                        self.ax.text(
                            x[i], b + v / 2, seg_text,
                            ha="center", va="center", fontsize=8.5, fontweight="bold",
                            color=lc, clip_on=True, zorder=4,
                        )

        # Totals on top of bars
        for i in range(len(self.categories)):
            pos_v = pos_bottom[i]
            neg_v = neg_bottom[i]
            net_v = pos_v + neg_v

            if pos_v >= total_span * 0.08:
                tot_str = fmt_currency(pos_v, self.currency, decimals=2, style="short", use_short_suffix=True).title()
                self.ax.text(x[i], pos_v + pad * 0.05, tot_str,
                    ha="center", va="bottom", fontsize=10, fontweight="bold", color=tc, zorder=4)
            elif net_v != 0:
                val_str = fmt_currency(net_v, self.currency, decimals=2, style="short", use_short_suffix=True).title()
                self.ax.annotate(
                    val_str,
                    xy=(x[i], max(pos_v, 0)),
                    xytext=(x[i], max(pos_v, 0) + pad * 0.5),
                    ha="center", va="bottom",
                    fontsize=9, fontweight="bold", color=tc,
                    bbox=dict(boxstyle="round,pad=0.25", fc=get_token("surface"),
                              ec=get_token("surface_mid"), lw=1.0, alpha=0.95),
                    arrowprops=dict(arrowstyle="-", color=get_token("surface_mid"), lw=1.0),
                    clip_on=False, zorder=5,
                )

        self._setup_axes_style(tc, gc, x, self.categories)
        self._setup_y_formatter()
        self.ax.set_ylim(min(0, y_min) - pad * 0.2, max(0, y_max) + pad)
        self._setup_spines(gc)
        self._setup_annotation(tc)
        self._make_legend(
            [Patch(facecolor=STAGE_COLORS.get(st, "#AAAAAA"), label=st) for st in self.stages],
            "Life Cycle Stages", tc,
        )
        return self.fig


# ─────────────────────────────────────────────────────────────────────────────
# WIDGET
# ─────────────────────────────────────────────────────────────────────────────
# CARD HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _create_metric_card(name: str, color: str, pct: float, amount_str: str) -> QFrame:
    item = QFrame()
    item.setStyleSheet(
        f"QFrame {{"
        f"  background-color: {get_token('surface')};"
        f"  border: 1px solid {get_token('surface_mid')};"
        f"  border-radius: {RADIUS_LG}px;"
        f"}}"
    )
    item_v = QVBoxLayout(item)
    item_v.setContentsMargins(SP3, SP3, SP3, SP3)
    item_v.setSpacing(SP1)

    # Row 1: dot + name on left, percentage on right
    r1 = QHBoxLayout()
    r1.setContentsMargins(0, 0, 0, 0)
    r1.setSpacing(SP2)

    dot = QLabel()
    dot.setFixedSize(9, 9)
    dot.setStyleSheet(f"background-color: {color}; border-radius: 4px; border: none;")
    r1.addWidget(dot)

    name_lbl = QLabel(name)
    name_lbl.setFont(_f(FS_BASE, FW_SEMIBOLD))
    name_lbl.setStyleSheet(f"color: {get_token('text')}; border: none; background: transparent;")
    r1.addWidget(name_lbl)
    r1.addStretch()

    pct_lbl = QLabel(f"{pct:.1f}%")
    pct_lbl.setFont(_f(FS_SM, FW_SEMIBOLD))
    pct_lbl.setStyleSheet(f"color: {get_token('text_secondary')}; border: none; background: transparent;")
    r1.addWidget(pct_lbl)
    item_v.addLayout(r1)

    # Row 2: Value
    val_lbl = QLabel(amount_str)
    val_lbl.setFont(_f(FS_DISP, FW_BOLD))
    val_lbl.setStyleSheet(f"color: {get_token('text')}; border: none; background: transparent; padding-top: 1px;")
    item_v.addWidget(val_lbl)

    # Row 3: Bar track with progress fill
    track = QFrame()
    track.setFixedHeight(5)
    track.setStyleSheet(f"background-color: {get_token('surface_mid')}; border-radius: 2px; border: none;")
    track_l = QHBoxLayout(track)
    track_l.setContentsMargins(0, 0, 0, 0)
    track_l.setSpacing(0)

    clamped_pct = max(0.0, min(100.0, pct))
    fill_weight = int(round(clamped_pct))
    empty_weight = int(round(100.0 - clamped_pct))

    if fill_weight > 0:
        fill = QFrame()
        fill.setFixedHeight(5)
        fill.setStyleSheet(f"background-color: {color}; border-radius: 2px; border: none;")
        track_l.addWidget(fill, fill_weight)
    if empty_weight > 0:
        track_l.addStretch(empty_weight)

    item_v.addWidget(track)
    return item


def _create_total_block(total_val: float, currency: str) -> QFrame:
    total_block = QFrame()
    total_block.setStyleSheet(
        f"border: none; border-top: 1px solid {get_token('surface_mid')}; background: transparent;"
    )
    tb_v = QVBoxLayout(total_block)
    tb_v.setContentsMargins(0, SP3, 0, 0)
    tb_v.setSpacing(2)

    tlabel = QLabel("Total cost")
    tlabel.setFont(_f(FS_XS, FW_NORMAL))
    tlabel.setStyleSheet(f"color: {get_token('text_secondary')}; border: none; background: transparent;")
    tb_v.addWidget(tlabel)

    formatted_total = fmt_currency(total_val, currency, decimals=2, style="short", use_short_suffix=True).title()
    tvalue = QLabel(
        f"<span style='font-size:16pt; font-weight:700; color:{get_token('text')};'>{formatted_total}</span> "
        f"<span style='font-size:9.5pt; font-weight:500; color:{get_token('text_secondary')};'>{currency}</span>"
    )
    tvalue.setTextFormat(Qt.RichText)
    tvalue.setStyleSheet("border: none; background: transparent;")
    tb_v.addWidget(tvalue)
    return total_block


class AggregateChartWidget(QWidget):
    def __init__(self, results: dict, currency: str = "INR",
                 default_pillar_view: bool = False,
                 note: str = "",
                 parent=None):
        super().__init__(parent)
        self._results             = results
        self._currency            = currency
        self._default_pillar_view = default_pillar_view
        self._note                = note
        self._setup_ui()

    def _setup_ui(self):
        self._main_v = QVBoxLayout(self)
        self._main_v.setContentsMargins(0, SP4, 0, SP4)

        self.card = QFrame()
        self.card.setObjectName("aggCard")
        self.card.setStyleSheet(
            f"#aggCard {{"
            f"  background-color: transparent;"
            f"  border: 1.5px solid {get_token('surface_mid')};"
            f"  border-radius: {RADIUS_XL}px;"
            f"}}"
        )
        self.card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._card_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.card)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(0)

        # ── Left panel ───────────────────────────────────────────────────────
        self._text_panel = QFrame()
        self._text_panel.setObjectName("aggTextPanel")
        self._text_panel.setStyleSheet(
            f"#aggTextPanel {{"
            f"  background-color: {get_token('window')};"
            f"  border-top-left-radius: {RADIUS_XL - 1}px;"
            f"  border-bottom-left-radius: {RADIUS_XL - 1}px;"
            f"  border-right: 1.5px solid {get_token('surface_mid')};"
            f"}}"
        )
        self._text_panel.setFixedWidth(310)

        text_v = QVBoxLayout(self._text_panel)
        text_v.setContentsMargins(SP5, SP5, SP5, SP5)
        text_v.setSpacing(SP3)

        title = QLabel("Across 3 Stages")
        title.setAlignment(Qt.AlignLeft)
        title.setFont(_f(FS_SUBHEAD, FW_BOLD))
        title.setStyleSheet(
            f"color: {get_token('text')}; border: none; background: transparent; letter-spacing: -0.2px;"
        )
        text_v.addWidget(title)

        sub_desc = QLabel(f"Total cost breakdown across 3 lifecycle stages, in {self._currency}.")
        sub_desc.setAlignment(Qt.AlignLeft)
        sub_desc.setWordWrap(True)
        sub_desc.setFont(_f(FS_SM))
        sub_desc.setStyleSheet(
            f"color: {get_token('text_secondary')}; border: none; background: transparent; line-height: 1.4;"
        )
        text_v.addWidget(sub_desc)

        # Stage cards
        summary = compute_all_summaries(self._results)
        st      = summary.get("stagewise", {})

        c_init = get_token("init")
        c_use  = get_token("use")
        c_end  = get_token("end")

        v_ini = st.get("initial",     0)
        v_use = st.get("use",         0)
        v_end = st.get("end_of_life", 0)

        sum_stages = sum(abs(v) for v in [v_ini, v_use, v_end]) or 1.0
        p_ini = v_ini / sum_stages * 100
        p_use = v_use / sum_stages * 100
        p_end = v_end / sum_stages * 100

        a_ini = fmt_currency(v_ini, self._currency, decimals=0, style="short", use_short_suffix=True).title()
        a_use = fmt_currency(v_use, self._currency, decimals=0, style="short", use_short_suffix=True).title()
        a_end = fmt_currency(v_end, self._currency, decimals=0, style="short", use_short_suffix=True).title()

        card_init = _create_metric_card("Initial", c_init, p_ini, a_ini)
        card_use  = _create_metric_card("Use", c_use, p_use, a_use)
        card_end  = _create_metric_card("End-of-Life", c_end, p_end, a_end)

        text_v.addWidget(card_init)
        text_v.addWidget(card_use)
        text_v.addWidget(card_end)

        text_v.addStretch()

        # Total Cost Block
        total_val = v_ini + v_use + v_end
        text_v.addWidget(_create_total_block(total_val, self._currency))

        # "Show pillar wise" checkbox
        self._pillar_cb = QCheckBox("Show pillar wise")
        self._pillar_cb.setFont(_f(FS_BASE))
        self._pillar_cb.setStyleSheet(
            f"color: {get_token('text_secondary')}; background: transparent; border: none; padding-top: {SP1}px;"
        )
        text_v.addWidget(self._pillar_cb)

        if self._note:
            note_lbl = QLabel(self._note)
            note_lbl.setAlignment(Qt.AlignLeft)
            note_lbl.setWordWrap(True)
            note_lbl.setFont(_f(FS_XS, FW_NORMAL, italic=True))
            note_lbl.setStyleSheet(
                f"color: {get_token('text_secondary')}; border: none; background: transparent;"
            )
            text_v.addWidget(note_lbl)

        self._card_layout.addWidget(self._text_panel)

        # ── Chart stack ──────────────────────────────────────────────────────
        self._chart_stack = QStackedWidget()
        self._chart_stack.setMaximumHeight(420)
        self._chart_stack.setStyleSheet("background: transparent; border: none;")
        self._toolbar_stack = QStackedWidget()
        self._toolbar_stack.setStyleSheet("background: transparent; border: none;")

        scroller = WheelForwarder(self)

        # Chart 0: stage-wise
        stage_data = _build_stage_data(self._results)
        if stage_data:
            p0   = StageBarPlotter(stage_data, currency=self._currency)
            fig0 = p0.setup_plot()
            c0   = FigureCanvasQTAgg(fig0)
            c0.setStyleSheet("background: transparent; border: none;")
            c0.setMinimumHeight(280)
            c0.setMaximumHeight(420)
            c0.installEventFilter(scroller)
            self._chart_stack.addWidget(c0)
            self._toolbar_stack.addWidget(ChartToolbar(c0, self))
        else:
            lbl = QLabel("Insufficient data.")
            lbl.setAlignment(Qt.AlignCenter)
            self._chart_stack.addWidget(lbl)
            self._toolbar_stack.addWidget(QWidget())

        # Chart 1: pillar-wise (stacked)
        pillar_data = _build_pillar_data(self._results)
        if pillar_data:
            p1   = SustainabilityBarPlotter(pillar_data, currency=self._currency)
            fig1 = p1.setup_plot()
            c1   = FigureCanvasQTAgg(fig1)
            c1.setStyleSheet("background: transparent; border: none;")
            c1.setMinimumHeight(280)
            c1.setMaximumHeight(420)
            c1.installEventFilter(scroller)
            self._chart_stack.addWidget(c1)
            self._toolbar_stack.addWidget(ChartToolbar(c1, self))
        else:
            lbl = QLabel("Insufficient data.")
            lbl.setAlignment(Qt.AlignCenter)
            self._chart_stack.addWidget(lbl)
            self._toolbar_stack.addWidget(QWidget())

        self._pillar_cb.toggled.connect(
            lambda checked: self._chart_stack.setCurrentIndex(1 if checked else 0)
        )
        self._pillar_cb.toggled.connect(
            lambda checked: self._toolbar_stack.setCurrentIndex(1 if checked else 0)
        )

        if self._default_pillar_view:
            self._pillar_cb.setChecked(True)

        self._chart_cont = QWidget()
        self._chart_cont.setStyleSheet("background: transparent; border: none;")
        chart_cv = QVBoxLayout(self._chart_cont)
        chart_cv.setContentsMargins(SP5, SP4, SP5, SP4)
        chart_cv.setSpacing(SP2)

        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.addStretch()
        unit_lbl = QLabel(f"All values in {self._currency}")
        unit_lbl.setFont(_f(FS_SM, FW_MEDIUM))
        unit_lbl.setStyleSheet(f"color: {get_token('text_secondary')}; border: none; background: transparent;")
        top_bar.addWidget(unit_lbl)
        chart_cv.addLayout(top_bar)

        chart_cv.addWidget(self._chart_stack, 1)

        footer_frame = QFrame()
        footer_frame.setStyleSheet(
            f"border: none; border-top: 1px solid {get_token('surface_mid')}; background: transparent; padding-top: 2px;"
        )
        footer_l = QHBoxLayout(footer_frame)
        footer_l.setContentsMargins(0, 4, 0, 0)
        footer_hint = QLabel("Hover on bars to inspect breakdown")
        footer_hint.setFont(_f(FS_XS))
        footer_hint.setStyleSheet(f"color: {get_token('text_disabled')}; border: none; background: transparent;")
        footer_l.addWidget(footer_hint)
        footer_l.addStretch()
        footer_l.addWidget(self._toolbar_stack)
        chart_cv.addWidget(footer_frame)

        self._card_layout.addWidget(self._chart_cont, 1)

        self._main_v.addWidget(self.card)

    # ── responsive layout ─────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        is_narrow = event.size().width() < 880
        if is_narrow:
            self._card_layout.setDirection(QBoxLayout.Direction.TopToBottom)
            self._text_panel.setMinimumWidth(0)
            self._text_panel.setMaximumWidth(16777215)
            self._text_panel.setStyleSheet(
                f"#aggTextPanel {{"
                f"  background-color: {get_token('window')};"
                f"  border-top-left-radius: {RADIUS_XL - 1}px;"
                f"  border-top-right-radius: {RADIUS_XL - 1}px;"
                f"  border-bottom-left-radius: 0px;"
                f"  border-bottom-right-radius: 0px;"
                f"  border-bottom: 1.5px solid {get_token('surface_mid')};"
                f"  border-right: none;"
                f"}}"
            )
        else:
            self._card_layout.setDirection(QBoxLayout.Direction.LeftToRight)
            self._text_panel.setFixedWidth(310)
            self._text_panel.setStyleSheet(
                f"#aggTextPanel {{"
                f"  background-color: {get_token('window')};"
                f"  border-top-left-radius: {RADIUS_XL - 1}px;"
                f"  border-bottom-left-radius: {RADIUS_XL - 1}px;"
                f"  border-top-right-radius: 0px;"
                f"  border-bottom-right-radius: 0px;"
                f"  border-right: 1.5px solid {get_token('surface_mid')};"
                f"  border-bottom: none;"
                f"}}"
            )

    def minimumSizeHint(self):
        return QSize(0, 400)

