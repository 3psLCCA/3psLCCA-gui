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
from three_ps_lcca_gui.gui.components.structure.material_flags import material_flag  # noqa: E402


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
    assert (sheet.selected_count(), sheet.selectable_count()) == (2, 3)
    assert _block(preview, "Excavation")._count_lbl.text() == "·  1 / 2 selected"
    assert _block(preview, "Pile")._count_lbl.text() == "·  1 / 1 selected"


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
    assert "(3)" in preview.tabs.tabText(0)  # 2 error rows + 1 warning row


def _status(tbl, row):
    item = tbl.item(row, _col("_issues"))
    return item.text(), item.data(ei._STATE_ROLE)


def test_problem_rows_show_a_status_pill_not_a_tint(preview):
    tbl = _block(preview, "Excavation")._tbl
    assert _status(tbl, 0) == ("Name exists", "warn")
    assert _status(tbl, 1) == ("", "")  # fine: no pill
    assert _status(tbl, 2) == ("Missing Rate", "error")
    for row in range(3):
        item = tbl.item(row, _col("name"))
        assert item.background().style() == Qt.NoBrush
        assert item.data(Qt.ForegroundRole) is None


def test_status_is_the_first_column_after_the_tick_box(preview):
    tbl = _block(preview, "Excavation")._tbl
    assert _col("_issues") == ei._CB_COL + 1
    assert tbl.horizontalHeaderItem(_col("_issues")).text() == "Status"


def test_fixing_rows_updates_tab_and_footer(preview, qapp):
    _block(preview, "Excavation")._tbl.item(2, _col("rate")).setText("250")
    _block(preview, "Pile")._tbl.item(0, _col("unit")).setText("m3")
    qapp.processEvents()

    footer = _text(preview._summary_lbl)
    assert "Errors: 0" in footer and "Valid: 5" in footer
    assert preview.tabs.tabText(0) == "Foundation (1)"  # "CAT#" not shown
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
    assert _status(tbl, 1) == ("", "")
    assert "Warnings: 1" in _text(preview._summary_lbl)


def test_collect_returns_ticked_valid_rows(preview):
    data = preview._collect()
    names = {c: [m["values"]["material_name"] for m in rows]
             for c, rows in data["str_foundation"].items()}
    assert names == {"Excavation": ["New trench"], "Pile": ["Bored pile"]}


def test_row_is_edited_in_the_material_dialog(preview, qapp, monkeypatch):
    """Double-click opens MaterialDialog with the row; its values come back
    into the cells and the row is checked again."""
    tbl = _block(preview, "Excavation")._tbl
    seen = {}

    class _Dialog:
        def __init__(self, comp, parent, data, **kw):
            seen["comp"], seen["data"], seen["kw"] = comp, data, kw

        def exec(self):
            return True

        def get_values(self):
            v = dict(seen["data"]["values"], rate=250.0, carbon_emission=0.2,
                     carbon_unit="kgCO₂e/kg", conversion_factor=2400.0)
            return {"values": v, "meta": {"source": "excel_modified"}}

    monkeypatch.setattr(ei, "MaterialDialog", _Dialog)
    tbl.cellDoubleClicked.emit(2, _col("name"))  # the "Missing Rate" row
    qapp.processEvents()

    assert seen["comp"] == "Excavation"
    assert seen["data"]["state"]["allow_edit_checked"]  # opens unlocked
    assert tbl.item(2, _col("rate")).text() == "250"
    assert tbl.item(2, _col("carbon_emission_units_den")).text() == "kg"
    assert _status(tbl, 2) == ("", "")  # fixed: no pill
    # imported as Excel material the user edited, the file's values kept
    record = tbl._rows[tbl.item(2, ei._CB_COL).data(Qt.UserRole + 1)]
    mat = ei.record_to_material_dict(record)
    assert material_flag(mat) == "excel_modified"
    assert mat["meta"]["db_original"]["rate"] is None  # the file had no rate
    assert mat["values"]["rate"] == 250.0


