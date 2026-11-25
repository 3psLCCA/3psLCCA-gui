"""Structure Excel import: reading the workbook and the Import Preview window.

Covers parse_excel / verify_schema on a real .xlsx, and the preview's
selection counts, Import button, warning counts, row colours and tab labels.
"""
import re

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
from PySide6.QtCore import Qt  # noqa: E402

from three_ps_lcca_gui.gui import themes  # noqa: E402
from three_ps_lcca_gui.gui.components.structure import excel_importer as ei  # noqa: E402


def _col(field):
    """Table column of an IMPORT_COLUMNS field (col 0 is the checkbox)."""
    return next(i for i, (f, _, _n) in enumerate(ei.IMPORT_COLUMNS) if f == field) + ei._DATA_START


def _text(label):
    return re.sub("<[^>]+>", "", label.text())


# ── workbook ────────────────────────────────────────────────────────────


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "boq.xlsx"
    header = ["CID#Name", "CID#Quantity", "CID#Unit", "CID#Rate", "CID#Component"]
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame(
            [["Title row above the header", "", "", "", ""],
             header,
             ["Backfilling", "10", "m3", "100", "Excavation"],
             ["New trench", "5", "m3", "200", "Excavation"],
             ["", "", "", "", ""],                       # blank: skipped
             ["No rate row", "1", "m3", "", "Excavation"],
             ["Pile cap", "2", "", "300", "Pile"],
             ["Bored pile", "3", "m", "400", "Pile"]]
        ).to_excel(xw, sheet_name="CAT#Foundation", header=False, index=False)
        pd.DataFrame([["CID#Name"], ["ignored"]]).to_excel(
            xw, sheet_name="Notes", header=False, index=False)
        pd.DataFrame([["CID#Keys", "CID#Values"], ["Source", "SOR 2023"]]).to_excel(
            xw, sheet_name="Metadata", header=False, index=False)
    return str(path)


def test_parse_reads_only_cat_sheets(workbook):
    out = ei.parse_excel(workbook)
    assert list(out["materials"]) == ["CAT#Foundation"]
    names = [r["name"] for r in out["materials"]["CAT#Foundation"]]
    assert names == ["Backfilling", "New trench", "No rate row", "Pile cap", "Bored pile"]
    assert out["metadata"] == [{"key": "Source", "value": "SOR 2023"}]


def test_verify_routes_and_flags_missing_fields(workbook):
    parsed = ei.verify_schema(ei.parse_excel(workbook)["materials"])
    rows = {r["name"]: r for r in parsed["CAT#Foundation"]}
    assert all(r["_chunk_key"] == "str_foundation" for r in rows.values())
    assert rows["No rate row"]["_errors"]
    assert rows["Pile cap"]["_errors"]
    assert not rows["New trench"]["_errors"]


# ── preview window ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    themes.reapply(app)
    return app


class _Engine:
    def fetch_chunk(self, chunk):
        # "Backfilling" is already in the project
        if chunk == "str_foundation":
            return {"Excavation": [{"values": {"material_name": "Backfilling"}, "state": {}}]}
        return {}


class _Manager:
    class controller:  # noqa: N801 - stands in for manager.controller
        engine = _Engine()


@pytest.fixture
def preview(qapp, workbook):
    parsed = ei.verify_schema(ei.parse_excel(workbook)["materials"])
    w = ei.ImportPreviewWindow(parsed, manager=_Manager())
    w.show()
    qapp.processEvents()  # rows are filled on the next event-loop pass
    yield w
    w.close()


def _block(w, name):
    return w._sheet_tables["CAT#Foundation"]._component_blocks[name]


def test_counts_once_rows_are_filled(preview):
    # 3 rows can be ticked (2 have errors); the 2 new ones start ticked,
    # the existing one does not
    assert preview._select_all_count_lbl.text() == "(2 / 3)"
    assert preview._select_all_chk.checkState() == Qt.PartiallyChecked
    sheet = preview._sheet_tables["CAT#Foundation"]
    assert sheet._sheet_count_lbl.text() == "(2 / 3 selected)"
    assert _block(preview, "Excavation")._count_lbl.text() == "(1 / 2 selected)"
    assert _block(preview, "Pile")._count_lbl.text() == "(1 / 1 selected)"


def test_import_button_follows_selection(preview, qapp):
    btn = preview._import_valid_btn
    assert btn.text() == "Import 2 Rows" and btn.isEnabled()

    preview._on_select_all_clicked()  # 2 of 3 ticked -> ticks all
    qapp.processEvents()
    assert btn.text() == "Import 3 Rows"

    preview._on_select_all_clicked()  # all ticked -> unticks all
    qapp.processEvents()
    assert btn.text() == "Import 0 Rows" and not btn.isEnabled()


def test_error_rows_cannot_be_ticked(preview):
    tbl = _block(preview, "Excavation")._tbl
    cb = tbl.item(2, ei._CB_COL)  # "No rate row"
    assert not (cb.flags() & Qt.ItemIsUserCheckable)


def test_existing_rows_count_as_warnings(preview):
    # the existing "Backfilling" row is tinted as a warning, so it is counted
    assert "Warnings: 1" in _text(preview._summary_lbl)
    assert "(2 ✗)" in preview.tabs.tabText(0)  # errors win over warnings


def test_tinted_rows_keep_the_theme_text_colour(preview):
    tbl = _block(preview, "Excavation")._tbl
    for row in (0, 2):  # warning row, error row
        item = tbl.item(row, _col("name"))
        assert item.background().style() != Qt.NoBrush
        assert item.data(Qt.ForegroundRole) is None


def test_fixing_rows_updates_tab_and_footer(preview, qapp):
    _block(preview, "Excavation")._tbl.item(2, _col("rate")).setText("250")
    _block(preview, "Pile")._tbl.item(0, _col("unit")).setText("m3")
    qapp.processEvents()

    footer = _text(preview._summary_lbl)
    assert "Errors: 0" in footer and "Valid: 5" in footer
    assert preview.tabs.tabText(0) == "CAT#Foundation (1 ⚠)"
    # fixed rows can now be ticked
    assert preview._select_all_count_lbl.text() == "(2 / 5)"


def test_editing_a_row_keeps_its_component(preview, qapp):
    # re-checking an edited row used to rename "Excavation" to
    # "Excavation - Excavation", so it imported into a new component
    _block(preview, "Excavation")._tbl.item(1, _col("rate")).setText("250")  # "New trench"
    qapp.processEvents()
    assert list(preview._collect()["str_foundation"]) == ["Excavation", "Pile"]


def test_renaming_to_an_existing_name_marks_and_unticks_it(preview, qapp):
    tbl = _block(preview, "Excavation")._tbl
    tbl.item(1, _col("name")).setText("BACKFILLING")  # "New trench" -> existing name
    qapp.processEvents()
    assert tbl.item(1, _col("_issues")).text() == "Name exists"
    assert tbl.item(1, ei._CB_COL).checkState() == Qt.Unchecked
    assert "Warnings: 2" in _text(preview._summary_lbl)

    tbl.item(1, _col("name")).setText("Fresh name")  # and away again
    qapp.processEvents()
    assert tbl.item(1, _col("_issues")).text() == "OK"
    assert "Warnings: 1" in _text(preview._summary_lbl)


def test_collect_returns_ticked_valid_rows(preview):
    data = preview._collect()
    names = {c: [m["values"]["material_name"] for m in rows]
             for c, rows in data["str_foundation"].items()}
    assert names == {"Excavation": ["New trench"], "Pile": ["Bored pile"]}
