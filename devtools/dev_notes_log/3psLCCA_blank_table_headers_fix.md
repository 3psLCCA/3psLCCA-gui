# 3psLCCA — Table column headings blank in installer builds

## Symptom

Installed app (exe) only: tables that use `WordWrapHeaderView` show the header
frames but no heading text (Vehicle Emission Factors, Vehicle Traffic Data,
machinery/equipment, transport, action columns). Tables using
`GroupedHeaderView` render fine. Running from source (`.venv`) looks fine.

## Root cause

`WordWrapHeaderView.paintSection` drew the section frame with
`style().drawControl(CE_Header, ...)` and then drew the text itself on the same
painter. With the app stylesheet active (`QHeaderView::section` with
`border-radius`), Qt's `QStyleSheetStyle` in **Qt 6.8** returns the painter with
an **empty clip region** (`hasClipping()==True`, `clipBoundingRect()==0x0`).
The following `drawText` is then clipped away.

Why exe-only: the installer is a conda build pinned to `pyside6<6.10`
(`environment.yml`, `conda-recipe/meta.yaml`) → PySide6 6.8.3. The dev `.venv`
has pip PySide6 6.12, where the clip is not left behind.

`GroupedHeaderView` is unaffected because Qt draws its text inside
`drawControl` (opt.text is set).

The earlier "deferred header swap race" theory was wrong: installing the header
in the constructor (ff0adb6 style, and a global `__init__` patch) did not help.

## Fix

In `WordWrapHeaderView.paintSection` (`gui/components/utils/table_widgets.py`):
wrap `drawControl` in `painter.save()/restore()` and then `setClipRect(rect)`
before drawing the text.

`GroupedHeaderView.paintEvent` (group labels) got the same `save()/restore()`
guard defensively; it was not broken because Qt draws that text itself.

## Coding inconsistencies that let this through

1. Three header-painting strategies: `GroupedHeaderView` and the tinted branch
   of `WordWrapHeaderView` let Qt draw the text (safe); the plain branch of
   `WordWrapHeaderView` blanked `opt.text` and drew text by hand after the
   style call, without isolating painter state. Only that path broke.
2. Dev and release run different Qt: `pyproject.toml`/`requirements.txt` have
   unpinned `PySide6` (dev: 6.12) while conda pins `pyside6<6.10` (release:
   6.8.3). Rendering bugs specific to the release Qt never show in dev. The
   reason for the `<6.10` pin is not recorded.
3. Headers are installed two ways: a global deferred swap
   (`_TableHeaderWordWrapFilter` in `main.py`) and explicit construction-time
   installs (`base_table.py`, `transport_emissions.py`, `comparison_page.py`).
   This was not the cause, but `transport_emissions.py` documented it as one;
   that docstring is corrected.

## Regression test

`tests/test_header_text_visible.py` renders themed headers with and without
labels and asserts the images differ. Fails on the old code under 6.8.3,
passes on the fix under 6.8.3 and 6.12.

## Verify

Render a themed table with the installer's interpreter against the source tree:
`PYTHONPATH=src <install>/python.exe script.py`. Check
`painter.hasClipping()/clipBoundingRect()` after `drawControl`.

## Rule

Any custom painting after a `style().drawControl/drawPrimitive` call must
isolate the style call with `save()/restore()`. Never assume the style leaves
painter state untouched, especially under a stylesheet.
