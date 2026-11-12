"""
gui/components/api_access_dialog.py

File -> API Access for the current project:
  - the manual token (for the user's own scripts), with generate /
    regenerate / revoke;
  - the programs given access through the popup, each with Revoke;
  - recent API activity, so unexpected use is visible.
See gui/api/tokens.py for how the two kinds of key differ.
"""

import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from three_ps_lcca_gui.gui.api import tokens
from three_ps_lcca_gui.gui.api.registry import CHUNK_PAGE_MAP
from three_ps_lcca_gui.gui.api.server import get_active_port

_ACTIVITY_SHOWN = 5
_REFRESH_MS = 2000


def _ago(ts: float | None) -> str:
    if ts is None:
        return "not used yet"
    s = int(time.time() - ts)
    if s < 60:
        return f"used {s} s ago"
    if s < 3600:
        return f"used {s // 60} min ago"
    return f"used {s // 3600} h ago"


class ApiAccessDialog(QDialog):
    def __init__(self, project_id: str, parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self.setWindowTitle("API Access")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._port = get_active_port()

        if self._port is None:
            layout.addWidget(QLabel(
                "The local API server is not running.\n"
                "It may be disabled in Settings, or failed to start."
            ))
            btn_close = QPushButton("Close")
            btn_close.clicked.connect(self.reject)
            layout.addWidget(btn_close)
            return

        # ── Manual token (URL, token, usage hint) ───────────────────────────
        layout.addWidget(self._heading("Token for your own scripts"))

        self._active_block = QWidget()
        active_layout = QVBoxLayout(self._active_block)
        active_layout.setContentsMargins(0, 0, 0, 0)
        active_layout.setSpacing(12)

        self._hint = QLabel(
            "Call <i>Base URL/&lt;page&gt;</i> with the token in an "
            "<b>X-API-Token</b> header. Works from any program."
        )
        self._hint.setWordWrap(True)
        active_layout.addWidget(self._hint)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._url_edit = self._readonly_row("", form, "Base URL")
        self._token_edit = self._readonly_row("", form, "Token")
        active_layout.addLayout(form)

        layout.addWidget(self._active_block)

        self._revoked_label = QLabel(
            "Revoked. Requests with the old token get 401 until you "
            "generate a new one."
        )
        self._revoked_label.setWordWrap(True)
        layout.addWidget(self._revoked_label)

        token_btns = QHBoxLayout()
        self._btn_generate = QPushButton("Generate Token")
        self._btn_generate.clicked.connect(self._on_generate)
        self._btn_regen = QPushButton("Regenerate")
        self._btn_regen.clicked.connect(self._on_regenerate)
        self._btn_revoke = QPushButton("Revoke")
        self._btn_revoke.clicked.connect(self._on_revoke)
        for b in (self._btn_generate, self._btn_regen, self._btn_revoke):
            self._size(b)
            token_btns.addWidget(b)
        token_btns.addStretch()
        layout.addLayout(token_btns)

        # ── Programs given access through the popup ─────────────────────────
        layout.addSpacing(4)
        layout.addWidget(self._heading("Programs you allowed"))
        self._grants_box = QVBoxLayout()
        self._grants_box.setSpacing(6)
        layout.addLayout(self._grants_box)

        # ── Recent activity ─────────────────────────────────────────────────
        layout.addSpacing(4)
        layout.addWidget(self._heading("Recent activity"))
        self._activity_label = QLabel()
        self._activity_label.setTextFormat(Qt.TextFormat.RichText)
        self._activity_label.setWordWrap(True)
        self._activity_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._activity_label)

        # ── Close ───────────────────────────────────────────────────────────
        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Close")
        self._size(btn_close)
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

        self._grant_ids: tuple | None = None
        self._grant_labels: list = []
        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_live)
        self._timer.start(_REFRESH_MS)

    # ── Building blocks ─────────────────────────────────────────────────────

    @staticmethod
    def _heading(text: str) -> QLabel:
        lbl = QLabel(f"<b>{html.escape(text)}</b>")
        lbl.setTextFormat(Qt.TextFormat.RichText)
        return lbl

    @staticmethod
    def _size(btn: QPushButton) -> None:
        btn.setMinimumWidth(110)
        btn.setMinimumHeight(34)

    def _readonly_row(self, value: str, form: QFormLayout, label: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit(value)
        edit.setReadOnly(True)
        btn_copy = QPushButton("Copy")
        btn_copy.setMinimumWidth(80)
        btn_copy.setMinimumHeight(34)
        edit.setMinimumHeight(34)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(edit.text()))
        row.addWidget(edit)
        row.addWidget(btn_copy)
        form.addRow(label, row)
        return edit

    # ── Refresh ─────────────────────────────────────────────────────────────

    def _refresh(self):
        self._refresh_manual()
        self._refresh_live()

    def _refresh_manual(self):
        token = tokens.get_token(self.project_id)
        active = token is not None

        self._active_block.setVisible(active)
        self._revoked_label.setVisible(not active)
        self._btn_generate.setVisible(not active)
        self._btn_regen.setVisible(active)
        self._btn_revoke.setVisible(active)

        if active:
            base_url = f"http://127.0.0.1:{self._port}/{self.project_id}"
            self._url_edit.setText(base_url)
            self._token_edit.setText(token)
            # Page list lives in a tooltip instead of filling the dialog.
            pages = "\n".join(sorted(CHUNK_PAGE_MAP.keys())) or "(none registered)"
            tip = f"Available pages:\n{pages}"
            self._hint.setToolTip(tip)
            self._url_edit.setToolTip(tip)

    def _refresh_live(self):
        """Programs list and activity - polled while the dialog is open."""
        grants = tokens.list_grants(self.project_id)
        ids = tuple(g.grant_id for g in grants)
        if ids != self._grant_ids:
            self._rebuild_grants(grants)
        else:
            for g, lbl in zip(grants, self._grant_labels):
                lbl.setText(self._grant_text(g))
        self._activity_label.setText(self._activity_html())

    def _rebuild_grants(self, grants):
        while self._grants_box.count():
            item = self._grants_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
            elif item.layout() is not None:
                lay = item.layout()
                while lay.count():
                    sub = lay.takeAt(0).widget()
                    if sub is not None:
                        sub.hide()
                        sub.deleteLater()
        self._grant_ids = tuple(g.grant_id for g in grants)
        self._grant_labels = []

        if not grants:
            none = QLabel(
                "None. A program asks through a popup; each one you allow "
                "gets its own key that only works for it."
            )
            none.setWordWrap(True)
            none.setEnabled(False)
            self._grants_box.addWidget(none)
            return

        for g in grants:
            row = QHBoxLayout()
            lbl = QLabel(self._grant_text(g))
            lbl.setTextFormat(Qt.TextFormat.RichText)
            lbl.setWordWrap(True)
            lbl.setToolTip(
                f"Program: {g.exe or 'unknown'}\n"
                f"Command: {g.cmdline or 'unknown'}"
            )
            btn = QPushButton("Revoke")
            self._size(btn)
            btn.clicked.connect(lambda _=False, gid=g.grant_id: self._on_revoke_grant(gid))
            row.addWidget(lbl, 1)
            row.addWidget(btn)
            self._grants_box.addLayout(row)
            self._grant_labels.append(lbl)

    @staticmethod
    def _grant_text(g) -> str:
        return (
            f"<b>{html.escape(g.name or 'unknown program')}</b> "
            f"&middot; PID {int(g.pid)} &middot; {_ago(g.last_used)}"
        )

    def _activity_html(self) -> str:
        events = tokens.activity(self.project_id)[:_ACTIVITY_SHOWN]
        if not events:
            return "<i>No API use yet.</i>"
        prefix = f"/{self.project_id}/"
        lines = []
        for e in events:
            action = e.action.replace(prefix, "")
            line = (
                f"{time.strftime('%H:%M:%S', time.localtime(e.when))} &nbsp;"
                f"{html.escape(e.who)} &nbsp;{html.escape(action)}"
            )
            if action.startswith("REFUSED"):
                line = f"<span style='color:#d20f39'><b>{line}</b></span>"
            lines.append(line)
        return "<br>".join(lines)

    # ── Actions ─────────────────────────────────────────────────────────────

    def _on_generate(self):
        tokens.ensure_token(self.project_id)
        self._refresh_manual()

    def _on_regenerate(self):
        tokens.regenerate(self.project_id)
        self._refresh_manual()

    def _on_revoke(self):
        tokens.revoke_manual(self.project_id)
        self._refresh_manual()

    def _on_revoke_grant(self, grant_id: str):
        tokens.revoke_grant(grant_id)
        self._refresh_live()
