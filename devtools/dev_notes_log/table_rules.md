# 3psLCCA — Table rules

Every table follows these rules. A table that needs to look different gets a
named variant (`table-cat-1`, `table-cat-2`, ...), not its own styling.

## 1. Action column is always floating

- Every Action column uses the shared `FrozenActionColumn` in
  `gui/components/utils/table_widgets.py`: a one-column `QTableWidget`
  overlay pinned to the right edge of the table. It never scrolls sideways
  with the data. Don't copy it into a table file; subclass it only for real
  differences (Structure overrides `reposition()` for its heading strip,
  Carbon adds `set_row_style()`).
- It follows Qt's Frozen Column pattern (see `dev_notes/pyside6_tables`):
  - vertical scrolling is linked both ways
  - row heights follow the main table's `sectionResized`
  - the header height follows the main header's `geometriesChanged`,
    guarded with `shiboken6.isValid` because the header still emits while
    the table is being deleted
- The main table keeps `_ACTION_W` px free on the right (a blank placeholder
  column and/or `setViewportMargins`), so no value sits under the overlay.
- The overlay sets its own `WordWrapHeaderView` in its constructor. If it
  doesn't, the global header swap (`_TableHeaderWordWrapFilter` in `main.py`)
  replaces the header later, after `reposition()` has fixed its height. The
  Action header then comes out taller than the main header, and its rows sit
  lower than the main table's rows.
- The overlay has no frame (`NoFrame`), so its rows start at the same y as the
  main table's rows.

## 2. One common style

- No per-table colours, fonts or stylesheets: no `setStyleSheet`,
  `setFont`, `setForeground` or `setBackground` used for looks, and no
  delegate `fillRect` backgrounds. Qt and the theme palette draw cells and
  headers.
- Delegates exist only for behaviour (editors, validators, action buttons,
  text rewriting via `initStyleOption`). A delegate that must paint something
  draws the cell background with the style (`PE_PanelItemViewItem`), not with
  a hard-coded colour.
- Colour is used only where it carries meaning (an invalid row, a warning),
  and always through `get_token(...)`.

## 3. Headers

- Plain tables get `WordWrapHeaderView`. Tables with column groups get
  `GroupedHeaderView`.
- Qt draws all header text. Header views must not paint text by hand: see
  `3psLCCA_blank_table_headers_fix.md`.
- `WordWrapHeaderView` only adds `Qt.TextWordWrap` and grows its height to fit
  the tallest wrapped title. There is no fixed minimum height.

## 4. Column widths

- Minimum content widths are the `COL_W_*` tokens in `gui/theme.py`. They come
  from the bundled SOR data and are given in px (characters × `CHAR_W_AVG`).
- They are applied with `QHeaderView.setMinimumSectionSize`.

## 5. Painting safety

Any custom painting after a `style().drawControl/drawPrimitive` call must wrap
the style call in `painter.save()/restore()`.