def test_unedited_row_is_imported_as_excel(preview):
    tbl = _block(preview, "Excavation")._tbl
    record = tbl._rows[tbl.item(0, ei._CB_COL).data(Qt.UserRole + 1)]
    assert material_flag(ei.record_to_material_dict(record)) == "excel"


def test_tick_box_does_not_open_the_dialog(preview, qapp, monkeypatch):
    monkeypatch.setattr(ei, "MaterialDialog", lambda *a, **k: pytest.fail("opened"))
    _block(preview, "Excavation")._tbl.cellDoubleClicked.emit(0, ei._CB_COL)


def test_cells_are_not_edited_in_place(preview):
    tbl = _block(preview, "Excavation")._tbl
    assert tbl.editTriggers() == QtWidgets.QAbstractItemView.NoEditTriggers


def _edit_with(tbl, monkeypatch, row, **changes):
    """Run edit_row(row) through a dialog that returns the row's values with
    ``changes`` - and always claims "excel_modified", as the real one can."""
    class _Dialog:
        def __init__(self, comp, parent, data, **kw):
            self.data = data

        def exec(self):
            return True

        def get_values(self):
            return {"values": dict(self.data["values"], **changes),
                    "meta": {"source": "excel_modified"}}

    monkeypatch.setattr(ei, "MaterialDialog", _Dialog)
    tbl.edit_row(row)
    return tbl._rows[tbl.item(row, ei._CB_COL).data(Qt.UserRole + 1)]


def test_update_without_a_change_is_imported_as_excel(preview, qapp, monkeypatch):
    tbl = _block(preview, "Excavation")._tbl
    record = _edit_with(tbl, monkeypatch, 0)
    assert material_flag(ei.record_to_material_dict(record)) == "excel"


def test_row_changed_and_changed_back_is_imported_as_excel(preview, qapp, monkeypatch):
    tbl = _block(preview, "Excavation")._tbl
    rate = ei.record_to_material_dict(
        tbl._rows[tbl.item(0, ei._CB_COL).data(Qt.UserRole + 1)])["values"]["rate"]
    record = _edit_with(tbl, monkeypatch, 0, rate=rate + 1)
    assert material_flag(ei.record_to_material_dict(record)) == "excel_modified"
    record = _edit_with(tbl, monkeypatch, 0, rate=rate)
    mat = ei.record_to_material_dict(record)
    assert material_flag(mat) == "excel"
    assert mat["meta"]["db_original"]["action"] == "excel"


def test_material_dialog_refuses_what_check_material_refuses(qapp, monkeypatch):
    from three_ps_lcca_gui.gui.components.structure.widgets import material_dialog as md
    shown = []
    monkeypatch.setattr(md.QMessageBox, "critical", lambda *a, **k: shown.append(a[2]))
    data = ei.record_to_material_dict(
        {"name": "A", "quantity": "1", "unit": "m3", "rate": "", "component": "Exc"}
    )
    dlg = md.MaterialDialog("Exc", None, data=data, show_sor_info=False)
    accepted = []
    dlg.accepted.connect(lambda: accepted.append(True))
    dlg.validate_and_accept()
    assert shown == ["Rate (unit cost) is required."]
    assert not accepted
    dlg.deleteLater()


def _cf_problems(unit, den, cf):
    from three_ps_lcca_gui.gui.components.structure.widgets.material_dialog import check_material
    return check_material(name="A", unit=unit, quantity="1", rate="5", carbon_on=True,
                          carbon_den=den, emission="0.2", conversion=cf,
                          recycle_on=False, scrap="", recovery="")


def test_blank_conversion_factor_is_refused_when_units_differ():
    assert [p[0] for p in _cf_problems("m3", "kg", "")] == ["error"]


def test_blank_conversion_factor_with_same_units_is_one_on_import():
    out = ei.verify_schema({"CAT#Foundation": [{
        "name": "A", "quantity": "1", "unit": "kg", "rate": "5", "component": "Exc",
        "carbon_emission": "0.2", "carbon_emission_units_den": "kg",
        "conversion_factor": "",
    }]})["CAT#Foundation"][0]
    assert out["conversion_factor"] == "1"
    assert out["_errors"] == [] and out["_warnings"] == []
