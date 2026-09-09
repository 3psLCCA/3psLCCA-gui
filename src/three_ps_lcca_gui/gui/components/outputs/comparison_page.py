"""
gui/components/outputs/comparison_page.py

Side-by-side LCCA project comparison.

Flow:
  1. Page scans projects with fit_for_comparison=True via list_all_projects().
  2. User picks ≥2 projects, optionally sets a common analysis period.
  3. Workers re-run run_full_lcc_analysis from the cached all_data + lcc_breakdown.
  4. Results are shown in a KPI table + grouped bar chart.

Reading the comparison_cache from disk without opening an engine instance keeps
other projects' locks untouched and avoids the overhead of a full engine attach.
"""

import json
import os
import traceback
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
except ImportError:
    from matplotlib.backends.backend_qt import FigureCanvasQTAgg, NavigationToolbar2QT

from matplotlib import font_manager as _fm

from PySide6.QtCore import Qt, QObject, QThread, QTimer, Signal, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
    QCheckBox,
)

from three_ps_lcca_gui.gui.themes import get_token, theme_manager
from three_ps_lcca_gui.gui.styles import font as _f, btn_primary, btn_ghost
from three_ps_lcca_gui.gui.theme import (
    SP1, SP2, SP3, SP4, SP5, SP6, SP8, SP10,
    RADIUS_SM, RADIUS_LG, RADIUS_MD,
    FS_XS, FS_SM, FS_BASE, FS_MD, FS_LG, FS_SUBHEAD, FS_DISP,
    FW_NORMAL, FW_MEDIUM, FW_SEMIBOLD, FW_BOLD,
    BTN_SM, BTN_MD, BTN_LG, FONT_FAMILY,
)
from three_ps_lcca_gui.gui.components.utils.icons import make_icon
from three_ps_lcca_gui.core.safechunk_engine import SafeChunkEngine, _decode, LCCA_EXT
import three_ps_lcca_gui.core.start_manager as _sm
from three_ps_lcca_core.core.main import run_full_lcc_analysis
from three_ps_lcca_gui.gui.components.utils.display_format import fmt_currency
from three_ps_lcca_gui.gui.components.sponsors_footer import SponsorsFooter
from .data_preparer import DataPreparer
from .helper_functions.lifecycle_summary import compute_all_summaries
from .helper_functions.lcc_colors import COLORS as LCC_PALETTE

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

_GUI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ASSETS_DIR = os.path.join(_GUI_DIR, "assets")

_STAGE_KEYS   = ["initial", "use_reconstruction", "end_of_life"]
_STAGE_LABELS = ["Initial Construction", "Use & Maintenance", "End of Life"]
_STAGE_COLORS = [
    LCC_PALETTE.get("init_color", "#CCCCCC"),
    LCC_PALETTE.get("use_color",  "#00C49A"),
    LCC_PALETTE.get("end_color",  "#EA9E9E"),
]

# Cycles for unlimited projects
_PROJECT_COLORS = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
    "#CCB974", "#64B5CD", "#E377C2", "#7F7F7F", "#BCBD22",
]


# ──────────────────────────────────────────────────────────────────────────────
# Date helper
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


# ──────────────────────────────────────────────────────────────────────────────
# Disk helper - read cache without opening an engine
# ──────────────────────────────────────────────────────────────────────────────

def _read_cache_from_disk(base_dir: Path, project_id: str) -> dict:
    chunk_path = base_dir / project_id / "chunks" / f"{CHUNK_COMPARISON}{LCCA_EXT}"
    if not chunk_path.exists():
        return {}
    try:
        return _decode(chunk_path.read_bytes())
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Background worker - one per project
# ──────────────────────────────────────────────────────────────────────────────

class _ComparisonWorker(QThread):
    """
    Subclasses QThread directly - avoids moveToThread + deleteLater fragility.
    The thread IS the worker; no separate QObject needed.
    """
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
# KPI comparison table
# ──────────────────────────────────────────────────────────────────────────────

