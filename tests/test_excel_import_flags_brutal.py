"""Brutal tests for the Excel import's edit flags.

The rules under test:
  * parse_excel keeps ``record["_original"]``: the row's cells exactly as the
    file had them, never touched by verify_schema or by edits in the preview.
  * The preview never flags while editing: edit_row writes whatever the
    MaterialDialog returns back into the record and cells; Cancel does nothing.
  * record_to_material_dict decides meta.source at import: "excel_modified"
    only when the values differ from the file's, "excel" otherwise (format
    differences and the blank-CF default are not edits). meta.db_original is
    always the file's values.
  * MaterialDialog's "Allow editing Excel-imported values" box locks / unlocks
    every input of an Excel row and, when unchecked, puts the file back.
"""
import copy

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
from PySide6.QtCore import Qt  # noqa: E402

from three_ps_lcca_gui.gui import themes  # noqa: E402
from three_ps_lcca_gui.gui.components.structure import excel_importer as ei  # noqa: E402
from three_ps_lcca_gui.gui.components.structure.material_flags import material_flag  # noqa: E402
from three_ps_lcca_gui.gui.components.structure.widgets import material_dialog as md  # noqa: E402

SHEET = "CAT#Foundation"
COMP = "Excavation"

# every CID# column, in file order
HEADER = [
    "CID#ID", "CID#Name", "CID#Quantity", "CID#Unit", "CID#Rate", "CID#Rate_Src",
    "CID#Carbon_Emission_Factor", "CID#Carbon_Emission_units", "CID#Conversion_Factor",
    "CID#Carbon_Emission_Src", "CID#Scrap_Rate", "CID#Recovery_Pct", "CID#Component",
]
FIELDS = (
    "src_id", "name", "quantity", "unit", "rate", "rate_src",
    "carbon_emission", "carbon_emission_units_den", "conversion_factor",
    "carbon_emission_src", "scrap_rate", "recovery_pct", "component",
)
EDITABLE = [f for f in FIELDS if f != "component"]

TEXT_INPUTS = ("name_in", "qty_in", "rate_in", "id_in", "src_in", "carbon_em_in",
               "carbon_src_in", "conv_factor_in", "scrap_in", "recycling_perc_in")
TOGGLES = ("unit_in", "carbon_denom_cb", "carbon_chk", "recycle_chk")


# ── helpers ─────────────────────────────────────────────────────────────


def row(**kw):
    """A file row (dict of FIELDS -> cell text); blanks by default."""
    r = {f: "" for f in FIELDS}
    r.update(name="Sand", quantity="10", unit="m3", rate="100", component=COMP)
    r.update(kw)
    return r


FULL = dict(src_id="A-1", name="Concrete M25", quantity="12", unit="m3", rate="4500",
            rate_src="DSR 2023", carbon_emission="0.25", carbon_emission_units_den="kg",
            conversion_factor="2400", carbon_emission_src="ICE v3", scrap_rate="50",
            recovery_pct="90")


def write_wb(path, rows, header=HEADER, sheet=SHEET):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(sheet)
    ws.append(header)
    for r in rows:
        ws.append([None if v == "" else v for v in r])
    wb.save(path)
    return str(path)


def wb_rows(tmp_path, rows, **kw):
    """Write ``rows`` (dicts of FIELDS) as text cells, parse + verify."""
    cells = [[r.get(f, "") for f in FIELDS] for r in rows]
    path = write_wb(tmp_path / "wb.xlsx", cells, **kw)
    return ei.verify_schema(ei.parse_excel(path)["materials"])


def handmade(**kw):
    """A record as parse_excel + verify_schema make it, without a workbook."""
    r = row(**kw)
    r.update(_row_num=2, _errors=[], _warnings=[])
    r["_original"] = {f: r[f] for f in FIELDS}
    ei.verify_schema({SHEET: [r]})
    return r


def mat(record):
    return ei.record_to_material_dict(record)


def source(record):
    return material_flag(mat(record))


def orig_values(record):
    return ei._record_values(record["_original"])


def rec_of(tbl, r):
    return tbl._rows[tbl.item(r, ei._CB_COL).data(Qt.UserRole + 1)]


def col(field):
    return next(i for i, (f, _, _n) in enumerate(ei.IMPORT_COLUMNS) if f == field) + ei._DATA_START


# ── Qt fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    themes.reapply(app)
    return app


