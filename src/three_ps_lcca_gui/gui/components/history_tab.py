"""
gui/components/history_tab.py

Comparison History UI components used by the Home page.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QScrollArea,
    QInputDialog, QMessageBox, QMenu, QSizePolicy,
)

import three_ps_lcca_gui.core.start_manager as sm
from three_ps_lcca_gui.gui.themes import get_token, theme_manager
from three_ps_lcca_gui.gui.styles import font as _f, btn_primary
from three_ps_lcca_gui.gui.theme import (
    SP1, SP2, SP3, SP4, SP5, SP6,
    RADIUS_SM, RADIUS_MD, RADIUS_LG,
    BTN_SM, BTN_MD,
    FS_SM, FS_BASE, FS_MD, FS_LG,
    FW_NORMAL, FW_MEDIUM, FW_SEMIBOLD, FW_BOLD,
    FONT_FAMILY,
)


def _rel_time(dt_str: str) -> str:
    """Return a human-friendly relative time string (same logic as home_page)."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str[:19])
    except ValueError:
        return dt_str[:10]
    now = datetime.now()
    secs = int((now - dt).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        m = secs // 60
        return f"{m} min ago" if m > 1 else "1 min ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hrs ago" if h > 1 else "1 hr ago"
    if secs < 172800:
        return "Yesterday"
    if secs < 604800:
        d = secs // 86400
        return f"{d} days ago"
    if secs < 2592000:
        w = secs // 604800
        return f"{w} wks ago" if w > 1 else "1 wk ago"
    fmt = "%b %d" if dt.year == now.year else "%b %d, %Y"
    return dt.strftime(fmt)


def _fmt_date(dt_str: str) -> str:
    """Format an ISO datetime string into a human-friendly relative date."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str[:19])
    except (ValueError, TypeError):
        return dt_str[:10] if dt_str else ""
    now = datetime.now()
    diff = now - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return "Just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    if secs < 172800:
        return "Yesterday"
    if secs < 604800:
        return f"{secs // 86400} days ago"
    fmt = "%b %d" if dt.year == now.year else "%b %d, %Y"
    return dt.strftime(fmt)


class _ElidedLabel(QLabel):
    """
    QLabel that elides text with '...' when horizontal space is constrained,
    allowing cards to shrink and strictly respect the parent window width.
    """
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(20)
        self.setToolTip(text)

    def setText(self, text):
        self._full_text = text
        super().setText(text)
        self.setToolTip(text)
        self.update()

    def minimumSizeHint(self):
        h = super().minimumSizeHint().height()
        return QSize(20, max(16, h))

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = self.fontMetrics()
        elided = metrics.elidedText(self._full_text, Qt.ElideRight, self.width())
        pen_color = self.palette().color(self.foregroundRole())
        painter.setPen(pen_color)
        painter.setFont(self.font())
        painter.drawText(self.rect(), self.alignment() | Qt.AlignVCenter, elided)


class _HomeTabBar(QWidget):
    tab_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 0
        self._btns: list[QPushButton] = []
        self._build()
        theme_manager().theme_changed.connect(self._apply_style)

    def _build(self):
        self.setFixedHeight(40)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(SP6 + SP4, 0, SP6 + SP4, 0)
        lay.setSpacing(0)

        for i, label in enumerate(["Projects", "Comparison History"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFont(_f(FS_BASE, FW_MEDIUM))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(40)
            btn.setProperty("tab_idx", i)
            btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            btn.clicked.connect(self._on_clicked)
            lay.addWidget(btn)
            self._btns.append(btn)

        lay.addStretch()
        self._btns[0].setChecked(True)
        self._apply_style()

    def update_history_count(self, count: int):
        self._btns[1].setText(
            f"Comparison History ({count})" if count > 0 else "Comparison History"
        )

    def set_current(self, idx: int):
        self._current = idx
        for i, btn in enumerate(self._btns):
            btn.setChecked(i == idx)
        self._apply_style()

    def _on_clicked(self):
        sender = self.sender()
        idx = sender.property("tab_idx")
        if idx == self._current:
            return
        for i, btn in enumerate(self._btns):
            btn.setChecked(i == idx)
        self._current = idx
        self._apply_style()
        self.tab_changed.emit(idx)

    def _apply_style(self):
        prim = get_token("primary")
        active = get_token("text")
        muted = get_token("text_secondary")
        for btn in self._btns:
            is_active = btn.isChecked()
            border_bottom = prim if is_active else "transparent"
            text_color = active if is_active else muted
            weight = FW_SEMIBOLD if is_active else FW_NORMAL
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: transparent;"
                f"  border: none;"
                f"  border-bottom: 2px solid {border_bottom};"
                f"  border-radius: 0px;"
                f"  color: {text_color};"
                f"  padding: 0 {SP4}px;"
                f"  font-weight: {weight};"
                f"  font-family: {FONT_FAMILY};"
                f"  font-size: {FS_BASE}pt;"
                f"}}"
                f"QPushButton:hover {{"
                f"  color: {active};"
                f"  background: transparent;"
                f"  border-radius: 0px;"
                f"}}"
            )


class _HistoryRow(QFrame):
    """
    Compact comparison history card (~44px) matching the compact design:
      - Left: project status dots + project names
      - Right: star, relative date, ⚠ warning icon with tooltip, ↗ re-run button, ✕ remove button
    """
    rerun_requested = Signal(dict)
    delete_requested = Signal(int)
    rename_requested = Signal(int, str)
    star_toggled = Signal(int, bool)

    def __init__(self, entry: dict, manager=None, live_caches: dict | None = None, on_disk_pids: set | None = None, parent=None):
        super().__init__(parent)
        self._entry = entry
        self._manager = manager
        self._live_caches = live_caches or {}
        self._on_disk_pids = on_disk_pids or set()
        self._starred = bool(entry.get("is_starred", 0))
        self._build()
        self._apply_style()
        theme_manager().theme_changed.connect(self._apply_style)
        self.setAttribute(Qt.WA_Hover, True)

    def _build(self):
        entry = self._entry
        pids = entry.get("project_ids", [])
        names = entry.get("project_names", [])
        ap = entry.get("analysis_period", 0)
        hid = entry.get("id")

        # ── Compute project availability statuses ─────────────────────────────
        p_status = {}
        avail = {}
        for p in pids:
            is_open = self._manager.is_project_open(p) if self._manager else False
            if p in self._live_caches:
                if is_open:
                    p_status[p] = "not_analysed"
                    avail[p] = False
                else:
                    p_status[p] = "ok"
                    avail[p] = True
            elif p in self._on_disk_pids:
                p_status[p] = "not_analysed"
                avail[p] = False
            else:
                p_status[p] = "missing"
                avail[p] = False

        self._p_status = p_status
        self._avail = avail
        self._avail_count = sum(1 for s in p_status.values() if s == "ok")
        self._n_not_ready = sum(1 for s in p_status.values() if s == "not_analysed")
        self._n_missing = sum(1 for s in p_status.values() if s == "missing")
        self._all_ok = (self._avail_count == len(pids))

        # ── Card Container Setup (~44px compact height) ──────────────────────
        self.setObjectName("histCard")
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card_h = QHBoxLayout(self)
        card_h.setContentsMargins(SP4, 0, SP3, 0)
        card_h.setSpacing(SP3)

        # Full tooltip on card for extra context
        ap_text = f"Analysis period: {ap} yrs" if ap > 0 else "Each project uses its own analysis period"
        label = entry.get("label", "Comparison")
        self.setToolTip(f"{label}\n{ap_text}\nRight-click for options")

        # ── Left: Project status dots + names ─────────────────────────────────
        projects_h = QHBoxLayout()
        projects_h.setContentsMargins(0, 0, 0, 0)
        projects_h.setSpacing(SP4)

        self._dot_widgets = []
        for pid, name in zip(pids, names):
            st = p_status.get(pid, "missing")
            dw_h = QHBoxLayout()
            dw_h.setContentsMargins(0, 0, 0, 0)
            dw_h.setSpacing(SP2)

            dot = QFrame()
            dot.setFixedSize(8, 8)

            name_lbl = _ElidedLabel(name)
            name_lbl.setFont(_f(FS_SM, FW_MEDIUM))

            dw_h.addWidget(dot, 0, Qt.AlignVCenter)
            dw_h.addWidget(name_lbl, 0, Qt.AlignVCenter)
            projects_h.addLayout(dw_h)
            self._dot_widgets.append((dot, name_lbl, st))

        # If custom AP (>0), show a subtle pill badge
        if ap > 0:
            ap_badge = QLabel(f"{ap} yrs")
            ap_badge.setFont(_f(FS_SM))
            ap_badge.setStyleSheet(
                f"color: {get_token('text_secondary')}; background: {get_token('surface_mid')};"
                f"border-radius: 3px; padding: 1px 6px;"
            )
            projects_h.addWidget(ap_badge, 0, Qt.AlignVCenter)

        projects_h.addStretch(1)
        card_h.addLayout(projects_h, 1)

        # ── Right: Star, Date, ⚠ Warning, ↗ Re-run, ✕ Remove ─────────────────
        right_h = QHBoxLayout()
        right_h.setContentsMargins(0, 0, 0, 0)
        right_h.setSpacing(SP3)
        right_h.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Date
        self._date_lbl = QLabel(_fmt_date(entry.get("compared_at", "")))
        self._date_lbl.setFont(_f(FS_SM))
        self._date_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        right_h.addWidget(self._date_lbl, 0, Qt.AlignVCenter)

        # Star toggle
        self._star_btn = QPushButton("★" if self._starred else "☆")
        self._star_btn.setFixedSize(24, 24)
        self._star_btn.setFont(_f(FS_BASE))
        self._star_btn.setCursor(Qt.PointingHandCursor)
        self._star_btn.setToolTip("Star comparison" if not self._starred else "Unstar comparison")
        self._star_btn.clicked.connect(self._on_star_clicked)
        right_h.addWidget(self._star_btn, 0, Qt.AlignVCenter)

        # Warning / error icon
        self._warn_lbl = None
        if not self._all_ok:
            if self._n_not_ready > 0:
                note_text = "One or more projects are not analysed. Please run and make ready for comparison."
            else:
                s_plural = "s" if self._n_missing > 1 else ""
                note_text = f"{self._n_missing} project{s_plural} no longer available on disk - will be excluded"

            self._warn_lbl = QLabel("⚠")
            self._warn_lbl.setFont(_f(FS_BASE, FW_BOLD))
            self._warn_lbl.setCursor(Qt.PointingHandCursor)
            self._warn_lbl.setToolTip(f"⚠ {note_text}")
            right_h.addWidget(self._warn_lbl, 0, Qt.AlignVCenter)

        # Re-run button (28x28 square)
        self._rerun_btn = QPushButton("↗")
        self._rerun_btn.setFixedSize(28, 28)
        self._rerun_btn.setFont(_f(FS_MD, FW_BOLD))
        self._rerun_btn.setCursor(Qt.PointingHandCursor if self._avail_count >= 2 else Qt.ForbiddenCursor)
        self._rerun_btn.setEnabled(self._avail_count >= 2)
        self._rerun_btn.setToolTip("Re-run this comparison" if self._avail_count >= 2 else "At least 2 valid analysed projects required")
        self._rerun_btn.clicked.connect(lambda: self.rerun_requested.emit(self._entry))
        right_h.addWidget(self._rerun_btn, 0, Qt.AlignVCenter)

        # Remove button (28x28 square)
        self._del_btn = QPushButton("✕")
        self._del_btn.setFixedSize(28, 28)
        self._del_btn.setFont(_f(FS_SM, FW_BOLD))
        self._del_btn.setToolTip("Remove from history")
        self._del_btn.setCursor(Qt.PointingHandCursor)
        self._del_btn.clicked.connect(lambda: self.delete_requested.emit(hid))
        right_h.addWidget(self._del_btn, 0, Qt.AlignVCenter)

        card_h.addLayout(right_h)

    def _apply_style(self):
        prim = get_token("primary")
        surf = get_token("surface")
        mid = get_token("surface_mid")
        text_color = get_token("text")
        sec_color = get_token("text_secondary")
        star_col = get_token("warning") if self._starred else get_token("text_disabled")

        self.setStyleSheet(
            f"#histCard {{"
            f"  background: {surf};"
            f"  border: 1px solid {mid};"
            f"  border-radius: {RADIUS_MD}px;"
            f"}}"
            f"#histCard:hover {{ border-color: {prim}; }}"
            f"QToolTip {{"
            f"  background-color: {surf};"
            f"  color: {text_color};"
            f"  border: 1px solid {mid};"
            f"  border-radius: {RADIUS_SM}px;"
            f"  padding: 5px 9px;"
            f"  font-family: {FONT_FAMILY};"
            f"  font-size: {FS_SM}pt;"
            f"}}"
        )

        # Status dots & labels
        for dot, name_lbl, st in getattr(self, "_dot_widgets", []):
            if st == "ok":
                dot_color = get_token("success")
                lbl_color = text_color
            elif st == "not_analysed":
                dot_color = get_token("warning")
                lbl_color = text_color
            else:
                dot_color = get_token("danger")
                lbl_color = get_token("danger")
            dot.setStyleSheet(f"background: {dot_color}; border-radius: 4px; border: none;")
            name_lbl.setStyleSheet(f"color: {lbl_color}; background: transparent; border: none;")

        self._date_lbl.setStyleSheet(f"color: {sec_color}; background: transparent; border: none;")

        if self._warn_lbl is not None:
            w_col = get_token("warning" if self._n_not_ready > 0 else "danger")
            self._warn_lbl.setStyleSheet(f"color: {w_col}; background: transparent; border: none; padding: 0 2px;")

        # Re-run button styling (borderless)
        if self._avail_count >= 2:
            self._rerun_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: transparent;"
                f"  border: none;"
                f"  color: {text_color};"
                f"  padding: 0;"
                f"}}"
                f"QPushButton:hover {{ color: {prim}; }}"
            )
        else:
            self._rerun_btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: transparent;"
                f"  border: none;"
                f"  color: {get_token('text_disabled')};"
                f"  padding: 0;"
                f"}}"
            )

        # Delete button styling (borderless)
        self._del_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent;"
            f"  border: none;"
            f"  color: {sec_color};"
            f"  padding: 0;"
            f"}}"
            f"QPushButton:hover {{ color: {get_token('danger')}; }}"
        )

        # Star button styling
        self._star_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {star_col}; padding: 0; }}"
            f"QPushButton:hover {{ color: {get_token('warning')}; }}"
        )

    def _on_star_clicked(self):
        self._starred = not self._starred
        self._star_btn.setText("★" if self._starred else "☆")
        self._apply_style()
        self.star_toggled.emit(self._entry["id"], self._starred)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        if self._avail_count >= 2:
            menu.addAction("Re-run  ↗", lambda: self.rerun_requested.emit(self._entry))
        menu.addAction("Rename", lambda: self.rename_requested.emit(
            self._entry["id"], self._entry.get("label", "")))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self.delete_requested.emit(self._entry["id"]))
        menu.exec(event.globalPos())


class _PaginationBar(QWidget):
    page_changed = Signal(int)
    _BTN_SZ = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 1
        self._total = 1
        self._build()
        theme_manager().theme_changed.connect(self._rebuild_page_btns)

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, SP3, 0, SP2)
        lay.setSpacing(SP2)
        lay.addStretch()

        self._prev = QPushButton("‹")
        self._prev.setFixedSize(self._BTN_SZ, self._BTN_SZ)
        self._prev.setFont(_f(FS_LG))
        self._prev.setCursor(Qt.PointingHandCursor)
        self._prev.clicked.connect(lambda: self._emit(self._current - 1))
        lay.addWidget(self._prev)

        self._pages_widget = QWidget()
        self._pages_layout = QHBoxLayout(self._pages_widget)
        self._pages_layout.setContentsMargins(0, 0, 0, 0)
        self._pages_layout.setSpacing(SP1)
        lay.addWidget(self._pages_widget)

        self._next = QPushButton("›")
        self._next.setFixedSize(self._BTN_SZ, self._BTN_SZ)
        self._next.setFont(_f(FS_LG))
        self._next.setCursor(Qt.PointingHandCursor)
        self._next.clicked.connect(lambda: self._emit(self._current + 1))
        lay.addWidget(self._next)

        lay.addStretch()
        self._refresh_nav_style()

    def set_state(self, current: int, total: int):
        self._current = current
        self._total = total
        self._rebuild_page_btns()
        self._refresh_nav_style()

    def _emit(self, page: int):
        if 1 <= page <= self._total and page != self._current:
            self.page_changed.emit(page)

    def _visible_pages(self) -> list:
        t, c = self._total, self._current
        if t <= 7:
            return list(range(1, t + 1))
        pages = [1]
        if c > 3:
            pages.append(None)
        for p in range(max(2, c - 1), min(t, c + 2)):
            pages.append(p)
        if c < t - 2:
            pages.append(None)
        pages.append(t)
        return pages

    def _rebuild_page_btns(self):
        while self._pages_layout.count():
            item = self._pages_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        prim = get_token("primary")
        base = get_token("base")
        mid = get_token("surface_mid")
        muted = get_token("text_secondary")

        for p in self._visible_pages():
            if p is None:
                dot = QLabel("…")
                dot.setFont(_f(FS_SM))
                dot.setAlignment(Qt.AlignCenter)
                dot.setStyleSheet(f"color: {muted};")
                dot.setFixedSize(self._BTN_SZ, self._BTN_SZ)
                self._pages_layout.addWidget(dot)
            else:
                btn = QPushButton(str(p))
                btn.setFixedSize(self._BTN_SZ, self._BTN_SZ)
                btn.setFont(_f(FS_SM, FW_MEDIUM))
                btn.setCursor(Qt.PointingHandCursor)
                is_active = (p == self._current)
                if is_active:
                    btn.setStyleSheet(
                        f"QPushButton {{"
                        f"  background: {prim}; color: {base}; border: none;"
                        f"  border-radius: {RADIUS_SM}px;"
                        f"}}"
                    )
                else:
                    btn.setStyleSheet(
                        f"QPushButton {{"
                        f"  background: transparent;"
                        f"  border: 1px solid {mid};"
                        f"  color: {muted};"
                        f"  border-radius: {RADIUS_SM}px;"
                        f"}}"
                        f"QPushButton:hover {{ border-color: {prim}; color: {prim}; }}"
                    )
                pg = p
                btn.clicked.connect(lambda _, pg=pg: self._emit(pg))
                self._pages_layout.addWidget(btn)

    def _refresh_nav_style(self):
        prim = get_token("primary")
        mid = get_token("surface_mid")
        muted = get_token("text_secondary")
        dis = get_token("text_disabled")
        nav_ss = (
            f"QPushButton {{"
            f"  background: transparent; border: 1px solid {mid};"
            f"  color: {muted}; border-radius: {RADIUS_SM}px;"
            f"}}"
            f"QPushButton:hover {{ border-color: {prim}; color: {prim}; }}"
            f"QPushButton:disabled {{ color: {dis}; border-color: {mid}; }}"
        )
        self._prev.setStyleSheet(nav_ss)
        self._next.setStyleSheet(nav_ss)
        self._prev.setEnabled(self._current > 1)
        self._next.setEnabled(self._current < self._total)


def _do_rerun(entry: dict, manager=None, picker_panel=None, parent_widget=None):
    """
    Rerun comparison matching comparison_page._rerun_comparison logic:
      1. Check missing projects on disk
      2. Check projects open for editing in manager
      3. Filter available and valid cached projects
      4. Guard minimum 2 projects
      5. Window deduplication / activation
      6. Launch ComparisonResultWindow
    """
    from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
        ComparisonResultWindow, _read_cache_from_disk,
    )
    from three_ps_lcca_gui.core.safechunk_engine import SafeChunkEngine

    pids = entry.get("project_ids", [])
    names = entry.get("project_names", [])
    ap = entry.get("analysis_period", 0)

    base = Path(SafeChunkEngine.get_default_base_dir())

    # 1. Missing on disk
    missing_on_disk = [names[i] for i, pid in enumerate(pids) if not (base / pid).exists()]
    if missing_on_disk:
        QMessageBox.warning(
            parent_widget, "Projects Missing",
            "The following projects no longer exist on disk and cannot be re-run:\n\n- " +
            "\n- ".join(missing_on_disk)
        )
        return

    # 2. Open for editing
    if manager:
        open_projects = [names[i] for i, pid in enumerate(pids) if manager.is_project_open(pid)]
        if open_projects:
            QMessageBox.information(
                parent_widget, "Project Open for Editing",
                "The following projects are currently open for editing and cannot be included in a comparison re-run:\n\n- " +
                "\n- ".join(open_projects) +
                "\n\nPlease close these projects before re-running the comparison."
            )
            return

    # 3. Cache readiness
    caches = {p: _read_cache_from_disk(base, p) for p in pids}
    caches = {p: c for p, c in caches.items() if c.get("is_valid")}

    avail_pids = [p for p in pids if p in caches]
    avail_names = [names[pids.index(p)] for p in avail_pids]

    if len(avail_pids) < 2:
        missing_names = [names[i] for i, p in enumerate(pids) if p not in caches]
        msg = "At least 2 projects with valid analyses are needed to re-run the comparison.\n\n"
        if missing_names:
            msg += "The following projects are not analysed or not ready:\n- "
            msg += "\n- ".join(missing_names)
        else:
            msg += "Some projects may have been deleted or modified."
        QMessageBox.warning(parent_widget, "Cannot Re-run", msg)
        return

    project_set = frozenset(avail_pids)
    if picker_panel is not None:
        existing = picker_panel._open_windows.get(project_set)
        if existing and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

    win = ComparisonResultWindow(
        pids=avail_pids, names=avail_names,
        caches=caches, override_ap=ap,
    )
    win.show()
    if picker_panel is not None:
        picker_panel._open_windows[project_set] = win


class _ComparisonHistoryTab(QWidget):
    PAGE_SIZE = 10
    history_changed = Signal()

    def __init__(self, manager=None, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._picker_panel = None
        self._search_text = ""
        self._page = 1
        self._total = 0
        self._build()
        theme_manager().theme_changed.connect(self._apply_theme)

    def set_picker_panel(self, panel):
        self._picker_panel = panel

    def set_manager(self, manager):
        self._manager = manager

    def refresh(self):
        self._page = 1
        self._render()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP6 + SP4, SP4, SP6 + SP4, SP3)
        lay.setSpacing(SP3)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search comparisons…")
        self._search.setFixedHeight(34)
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        lay.addWidget(self._search)

        self._hint_lbl = QLabel("ℹ  Each project uses its own analysis period · hover ⚠ for details")
        self._hint_lbl.setFont(_f(FS_SM))
        lay.addWidget(self._hint_lbl)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._rows_container = QWidget()
        self._rows_container.setStyleSheet("background: transparent;")
        self._rows_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(SP2)
        scroll.setWidget(self._rows_container)
        lay.addWidget(scroll, 1)

        self._pager = _PaginationBar()
        self._pager.page_changed.connect(self._go_page)
        lay.addWidget(self._pager)

        self._apply_theme()
        self._render()

    def _on_search(self, text: str):
        self._search_text = text.strip().lower()
        self._page = 1
        self._render()

    def _go_page(self, page: int):
        self._page = page
        self._render()

    def _render(self):
        from three_ps_lcca_gui.core.safechunk_engine import SafeChunkEngine
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import _read_cache_from_disk

        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Build live cache and on-disk set for project status resolution
        base = Path(SafeChunkEngine.get_default_base_dir())
        projects = SafeChunkEngine.list_all_projects(str(base))
        live_caches = {}
        on_disk_pids = {proj["project_id"] for proj in projects}
        for proj in projects:
            if not proj.get("user_meta", {}).get("fit_for_comparison"):
                continue
            c = _read_cache_from_disk(base, proj["project_id"])
            if c.get("is_valid"):
                live_caches[proj["project_id"]] = c

        all_entries = sm.get_comparison_history(limit=5000)

        q = self._search_text
        if q:
            all_entries = [
                e for e in all_entries
                if q in e.get("label", "").lower()
                or any(q in n.lower() for n in e.get("project_names", []))
            ]

        self._total = len(all_entries)

        start = (self._page - 1) * self.PAGE_SIZE
        page_entries = all_entries[start: start + self.PAGE_SIZE]

        if not page_entries:
            empty = QLabel("No comparisons found.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setFont(_f(FS_BASE))
            empty.setStyleSheet(f"color: {get_token('text_disabled')};")
            self._rows_layout.addWidget(empty)
        else:
            for entry in page_entries:
                row = _HistoryRow(
                    entry,
                    manager=self._manager,
                    live_caches=live_caches,
                    on_disk_pids=on_disk_pids,
                )
                row.rerun_requested.connect(self._on_rerun)
                row.delete_requested.connect(self._on_delete)
                row.rename_requested.connect(self._on_rename)
                row.star_toggled.connect(self._on_star)
                self._rows_layout.addWidget(row)

        self._rows_layout.addStretch()

        total_pages = max(1, (self._total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._pager.set_state(self._page, total_pages)
        self._pager.setVisible(total_pages > 1)

    def _on_rerun(self, entry: dict):
        _do_rerun(
            entry,
            manager=self._manager,
            picker_panel=self._picker_panel,
            parent_widget=self,
        )

    def _on_delete(self, history_id: int):
        entries = sm.get_comparison_history()
        entry = next((e for e in entries if e["id"] == history_id), None)
        label = entry["label"] if entry else "this comparison"
        res = QMessageBox.warning(
            self, "Remove Comparison",
            f"Remove '{label}' from history?\n\n"
            "This only removes the history record. Project data is unaffected.",
            QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if res == QMessageBox.Ok:
            sm.delete_comparison(history_id)
            if self._page > 1 and (self._total - 1) <= (self._page - 1) * self.PAGE_SIZE:
                self._page = max(1, self._page - 1)
            self._render()
            self.history_changed.emit()

    def _on_rename(self, history_id: int, current_label: str):
        new_label, ok = QInputDialog.getText(
            self, "Rename Comparison", "New name:", text=current_label
        )
        if ok and new_label.strip() and new_label.strip() != current_label:
            sm.rename_comparison(history_id, new_label.strip())
            self._render()

    def _on_star(self, history_id: int, starred: bool):
        sm.star_comparison(history_id, starred)

    def _apply_theme(self):
        prim = get_token("primary")
        surf = get_token("surface")
        mid = get_token("surface_mid")
        text_color = get_token("text")
        self.setStyleSheet(
            f"QToolTip {{"
            f"  background-color: {surf};"
            f"  color: {text_color};"
            f"  border: 1px solid {mid};"
            f"  border-radius: {RADIUS_SM}px;"
            f"  padding: 5px 9px;"
            f"  font-family: {FONT_FAMILY};"
            f"  font-size: {FS_SM}pt;"
            f"}}"
        )
        self._search.setStyleSheet(
            f"QLineEdit {{"
            f"  background: {surf};"
            f"  border: 1px solid {mid};"
            f"  border-radius: {RADIUS_MD}px;"
            f"  padding: 0 {SP3}px;"
            f"  color: {text_color};"
            f"  font-size: {FS_BASE}pt;"
            f"}}"
            f"QLineEdit:focus {{ border-color: {prim}; }}"
        )
        if hasattr(self, "_hint_lbl"):
            self._hint_lbl.setStyleSheet(f"color: {get_token('text_secondary')}; padding-left: 2px;")
