# Table Header Visibility and Sizing Issue

## Symptom
The horizontal header of the import preview table (`ImportComponentTable` in the "Import Preview - Review & Correct" dialog) or trash view tables was not visible or collapsed to 0–1 pixels, hiding column headers like "Name", "Quantity", "Rate", etc. This happened despite setting column headers in the table's constructor.

## Root Cause
The codebase implements a global application event filter, `_TableHeaderWordWrapFilter` (in [main.py](osbridgelcca_new/src/three_ps_lcca_gui/gui/main.py#L97)):

```python
class _TableHeaderWordWrapFilter(QObject):
    """Installs WordWrapHeaderView on every QTableWidget/QTableView that does not
    already use GroupedHeaderView (which handles word wrap itself)."""
```

* During widget polish, the filter checks if the table uses `GroupedHeaderView` or `WordWrapHeaderView`.
* If it uses a plain `QHeaderView` (default), the filter asynchronously (`QTimer.singleShot(0, ...)`) swaps out the horizontal header for a `WordWrapHeaderView`.
* Because this swap runs fully decoupled from the widget's constructor, show events, and resize/reposition calculations:
  1. Any height overrides or formatting applied in the constructor are lost or decoupled.
  2. If the table is embedded in dynamically loaded layouts (like multiple tables inside `QGroupBox` objects inside scroll areas), the layout engine calculates dimensions (e.g. `sizeHint()`) before the header is replaced, or uses stale header height queries, leading to layout collapse.

This same issue previously occurred in the Trash section (fixed in commit `bdf8f56362328175fe316d51a1051595edf35702` for `_FrozenActionTable`).

## Solution
To prevent the global event filter from swapping the header asynchronously and disrupting layout measurements:
1. **Use WordWrapHeaderView directly in constructor:** Explicitly set the horizontal header to `WordWrapHeaderView` (imported from `three_ps_lcca_gui.gui.components.utils.table_widgets`) in the table's `__init__` constructor before applying header actions:
   ```python
   from ..utils.table_widgets import WordWrapHeaderView
   ...
   self.setHorizontalHeader(WordWrapHeaderView(Qt.Horizontal, parent=self))
   self.horizontalHeader().setVisible(True)
   self.horizontalHeader().setFixedHeight(32)
   ```
2. **Defensive Sizing:** Ensure `sizeHint()` uses a minimum fallback height (e.g., `35px`) if `horizontalHeader().height()` returns an uninitialized small value (less than `30px`). Force the table's height geometry in `_update_height()` with `self.setFixedHeight(self.sizeHint().height())` if the vertical scrollbar policy is disabled (`Qt.ScrollBarAlwaysOff`), to prevent parent layout engines from squeezing it.

## Takeaways for Future Tables
* **Never use plain `QHeaderView` headers** on `QTableWidget` or `QTableView` subclasses if they are dynamically sized, nested in scroll area layouts, or require custom sizing.
* **Always set `WordWrapHeaderView` or `GroupedHeaderView`** in the constructor to exempt the table from the global `_TableHeaderWordWrapFilter` swap.
