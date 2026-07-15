"""
devtools/integrity_tool_gui.py

File Integrity Checker - records MD5 hashes of static data files
and detects changes (accidental corruption, tampering, unknown edits).

integrity.json (stored in devtools/) is the source of truth.
Each entry records the file path relative to the project root,
its MD5 hash, size, and the timestamp when the hash was last confirmed good.

Workflow
--------
  First run  → Regenerate to establish baseline hashes.
  Later      → Verify to compare current files against baseline.
  After intentional edits (e.g. via Unit Manager) → Regenerate again.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_DEVTOOLS_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT  = os.path.dirname(_DEVTOOLS_DIR)
_INTEGRITY_JSON = os.path.join(_DEVTOOLS_DIR, "integrity.json")

# Default files tracked on first run
_DEFAULT_FILES = [
    "gui/components/utils/units.json",
    "gui/components/structure/registry/material_catalog.json",
    "data/wpi_db.json",
]

# ---------------------------------------------------------------------------
# Style palette (Catppuccin Mocha)
# ---------------------------------------------------------------------------

_BG      = "#1e1e2e"
_BG2     = "#252535"
_BG3     = "#313244"
_SURFACE = "#181825"
_TEXT    = "#cdd6f4"
_DIM     = "#585b70"
_BLUE    = "#89b4fa"
_GREEN   = "#a6e3a1"
_RED     = "#f38ba8"
_YELLOW  = "#f9e2af"
_PEACH   = "#fab387"
_BORDER  = "#2a2a3e"

_BASE_STYLE = f"""
    QDialog, QWidget {{ background: {_BG}; color: {_TEXT}; }}
    QTableWidget {{
        background: {_BG2}; color: {_TEXT};
        gridline-color: {_BORDER}; border: none;
    }}
    QTableWidget QHeaderView::section {{
        background: {_BG3}; color: {_DIM};
        border: none; padding: 4px 8px; font-size: 11px;
    }}
    QTableWidget::item:selected {{ background: {_BG3}; color: {_TEXT}; }}
    QPushButton {{
        background: {_BG3}; color: {_TEXT};
        border: 1px solid {_BORDER}; border-radius: 4px;
        padding: 5px 14px; font-size: 12px;
    }}
    QPushButton:hover {{ background: {_BLUE}; color: {_SURFACE}; }}
    QPushButton:disabled {{ color: {_DIM}; }}
    QLabel {{ color: {_TEXT}; background: transparent; }}
