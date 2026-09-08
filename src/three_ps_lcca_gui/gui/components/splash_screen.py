"""
gui/components/splash_screen.py
────────────────────────────────────────────────────────────────────────────────
Theme-aware modern Splash Screen - sleek card layout matching splash_demo.html.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QPushButton,
    QWidget,
)

from three_ps_lcca_gui.gui.theme import FONT_FAMILY
from three_ps_lcca_gui.gui.themes import get_token, is_dark
from three_ps_lcca_gui.gui.version import VERSION

MIN_DISPLAY_MS = 1_500
CARD_W, CARD_H = 540, 320
SHADOW_MARGIN = 20
WIN_W, WIN_H = CARD_W + SHADOW_MARGIN * 2, CARD_H + SHADOW_MARGIN * 2

_GUI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ASSETS_DIR = os.path.join(_GUI_DIR, "assets")


class _LogoWidget(QWidget):
    """Renders the 3psLCCA logo crisply using SVG with smooth raster fallback."""

    def __init__(self, parent: QWidget, svg_path: str, fallback_png: str | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(320, 118)
        self._svg: QSvgRenderer | None = None
        self._pixmap: QPixmap | None = None

        if os.path.exists(svg_path):
            renderer = QSvgRenderer(svg_path, self)
            if renderer.isValid():
                self._svg = renderer

        if self._svg is None and fallback_png and os.path.exists(fallback_png):
            self._pixmap = QPixmap(fallback_png)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        if self._svg and self._svg.isValid():
            self._svg.render(p, QRectF(self.rect()))
        elif self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) / 2
            y = (self.height() - scaled.height()) / 2
            p.drawPixmap(int(x), int(y), scaled)

        p.end()


class _ProgressBar(QWidget):
    """Slim, rounded progress bar matching the reference mockup."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._v: float = 0.0
        self.setFixedSize(220, 3)

    def _get(self) -> float:
        return self._v

    def _set(self, v: float) -> None:
        self._v = max(0.0, min(1.0, v))
        self.update()

    progress = Property(float, fget=_get, fset=_set)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)

        # Background track
        p.setBrush(QColor(get_token("surface_mid")))
        p.drawRoundedRect(self.rect(), 2, 2)

        # Progress fill
        if self._v > 0.001:
            p.setBrush(QColor(get_token("primary")))
            fill_w = max(2, int(self.width() * self._v))
            p.drawRoundedRect(0, 0, fill_w, self.height(), 2, 2)

        p.end()


class SplashScreen(QWidget):
    """
    Theme-adaptive splash screen with modern card aesthetics:
    - Neutral window card with rounded corners & subtle drop shadow
    - Scalable vector logo
    - Track & smooth animated progress loader
    - Dynamic status text ('Loading workspace…' → 'Almost there…')
    - Skip button & version string footer
    """

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WIN_W, WIN_H)
        self._center()

        self._closing = False
        self._show_ts = 0.0
        self._main_win: QWidget | None = None

        # ── Floating Card Container ──────────────────────────────────────────
        self.card = QFrame(self)
        self.card.setGeometry(SHADOW_MARGIN, SHADOW_MARGIN, CARD_W, CARD_H)
        self.card.setObjectName("splashCard")

        bg = get_token("window")
        border = get_token("surface_mid")
        muted_color = "#A0A3AA" if is_dark() else get_token("text_disabled")
        primary = get_token("primary")

        self.card.setStyleSheet(f"""
            QFrame#splashCard {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 16px;
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
        """)

        # Drop shadow effect
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 85 if is_dark() else 35))
        self.card.setGraphicsEffect(shadow)

        # ── Logo ─────────────────────────────────────────────────────────────
        logo_file = "logo-3psLCCA-dark.svg" if is_dark() else "logo-3psLCCA-light.svg"
        logo_path = os.path.join(_ASSETS_DIR, "logo", logo_file)
        fallback_png = os.path.join(_ASSETS_DIR, "logo", "logo-3psLCCA-light.png")
        self._logo = _LogoWidget(self.card, logo_path, fallback_png)
        self._logo.move(int((CARD_W - 320) / 2), 58)

        # ── Progress Loader ──────────────────────────────────────────────────
        self._bar = _ProgressBar(self.card)
        self._bar.move(int((CARD_W - 220) / 2), 214)

        # Status text below loader
        self._status_label = QLabel("Loading workspace\u2026", self.card)
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setFixedSize(CARD_W, 20)
        self._status_label.move(0, 227)
        self._status_label.setStyleSheet(f"""
            color: {muted_color};
            font-size: 11px;
            font-family: "{FONT_FAMILY}", "Segoe UI", sans-serif;
        """)

        # Status update timer: changes to 'Almost there…' at 900ms
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._on_status_update)

        # ── Footer: Version String ───────────────────────────────────────────
        self._version_label = QLabel(f"{VERSION}", self.card)
        self._version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._version_label.setStyleSheet(f"""
            color: {muted_color};
            font-size: 11px;
            font-family: "{FONT_FAMILY}", "Segoe UI", sans-serif;
            padding-right: 4px;
        """)
        self._version_label.adjustSize()
        v_w = self._version_label.width() + 10
        self._version_label.setFixedSize(v_w, 24)
        self._version_label.move(CARD_W - 22 - v_w, CARD_H - 18 - 24)

        # ── Animations ───────────────────────────────────────────────────────
        # Main progress animation: 0.0 → 0.85 over MIN_DISPLAY_MS
        self._anim = QPropertyAnimation(self._bar, b"progress", self)
        self._anim.setDuration(MIN_DISPLAY_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(0.85)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        # Close snap animation: current → 1.0 snap before fade/close
        self._close_anim = QPropertyAnimation(self._bar, b"progress", self)
        self._close_anim.setDuration(150)
        self._close_anim.setEndValue(1.0)
        self._close_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._close_anim.finished.connect(self._start_fade_out)

        # Window fade-out animation: opacity 1.0 → 0.0
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(180)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._fade_anim.finished.connect(self._on_fade_finished)

    def _on_status_update(self) -> None:
        if not self._closing:
            self._status_label.setText("Almost there\u2026")

    def _on_skip(self) -> None:
        """Skip button or mouse click triggered - exit splash immediately."""
        self._do_close()

    def mousePressEvent(self, event) -> None:
        """Click anywhere on splash to dismiss/skip."""
        if event.button() == Qt.LeftButton:
            self._on_skip()
        super().mousePressEvent(event)

    def show(self) -> None:
        self._show_ts = time.monotonic()
        super().show()
        self._anim.start()
        self._status_timer.start(900)

    def finish(self, main_win: QWidget | None = None) -> None:
        """Called by main window when initialization completes."""
        self._main_win = main_win
        if self._closing:
            return

        elapsed_ms = (time.monotonic() - self._show_ts) * 1000
        delay = max(0, int(MIN_DISPLAY_MS - elapsed_ms))
        QTimer.singleShot(delay, self._do_close)

    def _do_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._status_timer.stop()
        self._anim.stop()
        self._status_label.setText("Almost there\u2026")
        self._close_anim.setStartValue(self._bar.progress)
        self._close_anim.start()

    def _start_fade_out(self) -> None:
        self._fade_anim.start()

    def _on_fade_finished(self) -> None:
        self.close()
        if self._main_win is not None:
            self._main_win.raise_()
            self._main_win.activateWindow()

    def _center(self) -> None:
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center() - self.rect().center())

