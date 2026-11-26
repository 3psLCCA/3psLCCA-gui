"""
gui/components/first_launch_dialog.py

First-launch welcome dialog - the same settings form as the sidebar Settings
dialog, shown one section per step (General, Theme, Storage) under a welcome
header, with "Back" / "Next" / "Get Started" buttons.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from three_ps_lcca_gui.gui.styles import font, btn_primary, btn_outline
from three_ps_lcca_gui.gui.theme import (
    SP2, SP8, SP10,
    BTN_MD,
    FS_MD, FS_DISP,
    FW_BOLD, FW_MEDIUM,
)
from three_ps_lcca_gui.gui.components.settings_dialog import SettingsPanel


class FirstLaunchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to 3psLCCA")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build_ui()
        self._go_to(0)
        # Qt opens a dialog no taller than 2/3 of the screen, which cut the
        # Theme step at 125% scaling; open at full height when the screen has
        # room, else as tall as it allows (the step scrolls).
        room = self.screen().availableGeometry().height() - 2 * SP10  # title bar
        self.resize(self.sizeHint().width(), min(self.sizeHint().height(), room))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SP10, SP10, SP10, SP8)
        layout.setSpacing(0)

        # Progress bar: one segment per step, green once reached (main.qss)
        progress = QHBoxLayout()
        progress.setSpacing(SP2)
        layout.addLayout(progress)
        layout.addSpacing(SP8 - SP2)

        # Welcome title + subtitle - first step only
        self._welcome = QWidget()
        welcome = QVBoxLayout(self._welcome)
        welcome.setContentsMargins(0, 0, 0, SP8)
        welcome.setSpacing(SP2)

        title = QLabel("Welcome to 3psLCCA")
        title.setFont(font(FS_DISP - 2, FW_BOLD))
        welcome.addWidget(title)

        sub = QLabel("Life Cycle Cost Analysis for bridge projects.")
        sub.setFont(font(FS_MD))
        sub.setEnabled(False)
        welcome.addWidget(sub)
        layout.addWidget(self._welcome)

        # ── Shared settings panel: one section per step ──────────────────
        # The panel only owns the widgets and save(); each section is a page.
        self._panel = SettingsPanel(self, stacked=False)
        self._panel.hide()
        self._panel.move_hint.hide()  # first launch: no existing projects to move
        steps = [section for _, section in self._panel.sections]
        self._segments = []
        for _ in steps:
            segment = QFrame()
            segment.setObjectName("stepSegment")
            segment.setFixedHeight(4)
            progress.addWidget(segment, stretch=1)
            self._segments.append(segment)
        self._pages = QStackedWidget()
        for section in steps:
            content = QWidget()
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.addWidget(section)
            content_layout.addStretch()  # keep a short step at the top, not spread out
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(content)
            self._pages.addWidget(scroll)
        layout.addWidget(self._pages, stretch=1)
        layout.addSpacing(SP8)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(SP2)

        self._btn_back = QPushButton("Back")
        self._btn_back.setFixedHeight(BTN_MD)
        self._btn_back.setFont(font(FS_MD))
        self._btn_back.setStyleSheet(btn_outline())
        self._btn_back.setAutoDefault(False)
        self._btn_back.clicked.connect(lambda: self._go_to(self._pages.currentIndex() - 1))
        policy = self._btn_back.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # Next stays put when Back hides on step 1
        self._btn_back.setSizePolicy(policy)
        btn_row.addWidget(self._btn_back)
        btn_row.addStretch()  # Back on the left, Next on the right

        self._btn_next = QPushButton()
        self._btn_next.setFixedHeight(BTN_MD)
        self._btn_next.setFont(font(FS_MD, FW_MEDIUM))
        self._btn_next.setDefault(True)
        self._btn_next.setStyleSheet(btn_primary())
        self._btn_next.clicked.connect(self._next)
        # As wide as its longest label, so its edge doesn't move on the last step
        self._btn_next.setText("Get Started")
        self._btn_next.setMinimumWidth(self._btn_next.sizeHint().width())
        btn_row.addWidget(self._btn_next)

        layout.addLayout(btn_row)

    def _go_to(self, index: int):
        self._pages.setCurrentIndex(index)
        for i, segment in enumerate(self._segments):
            segment.setProperty("reached", i <= index)
            segment.style().unpolish(segment)
            segment.style().polish(segment)
        self._welcome.setVisible(index == 0)
        self._btn_back.setVisible(index > 0)
        last = index == self._pages.count() - 1
        self._btn_next.setText("Get Started" if last else "Next")

    def _next(self):
        index = self._pages.currentIndex()
        if index < self._pages.count() - 1:
            self._go_to(index + 1)
        else:
            self._accept()

    def _accept(self):
        self._panel.save()
        self.accept()

    def get_name(self) -> str:
        return self._panel.get_name()
