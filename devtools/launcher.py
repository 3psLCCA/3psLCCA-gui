"""
devtools/launcher.py

3psLCCA Developer Tools - master launcher window.

Displays every dev tool as a card.  Click a card to open its window/dialog.
DevToolsWindow is kept as a single instance (raise if already open).
WPI + SOR dialogs open fresh each time (modeless).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Style palette (Catppuccin Mocha - same as devtools_window.py)
# ---------------------------------------------------------------------------

_BG      = "#1e1e2e"
_BG2     = "#252535"
_BG3     = "#313244"
_SURFACE = "#181825"
_TEXT    = "#cdd6f4"
_DIM     = "#585b70"
_BLUE    = "#89b4fa"
_GREEN   = "#a6e3a1"
_MAUVE   = "#cba6f7"
_PEACH   = "#fab387"
_YELLOW  = "#f9e2af"
_TEAL    = "#94e2d5"
_BORDER  = "#2a2a3e"


# ---------------------------------------------------------------------------
# Tool registry - add new tools here only
# ---------------------------------------------------------------------------

def _get_tools() -> list[dict]:
    """
    Returns list of tool descriptors.
    Imported lazily so a broken tool doesn't crash the launcher.
    """
    tools = []

    # ── Project Inspector ──────────────────────────────────────────────────
    try:
        from devtools_window import DevToolsWindow
        tools.append({
            "key":    "project_inspector",
            "icon":   "🔬",
            "name":   "Project Inspector",
            "desc":   (
                "Open and inspect .3ps project archive files.\n"
                "Browse every chunk and blob stored inside the archive, view or edit their "
                "raw JSON, run integrity checks, and export a repaired copy. "
                "Use this when a project fails to open or behaves unexpectedly."
            ),
            "accent": _BLUE,
            "open":   lambda parent, _ref={}: _open_main_window(DevToolsWindow, _ref, parent),
        })
    except ImportError as e:
        tools.append(_error_card("Project Inspector", str(e)))

    # ── WPI Database ───────────────────────────────────────────────────────
    try:
        from wpi_tool import WpiDatabaseDialog
        tools.append({
            "key":    "wpi_database",
            "icon":   "🗃",
            "name":   "WPI Database",
            "desc":   (
                "Manage the Wholesale Price Index (WPI) database used for cost escalation.\n"
                "Add, edit, or delete WPI entries, recompute hashes, and save wpi_db.json. "
                "Changes here affect how project costs are adjusted over time."
            ),
            "accent": _GREEN,
            "open":   lambda parent: _open_dialog(WpiDatabaseDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("WPI Database", str(e)))

    # ── Country Manager ────────────────────────────────────────────────────
    try:
        from country_manager_gui import CountryManagerDialog
        tools.append({
            "key":    "country_manager",
            "icon":   "🌍",
            "name":   "Country Manager",
            "desc":   (
                "Manage top-level country folders inside material_database/.\n"
                "Add a folder for a new country so its material data can be stored and "
                "discovered. Remove empty or orphaned folders that are no longer needed. "
                "Start here before importing material data for a new country."
            ),
            "accent": _PEACH,
            "open":   lambda parent: _open_dialog(CountryManagerDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("Country Manager", str(e)))

    # ── Material Importer ──────────────────────────────────────────────────
    try:
        from sor_generator_gui import SorGeneratorDialog
        tools.append({
            "key":    "material_importer",
            "icon":   "📥",
            "name":   "Material Importer",
            "desc":   (
                "Import material data from a CID#-formatted Excel file into the database.\n"
                "Parses rate, carbon emission, and recyclability columns, previews the "
                "sections found, then writes a JSON file into the chosen country folder. "
                "Rebuild the catalog afterward so the data appears in material suggestions."
            ),
            "accent": _MAUVE,
            "open":   lambda parent: _open_dialog(SorGeneratorDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("Material Importer", str(e)))

    # ── Catalog Builder ────────────────────────────────────────────────────
    try:
        from catalog_builder_gui import CatalogBuilderDialog
        tools.append({
            "key":    "catalog_builder",
            "icon":   "🗂",
            "name":   "Catalog Builder",
            "desc":   (
                "Build and maintain the material catalog index (material_catalog.json).\n"
                "Crawls material_database/, validates every JSON file for schema correctness, "
                "and writes the index used by the material suggestion engine. "
                "Run this after adding or modifying any material database file."
            ),
            "accent": _TEAL,
            "open":   lambda parent: _open_dialog(CatalogBuilderDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("Catalog Builder", str(e)))

    # ── Unit Manager ───────────────────────────────────────────────────────
    try:
        from unit_manager_gui import UnitManagerDialog
        tools.append({
            "key":    "unit_manager",
            "icon":   "📐",
            "name":   "Unit Manager",
            "desc":   (
                "Browse, add, and manage measurement units used across the app.\n"
                "View all built-in units from units.json, add new canonical units, promote "
                "custom units to built-in, and test how any raw unit string (e.g. Sqm., MT, Nos.) "
                "resolves at runtime."
            ),
            "accent": _YELLOW,
            "open":   lambda parent: _open_dialog(UnitManagerDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("Unit Manager", str(e)))

    # ── Custom DB Viewer ───────────────────────────────────────────────────
    try:
        from custom_db_viewer_gui import CustomDbViewerDialog
        tools.append({
            "key":    "custom_db_viewer",
            "icon":   "🗄",
            "name":   "Custom DB Viewer",
            "desc":   (
                "Browse all user-created custom material databases (SOR).\n"
                "Shows every material saved in data/user.db with all fields: rate, "
                "emission factor, conversion factor, scrap rate, recovery %, grade, "
                "type, and source attributions. Use this to verify what was saved "
                "to custom databases from the Material Dialog."
            ),
            "accent": _GREEN,
            "open":   lambda parent: _open_dialog(CustomDbViewerDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("Custom DB Viewer", str(e)))

    # ── Doc Builder ───────────────────────────────────────────────────────────
    try:
        from doc_builder_gui import DocBuilderDialog
        tools.append({
            "key":    "doc_builder",
            "icon":   "📄",
            "name":   "Doc Builder",
            "desc":   (
                "Pre-build the glossary docs/ folder into static HTML fragments.\n"
                "Converts every Markdown file under doc_handler/docs/ to HTML using the "
                "Python markdown package and writes output to doc_handler/doc_build/. "
                "The glossary browser loads pre-built HTML directly, skipping runtime "
                "Markdown parsing for faster page loads. Requires: pip install markdown"
            ),
            "accent": _YELLOW,
            "open":   lambda parent: _open_dialog(DocBuilderDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("Doc Builder", str(e)))

    # ── LaTeX Bundle Check ────────────────────────────────────────────────
    try:
        from latex_env_check_gui import LatexEnvCheckDialog
        tools.append({
            "key":    "latex_env_check",
            "icon":   "🧪",
            "name":   "LaTeX Bundle Check",
            "desc":   (
                "Verify that every package in REQUIRED_LATEX_PACKAGES is present "
                "in the bundled osdag_latex_env texmf-dist.\n"
                "Shows a green/red list instantly (filesystem check, no pdflatex run). "
                "Run this before generating a PDF report to catch missing packages early."
            ),
            "accent": _PEACH,
            "open":   lambda parent: _open_dialog(LatexEnvCheckDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("LaTeX Bundle Check", str(e)))

    # ── File Integrity Checker ─────────────────────────────────────────────
    try:
        from integrity_tool_gui import IntegrityToolDialog
        tools.append({
            "key":    "integrity_checker",
            "icon":   "🔒",
            "name":   "File Integrity Checker",
            "desc":   (
                "Track and verify static JSON files against a stored MD5 baseline.\n"
                "Detects tampering or accidental edits to units.json, material_catalog.json, "
                "wpi_db.json, and any other tracked file. Regen rebuilds the baseline after "
                "an intentional change. Integrity records are stored in devtools/integrity.json."
            ),
            "accent": _TEAL,
            "open":   lambda parent: _open_dialog(IntegrityToolDialog, parent),
        })
    except ImportError as e:
        tools.append(_error_card("File Integrity Checker", str(e)))

    return tools


def _error_card(name: str, reason: str) -> dict:
    return {
        "key":    f"error_{name}",
        "icon":   "⚠",
        "name":   name,
        "desc":   f"Failed to load:\n{reason}",
        "accent": "#f38ba8",
        "open":   None,
    }


# ── Open helpers ──────────────────────────────────────────────────────────────


def _open_main_window(cls, ref: dict, parent):
    """Open a QMainWindow tool; keep single instance, raise if already open."""
    existing = ref.get("win")
    if existing is not None and not existing.isHidden():
        existing.raise_()
        existing.activateWindow()
        return
    win = cls()
    ref["win"] = win
    win.show()


def _open_dialog(cls, parent):
    """Open a QDialog tool modeless so the launcher stays accessible."""
    dlg = cls(parent)
    dlg.setWindowModality(Qt.NonModal)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    # Keep a reference so it isn't GC'd
    if not hasattr(parent, "_open_dialogs"):
        parent._open_dialogs = []
    parent._open_dialogs.append(dlg)
    # Clean up reference when dialog closes
    dlg.finished.connect(lambda: parent._open_dialogs.remove(dlg)
                         if dlg in parent._open_dialogs else None)


# ---------------------------------------------------------------------------
# ToolCard widget
# ---------------------------------------------------------------------------


class ToolCard(QFrame):
    """
    Full-width row card: accent bar | icon | name + description | Open button.
    Stretches horizontally so the launcher works at any window width.
    """

    _CARD_BG     = "#252535"
    _CARD_BG_HOV = "#2a2a45"
    _CARD_RADIUS = 8
    _ACCENT_W    = 4

    def __init__(self, descriptor: dict, parent=None):
        super().__init__(parent)
        self._desc     = descriptor
        self._accent   = descriptor.get("accent", _BLUE)
        self._can_open = descriptor.get("open") is not None

        self.setMinimumWidth(500)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setCursor(Qt.PointingHandCursor if self._can_open else Qt.ArrowCursor)
        self._apply_style(hovered=False)
        self._build()

    # -- build ----------------------------------------------------------------

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Coloured left accent bar
        accent_bar = QWidget()
        accent_bar.setFixedWidth(self._ACCENT_W)
        accent_bar.setStyleSheet(f"background:{self._accent};")
        outer.addWidget(accent_bar)

        # Icon
        icon_lbl = QLabel(self._desc.get("icon", ""))
        icon_lbl.setFixedWidth(52)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet("font-size:22px; background:transparent;")
        outer.addWidget(icon_lbl)

        # Name + description (takes all remaining space)
        text_block = QWidget()
        text_block.setStyleSheet("background:transparent;")
        tl = QVBoxLayout(text_block)
        tl.setContentsMargins(0, 10, 12, 10)
        tl.setSpacing(3)

        name_lbl = QLabel(self._desc["name"])
        nf = QFont(); nf.setPointSize(10); nf.setBold(True)
        name_lbl.setFont(nf)
        name_lbl.setStyleSheet(f"color:{_TEXT};")
        tl.addWidget(name_lbl)

        desc_lbl = QLabel(self._desc["desc"])
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(f"color:{_DIM}; font-size:10px;")
        desc_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tl.addWidget(desc_lbl)

        outer.addWidget(text_block, stretch=1)

        # Open button - pinned to the right
        self._btn = QPushButton("Open")
        self._btn.setFixedHeight(30)
        self._btn.setFixedWidth(76)
        self._btn.setEnabled(self._can_open)
        self._btn.setStyleSheet(
            f"QPushButton {{ background:{self._accent}; color:{_SURFACE}; border:none;"
            f" border-radius:4px; font-weight:bold; font-size:11px; margin-right:16px; }}"
            f"QPushButton:hover:enabled {{ background: rgba(255,255,255,0.15); }}"
            f"QPushButton:disabled {{ background:{_BG3}; color:{_DIM}; margin-right:16px; }}"
        )
        self._btn.clicked.connect(self._on_open)
        outer.addWidget(self._btn, alignment=Qt.AlignVCenter)

    # -- interaction ----------------------------------------------------------

    def _on_open(self):
        opener = self._desc.get("open")
        if opener:
            opener(self.window())

    def enterEvent(self, event):
        if self._can_open:
            self._apply_style(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(hovered=False)
        super().leaveEvent(event)

    def _apply_style(self, hovered: bool):
        bg = self._CARD_BG_HOV if hovered else self._CARD_BG
        self.setStyleSheet(
            f"ToolCard {{ background:{bg}; border:1px solid {_BORDER};"
            f" border-radius:{self._CARD_RADIUS}px; }}"
        )


# ---------------------------------------------------------------------------
# Launcher window
# ---------------------------------------------------------------------------


class LauncherWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("3psLCCA Developer Tools")
        self.setMinimumSize(700, 380)
        self.setStyleSheet(f"QMainWindow {{ background:{_BG}; }}")
        self._open_dialogs: list = []
        self._build_ui()

    # -- build ----------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background:{_BG};")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_card_area(), stretch=1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        hdr = QWidget()
        hdr.setFixedHeight(72)
        hdr.setStyleSheet(
            f"background:{_BG2}; border-bottom:1px solid {_BORDER};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 0, 24, 0)
        hl.setSpacing(12)

        # Title block
        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title = QLabel("3psLCCA Developer Tools")
        tf = QFont(); tf.setPointSize(13); tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{_TEXT};")
        title_col.addWidget(title)

        subtitle = QLabel("Internal tooling for project inspection, data authoring, and format conversion")
        subtitle.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        title_col.addWidget(subtitle)

        hl.addLayout(title_col)
        hl.addStretch()

        # Version badge
        badge = QLabel("devtools")
        badge.setStyleSheet(
            f"background:{_BG3}; color:{_DIM}; font-size:10px;"
            f" border-radius:3px; padding:2px 8px;"
        )
        hl.addWidget(badge)

        return hdr

    def _build_card_area(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background:{_BG}; border:none; }}"
            f"QScrollBar:vertical {{ background:{_BG2}; width:8px; border:none; }}"
            f"QScrollBar::handle:vertical {{ background:{_BG3}; border-radius:4px; }}"
        )

        container = QWidget()
        container.setStyleSheet(f"background:{_BG};")
        cl = QVBoxLayout(container)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(8)

        section_lbl = QLabel("AVAILABLE TOOLS")
        section_lbl.setStyleSheet(
            f"color:{_DIM}; font-size:10px; font-weight:bold; letter-spacing:1px;"
        )
        cl.addWidget(section_lbl)

        for tool in _get_tools():
            cl.addWidget(ToolCard(tool))

        cl.addStretch()
        scroll.setWidget(container)
        return scroll

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(36)
        footer.setStyleSheet(
            f"background:{_BG2}; border-top:1px solid {_BORDER};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 0, 24, 0)

        tip = QLabel("Tip: tools open as separate windows - the launcher stays open.")
        tip.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        fl.addWidget(tip)
        fl.addStretch()

        count_lbl = QLabel(f"{len(_get_tools())} tool(s) available")
        count_lbl.setStyleSheet(f"color:{_DIM}; font-size:11px;")
        fl.addWidget(count_lbl)

        return footer


