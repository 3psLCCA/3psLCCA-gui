"""App-wide fix for spin boxes whose inner editor collapses under style sheets.

On some Qt/PySide builds the style-sheet edit-field rect of a QSpinBox /
QDoubleSpinBox is computed wrongly (no inner padding, or ~0 px wide), so the
text hugs the border or disappears.  This event filter re-fits the inner
editor to the padding defined in main.qss (6px 12px, 1px border, 18px buttons).

Table-cell spin boxes handle this themselves (see table_widgets._FitEditorMixin).
"""

from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QAbstractSpinBox

_SIDE = 13      # 1px border + 12px padding (matches main.qss)
_BUTTONS = 18   # up/down button width (matches main.qss)

_EVENTS = (QEvent.Resize, QEvent.Show, QEvent.StyleChange, QEvent.FontChange)


def _fit(sb: QAbstractSpinBox) -> None:
    right = _SIDE
    if sb.buttonSymbols() != QAbstractSpinBox.NoButtons:
        right += _BUTTONS
    sb.lineEdit().setGeometry(sb.rect().adjusted(_SIDE, 2, -right, -2))


class SpinBoxFitFilter(QObject):
    def eventFilter(self, obj, event):
        if (
            event.type() in _EVENTS
            and isinstance(obj, QAbstractSpinBox)
            and type(obj).__name__ not in ("TableSpinBox", "TableDoubleSpinBox")
        ):
            _fit(obj)
        return False


def install(app) -> SpinBoxFitFilter:
    flt = SpinBoxFitFilter(app)
    app.installEventFilter(flt)
    app._spinbox_fit_filter = flt
    return flt
