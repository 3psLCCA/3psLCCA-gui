"""
devtools/catalog_builder_gui.py

Catalog Builder - inspect, validate, and rebuild material_catalog.json.

Features:
  - Auto-detect material_database root from the project tree
  - Browse to a custom root
  - Load and display the existing registry manifest in a table
  - Rebuild the registry (re-crawl all JSON files)
  - Run integrity check on any selected database entry
  - Show per-entry errors and warnings in the log

material_catalog.py is located by walking up from a known anchor
(devtools/ → project root → registry/).

"""

from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Style palette (Catppuccin Mocha)
# ---------------------------------------------------------------------------

_BG      = "#1e1e2e"
_BG2     = "#252535"
_BG3     = "#313244"
_SURFACE = "#1a1a2e"
_TEXT    = "#cdd6f4"
_DIM     = "#585b70"
_GREEN   = "#a6e3a1"
_YELLOW  = "#f9e2af"
_ORANGE  = "#fab387"
_RED     = "#f38ba8"
_BLUE    = "#89b4fa"
_TEAL    = "#94e2d5"
_MAUVE   = "#cba6f7"
_BORDER  = "#333"

_BTN = (
    f"QPushButton {{ background:{_BG3}; color:{_TEXT}; border:1px solid #444;"
    f" border-radius:4px; padding:0 14px; }}"
    f"QPushButton:hover:enabled {{ background:#45475a; }}"
    f"QPushButton:disabled {{ color:{_DIM}; border-color:{_BORDER}; background:{_BG2}; }}"
)
_BTN_BLUE = (
    f"QPushButton {{ background:{_BLUE}; color:{_BG}; border:none;"
    f" border-radius:4px; padding:0 18px; font-weight:bold; }}"
    f"QPushButton:hover:enabled {{ background:#b4d0f7; }}"
    f"QPushButton:disabled {{ background:{_BG3}; color:{_DIM}; }}"
)
_BTN_MAUVE = (
    f"QPushButton {{ background:{_MAUVE}; color:{_BG}; border:none;"
    f" border-radius:4px; padding:0 18px; font-weight:bold; }}"
    f"QPushButton:hover:enabled {{ background:#dbb6ff; }}"
    f"QPushButton:disabled {{ background:{_BG3}; color:{_DIM}; }}"
)
_BTN_TEAL = (
    f"QPushButton {{ background:{_TEAL}; color:{_BG}; border:none;"
    f" border-radius:4px; padding:0 14px; font-weight:bold; }}"
    f"QPushButton:hover:enabled {{ background:#b0f0e8; }}"
    f"QPushButton:disabled {{ background:{_BG3}; color:{_DIM}; }}"
)
_INPUT = (
    f"QLineEdit {{ background:{_SURFACE}; color:{_TEXT}; border:1px solid #444;"
    f" border-radius:3px; padding:4px 8px; }}"
    f"QLineEdit:focus {{ border-color:{_BLUE}; }}"
)
_TABLE = (
    f"QTableWidget {{ background:{_SURFACE}; color:{_TEXT}; border:1px solid {_BORDER};"
    f" gridline-color:#2a2a3e; }}"
    f"QTableWidget::item {{ padding:3px 8px; }}"
    f"QTableWidget::item:selected {{ background:{_BG3}; }}"
    f"QHeaderView::section {{ background:{_BG2}; color:{_DIM}; border:none;"
    f" border-bottom:1px solid {_BORDER}; padding:4px 8px;"
    f" font-size:11px; font-weight:bold; }}"
)
_LOG = (
    f"QPlainTextEdit {{ background:{_SURFACE}; color:{_DIM}; border:1px solid {_BORDER};"
    f" font-family:Consolas,monospace; font-size:11px; }}"
)

# Table column indices
_COL_KEY     = 0
_COL_COUNTRY = 1
_COL_REGION  = 2
_COL_STATUS  = 3
_COL_RECORDS = 4
_COL_ERRORS  = 5
_COL_WARNS   = 6
_NCOLS       = 7


# ---------------------------------------------------------------------------
# Helpers - locate material_catalog.py
# ---------------------------------------------------------------------------


