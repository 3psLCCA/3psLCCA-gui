"""
gui/components/sponsors_footer.py

Unified sponsors footer displaying:
- Left: "Developed At" + IITB logo
- Right: "Supported by" + ConstructSteel, MOS, INSDAG logos
Automatically reacts to theme changes.
"""

import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel

from three_ps_lcca_gui.gui.theme import (
    SP3,
    SP4,
    SP6,
    SP8,
    SP10,
    FS_XS,
)
from three_ps_lcca_gui.gui.themes import get_token, theme_manager, is_dark
from three_ps_lcca_gui.gui.styles import font as _f

_GUI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ASSETS_DIR = os.path.join(_GUI_DIR, "assets")


class SponsorsFooter(QFrame):
    """Reusable, theme-aware sponsors footer for Home and Compare pages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sponsorsFooter")
        self.setFixedHeight(120)
        self._build_ui()
        self.refresh_theme()
        theme_manager().theme_changed.connect(self.refresh_theme)

    def _build_ui(self):
        fl = QHBoxLayout(self)
        fl.setContentsMargins(SP6, SP6, SP6, SP6)

        # Developed At Section
        dev_v = QVBoxLayout()
        dev_v.setSpacing(SP3)
        self.dev_lbl = QLabel("Developed At")
        self.dev_lbl.setFont(_f(FS_XS))
        dev_v.addWidget(self.dev_lbl)
        self.iitb_logo = QLabel()
        dev_v.addWidget(self.iitb_logo, 0, Qt.AlignLeft | Qt.AlignVCenter)
        fl.addLayout(dev_v)

        fl.addStretch()

        # Supported By Section
        sup_v = QVBoxLayout()
        sup_v.setSpacing(SP3)
        sup_v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sup_lbl = QLabel("Supported by")
        self.sup_lbl.setFont(_f(FS_XS))
        self.sup_lbl.setAlignment(Qt.AlignRight)
        sup_v.addWidget(self.sup_lbl)

        sup_h = QHBoxLayout()
        sup_h.setSpacing(SP4)
        sup_h.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.cs_logo = QLabel()
        self.mos_logo = QLabel()
        self.insdag_logo = QLabel()
        sup_h.addWidget(self.cs_logo)
        sup_h.addWidget(self.mos_logo)
        sup_h.addWidget(self.insdag_logo)
        sup_v.addLayout(sup_h)
        fl.addLayout(sup_v)

    def _set_svg_logo(self, label: QLabel, path: str, height: int):
        """Render SVG logo into a QLabel with no background."""
        if not os.path.exists(path):
            label.hide()
            return
        label.show()
        label.setStyleSheet("background: transparent; border: none;")
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            return
        aspect = renderer.defaultSize().width() / max(1, renderer.defaultSize().height())
        width = int(height * aspect)
        pixmap = QPixmap(width * 2, height * 2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        label.setPixmap(pixmap)
        label.setFixedSize(width, height)
        label.setScaledContents(True)

    def _set_themed_logo(self, label: QLabel, dark_path: str, light_path: str, height: int, is_dk: bool):
        path = dark_path if is_dk else light_path
        self._set_svg_logo(label, path, height)

    def refresh_theme(self):
        """Update logos, text styling, and background color based on active theme."""
        is_dk = is_dark()

        # 1. Developed At (IITB)
        self._set_themed_logo(
            self.iitb_logo,
            os.path.join(_ASSETS_DIR, "logo", "special", "IITB_logo_dark.svg"),
            os.path.join(_ASSETS_DIR, "logo", "special", "IITB_logo_light.svg"),
            50, is_dk
        )

        # 2. Supported By (ConstructSteel, MOS, INSDAG)
        self._set_themed_logo(
            self.cs_logo,
            os.path.join(_ASSETS_DIR, "logo", "special", "ConstructSteel_dark.svg"),
            os.path.join(_ASSETS_DIR, "logo", "special", "ConstructSteel_light.svg"),
            12, is_dk
        )
        self._set_themed_logo(
            self.mos_logo,
            os.path.join(_ASSETS_DIR, "logo", "special", "MOS_dark.svg"),
            os.path.join(_ASSETS_DIR, "logo", "special", "MOS_light.svg"),
            40, is_dk
        )
        self._set_themed_logo(
            self.insdag_logo,
            os.path.join(_ASSETS_DIR, "logo", "special", "INSDAG_dark.svg"),
            os.path.join(_ASSETS_DIR, "logo", "special", "INSDAG_light.svg"),
            40, is_dk
        )

        # 3. Targeted styling - ensure labels are strictly transparent with no background box
        bg = get_token("surface")
        muted = get_token("text_disabled")
        self.setStyleSheet(f"""
            #sponsorsFooter {{
                background-color: {bg};
                border: none;
            }}
            #sponsorsFooter QLabel {{
                background-color: transparent;
                border: none;
                color: {muted};
                letter-spacing: 1px;
            }}
        """)
