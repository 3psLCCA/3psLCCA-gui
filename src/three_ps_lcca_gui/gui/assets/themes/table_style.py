"""
table_style.py - column widths for every table, by column id.

QSS cannot size a single column, so this file does that job next to
main.qss. A table calls apply_column_style(table) once, after its headers
are set. Each header label is looked up in HEADER_IDS to get its column id
(like a CSS class), and the id's rule in COLUMN_STYLE sets the width:

    apply_column_style(table)                  # ids from the header labels
    apply_column_style(table, {5: "carbon"})   # a label that means two things

Labels are matched without line breaks, a trailing "(...)" or " *", and
ignoring case, so "Rate (INR)" and "Rate *" both match "rate".
Hidden and blank columns are skipped. A label with no id gets a warning:
add it to HEADER_IDS, or pass the column in overrides.

Widths come from theme.py (COL_PAD_X goes on each side) and are MINIMUM
widths: a column still grows with its contents, never below its width.
  - sized columns: ResizeToContents; the shared header (WordWrapHeaderView)
    never sizes a section under the floor stored in COL_MIN_ROLE.
  - name columns: Stretch; Qt has no floor for a stretched column, so the
    table adds ColumnMinWidthMixin, whose minimumSizeHint keeps the table
    wide enough for every column (the page scrolls sideways instead).
"""
import re
import warnings

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QHeaderView

# header data role holding a column's minimum width in px (set below,
# read by WordWrapHeaderView.sectionSizeFromContents)
COL_MIN_ROLE = Qt.UserRole + 100

from three_ps_lcca_gui.gui.theme import (
    COL_PAD_X,
    COL_W_AMOUNT,
    COL_W_CARBON,
    COL_W_CARBON_SRC,
    COL_W_CARBON_UNIT,
    COL_W_COMPONENT,
    COL_W_DATETIME,
    COL_W_FACTOR,
    COL_W_NAME,
    COL_W_NOTE,
    COL_W_PERCENT,
    COL_W_QUANTITY,
    COL_W_RATE,
    COL_W_RATE_SRC,
    COL_W_SRC_ID,
    COL_W_UNIT,
)

# ids whose column takes the table's spare width
STRETCH_IDS = {"name"}

# column id -> minimum content width in px.
# An id with no rule here (action, misc) keeps what the table set.
COLUMN_STYLE = {
    "name":        COL_W_NAME,
    "component":   COL_W_COMPONENT,
    "unit":        COL_W_UNIT,
    "carbon_unit": COL_W_CARBON_UNIT,
    "src_id":      COL_W_SRC_ID,
    "rate_src":    COL_W_RATE_SRC,
    "carbon_src":  COL_W_CARBON_SRC,
    "rate":        COL_W_RATE,
    "carbon":      COL_W_CARBON,
    "factor":      COL_W_FACTOR,
    "amount":      COL_W_AMOUNT,
    "quantity":    COL_W_QUANTITY,
    "percent":     COL_W_PERCENT,
    "note":        COL_W_NOTE,
    "datetime":    COL_W_DATETIME,
}

# column id -> the header labels that share it.
# "Value" is not listed: it is a quantity or an emission factor depending on
# its group, so those tables pass it in overrides.
_LABELS = {
    "name":        ["Work name", "Material", "Name", "Equipment Name",
                    "Vehicle Type", "Metric", "Cost Item", "Label"],
    "component":   ["Component", "Category", "Stage", "Hour Category",
                    "Energy Source"],
    "unit":        ["Unit"],
    "carbon_unit": ["Carbon Unit"],
    "src_id":      ["ID"],
    "rate_src":    ["Source", "Rate Source"],
    "carbon_src":  ["Carbon EF Source"],
    "rate":        ["Rate", "Scrap Rate"],
    "carbon":      ["Carbon EF", "EF", "Emission Factor", "kg Factor", "kg / unit"],
    "factor":      ["Conversion Factor", "Fuel / Power Rating",
                    "Power to weight ratio"],
    "amount":      ["Amount", "Total Emissions", "Emissions", "Emission",
                    "Recovered Value", "Economic", "Environmental", "Social",
                    "Stage Total"],
    "quantity":    ["Quantity", "Recyclable Quantity", "Vehicles / Day",
                    "Consumption", "No. of Days", "Avg Hrs/Day", "Trips"],
    "percent":     ["Recyclability %", "Recovery %", "Accident",
                    "Traffic Proportion", "Relative Cost"],
    "note":        ["Warning", "Warnings", "Issues", "Reason", "Notes", "Details"],
    "datetime":    ["Date & Time", "Saved At", "Timestamp"],
    "action":      ["Action"],
    "misc":        ["Size", "File", "Event"],
}


def _normalize(label: str) -> str:
    """'Rate (INR)', 'Rate *', 'Scrap Rate\\n(per unit)' -> 'rate', 'scrap rate'."""
    text = " ".join(label.split())             # line breaks -> spaces
    text = re.sub(r"\s*\(.*\)$", "", text)     # trailing "(unit / currency)"
    return text.rstrip(" *").strip().lower()


# normalized header label -> column id
HEADER_IDS = {_normalize(label): col_id
              for col_id, labels in _LABELS.items() for label in labels}


def apply_column_style(table, overrides=None):
    """Set each column's resize mode and width from its header label's id.

    overrides: {column index: column id} for labels that are ambiguous or
    not in HEADER_IDS; they win over the label lookup.
    """
    overrides = overrides or {}
    hdr = table.horizontalHeader()
    model = table.model()
    for col in range(table.columnCount()):
        if table.isColumnHidden(col):
            continue
        col_id = overrides.get(col)
        if col_id is None:
            label = model.headerData(col, hdr.orientation()) or ""
            key = _normalize(str(label))
            if not key:  # blank placeholder column
                continue
            col_id = HEADER_IDS.get(key)
            if col_id is None:
                warnings.warn(
                    f"table_style: header {str(label)!r} (column {col} of "
                    f"{type(table).__name__}) not found - add the mapping manually "
                    f"in HEADER_IDS (table_style.py) or pass it in overrides",
                    stacklevel=2,
                )
                continue
        width = COLUMN_STYLE.get(col_id)
        if width is None:
            continue
        model.setHeaderData(col, hdr.orientation(), width + 2 * COL_PAD_X, COL_MIN_ROLE)
        hdr.setSectionResizeMode(
            col, QHeaderView.Stretch if col_id in STRETCH_IDS else QHeaderView.ResizeToContents)


class ColumnMinWidthMixin:
    """For a table with a stretched column: never narrower than all its
    columns, the stretched one at its floor. Put it before the Qt class:
    class MyTable(ColumnMinWidthMixin, QTableWidget)."""

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hdr = self.horizontalHeader()
        margins = self.viewportMargins()
        width = 2 * self.frameWidth() + margins.left() + margins.right()
        for col in range(hdr.count()):
            if hdr.isSectionHidden(col):
                continue
            if hdr.sectionResizeMode(col) == QHeaderView.Stretch:
                width += self.model().headerData(col, hdr.orientation(), COL_MIN_ROLE) or 0
            else:
                width += hdr.sectionSize(col)
        return QSize(max(hint.width(), width), hint.height())
