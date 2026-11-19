"""Input where the user picks % or an absolute value, then types a number.

Stored as {"type": "percent" | "value", "value": float | None}.
None means blank. Switching the mode blanks the number.
"""

import math

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLineEdit, QPushButton, QWidget

PERCENT, VALUE = "percent", "value"


def _num(v):
    """v as a finite float, else None (bools, text, nan, inf are rejected)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def resolve_per_or_val(data, base):
    """Absolute amount for a stored dict: value as is, or percent of base.
    None when blank, malformed, or a percent with no usable base."""
    if not isinstance(data, dict) or data.get("type") not in (PERCENT, VALUE):
        return None
    v = _num(data.get("value"))
    if v is None or data["type"] == VALUE:
        return v
    b = _num(base)
    return None if b is None else b * v / 100


class _Segmented(QWidget):
    """[ % | INR ] toggle with the QComboBox calls this module uses.
    Styled in main.qss (QPushButton#povSeg)."""

    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.idClicked.connect(self._clicked)
        self._data = []

    def addItem(self, text, data):
        b = QPushButton(text)
        b.setObjectName("povSeg")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        self._group.addButton(b, len(self._data))
        self._lay.addWidget(b)
        self._data.append(data)
        for i, btn in enumerate(self._group.buttons()):  # round only the outer corners
            btn.setProperty("seg", "left" if i == 0 else "right" if i == len(self._data) - 1 else "mid")
        if len(self._data) == 1:
            b.setChecked(True)

    def count(self):
        return len(self._data)

    def currentIndex(self):
        return self._group.checkedId()

    def currentData(self):
        return self._data[self.currentIndex()]

    def findData(self, data):
        return self._data.index(data) if data in self._data else -1

    def setCurrentIndex(self, i):
        if 0 <= i < len(self._data) and i != self.currentIndex():
            self._group.button(i).setChecked(True)
            self.currentIndexChanged.emit(i)

    def _clicked(self, i):
        self.currentIndexChanged.emit(i)


class PercentOrValueInput(QWidget):
    changed = Signal()

    def __init__(self, *, unit="", percent_of="", decimals=2,
                 min_pct=0, max_pct=100, min_val=0, max_val=None, parent=None):
        super().__init__(parent)
        self.unit = unit
        self.decimals = decimals
        self.min_pct, self.max_pct = min_pct, max_pct
        self.min_val, self.max_val = min_val, max_val
        of = percent_of.replace("_", " ")
        self._hints = {PERCENT: f"% of {of}" if of else "%",
                       VALUE: f"Amount ({unit})" if unit else "Amount"}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.mode = _Segmented()
        self.mode.addItem("%", PERCENT)
        self.mode.addItem(unit or "Value", VALUE)

        self.line = QLineEdit()
        self.line.setMinimumHeight(30)
        neg = "-?" if min(min_pct, min_val if min_val is not None else -1) < 0 else ""
        frac = rf"(\.\d{{0,{decimals}}})?" if decimals > 0 else ""
        self.line.setValidator(QRegularExpressionValidator(
            QRegularExpression(rf"^{neg}\d*{frac}$")))

        lay.addWidget(self.mode)
        lay.addWidget(self.line, 1)

        self._update_hint()
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.line.textChanged.connect(self.changed)

    def parts(self):
        return self.mode, self.line

    def current_mode(self):
        return self.mode.currentData()

    def _update_hint(self):
        self.line.setPlaceholderText(self._hints[self.current_mode()])

    def _mode_changed(self):
        self._update_hint()
        self.line.blockSignals(True)
        self.line.clear()  # a number typed for one mode means nothing in the other
        self.line.blockSignals(False)
        self.changed.emit()

    def number(self):
        try:
            return float(self.line.text())
        except ValueError:  # blank, "-", "."
            return None

    def get_value(self):
        return {"type": self.current_mode(), "value": self.number()}

    def set_value(self, data):
        data = data if isinstance(data, dict) else {}
        idx = self.mode.findData(data.get("type"))
        raw = data.get("value")
        v = _num(raw) if idx >= 0 else None
        if v is None and raw is not None:  # unknown type or corrupt number: blank %
            idx = 0
        # fixed point, never 1.2e+06; trailing zeros dropped
        text = "" if v is None else f"{v:.{self.decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        for w in self.parts():
            w.blockSignals(True)
        self.mode.setCurrentIndex(max(idx, 0))
        self._update_hint()
        self.line.setText(text)
        for w in self.parts():
            w.blockSignals(False)

    def range_error(self, title):
        """Message when the number is outside its mode's range, else None."""
        v = self.number()
        if v is None:
            return None
        if self.current_mode() == PERCENT:
            lo, hi, u = self.min_pct, self.max_pct, "%"
        else:
            lo, hi, u = self.min_val, self.max_val, f" {self.unit}" if self.unit else ""
        if lo is not None and v < lo:
            return f"'{title}' must be at least {lo:g}{u}"
        if hi is not None and v > hi:
            return f"'{title}' must be at most {hi:g}{u}"
        return None

    def setReadOnly(self, ro):
        self.line.setReadOnly(ro)
        self.mode.setEnabled(not ro)  # switching mode would clear the number
