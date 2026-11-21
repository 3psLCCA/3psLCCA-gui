"""Floating "+" button in a page's bottom-right corner (main.qss: #fabButton).

A circle with "+" that widens to show its label on hover, like the
"+ Add Component" button on Construction Works Data. It is a child of the
page, not in its layout, and follows the page's size.
"""
from PySide6.QtCore import QEasingCurve, QEvent, QVariantAnimation, Qt
from PySide6.QtWidgets import QPushButton

from three_ps_lcca_gui.gui.theme import SP3, SP5, SP8

FAB_SIZE = 50  # px; keep in sync with border-radius (half) in main.qss


class FabButton(QPushButton):
    def __init__(self, label: str, parent):
        super().__init__("+", parent)
        self.setObjectName("fabButton")
        self.setToolTip(label.lstrip("+ ").strip())
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(FAB_SIZE)
        self._label = label
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda w: self._place(int(w)))
        self._anim.finished.connect(self._on_anim_done)
        parent.installEventFilter(self)
        self._set_collapsed(True)
        self._place(FAB_SIZE)

    def _set_collapsed(self, collapsed: bool):
        self.setText("+" if collapsed else self._label)
        self.setProperty("collapsed", collapsed)
        self.style().unpolish(self)
        self.style().polish(self)

    def _place(self, width: int):
        page = self.parentWidget()
        self.setFixedWidth(width)
        self.move(max(page.width() - width - SP8, 0), max(page.height() - FAB_SIZE - SP5, 0))
        self.raise_()

    def _animate(self, expand: bool):
        self._anim.stop()
        self._anim.setStartValue(self.width())
        if expand:
            self._set_collapsed(False)
            self._anim.setEndValue(self.sizeHint().width() + SP3)
        else:
            self._anim.setEndValue(FAB_SIZE)
        self._anim.start()

    def _on_anim_done(self):
        if self.width() <= FAB_SIZE:
            self._set_collapsed(True)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._animate(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._animate(False)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() in (QEvent.Resize, QEvent.Show):
            self._place(self.width() or FAB_SIZE)
        return super().eventFilter(obj, event)