"""

# ---------------------------------------------------------------------------
# Integrity helpers
# ---------------------------------------------------------------------------

def _md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _abs(rel: str) -> str:
    """Resolve a relative path against the project root."""
    path = os.path.normpath(os.path.join(_PROJECT_ROOT, rel))
    if not os.path.exists(path):
        # Try prepending src/three_ps_lcca_gui/
        alt_path = os.path.normpath(os.path.join(_PROJECT_ROOT, "src", "three_ps_lcca_gui", rel))
        if os.path.exists(alt_path):
            return alt_path
    return path


def _rel(abs_path: str) -> str:
    """Make a path relative to the project root, forward slashes."""
    try:
        rel = Path(abs_path).relative_to(_PROJECT_ROOT).as_posix()
        prefix = "src/three_ps_lcca_gui/"
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
        return rel
    except ValueError:
        return Path(abs_path).as_posix()


def _read_integrity() -> dict:
    if not os.path.isfile(_INTEGRITY_JSON):
        return {"_meta": {}, "files": {}}
    with open(_INTEGRITY_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_integrity(data: dict) -> None:
    with open(_INTEGRITY_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _hash_file(rel: str) -> dict:
    """Return a fresh hash record for a file. Raises if missing."""
    abs_path = _abs(rel)
    size = os.path.getsize(abs_path)
    md5  = _md5(abs_path)
    return {
        "md5":        md5,
        "size_bytes": size,
        "regen_at":   datetime.datetime.now().isoformat(),
    }


# Status constants
_OK        = "OK"
_MODIFIED  = "MODIFIED"
_MISSING   = "MISSING"
_NEW       = "NEW"           # tracked but never hashed
_PARSE_ERR = "PARSE_ERROR"   # JSON file but can't be parsed


def _verify_file(rel: str, stored: dict) -> tuple[str, str]:
    """
    Returns (status, detail_message).
    Compares current file against stored hash record.
    """
    abs_path = _abs(rel)

    if not os.path.isfile(abs_path):
        return _MISSING, "File not found on disk."

    if not stored:
        return _NEW, "No baseline hash recorded yet. Run Regenerate."

    # Try JSON parse if it's a .json file
    if rel.endswith(".json"):
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            return _PARSE_ERR, f"JSON parse error: {e}"

    current_md5  = _md5(abs_path)
    current_size = os.path.getsize(abs_path)

    if current_md5 != stored.get("md5"):
        old_size = stored.get("size_bytes", "?")
        return _MODIFIED, (
            f"Hash mismatch.  "
            f"Stored: {stored['md5'][:12]}…  "
            f"Current: {current_md5[:12]}…  "
            f"Size: {old_size} -> {current_size} bytes"
        )

    return _OK, f"MD5 {current_md5[:16]}…  {current_size:,} bytes"


# ---------------------------------------------------------------------------
# Worker thread for verify / regen (avoids UI freeze on large files)
# ---------------------------------------------------------------------------

class _Worker(QThread):
    row_done = Signal(str, str, str)   # rel_path, status, detail
    finished_all = Signal()

    def __init__(self, mode: str, records: dict[str, dict]):
        super().__init__()
        self._mode    = mode     # "verify" or "regen"
        self._records = records  # rel_path -> stored record

    def run(self):
        for rel, stored in self._records.items():
            if self._mode == "verify":
                status, detail = _verify_file(rel, stored)
            else:   # regen
                abs_path = _abs(rel)
                if not os.path.isfile(abs_path):
                    status, detail = _MISSING, "File not found - skipped."
                else:
                    try:
                        rec = _hash_file(rel)
                        self._records[rel] = rec
                        status = _OK
                        detail = f"MD5 {rec['md5'][:16]}…  {rec['size_bytes']:,} bytes"
                    except Exception as e:
                        status, detail = "ERROR", str(e)
            self.row_done.emit(rel, status, detail)
        self.finished_all.emit()


# ---------------------------------------------------------------------------
# Main Dialog
# ---------------------------------------------------------------------------

class IntegrityToolDialog(QDialog):

    _STATUS_COLORS = {
        _OK:        _GREEN,
        _MODIFIED:  _RED,
        _MISSING:   _RED,
        _NEW:       _YELLOW,
        _PARSE_ERR: _RED,
        "ERROR":    _RED,
        "...":      _DIM,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Integrity Checker")
        self.setMinimumSize(900, 480)
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint |
            Qt.WindowMinMaxButtonsHint
        )
        self.setStyleSheet(_BASE_STYLE)
        self._data: dict = {}
        self._worker: _Worker | None = None
        self._build()
        self._load()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(60)
        hdr.setStyleSheet(f"background: {_BG2}; border-bottom: 1px solid {_BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)

        title = QLabel("File Integrity Checker")
        tf = QFont(); tf.setPointSize(12); tf.setBold(True)
        title.setFont(tf)
        hl.addWidget(title)
        hl.addStretch()

        badge = QLabel("integrity.json")
        badge.setStyleSheet(
            f"background: {_BG3}; color: {_DIM}; font-size: 10px;"
            f" border-radius: 3px; padding: 2px 8px;"
        )
        hl.addWidget(badge)
        layout.addWidget(hdr)

        # Toolbar
        tb = QWidget()
        tb.setStyleSheet(f"background: {_BG2}; border-bottom: 1px solid {_BORDER};")
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(16, 8, 16, 8)
        tl.setSpacing(8)

        self._verify_btn = self._action_btn("Verify All", _BLUE)
        self._verify_btn.clicked.connect(self._on_verify)
        tl.addWidget(self._verify_btn)

        self._regen_btn = self._action_btn("Regenerate Hashes", _PEACH)
        self._regen_btn.clicked.connect(self._on_regen)
        tl.addWidget(self._regen_btn)

        tl.addSpacing(12)

        add_btn = QPushButton("+ Track File")
        add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self._on_add_file)
        tl.addWidget(add_btn)

        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setFixedHeight(30)
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove)
        tl.addWidget(self._remove_btn)

        tl.addStretch()

        self._status_lbl = QLabel("Load integrity.json to begin.")
        self._status_lbl.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        tl.addWidget(self._status_lbl)

        layout.addWidget(tb)

        # Table
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["File (relative to project root)", "Status", "Last Regenerated", "Detail"])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 340)
        self._table.setColumnWidth(1, 110)
        self._table.setColumnWidth(2, 170)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            f"QTableWidget {{ alternate-background-color: {_SURFACE}; }}"
        )
        self._table.itemSelectionChanged.connect(
            lambda: self._remove_btn.setEnabled(bool(self._table.selectedItems()))
        )
        layout.addWidget(self._table)

        # Footer
        footer = QWidget()
        footer.setFixedHeight(36)
        footer.setStyleSheet(f"background: {_BG2}; border-top: 1px solid {_BORDER};")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 0, 20, 0)

        self._meta_lbl = QLabel()
        self._meta_lbl.setStyleSheet(f"color: {_DIM}; font-size: 11px;")
        fl.addWidget(self._meta_lbl)
        fl.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(24)
        close_btn.clicked.connect(self.reject)
        fl.addWidget(close_btn)

        layout.addWidget(footer)

    def _action_btn(self, label: str, color: str) -> QPushButton:
        btn = QPushButton(label)
        btn.setFixedHeight(30)
        btn.setStyleSheet(
            f"QPushButton {{ background: {color}; color: {_SURFACE};"
            f" border: none; border-radius: 4px; font-weight: bold; padding: 0 16px; }}"
            f"QPushButton:hover {{ opacity: 0.85; }}"
            f"QPushButton:disabled {{ background: {_BG3}; color: {_DIM}; border: none; }}"
        )
        return btn

    # ── Data ────────────────────────────────────────────────────────────────

    def _load(self):
        self._data = _read_integrity()

        # Seed defaults if fresh
        if not self._data["files"]:
            for rel in _DEFAULT_FILES:
                if os.path.isfile(_abs(rel)):
                    self._data["files"][rel] = {}
            _write_integrity(self._data)

        self._rebuild_table()
        self._update_meta_lbl()

    def _rebuild_table(self, statuses: dict[str, tuple] | None = None):
        files = self._data.get("files", {})
        self._table.setRowCount(len(files))

        for r, (rel, stored) in enumerate(files.items()):
            # File path
            self._table.setItem(r, 0, self._cell(rel))

            # Status
            if statuses and rel in statuses:
                status, detail = statuses[rel]
            elif stored:
                status, detail = "...", "Not verified yet this session."
            else:
                status, detail = _NEW, "No baseline recorded. Run Regenerate."

            self._set_status(r, status, detail, stored)

    def _set_status(self, row: int, status: str, detail: str, stored: dict):
        color = self._STATUS_COLORS.get(status, _DIM)
        s_item = QTableWidgetItem(status)
        s_item.setForeground(QColor(color))
        s_item.setFlags(s_item.flags() & ~Qt.ItemIsEditable)
        self._table.setItem(row, 1, s_item)

        regen_at = stored.get("regen_at", "-")
        if regen_at and regen_at != "-":
            regen_at = regen_at[:19].replace("T", "  ")
        self._table.setItem(row, 2, self._cell(regen_at, _DIM))
        self._table.setItem(row, 3, self._cell(detail))

    def _cell(self, text: str, color: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        if color:
            item.setForeground(QColor(color))
        return item

    def _update_meta_lbl(self):
        meta = self._data.get("_meta", {})
        last = meta.get("last_regen", "Never")
        if last and last != "Never":
            last = last[:19].replace("T", "  ")
        total = len(self._data.get("files", {}))
        self._meta_lbl.setText(
            f"{total} file(s) tracked  |  Last regenerated: {last}"
        )

    # ── Actions ─────────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool):
        self._verify_btn.setEnabled(not busy)
        self._regen_btn.setEnabled(not busy)
        if busy:
            self._status_lbl.setText("Working…")

    def _on_verify(self):
        self._set_busy(True)
        records = dict(self._data.get("files", {}))
        self._statuses: dict[str, tuple] = {}

        self._worker = _Worker("verify", records)
        self._worker.row_done.connect(self._on_row_done_verify)
        self._worker.finished_all.connect(self._on_verify_done)
        self._worker.start()

    def _on_row_done_verify(self, rel: str, status: str, detail: str):
        self._statuses[rel] = (status, detail)
        files = list(self._data["files"].keys())
        if rel in files:
            row = files.index(rel)
            self._set_status(row, status, detail, self._data["files"].get(rel, {}))

    def _on_verify_done(self):
        ok  = sum(1 for s, _ in self._statuses.values() if s == _OK)
        bad = len(self._statuses) - ok
        color = _GREEN if bad == 0 else _RED
        self._status_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
        self._status_lbl.setText(
            f"Verified {len(self._statuses)} file(s) - {ok} OK, {bad} issue(s)"
        )
        self._set_busy(False)
        self._set_busy(False)  # re-enable buttons

    def _on_regen(self):
        reply = QMessageBox.question(
            self, "Regenerate Hashes",
            "This will overwrite all stored hashes with the current file state.\n\n"
            "Only do this after intentional changes (e.g. adding aliases in Unit Manager).\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._set_busy(True)
        records = dict(self._data.get("files", {}))
        self._regen_records = records

        self._worker = _Worker("regen", records)
        self._worker.row_done.connect(self._on_row_done_regen)
        self._worker.finished_all.connect(self._on_regen_done)
        self._worker.start()

    def _on_row_done_regen(self, rel: str, status: str, detail: str):
        files = list(self._data["files"].keys())
        if rel in files:
            row = files.index(rel)
            self._set_status(row, status, detail, self._regen_records.get(rel, {}))

    def _on_regen_done(self):
        # Commit updated hashes to self._data and save
        for rel, rec in self._regen_records.items():
            if rec:
                self._data["files"][rel] = rec
        self._data["_meta"]["last_regen"] = datetime.datetime.now().isoformat()
        self._data["_meta"]["root_hint"]  = os.path.basename(_PROJECT_ROOT)
        _write_integrity(self._data)

        self._update_meta_lbl()
        self._status_lbl.setStyleSheet(f"color: {_GREEN}; font-size: 11px; font-weight: bold;")
        self._status_lbl.setText("Hashes regenerated and saved.")
        self._set_busy(False)

    def _on_add_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File to Track", _PROJECT_ROOT,
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return

        rel = _rel(path)
        if rel in self._data["files"]:
            QMessageBox.information(self, "Already Tracked", f"'{rel}' is already tracked.")
            return

        self._data["files"][rel] = {}
        _write_integrity(self._data)
        self._rebuild_table()
        self._update_meta_lbl()

    def _on_remove(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        rel = self._table.item(rows[0].row(), 0).text()
        if QMessageBox.question(
            self, "Remove", f"Stop tracking '{rel}'?",
            QMessageBox.Yes | QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._data["files"].pop(rel, None)
        _write_integrity(self._data)
        self._rebuild_table()
        self._update_meta_lbl()

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait()
        event.accept()


