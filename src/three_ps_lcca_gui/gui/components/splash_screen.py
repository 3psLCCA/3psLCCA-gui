"""
gui/components/splash_screen.py
────────────────────────────────────────────────────────────────────────────────
Theme-aware modern Splash Screen - sleek card layout matching splash_demo.html.
"""

from __future__ import annotations

import math
import os
import sys
import time
from contextlib import contextmanager

from PySide6.QtCore import (
    Property,
    QEventLoop,
    QRectF,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QWidget,
)

from three_ps_lcca_gui.gui.theme import FONT_FAMILY
from three_ps_lcca_gui.gui.themes import get_token, is_dark
from three_ps_lcca_gui.gui.version import VERSION

CARD_W, CARD_H = 540, 320
SHADOW_MARGIN = 20
WIN_W, WIN_H = CARD_W + SHADOW_MARGIN * 2, CARD_H + SHADOW_MARGIN * 2

_GUI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ASSETS_DIR = os.path.join(_GUI_DIR, "assets")

# The splash currently on screen, so long-running startup code can call
# pump_splash() to keep the loader animating. None when no splash is shown.
_active_splash: "SplashScreen | None" = None


def pump_splash() -> None:
    """Repaint the startup splash if one is showing (throttled; ~free otherwise)."""
    if _active_splash is not None:
        _active_splash.pump()


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
    """
    Slim rounded progress bar that always looks alive:
    - the fill level is driven by SplashScreen (real milestones + slow trickle)
    - a soft highlight continuously sweeps across the filled part
    """

    BAR_W, BAR_H = 240, 4
    SWEEP_PERIOD = 1.1  # seconds per highlight pass
    SWEEP_W = 70.0

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._v: float = 0.0
        self._t0 = time.monotonic()
        self.setFixedSize(self.BAR_W, self.BAR_H)
        self._track = QColor(get_token("surface_mid"))
        self._fill = QColor(get_token("primary"))

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
        r = self.height() / 2

        # Background track
        p.setBrush(self._track)
        p.drawRoundedRect(QRectF(self.rect()), r, r)

        if self._v <= 0.001:
            p.end()
            return

        fill_w = max(float(self.height()), self.width() * self._v)
        fill_rect = QRectF(0, 0, fill_w, self.height())
        clip = QPainterPath()
        clip.addRoundedRect(fill_rect, r, r)
        p.setClipPath(clip)

        # Fill: primary, a touch lighter towards the leading edge
        grad = QLinearGradient(0, 0, fill_w, 0)
        grad.setColorAt(0.0, self._fill.darker(115))
        grad.setColorAt(1.0, self._fill.lighter(120))
        p.setBrush(grad)
        p.drawRect(fill_rect)

        # Moving highlight sweep
        phase = ((time.monotonic() - self._t0) % self.SWEEP_PERIOD) / self.SWEEP_PERIOD
        x = -self.SWEEP_W + phase * (fill_w + self.SWEEP_W)
        shine = QLinearGradient(x, 0, x + self.SWEEP_W, 0)
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.5, QColor(255, 255, 255, 140))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(shine)
        p.drawRect(QRectF(x, 0, self.SWEEP_W, self.height()))

        p.end()


# Status text shown when one of these modules starts importing.
_IMPORT_LABELS = {
    "three_ps_lcca_gui.gui.project_window": "Loading project workspace\u2026",
    "numpy": "Loading math libraries\u2026",
    "matplotlib": "Loading charts\u2026",
    "pandas": "Loading data tools\u2026",
    "three_ps_lcca_gui.code_to_latex": "Loading report engine\u2026",
    "three_ps_lcca_gui.gui.components.outputs.outputs_page": "Loading results views\u2026",
    "three_ps_lcca_gui.gui.components.home_page": "Loading home screen\u2026",
}


class _ImportPump:
    """sys.meta_path hook: repaints the splash while heavy modules import."""

    def __init__(self, splash: "SplashScreen") -> None:
        self._splash = splash

    def find_spec(self, name, path=None, target=None):
        label = _IMPORT_LABELS.get(name)
        if label:
            self._splash.set_status(label)
        self._splash.pump()
        return None  # never handles the import itself