@pytest.fixture(autouse=True)
def no_popups(monkeypatch):
    """Answer every message box: errors are recorded, questions get Yes."""
    shown = []
    monkeypatch.setattr(md.QMessageBox, "critical",
                        lambda *a, **k: shown.append(("critical", a[2])))
    monkeypatch.setattr(md.QMessageBox, "warning",
                        lambda *a, **k: shown.append(("warning", a[2])) or md.QMessageBox.Yes)
    monkeypatch.setattr(md.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(ei.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(ei.QMessageBox, "warning", lambda *a, **k: md.QMessageBox.Yes)
    return shown


@pytest.fixture
def window(qapp):
    made = []

    def _make(parsed, manager=None):
        w = ei.ImportPreviewWindow(parsed, manager=manager)
        w.show()
        qapp.processEvents()
        made.append(w)
        return w

    yield _make
    for w in made:
        w.close()
        w.deleteLater()
    qapp.processEvents()


@pytest.fixture
def table(window):
    """The component table for a list of records (one component)."""
    def _make(records):
        w = window({SHEET: records})
        return w, w._sheet_tables[SHEET]._component_blocks[COMP]._tbl
    return _make


@pytest.fixture
def dialog(qapp):
    made = []

    def _make(record_or_data, allow_edit=True, **kw):
        data = (mat(record_or_data) if "values" not in record_or_data
                else record_or_data)
        data["state"]["allow_edit_checked"] = allow_edit
        d = md.MaterialDialog(COMP, None, data=data, show_sor_info=False, **kw)
        made.append(d)
        return d

    yield _make
    for d in made:
        d.deleteLater()
    qapp.processEvents()


def fake_edit(monkeypatch, tbl, r, changes=None, source="excel_modified", accept=True):
    """edit_row through a stand-in dialog returning the row's values + changes."""
    seen = {}

    class _Dialog:
        def __init__(self, comp, parent, data, **kw):
            seen["data"] = data

        def exec(self):
            return accept

        def get_values(self):
            return {"values": dict(seen["data"]["values"], **(changes or {})),
                    "meta": {"source": source}, "state": {}}

    monkeypatch.setattr(ei, "MaterialDialog", _Dialog)
    tbl.edit_row(r)
    return seen


def real_edit(monkeypatch, tbl, r, drive=None, accept=True):
    """edit_row through the REAL MaterialDialog; ``drive(dlg)`` plays the
    user, then Update (accept) or Cancel is pressed."""
    seen = {}

    class _Real(md.MaterialDialog):
        def exec(self):
            seen["dlg"] = self
            if drive:
                drive(self)
            return accept

    monkeypatch.setattr(ei, "MaterialDialog", _Real)
    tbl.edit_row(r)
    return seen.get("dlg")


def set_unit(combo, code):
    idx = combo.findData(code)
    assert idx >= 0, code
    combo.setCurrentIndex(idx)


def numeric_text(t):
    return None if t.strip() == "" else float(t)


# ═════════════════════════ _original at upload ══════════════════════════


class TestOriginalAtUpload:
    def test_every_record_keeps_the_file_cells(self, tmp_path):
        recs = wb_rows(tmp_path, [row(**FULL), row(name="Gravel")])[SHEET]
        for r in recs:
            assert set(r["_original"]) == set(FIELDS)
        assert recs[0]["_original"] == {**row(**FULL)}

    def test_original_holds_raw_strings_as_written(self, tmp_path):
        recs = wb_rows(tmp_path, [row(quantity="5.00", rate="0100", scrap_rate="1e1")])[SHEET]
        o = recs[0]["_original"]
        assert (o["quantity"], o["rate"], o["scrap_rate"]) == ("5.00", "0100", "1e1")
        assert all(isinstance(v, str) for v in o.values())

    def test_numeric_cells_read_the_same_into_record_and_original(self, tmp_path):
        path = write_wb(tmp_path / "n.xlsx",
                        [["ID1", "Sand", 5, "m3", 100.5, "", 0.2, "m3", None, "", 0, 90, COMP]])
        r = ei.verify_schema(ei.parse_excel(path)["materials"])[SHEET][0]
        for f in FIELDS:
            if f not in ("conversion_factor",):
                assert r[f] == r["_original"][f], f
        assert source(r) == "excel"

    def test_verify_cf_default_does_not_touch_original(self, tmp_path):
        r = wb_rows(tmp_path, [row(unit="kg", carbon_emission="0.2",
                                   carbon_emission_units_den="kg")])[SHEET][0]
        assert r["conversion_factor"] == "1"
        assert r["_original"]["conversion_factor"] == ""
        assert source(r) == "excel"
        assert mat(r)["values"]["conversion_factor"] == 1.0
        assert mat(r)["meta"]["db_original"]["conversion_factor"] is None

    def test_blank_cf_different_units_stays_blank_everywhere(self, tmp_path):
        r = wb_rows(tmp_path, [row(unit="m3", carbon_emission="0.2",
                                   carbon_emission_units_den="kg")])[SHEET][0]
        assert r["conversion_factor"] == "" == r["_original"]["conversion_factor"]
        assert r["_errors"]  # the dialog would refuse it too
        assert mat(r)["values"]["conversion_factor"] is None

    def test_blank_cf_same_dimension_other_unit_is_not_defaulted(self, tmp_path):
        r = wb_rows(tmp_path, [row(unit="t", carbon_emission="0.2",
                                   carbon_emission_units_den="kg")])[SHEET][0]
        assert r["conversion_factor"] == ""
        assert mat(r)["values"]["conversion_factor"] is None

    def test_cf_not_defaulted_without_an_emission_factor(self, tmp_path):
        r = wb_rows(tmp_path, [row(unit="kg", carbon_emission_units_den="kg")])[SHEET][0]
        assert r["conversion_factor"] == ""
        assert mat(r)["values"]["conversion_factor"] is None
        assert source(r) == "excel"

    def test_original_is_not_aliased_with_the_record(self, tmp_path):
        r = wb_rows(tmp_path, [row()])[SHEET][0]
        assert r["_original"] is not r
        r["name"] = "Changed"
        assert r["_original"]["name"] == "Sand"
        r["_original"]["rate"] = "999"
        assert r["rate"] == "100"

    def test_rows_do_not_share_an_original(self, tmp_path):
        a, b = wb_rows(tmp_path, [row(), row()])[SHEET]  # duplicate rows
        assert a["_original"] == b["_original"]
        assert a["_original"] is not b["_original"]
        a["_original"]["name"] = "x"
        assert b["_original"]["name"] == "Sand"

    def test_unicode_and_whitespace(self, tmp_path):
        r = wb_rows(tmp_path, [row(name="  Béton armé – 混凝土 ✓  ")])[SHEET][0]
        assert r["_original"]["name"] == "Béton armé – 混凝土 ✓"
        assert source(r) == "excel"
        assert mat(r)["values"]["material_name"] == "Béton armé – 混凝土 ✓"

    def test_original_only_has_the_files_columns(self, tmp_path):
        path = write_wb(tmp_path / "s.xlsx", [["Sand", "10", "m3", "100", COMP]],
                        header=["CID#Name", "CID#Quantity", "CID#Unit", "CID#Rate",
                                "CID#Component"])
        r = ei.verify_schema(ei.parse_excel(path)["materials"])[SHEET][0]
        assert set(r["_original"]) == {"name", "quantity", "unit", "rate", "component"}
        assert source(r) == "excel"

    def test_fallback_sheet_component_prefix_is_not_an_edit(self, tmp_path):
        recs = wb_rows(tmp_path, [row(component="Joint")], sheet="CAT#Weird")["CAT#Weird"]
        r = recs[0]
        assert r["component"] == "Weird - Joint"
        assert r["_original"]["component"] == "Joint"
        assert source(r) == "excel"

    def test_error_rows_keep_an_original_too(self, tmp_path):
        r = wb_rows(tmp_path, [row(rate="", quantity="abc")])[SHEET][0]
        assert r["_errors"]
        assert r["_original"]["quantity"] == "abc"
        assert source(r) == "excel"


# ═════════════════════════ record_to_material_dict ══════════════════════


NUMERIC = ("quantity", "rate", "carbon_emission", "conversion_factor",
           "scrap_rate", "recovery_pct")


class TestImportFlag:
    def test_unedited_full_row_is_excel(self):
        assert source(handmade(**FULL)) == "excel"

    def test_handmade_record_without_original_is_excel(self):
        r = row(**FULL)
        m = mat(r)
        assert material_flag(m) == "excel"
        assert m["meta"]["db_original"]["action"] == "excel"
        assert m["meta"]["db_original"]["name"] == "Concrete M25"

    def test_handmade_record_without_original_even_after_changes(self):
        r = row(**FULL)
        r["rate"] = "1"
        assert source(r) == "excel"

    @pytest.mark.parametrize("field", NUMERIC)
    @pytest.mark.parametrize("shown", ["12.00", "12.0", " 12 ", "1.2e1", "012", "+12"])
    def test_format_differences_are_not_edits(self, field, shown):
        r = handmade(**{**FULL, field: "12"})
        r[field] = shown
        assert source(r) == "excel", (field, shown)

    @pytest.mark.parametrize("field", NUMERIC)
    def test_python_float_written_back_is_not_an_edit(self, field):
        r = handmade(**{**FULL, field: "12.50"})
        r[field] = ei._cell_text(field, 12.5)
        assert source(r) == "excel"

    @pytest.mark.parametrize("field,new", [
        ("src_id", "B-2"), ("name", "Concrete M30"), ("quantity", "13"),
        ("unit", "kg"), ("rate", "4501"), ("rate_src", "Market"),
        ("carbon_emission", "0.26"), ("carbon_emission_units_den", "t"),
        ("conversion_factor", "2401"), ("carbon_emission_src", "IPCC"),
        ("scrap_rate", "51"), ("recovery_pct", "91"),
    ])
    def test_any_field_changed_is_modified(self, field, new):
        r = handmade(**FULL)
        r[field] = new
        assert source(r) == "excel_modified"

    @pytest.mark.parametrize("field", EDITABLE)
    def test_abc_efg_abc_round_trip(self, field):
        r = handmade(**FULL)
        was = r[field]
        r[field] = "777" if field in NUMERIC else "efg"
        assert source(r) == "excel_modified"
        r[field] = was
        assert source(r) == "excel"

    def test_text_round_trip_with_different_case_is_an_edit(self):
        r = handmade(name="abc")
        r["name"] = "ABC"
        assert source(r) == "excel_modified"

    def test_whitespace_only_change_is_not_an_edit(self):
        r = handmade(**FULL)
        r["name"] = "  Concrete M25 "
        r["rate_src"] = "DSR 2023  "
        assert source(r) == "excel"

    def test_many_fields_partial_revert_then_full_revert(self):
        r = handmade(**FULL)
        before = {f: r[f] for f in EDITABLE}
        r.update(name="X", rate="1", carbon_emission="9", scrap_rate="1")
        assert source(r) == "excel_modified"
        r.update(name=before["name"], rate=before["rate"])
        assert source(r) == "excel_modified"
        r.update(carbon_emission=before["carbon_emission"])
        assert source(r) == "excel_modified"
        r.update(scrap_rate=before["scrap_rate"])
        assert source(r) == "excel"

    @pytest.mark.parametrize("field", ("rate", "carbon_emission", "scrap_rate",
                                       "recovery_pct", "conversion_factor"))
    def test_blank_and_zero_differ(self, field):
        r = handmade(**{**FULL, field: ""})
        r[field] = "0"
        assert source(r) == "excel_modified"
        r = handmade(**{**FULL, field: "0"})
        r[field] = ""
        assert source(r) == "excel_modified"

    def test_cf_default_is_not_an_edit_whatever_its_spelling(self):
        r = handmade(unit="kg", carbon_emission="0.2", carbon_emission_units_den="kg")
        for cf in ("1", "1.0", "1.00", "", " 1 "):
            r["conversion_factor"] = cf
            assert source(r) == "excel", cf

    def test_cf_changed_from_default_is_an_edit(self):
        r = handmade(unit="kg", carbon_emission="0.2", carbon_emission_units_den="kg")
        r["conversion_factor"] = "2"
        assert source(r) == "excel_modified"

    def test_explicit_cf_one_in_file_and_blank_now_same_units(self):
        r = handmade(unit="kg", carbon_emission="0.2", carbon_emission_units_den="kg",
                     conversion_factor="1")
        r["conversion_factor"] = ""
        assert source(r) == "excel"

    def test_blank_cf_different_units_stays_none(self):
        r = handmade(unit="m3", carbon_emission="0.2", carbon_emission_units_den="kg")
        assert mat(r)["values"]["conversion_factor"] is None
        assert source(r) == "excel"

    def test_filling_a_missing_cf_is_an_edit(self):
        r = handmade(unit="m3", carbon_emission="0.2", carbon_emission_units_den="kg")
        r["conversion_factor"] = "2400"
        assert source(r) == "excel_modified"

    def test_db_original_is_the_file_after_several_edits(self):
        r = handmade(**{**FULL, "conversion_factor": "", "unit": "kg"})
        r.update(name="A", rate="1")
        r.update(name="B", rate="2", conversion_factor="5")
        snap = mat(r)["meta"]["db_original"]
        assert snap["action"] == "excel"
        assert snap["name"] == "Concrete M25"
        assert snap["rate"] == "4500"
        assert snap["conversion_factor"] is None  # blank in the file -> None
        assert snap["unit"] == "kg"
        assert not any(k.startswith("_") for k in snap)

    def test_db_original_blanks_are_none(self):
        snap = mat(handmade())["meta"]["db_original"]
        for f in ("src_id", "rate_src", "carbon_emission", "conversion_factor",
                  "scrap_rate", "recovery_pct"):
            assert snap[f] is None, f

    def test_db_original_is_a_fresh_dict_each_time(self):
        r = handmade(**FULL)
        snap = mat(r)["meta"]["db_original"]
        snap["name"] = "mutated"
        assert r["_original"]["name"] == "Concrete M25"
        assert mat(r)["meta"]["db_original"]["name"] == "Concrete M25"

    def test_record_to_material_dict_mutates_nothing(self):
        r = handmade(**FULL)
        r["rate"] = "5"
        before = copy.deepcopy(r)
        mat(r)
        mat(r)
        assert r == before

    def test_state_flags_follow_current_values(self):
        r = handmade(**FULL)
        r.update(carbon_emission="", carbon_emission_units_den="", scrap_rate="",
                 recovery_pct="")
        m = mat(r)
        assert material_flag(m) == "excel_modified"
        assert m["state"]["included_in_carbon_emission"] is False
        assert m["state"]["included_in_recyclability"] is False

    def test_original_missing_columns_vs_blank_written_back(self):
        r = {"name": "Sand", "quantity": "1", "unit": "m3", "rate": "5", "component": COMP}
        r["_original"] = dict(r)
        for f in EDITABLE:
            r.setdefault(f, "")  # edit_row writes every dialog field back
        assert source(r) == "excel"


# ═════════════════════════ edit_row (stand-in dialog) ═══════════════════


class TestEditRowWriteBack:
    def test_cancel_leaves_record_and_cells_untouched(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        before = copy.deepcopy(rec_of(tbl, 0))
        cells = [tbl.item(0, c).text() for c in range(1, tbl.columnCount())]
        fake_edit(monkeypatch, tbl, 0, {"rate": 1.0, "material_name": "X"}, accept=False)
        assert rec_of(tbl, 0) == before
        assert [tbl.item(0, c).text() for c in range(1, tbl.columnCount())] == cells
        assert source(rec_of(tbl, 0)) == "excel"

    def test_cancel_with_the_real_dialog_after_edits(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        before = copy.deepcopy(rec_of(tbl, 0))

        def drive(d):
            d.name_in.setText("Nope")
            d.rate_in.setText("1")
        real_edit(monkeypatch, tbl, 0, drive, accept=False)
        assert rec_of(tbl, 0) == before

    @pytest.mark.parametrize("claimed", ["excel", "excel_modified", "manual", "db", ""])
    def test_values_written_whatever_source_the_dialog_reports(self, table, monkeypatch,
                                                              claimed):
        w, tbl = table([handmade(**FULL)])
        fake_edit(monkeypatch, tbl, 0, {"rate": 5000.0}, source=claimed)
        r = rec_of(tbl, 0)
        assert r["rate"] == "5000"
        assert tbl.item(0, col("rate")).text() == "5000"
        assert source(r) == "excel_modified"

    @pytest.mark.parametrize("claimed", ["excel", "excel_modified"])
    def test_no_change_is_excel_whatever_the_dialog_claims(self, table, monkeypatch,
                                                           claimed):
        w, tbl = table([handmade(**FULL)])
        fake_edit(monkeypatch, tbl, 0, source=claimed)
        assert source(rec_of(tbl, 0)) == "excel"

    def test_dialog_opens_with_the_files_snapshot_after_edits(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        fake_edit(monkeypatch, tbl, 0, {"rate": 1.0, "material_name": "Edited"})
        seen = fake_edit(monkeypatch, tbl, 0)  # open again
        data = seen["data"]
        assert data["values"]["rate"] == 1.0
        assert data["values"]["material_name"] == "Edited"
        assert material_flag(data) == "excel_modified"
        assert data["meta"]["db_original"]["rate"] == "4500"
        assert data["meta"]["db_original"]["name"] == "Concrete M25"
        assert data["state"]["allow_edit_checked"] is True

    def test_original_untouched_by_edits(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        orig = copy.deepcopy(rec_of(tbl, 0)["_original"])
        for rate in (1.0, 2.0, 3.0):
            fake_edit(monkeypatch, tbl, 0, {"rate": rate, "material_name": f"n{rate}"})
        assert rec_of(tbl, 0)["_original"] == orig

    def test_carbon_unit_written_back_as_the_denominator(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        fake_edit(monkeypatch, tbl, 0, {"carbon_unit": "kgCO₂e/t"})
        r = rec_of(tbl, 0)
        assert r["carbon_emission_units_den"] == "t"
        assert tbl.item(0, col("carbon_emission_units_den")).text() == "t"
        assert source(r) == "excel_modified"

    def test_edit_that_breaks_the_row_unticks_it_and_skips_it(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL), handmade(name="Other")])
        fake_edit(monkeypatch, tbl, 0, {"quantity": 0.0})
        assert rec_of(tbl, 0)["_errors"]
        assert tbl.item(0, ei._CB_COL).checkState() == Qt.Unchecked
        names = [m["values"]["material_name"] for m in w._collect()["str_foundation"][COMP]]
        assert names == ["Other"]

    def test_fixing_an_error_row_is_modified(self, table, monkeypatch):
        w, tbl = table([handmade(rate="")])
        assert rec_of(tbl, 0)["_errors"]
        fake_edit(monkeypatch, tbl, 0, {"rate": 10.0})
        r = rec_of(tbl, 0)
        assert not r["_errors"]
        assert source(r) == "excel_modified"
        assert mat(r)["meta"]["db_original"]["rate"] is None

    def test_edit_to_blank_cf_same_units_is_defaulted_and_not_an_edit(self, table,
                                                                     monkeypatch):
        w, tbl = table([handmade(unit="kg", carbon_emission="0.2",
                                 carbon_emission_units_den="kg")])
        fake_edit(monkeypatch, tbl, 0, {"conversion_factor": None})
        r = rec_of(tbl, 0)
        assert r["conversion_factor"] == "1"  # re-checked like on upload
        assert r["_original"]["conversion_factor"] == ""
        assert source(r) == "excel"

    def test_duplicate_rows_flag_independently(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL), handmade(**FULL)])
        fake_edit(monkeypatch, tbl, 1, {"rate": 1.0})
        assert source(rec_of(tbl, 0)) == "excel"
        assert source(rec_of(tbl, 1)) == "excel_modified"

    def test_edit_keeps_component_and_routing(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        fake_edit(monkeypatch, tbl, 0, {"rate": 1.0})
        r = rec_of(tbl, 0)
        assert r["component"] == COMP and r["_chunk_key"] == "str_foundation"


# ═════════════════════════ the real MaterialDialog: lock ════════════════


def assert_locked(d, locked):
    for name in TEXT_INPUTS:
        assert getattr(d, name).isReadOnly() == locked, name
    for name in TOGGLES:
        assert getattr(d, name).isEnabled() == (not locked), name


class TestAllowEditLock:
    def test_opens_unlocked_from_the_preview(self, dialog):
        d = dialog(handmade(**FULL))
        assert d._allow_edit_chk.isChecked() and d._allow_edit_chk.isEnabled()
        assert d._allow_edit_chk.text() == "Allow editing Excel-imported values"
        assert_locked(d, False)

    def test_unchecked_locks_every_input(self, dialog):
        d = dialog(handmade(**FULL))
        d._allow_edit_chk.setChecked(False)
        assert_locked(d, True)

    def test_check_uncheck_check_cycles(self, dialog):
        d = dialog(handmade(**FULL))
        for _ in range(3):
            d._allow_edit_chk.setChecked(False)
            assert_locked(d, True)
            d._allow_edit_chk.setChecked(True)
            assert_locked(d, False)

    def test_opened_locked_locks_every_input(self, dialog):
        d = dialog(handmade(**FULL), allow_edit=False)
        assert not d._allow_edit_chk.isChecked()
        assert_locked(d, True)
        d._allow_edit_chk.setChecked(True)
        assert_locked(d, False)

    def test_row_without_carbon_locks_and_unlocks_too(self, dialog):
        d = dialog(handmade())
        d._allow_edit_chk.setChecked(False)
        assert_locked(d, True)
        d._allow_edit_chk.setChecked(True)
        assert_locked(d, False)

    def test_excel_modified_row_locks_every_input(self, dialog, table, monkeypatch):
        r = handmade(**FULL)
        r["rate"] = "1"
        data = mat(r)
        assert material_flag(data) == "excel_modified"
        d = dialog(data)
        d._allow_edit_chk.setChecked(False)
        assert_locked(d, True)

    @pytest.mark.parametrize("mode", ["emissions_only", "recyclability_only"])
    def test_partial_dialogs_keep_their_own_read_only_set(self, dialog, mode):
        d = dialog(handmade(**FULL), allow_edit=False, **{mode: True})
        for _ in range(2):
            for checked in (True, False):
                d._allow_edit_chk.setChecked(checked)
                # (rate/unit/carbon follow the old DB lock there, as before;
                # the Excel lock must not touch name/qty/recycling)
                for name in ("name_in", "qty_in"):
                    assert getattr(d, name).isReadOnly(), (mode, checked, name)
                if mode == "emissions_only":
                    assert d.scrap_in.isReadOnly() and d.recycling_perc_in.isReadOnly()
                else:
                    assert not d.scrap_in.isReadOnly()
                    assert not d.recycling_perc_in.isReadOnly()

    def test_database_material_quantity_stays_editable_when_locked(self, dialog):
        data = {
            "values": {"material_name": "DB Sand", "quantity": 5.0, "unit": "m3",
                       "rate": 100.0, "rate_source": "SOR"},
            "meta": {"source": "db", "source_db_key": "k",
                     "db_original": {"action": "internal_db", "name": "DB Sand",
                                     "unit": "m3", "rate": 100.0, "db_key": "k"}},
            "state": {"included_in_carbon_emission": False,
                      "included_in_recyclability": False},
        }
        d = dialog(data, allow_edit=False)
        assert d.rate_in.isReadOnly()  # the DB-filled inputs are locked
        assert not d.qty_in.isReadOnly()
        assert not d.name_in.isReadOnly()
        assert not d.scrap_in.isReadOnly()
        d._allow_edit_chk.setChecked(True)
        d._allow_edit_chk.setChecked(False)
        assert not d.qty_in.isReadOnly()
        assert d.rate_in.isReadOnly()


# ═════════════════════════ the real MaterialDialog: restore ═════════════


def edit_everything(d):
    d.name_in.setText("Something else")
    d.id_in.setText("ZZ-9")
    d.qty_in.setText("99")
    set_unit(d.unit_in, "kg")
    d.rate_in.setText("1")
    d.src_in.setText("Other source")
    d.carbon_chk.setChecked(True)
    d.carbon_em_in.setText("9")
    set_unit(d.carbon_denom_cb, "t")
    d.conv_factor_in.setText("5")
    d.carbon_src_in.setText("Other carbon")
    d.recycle_chk.setChecked(True)
    d.scrap_in.setText("1")
    d.recycling_perc_in.setText("2")


def assert_shows_file(d, f):
    """The dialog's inputs hold the file row ``f`` (numbers compared as numbers)."""
    assert d.name_in.text() == f["name"]
    assert d.id_in.text() == f["src_id"]
    assert numeric_text(d.qty_in.text()) == numeric_text(f["quantity"])
    assert d.unit_in.currentData() == f["unit"]
    assert numeric_text(d.rate_in.text()) == numeric_text(f["rate"])
    assert d.src_in.text() == f["rate_src"]
    has_carbon = bool(f["carbon_emission"] and f["carbon_emission_units_den"])
    assert d.carbon_chk.isChecked() == has_carbon
    if has_carbon:
        assert numeric_text(d.carbon_em_in.text()) == numeric_text(f["carbon_emission"])
        assert d.carbon_denom_cb.currentData() == f["carbon_emission_units_den"]
        assert d.carbon_src_in.text() == f["carbon_emission_src"]
        if f["conversion_factor"]:
            assert numeric_text(d.conv_factor_in.text()) == numeric_text(
                f["conversion_factor"])
    has_recycle = bool(f["scrap_rate"] or f["recovery_pct"])
    assert d.recycle_chk.isChecked() == has_recycle
    assert numeric_text(d.scrap_in.text()) == numeric_text(f["scrap_rate"])
    assert numeric_text(d.recycling_perc_in.text()) == numeric_text(f["recovery_pct"])


class TestUncheckRestoresTheFile:
    def test_every_value_comes_back(self, dialog):
        r = handmade(**FULL)
        d = dialog(r)
        edit_everything(d)
        d._allow_edit_chk.setChecked(False)
        assert_shows_file(d, r["_original"])

    def test_restored_values_import_as_excel(self, dialog):
        r = handmade(**FULL)
        d = dialog(r)
        edit_everything(d)
        d._allow_edit_chk.setChecked(False)
        expected = orig_values(r)
        expected.pop("is_recyclable")  # not part of the dialog's values
        assert d.get_values()["values"] == expected

    @pytest.mark.parametrize("field,value", [
        ("carbon_emission", "0.179"),
        ("rate", "4500.755"),
        ("conversion_factor", "2400.125"),
        ("quantity", "12.345"),
    ])
    def test_uncheck_restores_full_precision(self, dialog, field, value):
        r = handmade(**{**FULL, field: value})
        d = dialog(r)
        edit_everything(d)
        d._allow_edit_chk.setChecked(False)
        got = d.get_values()["values"]
        key = {"quantity": "quantity", "rate": "rate", "carbon_emission": "carbon_emission",
               "conversion_factor": "conversion_factor"}[field]
        assert got[key] == float(value)

    def test_includes_come_back_off_for_a_row_without_carbon_or_recycling(self, dialog):
        r = handmade(src_id="S1", rate_src="Mkt")
        d = dialog(r)
        edit_everything(d)  # turns both sections on
        assert d.carbon_chk.isChecked() and d.recycle_chk.isChecked()
        d._allow_edit_chk.setChecked(False)
        assert not d.carbon_chk.isChecked()
        assert not d.recycle_chk.isChecked()
        assert_shows_file(d, r["_original"])

    def test_includes_come_back_on_after_being_switched_off(self, dialog):
        r = handmade(**FULL)
        d = dialog(r)
        d.carbon_chk.setChecked(False)
        d.recycle_chk.setChecked(False)
        d._allow_edit_chk.setChecked(False)
        assert d.carbon_chk.isChecked() and d.recycle_chk.isChecked()

    def test_only_scrap_in_file(self, dialog):
        r = handmade(scrap_rate="40")
        d = dialog(r)
        edit_everything(d)
        d._allow_edit_chk.setChecked(False)
        assert_shows_file(d, r["_original"])

    def test_restores_the_file_not_the_shown_record(self, dialog):
        r = handmade(**FULL)
        r.update(name="Edited before", rate="7", scrap_rate="3")  # an earlier edit
        d = dialog(r)
        assert d.name_in.text() == "Edited before"
        d._allow_edit_chk.setChecked(False)
        assert_shows_file(d, r["_original"])

    def test_cf_default_row_restores_to_one(self, dialog):
        r = handmade(unit="kg", carbon_emission="0.2", carbon_emission_units_den="kg")
        d = dialog(r)
        set_unit(d.unit_in, "m3")
        d.conv_factor_in.setText("2400")
        d._allow_edit_chk.setChecked(False)
        assert d.unit_in.currentData() == "kg"
        assert d.carbon_denom_cb.currentData() == "kg"
        assert numeric_text(d.conv_factor_in.text()) == 1.0

    def test_uncheck_then_recheck_keeps_values_editable_and_importable(self, dialog):
        r = handmade(**FULL)
        d = dialog(r)
        d._allow_edit_chk.setChecked(False)
        d._allow_edit_chk.setChecked(True)
        assert_locked(d, False)
        d.rate_in.setText("4600")
        assert d.get_values()["values"]["rate"] == 4600.0


# ═════════════════════════ real dialog through edit_row ═════════════════


NO_CHANGE_ROWS = {
    "plain": dict(),
    "full": FULL,
    "unicode": dict(name="Béton armé – 混凝土 ✓", src_id="Ж-7", rate_src="СОР"),
    "carbon_same_unit_cf_default": dict(unit="kg", carbon_emission="0.2",
                                        carbon_emission_units_den="kg"),
    "carbon_same_unit_cf_one": dict(unit="kg", carbon_emission="0.2",
                                    carbon_emission_units_den="kg",
                                    conversion_factor="1"),
    "carbon_cf_other_dimension": dict(unit="m3", carbon_emission="0.2",
                                      carbon_emission_units_den="kg",
                                      conversion_factor="2400"),
    "carbon_cf_same_dimension": dict(unit="t", carbon_emission="0.2",
                                     carbon_emission_units_den="kg",
                                     conversion_factor="1000"),
    "recycle_both": dict(scrap_rate="50", recovery_pct="90"),
    "recycle_scrap_only": dict(scrap_rate="50"),
    "recycle_recovery_only": dict(recovery_pct="90"),
    "rate_decimals": dict(rate="4500.75"),
    "formatted_numbers": dict(quantity="10.00", rate="100.0"),
}


class TestRealDialogUpdateWithoutChange:
    @pytest.mark.parametrize("kw", NO_CHANGE_ROWS.values(), ids=NO_CHANGE_ROWS.keys())
    def test_update_without_change_is_excel(self, table, monkeypatch, kw):
        w, tbl = table([handmade(**kw)])
        assert not rec_of(tbl, 0)["_errors"]
        real_edit(monkeypatch, tbl, 0)
        r = rec_of(tbl, 0)
        assert mat(r)["values"] == orig_values(r)
        assert source(r) == "excel"

    @pytest.mark.parametrize("kw", NO_CHANGE_ROWS.values(), ids=NO_CHANGE_ROWS.keys())
    def test_update_twice_without_change_is_excel(self, table, monkeypatch, kw):
        w, tbl = table([handmade(**kw)])
        real_edit(monkeypatch, tbl, 0)
        real_edit(monkeypatch, tbl, 0)
        assert source(rec_of(tbl, 0)) == "excel"

    @pytest.mark.parametrize("kw", [dict(quantity="12.345"),
                                    dict(scrap_rate="12.345"),
                                    dict(recovery_pct="33.333")],
                             ids=["quantity", "scrap", "recovery"])
    def test_more_than_two_decimals_survive_update(self, table, monkeypatch, kw):
        w, tbl = table([handmade(**kw)])
        real_edit(monkeypatch, tbl, 0)
        r = rec_of(tbl, 0)
        assert mat(r)["values"] == orig_values(r)
        assert source(r) == "excel"

    def test_zero_rate_survives_update(self, table, monkeypatch):
        w, tbl = table([handmade(rate="0")])
        assert not rec_of(tbl, 0)["_errors"]
        real_edit(monkeypatch, tbl, 0)
        r = rec_of(tbl, 0)
        assert not r["_errors"]
        assert source(r) == "excel"

    def test_zero_recovery_with_scrap_survives_update(self, table, monkeypatch):
        w, tbl = table([handmade(scrap_rate="10", recovery_pct="0")])
        real_edit(monkeypatch, tbl, 0)
        assert source(rec_of(tbl, 0)) == "excel"

    def test_zero_emission_factor_survives_update(self, table, monkeypatch):
        w, tbl = table([handmade(unit="kg", carbon_emission="0",
                                 carbon_emission_units_den="kg")])
        assert not rec_of(tbl, 0)["_errors"]
        real_edit(monkeypatch, tbl, 0)
        assert source(rec_of(tbl, 0)) == "excel"

    def test_zero_scrap_only_survives_update(self, table, monkeypatch):
        w, tbl = table([handmade(scrap_rate="0")])
        assert not rec_of(tbl, 0)["_errors"]
        real_edit(monkeypatch, tbl, 0)
        assert source(rec_of(tbl, 0)) == "excel"

    def test_unknown_unit_survives_update(self, table, monkeypatch):
        w, tbl = table([handmade(unit="bag")])
        assert not rec_of(tbl, 0)["_errors"]
        real_edit(monkeypatch, tbl, 0)
        r = rec_of(tbl, 0)
        assert r["unit"] == "bag"
        assert source(r) == "excel"

    def test_three_decimal_emission_factor_survives_update(self, table, monkeypatch):
        w, tbl = table([handmade(unit="kg", carbon_emission="0.179",
                                 carbon_emission_units_den="kg")])
        real_edit(monkeypatch, tbl, 0)
        assert source(rec_of(tbl, 0)) == "excel"


class TestRealDialogEdits:
    def test_rename_then_rename_back_is_excel(self, table, monkeypatch):
        w, tbl = table([handmade(**{**FULL, "name": "abc"})])
        real_edit(monkeypatch, tbl, 0, lambda d: d.name_in.setText("efg"))
        assert rec_of(tbl, 0)["name"] == "efg"
        assert source(rec_of(tbl, 0)) == "excel_modified"
        real_edit(monkeypatch, tbl, 0, lambda d: d.name_in.setText("abc"))
        assert source(rec_of(tbl, 0)) == "excel"

    def test_several_fields_then_partial_then_full_revert(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])

        def change(d):
            d.rate_in.setText("1")
            d.qty_in.setText("2")
            d.carbon_em_in.setText("3")
        real_edit(monkeypatch, tbl, 0, change)
        assert source(rec_of(tbl, 0)) == "excel_modified"
        real_edit(monkeypatch, tbl, 0, lambda d: (d.rate_in.setText("4500"),
                                                  d.qty_in.setText("12")))
        assert source(rec_of(tbl, 0)) == "excel_modified"
        real_edit(monkeypatch, tbl, 0, lambda d: d.carbon_em_in.setText("0.25"))
        assert source(rec_of(tbl, 0)) == "excel"

    def test_edit_everything_then_uncheck_is_excel(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])

        def drive(d):
            edit_everything(d)
            d._allow_edit_chk.setChecked(False)
        real_edit(monkeypatch, tbl, 0, drive)
        r = rec_of(tbl, 0)
        assert mat(r)["values"] == orig_values(r)
        assert source(r) == "excel"

    def test_reopen_an_edited_row_and_uncheck_restores_the_file(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        real_edit(monkeypatch, tbl, 0, edit_everything)
        assert rec_of(tbl, 0)["name"] == "Something else"
        assert source(rec_of(tbl, 0)) == "excel_modified"

        seen = {}

        def drive(d):
            seen["opened_with"] = d.name_in.text()
            d._allow_edit_chk.setChecked(False)
            seen["restored"] = d.name_in.text()
        real_edit(monkeypatch, tbl, 0, drive)
        assert seen["opened_with"] == "Something else"
        assert seen["restored"] == "Concrete M25"
        r = rec_of(tbl, 0)
        assert r["name"] == "Concrete M25"
        assert source(r) == "excel"

    def test_three_edits_then_uncheck_still_restores_the_file(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        for rate in ("1", "2", "3"):
            real_edit(monkeypatch, tbl, 0, lambda d, rate=rate: d.rate_in.setText(rate))
        assert rec_of(tbl, 0)["rate"] == "3"
        real_edit(monkeypatch, tbl, 0, lambda d: d._allow_edit_chk.setChecked(False))
        assert rec_of(tbl, 0)["rate"] == "4500"
        assert source(rec_of(tbl, 0)) == "excel"

    def test_real_dialog_edit_revalidates_the_row(self, table, monkeypatch):
        w, tbl = table([handmade(rate="")])
        assert rec_of(tbl, 0)["_errors"]
        real_edit(monkeypatch, tbl, 0, lambda d: d.rate_in.setText("250"))
        r = rec_of(tbl, 0)
        assert not r["_errors"]
        assert tbl.item(0, col("_issues")).text() == ""
        assert source(r) == "excel_modified"
        assert mat(r)["meta"]["db_original"]["rate"] is None

    def test_fixing_missing_cf_by_unit_suggestion_is_not_modified(self, table, monkeypatch):
        """A blank CF filled with the units' own ratio is what the report
        assumes anyway (material_flag), so the row stays plain excel."""
        w, tbl = table([handmade(unit="t", carbon_emission="0.2",
                                 carbon_emission_units_den="kg")])
        assert rec_of(tbl, 0)["_errors"]
        real_edit(monkeypatch, tbl, 0)  # the dialog suggests 1000
        r = rec_of(tbl, 0)
        assert not r["_errors"]
        assert float(r["conversion_factor"]) == 1000.0
        assert source(r) == "excel"

    def test_original_never_changes_through_real_edits(self, table, monkeypatch):
        w, tbl = table([handmade(**FULL)])
        orig = copy.deepcopy(rec_of(tbl, 0)["_original"])
        real_edit(monkeypatch, tbl, 0, edit_everything)
        real_edit(monkeypatch, tbl, 0, lambda d: d._allow_edit_chk.setChecked(False))
        assert rec_of(tbl, 0)["_original"] == orig


# ═════════════════════════ end to end: collect ══════════════════════════


class TestCollect:
    def test_flags_per_row(self, tmp_path, window, monkeypatch):
        rows = [
            row(**{**FULL, "name": "Untouched"}),
            row(**{**FULL, "name": "Edited"}),
            row(**{**FULL, "name": "Edited and back"}),
            row(**{**FULL, "name": "Opened and updated"}),
            row(**{**FULL, "name": "Unchecked"}),
            row(unit="kg", carbon_emission="0.2", carbon_emission_units_den="kg",
                name="CF default"),
        ]
        w = window(wb_rows(tmp_path, rows))
        tbl = w._sheet_tables[SHEET]._component_blocks[COMP]._tbl

        real_edit(monkeypatch, tbl, 1, lambda d: d.rate_in.setText("1"))
        real_edit(monkeypatch, tbl, 2, lambda d: d.rate_in.setText("1"))
        real_edit(monkeypatch, tbl, 2, lambda d: d.rate_in.setText("4500"))
        real_edit(monkeypatch, tbl, 3)

        def drive(d):
            edit_everything(d)
            d._allow_edit_chk.setChecked(False)
        real_edit(monkeypatch, tbl, 4, drive)
        real_edit(monkeypatch, tbl, 5)

        out = w._collect()["str_foundation"][COMP]
        got = {m["values"]["material_name"]: material_flag(m) for m in out}
        assert got == {
            "Untouched": "excel",
            "Edited": "excel_modified",
            "Edited and back": "excel",
            "Opened and updated": "excel",
            "Unchecked": "excel",
            "CF default": "excel",
        }
        for m in out:
            snap = m["meta"]["db_original"]
            assert snap["action"] == "excel"
            assert snap["name"] == m["values"]["material_name"]
        edited = next(m for m in out if m["values"]["material_name"] == "Edited")
        assert edited["values"]["rate"] == 1.0
        assert edited["meta"]["db_original"]["rate"] == "4500"

    def test_renamed_row_keeps_the_files_name_in_db_original(self, tmp_path, window,
                                                              monkeypatch):
        w = window(wb_rows(tmp_path, [row(**FULL)]))
        tbl = w._sheet_tables[SHEET]._component_blocks[COMP]._tbl
        real_edit(monkeypatch, tbl, 0, lambda d: d.name_in.setText("Renamed"))
        (m,) = w._collect()["str_foundation"][COMP]
        assert m["values"]["material_name"] == "Renamed"
        assert material_flag(m) == "excel_modified"
        assert m["meta"]["db_original"]["name"] == "Concrete M25"

    def test_collect_twice_gives_the_same_flags(self, tmp_path, window, monkeypatch):
        w = window(wb_rows(tmp_path, [row(**FULL), row(name="B")]))
        tbl = w._sheet_tables[SHEET]._component_blocks[COMP]._tbl
        fake_edit(monkeypatch, tbl, 0, {"rate": 1.0})
        a = [material_flag(m) for m in w._collect()["str_foundation"][COMP]]
        b = [material_flag(m) for m in w._collect()["str_foundation"][COMP]]
        assert a == b == ["excel_modified", "excel"]


# ═════════════════════════ re-import over an existing material ══════════


class _Engine:
    def __init__(self, data):
        self.data = data
        self.staged = []

    def fetch_chunk(self, chunk):
        return self.data.get(chunk, {})

    def stage_update(self, chunk_name, data):
        self.data[chunk_name] = data
        self.staged.append(chunk_name)


def _mgr(engine):
    class Ctl:
        pass
    Ctl.engine = engine

    class Mgr:
        controller = Ctl
        chunk_name = "str_foundation"
        on_refresh = staticmethod(lambda: None)
        save_current_state = staticmethod(lambda: None)

        def add_material(self, comp, values_dict):  # pragma: no cover - not reached
            raise AssertionError("should overwrite in place")
    return Mgr()


@pytest.mark.parametrize("edit,expected", [(False, "excel"), (True, "excel_modified")])
def test_overwrite_keeps_the_rows_own_source(edit, expected):
    existing = {"values": {"material_name": "Concrete M25"},
                "meta": {"source": "manual"}, "state": {"in_trash": False}}
    engine = _Engine({"str_foundation": {COMP: [existing]}})
    r = handmade(**FULL)
    if edit:
        r["rate"] = "1"
    m = mat(r)
    m["_force_overwrite"] = True
    m.pop("_chunk_key", None)
    m.pop("_component", None)
    imported, skipped, failures = ei._emit_result({"str_foundation": {COMP: [m]}},
                                                  manager=_mgr(engine))
    assert (imported, skipped, failures) == (1, 0, [])
    item = engine.data["str_foundation"][COMP][0]
    assert material_flag(item) == expected
    assert item["meta"]["db_original"]["rate"] == "4500"
    assert item["meta"]["db_original"]["action"] == "excel"