def _auto_detect_catalog_py() -> Path | None:
    """
    Try to find material_catalog.py relative to this devtools file's location.
    Expected structure:
        <project>/devtools/catalog_builder_gui.py  ← this file
        <project>/src/three_ps_lcca_gui/gui/components/structure/registry/material_catalog.py
    """
    here = Path(__file__).resolve().parent          # devtools/
    project_root = here.parent                      # <project>/
    candidate = (
        project_root
        / "src" / "three_ps_lcca_gui" / "gui" / "components" / "structure" / "registry"
        / "material_catalog.py"
    )
    return candidate if candidate.exists() else None


def _load_catalog_module(reg_py: Path) -> ModuleType | None:
    try:
        spec = importlib.util.spec_from_file_location("_material_catalog_tool", str(reg_py))
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------


class _RebuildWorker(QThread):
    finished = Signal(dict)   # full manifest
    error    = Signal(str)

    def __init__(self, mod: ModuleType, root: str, manifest_path: str):
        super().__init__()
        self._mod           = mod
        self._root          = root
        self._manifest_path = manifest_path

    def run(self):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                manifest = self._mod.build_registry(self._root, self._manifest_path)
            self.finished.emit(manifest)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")


class _IntegrityWorker(QThread):
    finished = Signal(dict)   # report
    error    = Signal(str)

    def __init__(self, mod: ModuleType, file_path: str):
        super().__init__()
        self._mod  = mod
        self._path = file_path

    def run(self):
        try:
            report = self._mod.check_integrity_by_path(self._path)
            self.finished.emit(report)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------