class _KPITable(QWidget):
    """
    Rows = metrics, Columns = projects.
    Best (lowest cost) value per row is highlighted with a green dot.
    """

    def __init__(self, ordered_pids: list[str], display_names: list[str],
                 summaries: dict[str, dict], caches: dict[str, dict],
                 currency: str, parent=None):
        super().__init__(parent)
        self._build(ordered_pids, display_names, summaries, caches, currency)

    def _build(self, pids, names, summaries, caches, currency):
        grid = QGridLayout(self)
        grid.setSpacing(0)
        grid.setContentsMargins(0, 0, 0, 0)

        # ── Column headers ────────────────────────────────────────────────────
        corner = QLabel("Metric")
        corner.setFont(_f(FS_SM, FW_SEMIBOLD))
        corner.setStyleSheet(
            f"color: {get_token('text_secondary')}; "
            f"padding: {SP2}px {SP4}px; "
            f"background: {get_token('surface_mid')};"
        )
        grid.addWidget(corner, 0, 0)

        for col, (pid, name) in enumerate(zip(pids, names), start=1):
            color = _PROJECT_COLORS[(col - 1) % len(_PROJECT_COLORS)]
            lbl = QLabel(name)
            lbl.setFont(_f(FS_SM, FW_SEMIBOLD))
            lbl.setWordWrap(True)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setStyleSheet(
                f"color: {color}; padding: {SP2}px {SP4}px; "
                f"background: {get_token('surface_mid')};"
            )
            grid.addWidget(lbl, 0, col)

        # ── Row definitions ───────────────────────────────────────────────────
        def _total(pid):
            sw = summaries[pid]["stagewise"]
            return sum(sw.values())

        rows = [
            ("Total LCCA (NPV)",           lambda pid: _total(pid),                                  True),
            ("Initial Construction",        lambda pid: summaries[pid]["stagewise"]["initial"],        True),
            ("Use & Maintenance",           lambda pid: summaries[pid]["stagewise"]["use_reconstruction"], True),
            ("End of Life",                 lambda pid: summaries[pid]["stagewise"]["end_of_life"],    True),
            ("Economic Pillar",             lambda pid: summaries[pid]["pillar_totals"]["eco"],        True),
            ("Environmental Pillar",        lambda pid: summaries[pid]["pillar_totals"]["env"],        True),
            ("Social Pillar",               lambda pid: summaries[pid]["pillar_totals"]["social"],     True),
            ("Analysis Period",             lambda pid: caches[pid].get("analysis_period", "-"),      False),
        ]

        for row, (label, fn, is_cost) in enumerate(rows, start=1):
            is_total = row == 1
            row_bg = get_token("surface") if row % 2 == 0 else "transparent"
            sep_top = f"border-top: 1px solid {get_token('surface_mid')};" if is_total else ""

            metric_lbl = QLabel(label)
            metric_lbl.setFont(_f(FS_BASE, FW_BOLD if is_total else FW_NORMAL))
            metric_lbl.setStyleSheet(
                f"color: {get_token('text_secondary')}; padding: {SP2}px {SP4}px; "
                f"background: {row_bg}; {sep_top}"
            )
            grid.addWidget(metric_lbl, row, 0)

            # Compute values for all projects
            values = {}
            for pid in pids:
                try:
                    values[pid] = fn(pid)
                except Exception:
                    values[pid] = 0.0

            # Find best (minimum cost)
            best_pid = None
            if is_cost and len(pids) > 1:
                numeric = {p: v for p, v in values.items() if isinstance(v, (int, float))}
                if numeric:
                    best_pid = min(numeric, key=numeric.get)

            for col, pid in enumerate(pids, start=1):
                val = values[pid]
                is_best = (pid == best_pid)

                cell = QWidget()
                cell.setStyleSheet(f"background: {row_bg}; {sep_top}")
                cell_h = QHBoxLayout(cell)
                cell_h.setContentsMargins(SP3, SP2, SP4, SP2)
                cell_h.setSpacing(SP1)
                cell_h.addStretch()

                if is_cost and is_best:
                    dot_wrap = QWidget()
                    dot_wrap.setStyleSheet("background: transparent;")
                    dv = QVBoxLayout(dot_wrap)
                    dv.setContentsMargins(0, 0, 0, 0)
                    dv.addStretch()
                    dot = QFrame()
                    dot.setFixedSize(6, 6)
                    dot.setStyleSheet(
                        f"background: {get_token('success')}; border-radius: 3px;"
                    )
                    dv.addWidget(dot)
                    dv.addStretch()
                    cell_h.addWidget(dot_wrap)

                if is_cost:
                    text = fmt_currency(val, currency, decimals=0, style="both")
                elif isinstance(val, int):
                    text = f"{val} yrs"
                else:
                    text = str(val)

                val_lbl = QLabel(text)
                val_lbl.setFont(_f(FS_BASE, FW_BOLD if is_total else FW_NORMAL))
                val_lbl.setStyleSheet(
                    f"color: {get_token('success') if is_best and is_cost else get_token('text')}; "
                    f"background: transparent;"
                )
                val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                cell_h.addWidget(val_lbl)

                if is_cost and best_pid and pid != best_pid:
                    best_val = values[best_pid]
                    if isinstance(best_val, (int, float)) and best_val > 0:
                        delta = ((val - best_val) / best_val) * 100
                        delta_lbl = QLabel(f"+{delta:.1f}%" if delta > 0 else f"{delta:.1f}%")
                        delta_lbl.setFont(_f(FS_XS, FW_MEDIUM))
                        delta_lbl.setStyleSheet(f"color: {get_token('text_secondary')}; background: transparent;")
                        cell_h.addWidget(delta_lbl)

                grid.addWidget(cell, row, col)

        grid.setColumnStretch(0, 3)
        for c in range(1, len(pids) + 1):
            grid.setColumnStretch(c, 2)


