"""
gui/components/outputs/table_export.py

Shared utilities for exporting table widgets and custom-painted report widgets
to SVG vector graphics, PNG/JPEG images, and clipboard.
"""

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgGenerator, QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolTip,
    QWidget,
)

from three_ps_lcca_gui.gui.theme import RADIUS_MD, RADIUS_SM
from three_ps_lcca_gui.gui.themes import get_token

# User-provided save table / floppy disk SVG path
SAVE_TABLE_SVG_TEMPLATE = (
    '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M5 3H16L19 6V19C19 19.5523 18.5523 20 18 20H5C4.44772 20 4 19.5523 4 19V4C4 3.44772 4.44772 3 5 3Z" '
    'stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>'
    '<path d="M7 3V8H15V3" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>'
    '<path d="M7 20V13H16V20" stroke="{color}" stroke-width="1.5" stroke-linejoin="round"/>'
    "</svg>"
)


class _SaveTableIconEngine(QIconEngine):
    """Dynamically renders the save table SVG icon in the active theme stroke color."""

    def __init__(self, color: str | None = None):
        super().__init__()
        self._color = color

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State):
        c = self._color or get_token("text")
        svg_xml = SAVE_TABLE_SVG_TEMPLATE.format(color=c)
        renderer = QSvgRenderer(QByteArray(svg_xml.encode("utf-8")))
        renderer.render(painter, QRectF(rect))

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        pix = QPixmap(size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        self.paint(p, QRect(0, 0, size.width(), size.height()), mode, state)
        p.end()
        return pix


def make_save_table_icon(color: str | None = None) -> QIcon:
    """Returns a QIcon for the save table action with the user-specified SVG path."""
    return QIcon(_SaveTableIconEngine(color))


def export_widget_as_image(
    widget: QWidget,
    title: str = "Table Export",
    default_filename: str = "table_export.svg",
    parent: QWidget | None = None,
    format: str = "svg",
) -> str | None:
    """Export any QWidget (table, custom canvas, chart) as SVG vector or PNG/JPEG image.

    Option 4: Uses QSvgGenerator for crisp, scalable vector graphics.
    Falls back to high-resolution QPixmap for raster image formats.
    """
    if not default_filename.endswith((".svg", ".png", ".jpg", ".jpeg")):
        default_filename = f"{default_filename}.svg" if format == "svg" else f"{default_filename}.png"

    file_path, _ = QFileDialog.getSaveFileName(
        parent or widget,
        f"Export {title}",
        default_filename,
        "Scalable Vector Graphics (*.svg);;PNG Image (*.png);;JPEG Image (*.jpg)",
    )
    if not file_path:
        return None

    try:
        # Determine full content dimensions
        w = max(widget.width(), 800)
        h = max(widget.height(), 400)
        if hasattr(widget, "_total_content_h"):
            h = max(h, getattr(widget, "_total_content_h"))

        if file_path.lower().endswith(".svg"):
            generator = QSvgGenerator()
            generator.setFileName(file_path)
            generator.setSize(QSize(w, h))
            generator.setViewBox(QRect(0, 0, w, h))
            generator.setTitle(title)
            generator.setDescription(f"3psLCCA Export: {title}")
            widget.render(generator)
            del generator  # Flush buffer and release file handle
        else:
            pixmap = QPixmap(w, h)
            pixmap.fill(QColor(get_token("window")))
            widget.render(pixmap)
            pixmap.save(file_path)

        return file_path
    except Exception as exc:
        QMessageBox.warning(
            parent or widget,
            "Export Failed",
            f"Could not export {title}:\n{exc}",
        )
        return None


def copy_widget_to_clipboard(widget: QWidget) -> bool:
    """Renders the widget off-screen and copies it to the system clipboard."""
    try:
        w = max(widget.width(), 800)
        h = max(widget.height(), 400)
        if hasattr(widget, "_total_content_h"):
            h = max(h, getattr(widget, "_total_content_h"))

        pixmap = QPixmap(w, h)
        pixmap.fill(QColor(get_token("window")))
        widget.render(pixmap)
        QApplication.clipboard().setPixmap(pixmap)

        center = widget.mapToGlobal(widget.rect().center())
        QToolTip.showText(center, "Table image copied to clipboard!")
        return True
    except Exception:
        return False


def create_table_context_menu(
    widget: QWidget,
    title: str = "Table Export",
    default_filename: str = "table_export.svg",
    custom_actions: list | None = None,
    target_widget: QWidget | None = None,
) -> QMenu:
    """Builds a standardized theme-styled context menu for exporting widgets."""
    target = target_widget or widget
    menu = QMenu(widget)
    menu.setStyleSheet(
        f"""
        QMenu {{
            background-color: {get_token('surface')};
            color: {get_token('text')};
            border: 1px solid {get_token('surface_mid')};
            border-radius: {RADIUS_SM}px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 20px;
            border-radius: {RADIUS_SM}px;
        }}
        QMenu::item:selected {{
            background-color: {get_token('surface_mid')};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {get_token('surface_mid')};
            margin: 4px 8px;
        }}
        """
    )

    icon = make_save_table_icon()

    act_svg = menu.addAction(icon, "Export Table as Vector (SVG)...")
    act_svg.triggered.connect(
        lambda: export_widget_as_image(target, title=title, default_filename=default_filename, format="svg")
    )

    act_png = menu.addAction(icon, "Export Table as PNG Image...")
    act_png.triggered.connect(
        lambda: export_widget_as_image(
            target,
            title=title,
            default_filename=default_filename.rsplit(".", 1)[0] + ".png",
            format="png",
        )
    )

    menu.addSeparator()

    act_copy = menu.addAction("Copy Table Image to Clipboard")
    act_copy.triggered.connect(lambda: copy_widget_to_clipboard(target))

    if custom_actions:
        menu.addSeparator()
        for act in custom_actions:
            menu.addAction(act)

    return menu


def attach_table_context_menu(
    widget: QWidget,
    title: str = "Table Export",
    default_filename: str = "table_export.svg",
    custom_actions: list | None = None,
    target_widget: QWidget | None = None,
):
    """Enables CustomContextMenu policy on the widget (and its viewport if scrollable/table) and shows the export menu."""
    def _show_menu(global_pt):
        menu = create_table_context_menu(
            widget, title=title, default_filename=default_filename,
            custom_actions=custom_actions, target_widget=target_widget
        )
        menu.exec(global_pt)

    widget.setContextMenuPolicy(Qt.CustomContextMenu)
    widget.customContextMenuRequested.connect(lambda pos: _show_menu(widget.mapToGlobal(pos)))

    if hasattr(widget, "viewport") and callable(widget.viewport):
        vp = widget.viewport()
        vp.setContextMenuPolicy(Qt.CustomContextMenu)
        vp.customContextMenuRequested.connect(lambda pos: _show_menu(vp.mapToGlobal(pos)))


def create_export_button(
    widget: QWidget,
    title: str = "Table Export",
    default_filename: str = "table_export.svg",
    tooltip: str = "Export or copy table (SVG / PNG / Clipboard)",
    target_widget: QWidget | None = None,
) -> QPushButton:
    """Creates a compact icon button with the save table icon.

    Left-click or right-click pops up the export menu (SVG vector, PNG image, Copy to clipboard).
    """
    btn = QPushButton()
    btn.setIcon(make_save_table_icon())
    btn.setIconSize(QSize(18, 18))
    btn.setFixedSize(32, 32)
    btn.setToolTip(f"{tooltip}\nClick or right-click for export options")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(
        f"""
        QPushButton {{
            background-color: transparent;
            border: 1px solid {get_token('surface_mid')};
            border-radius: {RADIUS_MD}px;
            padding: 3px;
        }}
        QPushButton:hover {{
            background-color: {get_token('surface')};
            border: 1px solid {get_token('primary')};
        }}
        QPushButton:pressed {{
            background-color: {get_token('surface_pressed')};
        }}
        """
    )

    def _open_options_menu():
        menu = create_table_context_menu(
            widget, title=title, default_filename=default_filename, target_widget=target_widget
        )
        # Display menu immediately beneath the button
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    # Click opens options menu
    btn.clicked.connect(_open_options_menu)

    # Right-click also opens options menu
    btn.setContextMenuPolicy(Qt.CustomContextMenu)
    btn.customContextMenuRequested.connect(lambda _pos: _open_options_menu())

    return btn