class CatalogBuilderDialog(QDialog):
    """
    Registry Builder dialog.

    Workflow:
      1. Root auto-detected (or browse to a material_database/ folder)
      2. Click Load  → reads existing material_catalog.json into the table
      3. Select a row and click Check Integrity for a single-entry report
      4. Click Rebuild Registry → re-crawls all *.json files, refreshes table
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registry Builder")
        self.setMinimumSize(860, 600)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowMinimizeButtonHint
            & ~Qt.WindowContextHelpButtonHint
        )
        self.setStyleSheet(f"QDialog {{ background:{_BG}; color:{_TEXT}; }}")

        self._mod: ModuleType | None = None       # loaded material_catalog module
        self._manifest: dict = {}                 # last loaded / built manifest
        self._worker: QThread | None = None

        self._build_ui()
        self._auto_load()

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(10)

        # Title
        title = QLabel("Registry Builder")
        tf = QFont(); tf.setPointSize(12); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{_TEXT};")
        root_layout.addWidget(title)

        desc = QLabel(
            "Crawls the material_database/ folder, validates every SOR JSON file,\n"
            "and writes material_catalog.json used by the search engine and material dialog."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        root_layout.addWidget(desc)

        root_layout.addWidget(self._sep())

        # Root path row
        root_layout.addWidget(self._lbl("material_database/ root"))
        path_row = QHBoxLayout()
        self._root_edit = QLineEdit()
        self._root_edit.setPlaceholderText("Auto-detected from project structure…")
        self._root_edit.setStyleSheet(_INPUT)
        self._root_edit.textChanged.connect(self._on_root_changed)
        path_row.addWidget(self._root_edit)

        self._browse_root_btn = QPushButton("Browse…")
        self._browse_root_btn.setFixedHeight(30)
        self._browse_root_btn.setStyleSheet(_BTN)
        self._browse_root_btn.clicked.connect(self._browse_root)
        path_row.addWidget(self._browse_root_btn)

        self._load_btn = QPushButton("Load Registry")
        self._load_btn.setFixedHeight(30)
        self._load_btn.setEnabled(False)
        self._load_btn.setStyleSheet(_BTN)
        self._load_btn.clicked.connect(self._load_registry)
        path_row.addWidget(self._load_btn)

        root_layout.addLayout(path_row)
        root_layout.addWidget(self._sep())

        # Splitter: table (top) + log (bottom)
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background:{_BORDER}; height:2px; }}"
        )

        # Table
        table_wrapper = QWidget()
        table_wrapper.setStyleSheet("background:transparent;")
        tw_layout = QVBoxLayout(table_wrapper)
        tw_layout.setContentsMargins(0, 0, 0, 0)
        tw_layout.setSpacing(4)
        tw_layout.addWidget(self._lbl("Registered databases"))

        self._table = QTableWidget(0, _NCOLS)
        self._table.setHorizontalHeaderLabels(
            ["DB Key", "Country", "Region", "Status", "Records", "Errors", "Warnings"]
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_KEY,     QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_COUNTRY, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_REGION,  QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_STATUS,  QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_RECORDS, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_ERRORS,  QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_WARNS,   QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(_TABLE)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.doubleClicked.connect(self._on_row_double_clicked)
        tw_layout.addWidget(self._table)

        splitter.addWidget(table_wrapper)

        # Log
        log_wrapper = QWidget()
        log_wrapper.setStyleSheet("background:transparent;")
        lw_layout = QVBoxLayout(log_wrapper)
        lw_layout.setContentsMargins(0, 4, 0, 0)
        lw_layout.setSpacing(4)
        lw_layout.addWidget(self._lbl("Log"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(_LOG)
        self._log.setMinimumHeight(80)
        lw_layout.addWidget(self._log)

        splitter.addWidget(log_wrapper)
        splitter.setSizes([380, 140])
        root_layout.addWidget(splitter, stretch=1)

        # Bottom bar
        root_layout.addWidget(self._sep())
        btn_row = QHBoxLayout()

        self._meta_lbl = QLabel("")
        self._meta_lbl.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        btn_row.addWidget(self._meta_lbl)
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(34)
        close_btn.setStyleSheet(_BTN)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        self._check_btn = QPushButton("Check Selected")
        self._check_btn.setFixedHeight(34)
        self._check_btn.setEnabled(False)
        self._check_btn.setToolTip("Run integrity check on the selected database entry")
        self._check_btn.setStyleSheet(_BTN_TEAL)
        self._check_btn.clicked.connect(self._check_selected)
        btn_row.addWidget(self._check_btn)

        self._rebuild_btn = QPushButton("Rebuild Registry")
        self._rebuild_btn.setFixedHeight(34)
        self._rebuild_btn.setEnabled(False)
        self._rebuild_btn.setToolTip("Re-crawl material_database/ and rewrite material_catalog.json")
        self._rebuild_btn.setStyleSheet(_BTN_MAUVE)
        self._rebuild_btn.clicked.connect(self._rebuild_registry)
        btn_row.addWidget(self._rebuild_btn)

        self._manage_countries_btn = QPushButton("Manage Country Folders…")
        self._manage_countries_btn.setFixedHeight(34)
        self._manage_countries_btn.setEnabled(False)
        self._manage_countries_btn.setToolTip(
            "Add or remove country folders in material_database/"
        )
        self._manage_countries_btn.setStyleSheet(_BTN_BLUE)
        self._manage_countries_btn.clicked.connect(self._open_country_manager)
        btn_row.addWidget(self._manage_countries_btn)

        self._sor_generator_btn = QPushButton("Open SOR Generator…")
        self._sor_generator_btn.setFixedHeight(34)
        self._sor_generator_btn.setEnabled(False)
        self._sor_generator_btn.setToolTip(
            "Convert an SOR Excel file to JSON and place it in a country folder"
        )
        self._sor_generator_btn.setStyleSheet(_BTN_BLUE)
        self._sor_generator_btn.clicked.connect(self._open_sor_generator)
        btn_row.addWidget(self._sor_generator_btn)

        root_layout.addLayout(btn_row)

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _sep() -> QWidget:
        w = QWidget(); w.setFixedHeight(1)
        w.setStyleSheet(f"background:{_BORDER};")
        return w

    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(f"color:{_DIM}; font-size:11px; font-weight:bold;")
        return l

    def _cell(self, text: str, fg: str | None = None, bg: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(str(text))
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if fg:
            item.setForeground(QColor(fg))
        if bg:
            item.setBackground(QColor(bg))
        return item

    def _log_line(self, text: str, color: str | None = None):
        if color:
            self._log.appendHtml(f'<span style="color:{color};">{text}</span>')
        else:
            self._log.appendPlainText(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_busy(self, busy: bool):
        self._rebuild_btn.setEnabled(not busy)
        self._load_btn.setEnabled(not busy and bool(self._root_edit.text().strip()))
        self._manage_countries_btn.setEnabled(not busy and self._mod is not None)
        self._sor_generator_btn.setEnabled(not busy and self._mod is not None)
        if not busy:
            self._on_selection_changed()   # restore check_btn based on selection

    def _open_country_manager(self):
        if self._mod is None:
            return
        try:
            from country_manager_gui import CountryManagerDialog
        except ImportError as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
            return

        db_root = Path(self._mod.MATERIAL_DB_ROOT)
        dlg = CountryManagerDialog(parent=self, mod=self._mod, db_root=db_root)
        dlg.folders_changed.connect(self._load_registry)
        dlg.rebuild_needed.connect(self._rebuild_registry)
        dlg.exec()

    def _open_sor_generator(self):
        if self._mod is None:
            return
        try:
            from sor_generator_gui import SorGeneratorDialog
        except ImportError as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
            return

        dlg = SorGeneratorDialog(parent=self, mod=self._mod)
        dlg.sor_generated.connect(self._load_registry)
        dlg.exec()

    # ── Auto-load ──────────────────────────────────────────────────────────────

    def _auto_load(self):
        reg_py = _auto_detect_catalog_py()
        if reg_py is None:
            self._log_line("material_catalog.py not found in expected project location.", color=_ORANGE)
            return

        mod = _load_catalog_module(reg_py)
        if mod is None:
            self._log_line(f"Failed to import material_catalog from:\n  {reg_py}", color=_RED)
            return

        self._mod = mod
        db_root = str(Path(mod.MATERIAL_DB_ROOT))
        self._root_edit.setText(db_root)
        self._log_line(f"Auto-detected root: {db_root}", color=_DIM)
        self._rebuild_btn.setEnabled(True)
        self._load_btn.setEnabled(True)
        self._manage_countries_btn.setEnabled(True)
        self._sor_generator_btn.setEnabled(True)

        # Load manifest if it exists
        manifest_path = Path(mod.CATALOG_MANIFEST_PATH)
        if manifest_path.exists():
            self._load_registry()
        else:
            self._log_line("No material_catalog.json found - click Rebuild Registry to create it.", color=_YELLOW)

    # ── Browse root ────────────────────────────────────────────────────────────

    def _browse_root(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select material_database/ folder",
            self._root_edit.text() or "",
        )
        if not folder:
            return

        # Try to find material_catalog.py as a sibling of the chosen folder
        chosen   = Path(folder).resolve()
        reg_py   = chosen.parent / "material_catalog.py"
        if not reg_py.exists():
            QMessageBox.warning(
                self, "material_catalog.py Not Found",
                f"Could not find material_catalog.py at:\n{reg_py}\n\n"
                "Select the material_database/ folder directly inside the registry/ directory."
            )
            return

        mod = _load_catalog_module(reg_py)
        if mod is None:
            QMessageBox.critical(self, "Import Error", f"Failed to import:\n{reg_py}")
            return

        self._mod = mod
        self._root_edit.setText(str(chosen))
        self._rebuild_btn.setEnabled(True)
        self._load_btn.setEnabled(True)
        self._manage_countries_btn.setEnabled(True)
        self._sor_generator_btn.setEnabled(True)
        self._log_line(f"Root set to: {chosen}", color=_DIM)

    def _on_root_changed(self, text: str):
        has = bool(text.strip())
        self._load_btn.setEnabled(has and self._mod is not None)
        self._rebuild_btn.setEnabled(has and self._mod is not None)

    # ── Load manifest ──────────────────────────────────────────────────────────

    def _load_registry(self):
        if self._mod is None:
            return
        manifest_path = Path(self._mod.CATALOG_MANIFEST_PATH)
        if not manifest_path.exists():
            self._log_line("material_catalog.json not found - rebuild first.", color=_YELLOW)
            return

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                full = json.load(f)
        except Exception as exc:
            self._log_line(f"Failed to load manifest: {exc}", color=_RED)
            return

        self._manifest = full
        self._populate_table(full)

        meta = full.get("_meta", {})
        built_at = meta.get("built_at", "unknown")
        total    = meta.get("total_files", "?")
        ok       = meta.get("ok", "?")
        failed   = meta.get("failed", 0)
        self._meta_lbl.setText(
            f"Built: {built_at[:19]}   |   {total} file(s)   {ok} OK   {failed} failed"
        )
        self._log_line(
            f"Loaded registry: {total} database(s), {ok} OK, {failed} failed",
            color=_GREEN if not failed else _YELLOW,
        )

    # ── Populate table ─────────────────────────────────────────────────────────

    def _populate_table(self, manifest: dict):
        self._table.setRowCount(0)

        entries = [(k, v) for k, v in manifest.items() if k != "_meta"]
        entries.sort(key=lambda kv: (kv[1].get("country", ""), kv[1].get("region", ""), kv[0]))

        for db_key, entry in entries:
            row = self._table.rowCount()
            self._table.insertRow(row)

            status  = entry.get("status", "?")
            n_err   = len(entry.get("errors", []))
            n_warn  = len(entry.get("warnings", []))
            n_rec   = entry.get("record_count", 0)

            status_color = _GREEN if status == "OK" else _RED
            err_color    = _RED    if n_err  else _DIM
            warn_color   = _YELLOW if n_warn else _DIM
            row_bg       = "#2a1a1a" if status != "OK" else None

            cells = [
                (db_key,                    _TEXT,        row_bg),
                (entry.get("country", "?"), _DIM,         row_bg),
                (entry.get("region",  "?"), _DIM,         row_bg),
                (status,                    status_color, row_bg),
                (str(n_rec),                _BLUE,        row_bg),
                (str(n_err) if n_err else "-",  err_color,  row_bg),
                (str(n_warn) if n_warn else "-", warn_color, row_bg),
            ]
            for col, (text, fg, bg) in enumerate(cells):
                self._table.setItem(row, col, self._cell(text, fg, bg))

            # Store full entry for detail view
            self._table.item(row, _COL_KEY).setData(Qt.UserRole, entry)

        self._table.resizeRowsToContents()

    # ── Selection / detail ─────────────────────────────────────────────────────

    def _on_selection_changed(self):
        has_sel = bool(self._table.selectedItems())
        self._check_btn.setEnabled(has_sel and self._mod is not None)

    def _on_row_double_clicked(self, index):
        """Show full error + warning detail for the clicked row in the log."""
        row = index.row()
        item = self._table.item(row, _COL_KEY)
        if item is None:
            return
        entry = item.data(Qt.UserRole)
        if not entry:
            return

        db_key = entry.get("db_key", "?")
        self._log_line(f"--- Detail: {db_key} ---", color=_DIM)
        self._log_line(f"  Path   : {entry.get('path', '?')}", color=_DIM)
        self._log_line(f"  Status : {entry.get('status', '?')}  |  {entry.get('record_count', 0)} record(s)", color=_DIM)

        meta = entry.get("file_meta", {})
        if meta:
            self._log_line(
                f"  File   : {meta.get('size_bytes', 0):,} bytes  |  "
                f"MD5: {meta.get('md5', '?')[:12]}…",
                color=_DIM,
            )
            self._log_line(f"  Modified: {meta.get('last_modified', '?')[:19]}", color=_DIM)

        sheets = entry.get("sheets", [])
        types  = entry.get("types",  [])
        if sheets:
            self._log_line(f"  Sheets : {', '.join(sheets)}", color=_DIM)
        if types:
            self._log_line(f"  Types  : {', '.join(types)}", color=_DIM)

        for e in entry.get("errors", []):
            self._log_line(f"  x {e}", color=_RED)
        for w in entry.get("warnings", []):
            self._log_line(f"  ! {w}", color=_YELLOW)
        if not entry.get("errors") and not entry.get("warnings"):
            self._log_line("  No errors or warnings.", color=_GREEN)

    # ── Check selected ─────────────────────────────────────────────────────────

    def _check_selected(self):
        if self._mod is None:
            return
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        row   = rows[0].row()
        entry = self._table.item(row, _COL_KEY).data(Qt.UserRole)
        if not entry:
            return

        # Resolve absolute path
        manifest_dir = Path(self._mod.CATALOG_MANIFEST_PATH).parent
        rel_path     = entry.get("path", "")
        abs_path     = str((manifest_dir / rel_path).resolve())

        db_key = entry.get("db_key", "?")
        self._log_line(f"--- Integrity check: {db_key} ---", color=_DIM)
        self._check_btn.setEnabled(False)

        self._worker = _IntegrityWorker(self._mod, abs_path)
        self._worker.finished.connect(lambda r: self._on_integrity_done(r, row))
        self._worker.error.connect(self._on_integrity_error)
        self._worker.start()

    def _on_integrity_done(self, report: dict, table_row: int):
        self._worker = None
        self._on_selection_changed()

        status   = report.get("status", "?")
        n_rec    = report.get("record_count", 0)
        errors   = report.get("errors", [])
        warnings = report.get("warnings", [])

        color = _GREEN if status == "OK" else _RED
        self._log_line(
            f"  Status: {status}  |  {n_rec} record(s)  "
            f"|  {len(errors)} error(s)  |  {len(warnings)} warning(s)",
            color=color,
        )
        for e in errors:
            self._log_line(f"  x {e}", color=_RED)
        for w in warnings:
            self._log_line(f"  ! {w}", color=_YELLOW)

        # Update the row in the table to reflect the fresh check
        self._table.item(table_row, _COL_STATUS).setText(status)
        self._table.item(table_row, _COL_STATUS).setForeground(QColor(color))
        self._table.item(table_row, _COL_ERRORS).setText(str(len(errors)) if errors else "-")
        self._table.item(table_row, _COL_ERRORS).setForeground(
            QColor(_RED if errors else _DIM)
        )
        self._table.item(table_row, _COL_WARNS).setText(str(len(warnings)) if warnings else "-")
        self._table.item(table_row, _COL_WARNS).setForeground(
            QColor(_YELLOW if warnings else _DIM)
        )

    def _on_integrity_error(self, msg: str):
        self._worker = None
        self._on_selection_changed()
        self._log_line(f"  Integrity check failed: {msg}", color=_RED)

    # ── Rebuild registry ───────────────────────────────────────────────────────

    def _rebuild_registry(self):
        if self._mod is None:
            QMessageBox.warning(self, "Not Ready", "No material_catalog module loaded.")
            return

        root_path     = self._root_edit.text().strip() or str(self._mod.MATERIAL_DB_ROOT)
        manifest_path = str(self._mod.CATALOG_MANIFEST_PATH)

        if not Path(root_path).is_dir():
            QMessageBox.warning(self, "Invalid Path", f"Not a directory:\n{root_path}")
            return

        self._log_line(f"--- Rebuilding registry ---", color=_DIM)
        self._log_line(f"  Root    : {root_path}", color=_DIM)
        self._log_line(f"  Manifest: {manifest_path}", color=_DIM)

        self._set_busy(True)
        self._rebuild_btn.setText("Rebuilding…")

        self._worker = _RebuildWorker(self._mod, root_path, manifest_path)
        self._worker.finished.connect(self._on_rebuild_done)
        self._worker.error.connect(self._on_rebuild_error)
        self._worker.start()

    def _on_rebuild_done(self, manifest: dict):
        self._rebuild_btn.setText("Rebuild Registry")
        self._set_busy(False)
        self._worker = None

        self._manifest = manifest
        self._populate_table(manifest)

        meta   = manifest.get("_meta", {})
        total  = meta.get("total_files", "?")
        ok     = meta.get("ok", "?")
        failed = meta.get("failed", 0)
        built  = meta.get("built_at", "")[:19]

        self._meta_lbl.setText(
            f"Built: {built}   |   {total} file(s)   {ok} OK   {failed} failed"
        )

        if failed:
            self._log_line(
                f"Registry rebuilt: {total} file(s), {ok} OK, {failed} FAILED",
                color=_YELLOW,
            )
            for key, entry in manifest.items():
                if key == "_meta":
                    continue
                if entry.get("status") == "FAILED":
                    self._log_line(f"  x [{entry['db_key']}]", color=_RED)
                    for e in entry.get("errors", []):
                        self._log_line(f"      {e}", color=_RED)
        else:
            self._log_line(
                f"Registry rebuilt: {total} file(s) scanned, all OK",
                color=_GREEN,
            )

    def _on_rebuild_error(self, msg: str):
        self._rebuild_btn.setText("Rebuild Registry")
        self._set_busy(False)
        self._worker = None
        self._log_line(f"Rebuild failed: {msg}", color=_RED)
        QMessageBox.critical(self, "Rebuild Failed", msg)