# ──────────────────────────────────────────────────────────────────────────────
# Grouped bar chart - stages × projects
# ──────────────────────────────────────────────────────────────────────────────

class _ComparisonChart(QWidget):
    """
    Grouped bar chart: x = life cycle stage, bars within group = projects.
    Each project gets a distinct color; stage groups are visually separated.
    """

    def __init__(self, ordered_pids: list[str], display_names: list[str],
                 summaries: dict[str, dict], currency: str, parent=None):
        super().__init__(parent)
        self._pids      = ordered_pids
        self._names     = display_names
        self._summaries = summaries
        self._currency  = currency
        self._visible_stages = list(_STAGE_KEYS)
        self._fig       = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._build()
        theme_manager().theme_changed.connect(self._rebuild)

    def update_stages(self, stages: list[str]):
        """Update chart to show only selected life cycle stages."""
        self._visible_stages = stages
        self._rebuild()

    def _rebuild(self):
        if self._fig:
            plt.close(self._fig)
            self._fig = None
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._build()

    def _build(self):
        text_color = get_token("text")
        bg_color   = get_token("window")
        mid_color  = get_token("surface_mid")

        # Filter stages based on interactive selection
        indices = [i for i, k in enumerate(_STAGE_KEYS) if k in self._visible_stages]
        labels  = [_STAGE_LABELS[i] for i in indices]
        n_stages = len(indices)
        
        if n_stages == 0:
            msg = QLabel("No stages selected.")
            msg.setAlignment(Qt.AlignCenter)
            msg.setStyleSheet(f"color: {get_token('text_disabled')};")
            self.layout().addWidget(msg)
            return

        n_projects = len(self._pids)
        bar_w      = 0.7 / max(1, n_projects)
        x          = np.arange(n_stages)

        fig, ax = plt.subplots(figsize=(max(5, n_stages * 2.5), 4.5))
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)
        self._fig = fig

        legend_patches = []
        for i, (pid, name) in enumerate(zip(self._pids, self._names)):
            sw  = self._summaries[pid]["stagewise"]
            # Extract only the visible stage values
            vals = np.array([sw.get(_STAGE_KEYS[idx], 0) / 1_000_000 for idx in indices])
            
            offset = (i - (n_projects - 1) / 2) * bar_w
            color  = _PROJECT_COLORS[i % len(_PROJECT_COLORS)]
            ax.bar(x + offset, vals, bar_w, color=color, label=name,
                   edgecolor=bg_color, linewidth=0.5)
            legend_patches.append(
                mpatches.Patch(color=color, label=name)
            )

        ax.set_xticks(x)
        ax.set_xticklabels(labels, color=text_color,
                           fontsize=8, fontfamily=FONT_FAMILY)
        ax.set_ylabel(f"Cost  (Million {self._currency})",
                      color=text_color, fontsize=8, fontfamily=FONT_FAMILY)
        ax.tick_params(colors=text_color, labelsize=8)
        for spine in ax.spines.values():
            spine.set_color(mid_color)
        ax.yaxis.set_tick_params(color=mid_color)
        ax.xaxis.set_tick_params(color=mid_color)
        ax.set_title("Life-Cycle Cost Breakdown  (NPV)",
                     color=text_color, fontsize=10, fontfamily=FONT_FAMILY, pad=10)

        ax.legend(handles=legend_patches, fontsize=8, facecolor=bg_color,
                  labelcolor=text_color, framealpha=0.85,
                  edgecolor=mid_color, loc="upper right")
        fig.tight_layout(pad=1.5)

        class _ChartToolbar(NavigationToolbar2QT):
            toolitems = [t for t in NavigationToolbar2QT.toolitems
                         if t[0] not in ("Subplots", "Customize")]
            def set_message(self, s): pass

        canvas = FigureCanvasQTAgg(fig)
        canvas.setMinimumHeight(340)
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        canvas.wheelEvent = lambda event: event.ignore()
        toolbar = _ChartToolbar(canvas, self)

        self.layout().addWidget(toolbar)
        self.layout().addWidget(canvas)


