"""
devtools/sor_generator_gui.py

SOR JSON Generator - GUI wrapper around sor_json_generator.py.

Opens from the DevToolsWindow toolbar.  Lets the user:
  1. Pick an SOR Excel file (.xlsx)
  2. Preview the sections that will be generated
  3. Choose (or confirm) the output JSON path
  4. Write the JSON file
  5. Auto-run integrity check (via material_catalog.check_integrity_by_path)
  6. Rebuild the registry manifest (via material_catalog.build_registry)

material_catalog.py is located automatically by walking up from the output
path until the parent of the 'material_database' folder is found.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Style constants (Catppuccin Mocha - matches devtools_window.py)
# ---------------------------------------------------------------------------

_BG       = "#1e1e2e"
_BG2      = "#252535"
_BG3      = "#313244"
_SURFACE  = "#1a1a2e"
_TEXT     = "#cdd6f4"
_DIM      = "#585b70"
_GREEN    = "#a6e3a1"
_YELLOW   = "#f9e2af"
_ORANGE   = "#fab387"
_RED      = "#f38ba8"
_BLUE     = "#89b4fa"
_MAUVE    = "#cba6f7"
_TEAL     = "#94e2d5"
_BORDER   = "#333"

_BTN_STYLE = (
    f"QPushButton {{ background:{_BG3}; color:{_TEXT}; border:1px solid #444;"
    f" border-radius:4px; padding:0 14px; }}"
    f"QPushButton:hover:enabled {{ background:#45475a; }}"
    f"QPushButton:disabled {{ color:{_DIM}; border-color:{_BORDER};"
    f" background:{_BG2}; }}"
)

_PRIMARY_BTN_STYLE = (
    f"QPushButton {{ background:{_BLUE}; color:{_BG}; border:none;"
    f" border-radius:4px; padding:0 20px; font-weight:bold; }}"
    f"QPushButton:hover:enabled {{ background:#b4d0f7; }}"
    f"QPushButton:disabled {{ background:{_BG3}; color:{_DIM}; }}"
)

_REGISTRY_BTN_STYLE = (
    f"QPushButton {{ background:{_MAUVE}; color:{_BG}; border:none;"
    f" border-radius:4px; padding:0 16px; font-weight:bold; }}"
    f"QPushButton:hover:enabled {{ background:#dbb6ff; }}"
    f"QPushButton:disabled {{ background:{_BG3}; color:{_DIM}; }}"
)

_INPUT_STYLE = (
    f"QLineEdit {{ background:{_SURFACE}; color:{_TEXT}; border:1px solid #444;"
    f" border-radius:3px; padding:4px 8px; }}"
    f"QLineEdit:focus {{ border-color:{_BLUE}; }}"
)

_TABLE_STYLE = (
    f"QTableWidget {{ background:{_SURFACE}; color:{_TEXT}; border:1px solid {_BORDER};"
    f" gridline-color:#2a2a3e; }}"
    f"QTableWidget::item {{ padding:4px 8px; }}"
    f"QTableWidget::item:selected {{ background:{_BG3}; }}"
    f"QHeaderView::section {{ background:{_BG2}; color:{_DIM};"
    f" border:none; border-bottom:1px solid {_BORDER}; padding:4px 8px;"
    f" font-size:11px; font-weight:bold; }}"
)

_LOG_STYLE = (
    f"QPlainTextEdit {{ background:{_SURFACE}; color:{_DIM}; border:1px solid {_BORDER};"
    f" font-family:Consolas,monospace; font-size:11px; }}"
)


# ---------------------------------------------------------------------------
# material_catalog loader
# ---------------------------------------------------------------------------


def _find_catalog_path(output_json: str) -> Path | None:
    """
    Walk up from output_json looking for a 'material_database' folder.
    material_catalog.py is expected to live in material_database's parent directory.

    Example:
        output  : .../registry/material_database/INDIA/Bihar/Darbhanga.json
        walks to: .../registry/material_database/
        finds   : .../registry/material_catalog.py   ← sibling of material_database/
    """
    p = Path(output_json).resolve()
    for parent in p.parents:
        if parent.name == "material_database":
            candidate = parent.parent / "material_catalog.py"
            if candidate.exists():
                return candidate
    return None


def _load_catalog(output_json: str) -> ModuleType | None:
    """
    Dynamically import material_catalog from the project tree.
    Returns the module, or None if not found / failed to import.
    """
    reg_path = _find_catalog_path(output_json)
    if reg_path is None:
        return None
    try:
        spec = importlib.util.spec_from_file_location("_material_catalog_dev", str(reg_path))
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Worker thread - runs parse + build off the main thread
# ---------------------------------------------------------------------------


class _ParseWorker(QThread):
    """Parses the Excel and builds the SOR list in a background thread."""

    finished = Signal(list, str)   # (sor_list, log_text)
    error    = Signal(str)

    def __init__(self, xlsx_path: str):
        super().__init__()
        self._path = xlsx_path

    def run(self):
        buf = io.StringIO()
        try:
            from sor_json_generator import build_sor_json, parse_excel

            with redirect_stdout(buf):
                parsed = parse_excel(self._path)
                sor    = build_sor_json(parsed)

            self.finished.emit(sor, buf.getvalue())
        except SystemExit as exc:
            self.error.emit(str(exc))
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")


class _BatchWorker(QThread):
    """Recursively converts all .xlsx files in a folder to JSON in-place."""

    progress = Signal(str, bool)   # (message, is_error)
    finished = Signal(int, int)    # (ok_count, fail_count)

    def __init__(self, folder: str):
        super().__init__()
        self._folder = folder

    def run(self):
        import json as _json
        folder = Path(self._folder)
        ok = fail = 0

        all_xlsx = sorted(folder.rglob("*.xlsx"))
        xlsx_files = []
        for p in all_xlsx:
            if p.name.startswith("~$"):
                self.progress.emit(f"⚠ {p.relative_to(folder)}: cannot open this file (locked by Excel)", True)
                fail += 1
            else:
                xlsx_files.append(p)

        if not xlsx_files:
            self.progress.emit("No .xlsx files found.", True)
            self.finished.emit(0, 0)
            return
        for xlsx_path in xlsx_files:
            json_path = xlsx_path.with_suffix(".json")
            rel = xlsx_path.relative_to(folder)
            try:
                from sor_json_generator import build_sor_json, parse_excel
                buf = io.StringIO()
                with redirect_stdout(buf):
                    parsed = parse_excel(str(xlsx_path))
                    sor = build_sor_json(parsed)
                json_path.write_text(
                    _json.dumps(sor, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                self.progress.emit(f"✓ {rel}", False)
                ok += 1
            except Exception as exc:
                self.progress.emit(f"✗ {rel}: cannot open this file ({exc})", True)
                fail += 1

        self.finished.emit(ok, fail)


class _RegistryWorker(QThread):
    """Runs build_registry() in a background thread."""

    finished = Signal(dict)   # manifest dict
    error    = Signal(str)

    def __init__(self, reg_module: ModuleType):
        super().__init__()
        self._mod = reg_module

    def run(self):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                manifest = self._mod.build_registry()
            self.finished.emit(manifest)
        except Exception as exc:
            self.error.emit(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Main dialog
# ---------------------------------------------------------------------------


class SorGeneratorDialog(QDialog):
    """
    SOR JSON Generator dialog.

    Workflow:
      1. Browse for .xlsx
      2. Click Parse    → preview table fills with section summary
      3. Confirm / change output path
      4. Click Generate → file written, integrity check runs automatically
      5. Click Rebuild Registry → material_catalog.json refreshed
                                  (standalone mode only)

    Parameters
    ----------
    parent : QWidget, optional
    mod    : ModuleType, optional
        Pre-loaded material_catalog module from RegistryBuilderDialog.
        If None, located automatically from the output JSON path (standalone).
    """

    sor_generated = Signal()   # emitted after a JSON file is successfully written

    def __init__(self, parent=None, mod: ModuleType | None = None):
        super().__init__(parent)
        self.setWindowTitle("SOR JSON Generator")
        self.setMinimumSize(780, 640)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowMinimizeButtonHint
            & ~Qt.WindowContextHelpButtonHint
        )
        self.setStyleSheet(f"QDialog {{ background:{_BG}; color:{_TEXT}; }}")

        self._sor: list[dict] = []
        self._last_written: str = ""          # path of the last successfully written file
        self._worker: QThread | None = None
        self._reg_mod: ModuleType | None = mod
        self._standalone: bool = mod is None

        self._build_ui()

    # ── Build UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── Title ─────────────────────────────────────────────────────────────
        title = QLabel("SOR JSON Generator")
        f = QFont(); f.setPointSize(12); f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(f"color:{_TEXT};")
        root.addWidget(title)

        desc = QLabel(
            "Converts a CID#/CAT#-formatted SOR Excel file into the MumbaiSOR.json schema.\n"
            "CAT# sheet prefixes and hyphens are normalised automatically (e.g. CAT#Sub-Structure → Sub Structure).\n"
            "Multi-component syntax supported: {Pier}, {Pier Cap} stores an array on the entry.\n"
            "CID#Description column is optional — included when present. "
            "After writing, an integrity check runs and the registry can be rebuilt."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        root.addWidget(desc)

        root.addWidget(self._separator())

        # ── Input file row ────────────────────────────────────────────────────
        root.addWidget(self._row_label("Source Excel file (.xlsx)"))
        in_row = QHBoxLayout()
        self._input_edit = QLineEdit()
        self._input_edit.setPlaceholderText("Browse or drag & drop an .xlsx file…")
        self._input_edit.setStyleSheet(_INPUT_STYLE)
        self._input_edit.textChanged.connect(self._on_input_changed)
        self._input_edit.setAcceptDrops(False)
        in_row.addWidget(self._input_edit)

        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.setFixedHeight(30)
        self._browse_btn.setStyleSheet(_BTN_STYLE)
        self._browse_btn.clicked.connect(self._browse_input)
        in_row.addWidget(self._browse_btn)
        root.addLayout(in_row)

        # ── Output file row ───────────────────────────────────────────────────
        root.addWidget(self._row_label("Output JSON file"))
        out_row = QHBoxLayout()
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("Auto-filled when source is chosen")
        self._output_edit.setStyleSheet(_INPUT_STYLE)
        self._output_edit.textChanged.connect(self._on_output_changed)
        out_row.addWidget(self._output_edit)

        self._out_browse_btn = QPushButton("Browse…")
        self._out_browse_btn.setFixedHeight(30)
        self._out_browse_btn.setStyleSheet(_BTN_STYLE)
        self._out_browse_btn.clicked.connect(self._browse_output)
        out_row.addWidget(self._out_browse_btn)
        root.addLayout(out_row)

        # ── Parse button ──────────────────────────────────────────────────────
        parse_row = QHBoxLayout()
        self._parse_btn = QPushButton("Parse Excel")
        self._parse_btn.setFixedHeight(32)
        self._parse_btn.setEnabled(False)
        self._parse_btn.setStyleSheet(_BTN_STYLE)
        self._parse_btn.clicked.connect(self._run_parse)
        parse_row.addWidget(self._parse_btn)

        self._batch_btn = QPushButton("Batch Convert Folder...")
        self._batch_btn.setFixedHeight(32)
        self._batch_btn.setStyleSheet(_BTN_STYLE)
        self._batch_btn.setToolTip(
            "Pick a root folder - all .xlsx files found recursively will be\n"
            "converted to JSON and saved alongside each Excel file."
        )
        self._batch_btn.clicked.connect(self._run_batch)
        parse_row.addWidget(self._batch_btn)

        parse_row.addStretch()
        root.addLayout(parse_row)

        root.addWidget(self._separator())

        # ── Preview table ─────────────────────────────────────────────────────
        root.addWidget(self._row_label("Sections preview"))

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Sheet", "Components found", "Entries", "w/ Desc"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.setMinimumHeight(150)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self._table, stretch=2)

        # ── Log area ──────────────────────────────────────────────────────────
        root.addWidget(self._row_label("Log"))
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(110)
        self._log.setMaximumHeight(160)
        self._log.setStyleSheet(_LOG_STYLE)
        root.addWidget(self._log, stretch=1)

        # ── Bottom buttons ────────────────────────────────────────────────────
        root.addWidget(self._separator())
        btn_row = QHBoxLayout()

        self._stats_lbl = QLabel("")
        self._stats_lbl.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        btn_row.addWidget(self._stats_lbl)
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(34)
        close_btn.setStyleSheet(_BTN_STYLE)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        # Rebuild only in standalone mode - Registry Builder handles it when used as sub-dialog
        if self._standalone:
            self._rebuild_btn = QPushButton("Rebuild Registry")
            self._rebuild_btn.setFixedHeight(34)
            self._rebuild_btn.setEnabled(False)
            self._rebuild_btn.setToolTip(
                "Rebuild material_catalog.json so the new file appears in the search index.\n"
                "Runs material_catalog.build_registry() on the material_database/ folder."
            )
            self._rebuild_btn.setStyleSheet(_REGISTRY_BTN_STYLE)
            self._rebuild_btn.clicked.connect(self._rebuild_registry)
            btn_row.addWidget(self._rebuild_btn)
        else:
            self._rebuild_btn = None

        self._generate_btn = QPushButton("Generate JSON")
        self._generate_btn.setFixedHeight(34)
        self._generate_btn.setEnabled(False)
        self._generate_btn.setStyleSheet(_PRIMARY_BTN_STYLE)
        self._generate_btn.clicked.connect(self._generate)
        btn_row.addWidget(self._generate_btn)

        root.addLayout(btn_row)

        self.setAcceptDrops(True)

    # ── Widget helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _separator() -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{_BORDER};")
        return line

    @staticmethod
    def _row_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{_DIM}; font-size:11px; font-weight:bold;")
        return lbl

    @staticmethod
    def _cell(text: str, color: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if color:
            item.setForeground(QColor(color))
        return item

    # ── Drag & drop ────────────────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith((".xlsx", ".xls")):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith((".xlsx", ".xls")):
                self._set_input(path)
                event.acceptProposedAction()

    # ── Browse ─────────────────────────────────────────────────────────────────

    def _browse_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select SOR Excel File", "", "Excel Files (*.xlsx *.xls)"
        )
        if path:
            self._set_input(path)

    def _browse_output(self):
        default = self._output_edit.text() or ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save JSON As", default, "JSON Files (*.json)"
        )
        if path:
            if not path.lower().endswith(".json"):
                path += ".json"
            self._output_edit.setText(path)

    def _set_input(self, path: str):
        self._input_edit.setText(path)
        # Output path is derived automatically in _on_input_changed

    def _on_input_changed(self, text: str):
        stripped = text.strip()
        has_file = bool(stripped) and stripped.lower().endswith((".xlsx", ".xls"))
        self._parse_btn.setEnabled(has_file)

        # Always sync output path to match the new input (user can override via Browse)
        if has_file:
            derived = str(Path(stripped).with_suffix(".json"))
            if self._output_edit.text() != derived:
                self._output_edit.blockSignals(True)
                self._output_edit.setText(derived)
                self._output_edit.blockSignals(False)
        elif not stripped:
            self._output_edit.blockSignals(True)
            self._output_edit.clear()
            self._output_edit.blockSignals(False)

        if self._sor:
            self._sor = []
            self._table.setRowCount(0)
            self._stats_lbl.setText("")
            self._generate_btn.setEnabled(False)

    def _on_output_changed(self, text: str):
        self._generate_btn.setEnabled(bool(self._sor) and bool(text.strip()))

    # ── Batch convert ──────────────────────────────────────────────────────────

    def _run_batch(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Root Folder")
        if not folder:
            return

        self._log.clear()
        self._table.setRowCount(0)
        self._sor = []
        self._stats_lbl.setText("")
        self._generate_btn.setEnabled(False)
        if self._rebuild_btn:
            self._rebuild_btn.setEnabled(False)
        self._parse_btn.setEnabled(False)
        self._batch_btn.setEnabled(False)
        self._batch_btn.setText("Converting...")
        self._log_line(f"Batch folder: {folder}")

        self._worker = _BatchWorker(folder)
        self._worker.progress.connect(self._on_batch_progress)
        self._worker.finished.connect(self._on_batch_done)
        self._worker.start()

    def _on_batch_progress(self, msg: str, is_error: bool):
        self._log_line(msg, color=_RED if is_error else _GREEN)

    def _on_batch_done(self, ok: int, fail: int):
        self._batch_btn.setText("Batch Convert Folder...")
        self._batch_btn.setEnabled(True)
        self._parse_btn.setEnabled(bool(self._input_edit.text().strip()))
        self._worker = None
        total = ok + fail
        self._stats_lbl.setText(f"Batch: {ok}/{total} converted")
        color = _GREEN if fail == 0 else (_YELLOW if ok > 0 else _RED)
        self._log_line(f"Batch done — {ok} OK, {fail} failed.", color=color)
        if self._rebuild_btn:
            self._rebuild_btn.setEnabled(True)

    # ── Parse ──────────────────────────────────────────────────────────────────

    def _run_parse(self):
        path = self._input_edit.text().strip()
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "File Not Found", f"Cannot find:\n{path}")
            return

        self._log.clear()
        self._table.setRowCount(0)
        self._sor = []
        self._stats_lbl.setText("")
        self._generate_btn.setEnabled(False)
        if self._rebuild_btn:
            self._rebuild_btn.setEnabled(False)
        self._parse_btn.setEnabled(False)
        self._parse_btn.setText("Parsing…")
        self._log_line(f"Parsing: {path}")

        self._worker = _ParseWorker(path)
        self._worker.finished.connect(self._on_parse_done)
        self._worker.error.connect(self._on_parse_error)
        self._worker.start()

    def _on_parse_done(self, sor: list[dict], log_text: str):
        self._parse_btn.setText("Parse Excel")
        self._parse_btn.setEnabled(True)
        self._worker = None

        for line in log_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "[warn]" in line.lower():
                self._log_line(line, color=_YELLOW)
            elif "[skip]" in line.lower():
                self._log_line(line, color=_ORANGE)
            elif "[ok]" in line.lower():
                self._log_line(line, color=_GREEN)
            else:
                self._log_line(line)

        if not sor:
            self._log_line("No sections generated - check the file has CID# or CAT# headers.", color=_RED)
            return

        self._sor = sor
        self._populate_table(sor)

        total_entries = sum(len(s["data"]) for s in sor)
        total_with_desc = sum(
            1 for s in sor for e in s["data"] if e.get("description") is not None
        )
        desc_note = f"  |  {total_with_desc} w/ description" if total_with_desc else ""
        self._stats_lbl.setText(
            f"{len(sor)} sheet(s)  |  {total_entries} entries total{desc_note}"
        )
        self._generate_btn.setEnabled(bool(self._output_edit.text().strip()))
        self._log_line(f"Done - {len(sor)} sheet(s), {total_entries} entries.", color=_GREEN)

    def _on_parse_error(self, msg: str):
        self._parse_btn.setText("Parse Excel")
        self._parse_btn.setEnabled(True)
        self._worker = None
        self._log_line(f"Error: {msg}", color=_RED)
        QMessageBox.critical(self, "Parse Failed", msg)

    def _populate_table(self, sor: list[dict]):
        self._table.setRowCount(0)

        sheet_colors = {
            "Foundation":      "#3a2a4e",
            "Sub Structure":   "#1e3a2a",
            "Super Structure": "#1e2a3a",
            "Miscellaneous":   "#3a3a1e",
        }

        for section in sor:
            row = self._table.rowCount()
            self._table.insertRow(row)

            sheet_name = section["sheetName"]
            data       = section["data"]
            count      = len(data)
            desc_count = sum(1 for e in data if e.get("description") is not None)
            bg_hex     = sheet_colors.get(sheet_name, _BG2)

            # Collect unique component values preserving first-seen order
            seen: dict[str, None] = {}
            for e in data:
                comp = e.get("component", "Uncategorised")
                if isinstance(comp, list):
                    for c in comp:
                        seen[c] = None
                else:
                    seen[comp] = None
            components_str = ", ".join(seen.keys())
            has_multi = any(isinstance(e.get("component"), list) for e in data)

            desc_text  = str(desc_count) if desc_count else "-"
            desc_color = _TEAL if desc_count else _DIM

            for col, (text, fg) in enumerate([
                (sheet_name,     _TEXT),
                (components_str, _MAUVE if has_multi else _TEXT),
                (str(count),     _BLUE if count > 0 else _DIM),
                (desc_text,      desc_color),
            ]):
                item = self._cell(text, fg)
                item.setBackground(QColor(bg_hex))
                self._table.setItem(row, col, item)

        self._table.resizeRowsToContents()

    # ── Generate ───────────────────────────────────────────────────────────────

    def _generate(self):
        if not self._sor:
            return

        out_path = self._output_edit.text().strip()
        if not out_path:
            QMessageBox.warning(self, "No Output Path", "Specify an output JSON path to continue.")
            return
        if not out_path.lower().endswith(".json"):
            out_path += ".json"

        dest = Path(out_path)

        if dest.exists():
            resp = QMessageBox.question(
                self, "Overwrite?",
                f"File already exists:\n{dest}\n\nOverwrite?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(self._sor, f, indent=4, ensure_ascii=False)
        except Exception as exc:
            self._log_line(f"Write failed: {exc}", color=_RED)
            QMessageBox.critical(self, "Write Failed", str(exc))
            return

        self._last_written = str(dest)
        total_entries = sum(len(s["data"]) for s in self._sor)
        self._log_line(f"Written {total_entries} entries -> {dest}", color=_GREEN)

        # --- Integrity check -------------------------------------------------
        self._run_integrity_check(str(dest))

        # --- Signal parent / enable rebuild ----------------------------------
        self.sor_generated.emit()

        if self._standalone:
            # In standalone mode locate material_catalog from the output path
            reg_mod = _load_catalog(str(dest))
            if reg_mod is not None:
                self._reg_mod = reg_mod
                if self._rebuild_btn:
                    self._rebuild_btn.setEnabled(True)
            else:
                self._log_line(
                    "Note: material_catalog.py not found relative to output path - "
                    "Rebuild Registry unavailable.",
                    color=_DIM,
                )

    # ── Integrity check ────────────────────────────────────────────────────────

    def _run_integrity_check(self, file_path: str):
        """Run material_catalog.check_integrity_by_path and display results in the log."""
        reg_mod = _load_catalog(file_path)
        if reg_mod is None:
            self._log_line("Integrity check skipped - material_catalog.py not found.", color=_DIM)
            return

        self._log_line("--- Integrity check ---", color=_DIM)
        try:
            report = reg_mod.check_integrity_by_path(file_path)
        except Exception as exc:
            self._log_line(f"Integrity check failed: {exc}", color=_RED)
            return

        status  = report.get("status", "?")
        n_rec   = report.get("record_count", 0)
        errors  = report.get("errors", [])
        warnings = report.get("warnings", [])

        if status == "OK":
            self._log_line(
                f"Integrity: OK - {n_rec} record(s), "
                f"{len(errors)} error(s), {len(warnings)} warning(s)",
                color=_GREEN,
            )
        else:
            self._log_line(
                f"Integrity: FAILED - {len(errors)} error(s)", color=_RED
            )

        for e in errors:
            self._log_line(f"  x {e}", color=_RED)
        for w in warnings:
            self._log_line(f"  ! {w}", color=_YELLOW)

    # ── Rebuild registry ───────────────────────────────────────────────────────

    def _rebuild_registry(self):
        if self._reg_mod is None:
            QMessageBox.warning(
                self, "material_catalog Not Found",
                "Could not locate material_catalog.py relative to the output path.\n"
                "Make sure the JSON is inside a material_database/ subfolder."
            )
            return

        self._rebuild_btn.setEnabled(False)  # only reachable in standalone mode
        self._rebuild_btn.setText("Rebuilding…")
        self._log_line("--- Rebuilding registry ---", color=_DIM)

        self._worker = _RegistryWorker(self._reg_mod)
        self._worker.finished.connect(self._on_registry_done)
        self._worker.error.connect(self._on_registry_error)
        self._worker.start()

    def _on_registry_done(self, manifest: dict):
        if self._rebuild_btn:
            self._rebuild_btn.setText("Rebuild Registry")
            self._rebuild_btn.setEnabled(True)
        self._worker = None

        meta  = manifest.get("_meta", {})
        total = meta.get("total_files", "?")
        ok    = meta.get("ok", "?")
        failed = meta.get("failed", 0)

        if failed:
            self._log_line(
                f"Registry rebuilt: {total} file(s) scanned, {ok} OK, {failed} FAILED",
                color=_YELLOW,
            )
            # List the failed entries
            for key, entry in manifest.items():
                if key == "_meta":
                    continue
                if entry.get("status") == "FAILED":
                    for e in entry.get("errors", []):
                        self._log_line(f"  x [{entry['db_key']}] {e}", color=_RED)
        else:
            self._log_line(
                f"Registry rebuilt: {total} file(s) scanned, all OK", color=_GREEN
            )

        # Show a summary table of all registered databases
        self._log_line("  DB Key            Region              Status  Records", color=_DIM)
        for key, entry in manifest.items():
            if key == "_meta":
                continue
            icon = "+" if entry["status"] == "OK" else "x"
            self._log_line(
                f"  {icon} {entry['db_key']:<18} {entry.get('region','?'):<20}"
                f" {entry['status']:<7} {entry['record_count']}",
                color=_GREEN if entry["status"] == "OK" else _RED,
            )

    def _on_registry_error(self, msg: str):
        if self._rebuild_btn:
            self._rebuild_btn.setText("Rebuild Registry")
            self._rebuild_btn.setEnabled(True)
        self._worker = None
        self._log_line(f"Registry rebuild failed: {msg}", color=_RED)
        QMessageBox.critical(self, "Registry Rebuild Failed", msg)

    # ── Log ────────────────────────────────────────────────────────────────────

    def _log_line(self, text: str, color: str | None = None):
        if color:
            self._log.appendHtml(f'<span style="color:{color};">{text}</span>')
        else:
            self._log.appendPlainText(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())


