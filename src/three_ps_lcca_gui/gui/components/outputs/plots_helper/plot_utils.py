"""
gui/components/outputs/plots_helper/plot_utils.py

Shared utilities for matplotlib-based chart widgets.
"""

import os
from matplotlib import font_manager as _fm
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QScrollArea
from three_ps_lcca_gui.gui.theme import FONT_FAMILY, RADIUS_SM
from three_ps_lcca_gui.gui.themes import get_token

def register_ubuntu_fonts():
    """Register Ubuntu TTF fonts with Matplotlib."""
    font_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "themes", "Ubuntu_font")
    )
    for ttf in ["Ubuntu-Light.ttf", "Ubuntu-Regular.ttf", "Ubuntu-Medium.ttf", "Ubuntu-Bold.ttf"]:
        path = os.path.join(font_dir, ttf)
        if os.path.exists(path):
            _fm.fontManager.addfont(path)

class WheelForwarder(QObject):
    """Forwards wheel events from a child widget to the nearest parent QScrollArea."""
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            parent = obj.parent()
            while parent is not None:
                if isinstance(parent, QScrollArea):
                    QApplication.sendEvent(parent.verticalScrollBar(), event)
                    return True
                parent = parent.parent()
        return False

class ChartToolbar(NavigationToolbar2QT):
    """Custom Matplotlib toolbar with fewer items and silenced messages."""
    toolitems = [t for t in NavigationToolbar2QT.toolitems
                 if t[0] in ("Home", "Pan", "Zoom", "Save")]

    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent)
        self.setStyleSheet(f"""
            QToolBar {{
                background: transparent;
                border: none;
                spacing: 3px;
            }}
            QToolButton {{
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: {RADIUS_SM}px;
                padding: 3px;
                min-width: 22px;
                min-height: 22px;
            }}
            QToolButton:hover {{
                background-color: {get_token('surface')};
                border: 1px solid {get_token('surface_mid')};
            }}
            QToolButton:checked {{
                background-color: {get_token('surface')};
                border: 1px solid {get_token('surface_mid')};
            }}
        """)

    def set_message(self, s): pass

def currency_note(currency: str) -> str:
    """Standard note for currency units."""
    return f"All values in {currency}"