class SplashScreen(QWidget):
    """
    Theme-adaptive splash screen with modern card aesthetics:
    - Neutral window card with rounded corners & subtle drop shadow
    - Scalable vector logo
    - Trickle progress loader with a moving highlight (never looks stalled)
    - Status text driven by real loading stages (set_stage)
    - Version string footer
    """

    TRICKLE_CAP = 0.94   # the bar never reaches 100% until finish()
    TRICKLE_TAU = 4.0    # seconds - how quickly the trickle approaches the cap
    FINISH_FILL_S = 0.2  # quick fill to 100% just before closing

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WIN_W, WIN_H)
        self._center()

        self._closing = False
        self._main_win: QWidget | None = None

        # ── Floating Card Container ──────────────────────────────────────────
        self.card = QFrame(self)
        self.card.setGeometry(SHADOW_MARGIN, SHADOW_MARGIN, CARD_W, CARD_H)
        self.card.setObjectName("splashCard")

        bg = get_token("window")
        border = get_token("surface_mid")
        muted_color = "#A0A3AA" if is_dark() else get_token("text_disabled")

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
        self._bar.move(int((CARD_W - _ProgressBar.BAR_W) / 2), 212)

        # Status text below loader
        self._status_label = QLabel("Starting…", self.card)
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setFixedSize(CARD_W, 20)
        self._status_label.move(0, 227)
        self._status_label.setStyleSheet(f"""
            color: {muted_color};
            font-size: 11px;
            font-family: "{FONT_FAMILY}", "Segoe UI", sans-serif;
        """)

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

        # ── Loader driver ────────────────────────────────────────────────────
        # _target creeps towards TRICKLE_CAP so the bar never stalls; set_stage()
        # bumps it on real milestones. The visible bar eases after _target.
        self._target = 0.0
        self._last_tick = time.monotonic()
        self._last_pump = 0.0
        self._ticker = QTimer(self)
        self._ticker.setInterval(16)
        self._ticker.timeout.connect(self._tick)

    # ── Loading progress ─────────────────────────────────────────────────────

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(now - self._last_tick, 0.25)
        self._last_tick = now
        if self._closing:
            return
        # Trickle: close a fraction of the remaining gap every frame
        self._target += (self.TRICKLE_CAP - self._target) * (1 - math.exp(-dt / self.TRICKLE_TAU))
        # Ease the visible bar towards the target
        v = self._bar.progress
        self._bar.progress = v + (self._target - v) * min(1.0, dt * 9)

    def set_stage(self, value: float, text: str | None = None) -> None:
        """Report a real loading milestone (0..1) with optional status text."""
        if self._closing:
            return
        self._target = max(self._target, min(value, self.TRICKLE_CAP))
        if text:
            self._status_label.setText(text)
        self.pump(force=True)

    def set_status(self, text: str) -> None:
        """Change the status line without moving the progress bar."""
        if not self._closing:
            self._status_label.setText(text)

    def pump(self, force: bool = False) -> None:
        """Advance and repaint the splash while the main thread is busy."""
        if self._closing or not self.isVisible():
            return
        # Only the GUI thread may touch widgets / run the event loop.
        if QThread.currentThread() is not self.thread():
            return
        now = time.monotonic()
        if not force and now - self._last_pump < 0.03:
            return
        self._last_pump = now
        self._tick()
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    @contextmanager
    def pumping_imports(self):
        """Keep the splash animating while slow imports run on the main thread."""
        hook = _ImportPump(self)
        sys.meta_path.insert(0, hook)
        try:
            yield
        finally:
            try:
                sys.meta_path.remove(hook)
            except ValueError:
                pass

    # ── Show / close ─────────────────────────────────────────────────────────

    def show(self) -> None:
        global _active_splash
        self._last_tick = time.monotonic()
        super().show()
        self._ticker.start()
        _active_splash = self

    def finish(self, main_win: QWidget | None = None) -> None:
        """Called when the main window is ready: fill the bar to 100%, then close."""
        self._main_win = main_win
        self._fill_to_end()
        self._do_close()

    def _fill_to_end(self) -> None:
        """Quickly run the bar to 100% so the user sees loading complete."""
        if self._closing or not self.isVisible():
            return
        self._ticker.stop()
        self._status_label.setText("Ready")
        start = self._bar.progress
        t0 = time.monotonic()
        while True:
            f = min(1.0, (time.monotonic() - t0) / self.FINISH_FILL_S)
            ease = 1 - (1 - f) ** 3  # ease-out
            self._bar.progress = start + (1.0 - start) * ease
            self._bar.repaint()
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            if f >= 1.0:
                break
            time.sleep(0.012)

    def _do_close(self) -> None:
        global _active_splash
        if self._closing:
            return
        self._closing = True
        if _active_splash is self:
            _active_splash = None
        self._ticker.stop()
        self.close()
        if self._main_win is not None:
            self._main_win.raise_()
            self._main_win.activateWindow()

    def _center(self) -> None:
        geo = QApplication.primaryScreen().availableGeometry()
        self.move(geo.center() - self.rect().center())