# ──────────────────────────────────────────────────────────────────────────────
# Standalone result window - one per confirmed comparison group
# ──────────────────────────────────────────────────────────────────────────────

class ComparisonResultWindow(QWidget):
    """
    Opened by ComparisonPickerPanel when the user confirms a group.
    Runs workers, shows KPI table + chart. No picker inside.
    """

    def __init__(self, pids: list, names: list, caches: dict,
                 override_ap: int, parent=None):
        super().__init__(parent, Qt.Window)
        label = "  ·  ".join(sorted(names))
        self.setWindowTitle(f"Comparison: {label}")
        self.setMinimumSize(980, 680)

        self._pids       = pids
        self._names      = names        # parallel to pids
        self._caches     = caches
        self._override_ap = override_ap
        self._results: dict = {}
        self._errors:  dict = {}
        self._pending: set  = set()
        self._workers: dict = {}
        self._currency = caches[pids[0]].get("currency", "INR") if pids else "INR"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(SP6, SP5, SP6, SP5)
        self._body_layout.setSpacing(SP4)
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

    def _section_heading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(_f(FS_LG, FW_BOLD))
        lbl.setStyleSheet(f"color: {get_token('text')};")
        return lbl

    def _banner(self, text: str, token: str) -> QWidget:
        outer = QWidget()
        h = QHBoxLayout(outer)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        strip = QFrame()
        strip.setFixedWidth(3)
        strip.setStyleSheet(f"background: {get_token(token)}; border-radius: 2px;")
        h.addWidget(strip)
        inner = QFrame()
        inner.setStyleSheet("QFrame { background: transparent; border: none; }")
        v = QVBoxLayout(inner)
        v.setContentsMargins(SP3, SP2, SP3, SP2)
        lbl = QLabel(text)
        lbl.setFont(_f(FS_BASE))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {get_token('text')}; background: transparent;")
        v.addWidget(lbl)
        h.addWidget(inner, 1)
        return outer

    def _on_theme(self):
        pass   # _ComparisonChart rebuilds itself; static labels stay readable

    # ── running state ─────────────────────────────────────────────────────────

    def _show_running(self):
        self._clear_body()
        self._progress_status: dict = {}

        hdr = QLabel("Running Analysis…")
        hdr.setFont(_f(FS_LG, FW_BOLD))
        hdr.setStyleSheet(f"color: {get_token('text')};")
        self._body_layout.addWidget(hdr)

        for pid, name in zip(self._pids, self._names):
            row = QWidget()
            row_h = QHBoxLayout(row)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(SP3)

            name_lbl = QLabel(name)
            name_lbl.setFont(_f(FS_BASE, FW_MEDIUM))
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
            ap = self._override_ap if self._override_ap > 0 \
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
        self._errors[pid] = error
        self._pending.discard(pid)
        if pid in self._progress_status:
            self._progress_status[pid].setText("Failed")
            self._progress_status[pid].setStyleSheet(f"color: {get_token('danger')};")
        if not self._pending:
            self._drain_workers()
            QTimer.singleShot(0, self._show_results)

    def _drain_workers(self):
        """Wait for every thread to exit then drop Python references."""
        for worker in self._workers.values():
            worker.wait()   # blocks briefly - thread has already emitted its signal
        self._workers.clear()

    def _on_stage_filter_changed(self):
        visible = [k for k, cb in self._stage_checks.items() if cb.isChecked()]
        self._chart.update_stages(visible)

    def _show_results(self):
        self._clear_body()

        for pid, err in self._errors.items():
            idx = self._pids.index(pid)
            self._body_layout.addWidget(
                self._banner(f"{self._names[idx]}: {err}", "danger")
            )

        if not self._results:
            self._body_layout.addWidget(
                self._banner("All analyses failed - no results to display.", "danger")
            )
            self._body_layout.addStretch()
            return

        pids  = [p for p in self._pids if p in self._results]
        names = [self._names[self._pids.index(p)] for p in pids]

        # Period line
        if self._override_ap > 0:
            period_text = f"All projects analysed at a {self._override_ap}-year horizon."
        else:
            parts = [
                f"{n}: {self._caches[p].get('analysis_period', '?')} yrs"
                for p, n in zip(pids, names)
            ]
            period_text = "Analysis periods - " + "  ·  ".join(parts)
        period_lbl = QLabel(period_text)
        period_lbl.setFont(_f(FS_SM))
        period_lbl.setWordWrap(True)
        period_lbl.setStyleSheet(f"color: {get_token('text_secondary')};")
        self._body_layout.addWidget(period_lbl)

        summaries = {p: compute_all_summaries(self._results[p]) for p in pids}

        # KPI table
        self._body_layout.addWidget(self._section_heading("Cost Summary"))
        table_card = QFrame()
        table_card.setObjectName("compTableCard")
        table_card.setStyleSheet(
            f"#compTableCard {{ background: {get_token('surface')}; "
            f"border: 1px solid {get_token('surface_mid')}; "
            f"border-radius: {RADIUS_LG}px; }}"
        )
        tc_lay = QVBoxLayout(table_card)
        tc_lay.setContentsMargins(0, 0, 0, 0)
        tc_lay.addWidget(
            _KPITable(pids, names, summaries,
                      {p: self._caches[p] for p in pids}, self._currency)
        )
        self._body_layout.addWidget(table_card)

        # Color legend
        legend_row = QWidget()
        lr_h = QHBoxLayout(legend_row)
        lr_h.setContentsMargins(SP2, 0, 0, 0)
        lr_h.setSpacing(SP4)
        for i, name in enumerate(names):
            color = _PROJECT_COLORS[i % len(_PROJECT_COLORS)]
            dot = QFrame()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
            lbl = QLabel(name)
            lbl.setFont(_f(FS_SM))
            lbl.setStyleSheet(f"color: {get_token('text_secondary')};")
            dot_wrap = QWidget()
            dw_h = QHBoxLayout(dot_wrap)
            dw_h.setContentsMargins(0, 0, 0, 0)
            dw_h.setSpacing(SP1)
            dw_h.addWidget(dot)
            dw_h.addWidget(lbl)
            lr_h.addWidget(dot_wrap)
        lr_h.addStretch()
        self._body_layout.addWidget(legend_row)

        # Interactive Chart Section
        self._body_layout.addWidget(self._section_heading("Stage Breakdown"))
        
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(SP2, 0, 0, 0)
        filter_row.setSpacing(SP6)
        
        self._stage_checks = {}
        for key, label in zip(_STAGE_KEYS, _STAGE_LABELS):
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setFont(_f(FS_SM, FW_MEDIUM))
            cb.setStyleSheet(f"color: {get_token('text_secondary')};")
            cb.setCursor(Qt.PointingHandCursor)
            cb.stateChanged.connect(lambda: self._on_stage_filter_changed())
            filter_row.addWidget(cb)
            self._stage_checks[key] = cb
        filter_row.addStretch()
        self._body_layout.addLayout(filter_row)

        self._chart = _ComparisonChart(pids, names, summaries, self._currency)
        self._body_layout.addWidget(self._chart)
        self._body_layout.addStretch()



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
