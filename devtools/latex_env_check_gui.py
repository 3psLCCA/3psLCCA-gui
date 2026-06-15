"""
devtools/latex_env_check_gui.py

Checks REQUIRED_LATEX_PACKAGES against the static osdag_latex_bundle_packages.py list.
Tab 1: required packages — available vs missing.
Tab 2: full bundle list as a copyable Python literal.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

_BG      = "#1e1e2e"
_BG2     = "#252535"
_BG3     = "#313244"
_TEXT    = "#cdd6f4"
_DIM     = "#585b70"
_GREEN   = "#a6e3a1"
_RED     = "#f38ba8"
_BLUE    = "#89b4fa"
_BORDER  = "#2a2a3e"
_SURFACE = "#181825"

_SRC = Path(__file__).resolve().parent.parent / "src"


class LatexEnvCheckDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LaTeX Bundle Package Check")
        self.setMinimumSize(620, 520)
        self.setStyleSheet(f"QDialog {{ background:{_BG}; }}")
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        title = QLabel("LaTeX Bundle Package Check")
        tf = QFont(); tf.setPointSize(12); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{_TEXT};")
        root.addWidget(title)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{_DIM}; font-size:10px; font-family:monospace;")
        root.addWidget(self._status)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            f"QTabWidget::pane {{ border:1px solid {_BORDER}; background:{_BG2}; border-radius:4px; }}"
            f"QTabBar::tab {{ background:{_BG3}; color:{_DIM}; padding:6px 14px; border:none; }}"
            f"QTabBar::tab:selected {{ background:{_BG2}; color:{_TEXT}; }}"
        )
        root.addWidget(self._tabs, stretch=1)

        btn_row = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setFixedHeight(30)
        refresh.setStyleSheet(
            f"QPushButton {{ background:{_BLUE}; color:{_SURFACE}; border:none;"
            f" border-radius:4px; font-weight:bold; font-size:11px; }}"
            f"QPushButton:hover {{ background:#b4d0fa; }}"
        )
        refresh.clicked.connect(self._run)
        btn_row.addWidget(refresh)
        btn_row.addStretch()

        close = QPushButton("Close")
        close.setFixedHeight(30)
        close.setStyleSheet(
            f"QPushButton {{ background:{_BG3}; color:{_TEXT}; border:none;"
            f" border-radius:4px; font-size:11px; }}"
            f"QPushButton:hover {{ background:#44475a; }}"
        )
        close.clicked.connect(self.close)
        btn_row.addWidget(close)
        root.addLayout(btn_row)

        self._run()

    def _run(self):
        self._tabs.clear()

        if str(_SRC) not in sys.path:
            sys.path.insert(0, str(_SRC))

        try:
            from osdag_latex_bundle_packages import list_of_lib_av
        except Exception as exc:
            self._status.setText(f"Cannot load osdag_latex_bundle_packages.py: {exc}")
            self._status.setStyleSheet(f"color:{_RED}; font-size:10px;")
            return

        try:
            from three_ps_lcca_gui.code_to_latex.SETTINGS import REQUIRED_LATEX_PACKAGES
        except Exception as exc:
            self._status.setText(f"Cannot load SETTINGS: {exc}")
            self._status.setStyleSheet(f"color:{_RED}; font-size:10px;")
            return

        bundle = set(list_of_lib_av)
        available = [p for p in REQUIRED_LATEX_PACKAGES if p in bundle]
        missing   = [p for p in REQUIRED_LATEX_PACKAGES if p not in bundle]

        self._status.setText(
            f"Source: osdag_latex_bundle_packages.py  |  {len(list_of_lib_av)} packages"
        )
        self._status.setStyleSheet(f"color:{_GREEN}; font-size:10px; font-family:monospace;")

        self._tabs.addTab(
            _required_tab(available, missing),
            f"Required ({len(available)}/{len(REQUIRED_LATEX_PACKAGES)} ok)",
        )
        self._tabs.addTab(
            _bundle_tab(list_of_lib_av),
            f"All Bundle Packages ({len(list_of_lib_av)})",
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _scroll(inner: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QScrollArea.Shape.NoFrame)
    s.setStyleSheet(
        f"QScrollArea {{ background:{_BG2}; border:none; }}"
        f"QScrollBar:vertical {{ background:{_BG2}; width:6px; border:none; }}"
        f"QScrollBar::handle:vertical {{ background:{_BG3}; border-radius:3px; }}"
    )
    s.setWidget(inner)
    return s


def _required_tab(available: list, missing: list) -> QWidget:
    inner = QWidget()
    inner.setStyleSheet(f"background:{_BG2};")
    vl = QVBoxLayout(inner)
    vl.setContentsMargins(14, 12, 14, 12)
    vl.setSpacing(3)

    summary = QLabel(f"{len(available)} available   •   {len(missing)} missing")
    sf = QFont(); sf.setBold(True)
    summary.setFont(sf)
    summary.setStyleSheet(
        f"color:{_GREEN if not missing else _RED}; font-size:12px; padding-bottom:8px;"
    )
    vl.addWidget(summary)

    for pkg in available:
        vl.addWidget(_row(pkg, ok=True,  tag="in bundle"))
    for pkg in missing:
        vl.addWidget(_row(pkg, ok=False, tag="MISSING"))
    vl.addStretch()

    w = QWidget(); w.setStyleSheet(f"background:{_BG2};")
    wl = QVBoxLayout(w)
    wl.setContentsMargins(0, 0, 0, 0)
    wl.addWidget(_scroll(inner))
    return w


def _bundle_tab(packages: list) -> QWidget:
    w = QWidget()
    w.setStyleSheet(f"background:{_BG2};")
    vl = QVBoxLayout(w)
    vl.setContentsMargins(14, 12, 14, 12)
    vl.setSpacing(6)

    vl.addWidget(_lbl(f"{len(packages)} packages  —  read-only"))

    lines = [
        "    " + ", ".join(f'"{p}"' for p in packages[i:i+6]) + ","
        for i in range(0, len(packages), 6)
    ]
    editor = QPlainTextEdit("list_of_lib_av = [\n" + "\n".join(lines) + "\n]")
    editor.setReadOnly(True)
    editor.setStyleSheet(
        f"QPlainTextEdit {{ background:{_SURFACE}; color:{_TEXT};"
        f" font-family:Consolas,monospace; font-size:11px;"
        f" border:1px solid {_BORDER}; border-radius:4px; padding:8px; }}"
    )
    vl.addWidget(editor, stretch=1)

    btn = QPushButton("Copy to Clipboard")
    btn.setFixedHeight(28)
    btn.setStyleSheet(
        f"QPushButton {{ background:{_BG3}; color:{_TEXT}; border:none;"
        f" border-radius:4px; font-size:11px; }}"
        f"QPushButton:hover {{ background:#44475a; }}"
    )
    btn.clicked.connect(lambda: _copy(editor.toPlainText(), btn))
    vl.addWidget(btn, alignment=Qt.AlignRight)
    return w


def _lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color:{_DIM}; font-size:10px;")
    return l


def _row(pkg: str, ok: bool, tag: str = "") -> QWidget:
    w = QWidget(); w.setStyleSheet("background:transparent;")
    hl = QHBoxLayout(w)
    hl.setContentsMargins(4, 1, 4, 1)
    hl.setSpacing(8)

    dot = QLabel("✓" if ok else "✗")
    dot.setFixedWidth(14)
    dot.setAlignment(Qt.AlignCenter)
    dot.setStyleSheet(f"color:{'#a6e3a1' if ok else '#f38ba8'}; font-weight:bold;")
    hl.addWidget(dot)

    name = QLabel(pkg)
    name.setStyleSheet(f"color:{'#cdd6f4' if ok else '#f38ba8'}; font-size:11px;")
    hl.addWidget(name)
    hl.addStretch()

    if tag:
        tl = QLabel(tag)
        tl.setStyleSheet(
            f"color:{'#585b70' if ok else '#f38ba8'}; font-size:10px;"
            f"{'font-weight:bold;' if not ok else ''}"
        )
        hl.addWidget(tl)
    return w


def _copy(text: str, btn: QPushButton):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    QApplication.clipboard().setText(text)
    btn.setText("Copied!")
    QTimer.singleShot(1500, lambda: btn.setText("Copy to Clipboard"))
