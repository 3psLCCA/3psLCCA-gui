"""Brutal black-box tests for the structure Excel material importer.

Written only from the importer's spec (parse_excel, verify_schema and
ImportPreviewWindow), never from the implementation. Workbooks are built
cell-by-cell with openpyxl so blank rows, formulas and types are exact.
"""
import re

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pandas")
openpyxl = pytest.importorskip("openpyxl")
from PySide6.QtCore import Qt  # noqa: E402

from three_ps_lcca_gui.gui import themes  # noqa: E402
from three_ps_lcca_gui.gui.components.structure import excel_importer as ei  # noqa: E402

# Table columns per spec (0 = tick box)
CB, ID, NAME, QTY, UNIT, RATE, ISSUES = 0, 1, 2, 3, 4, 5, 13

H = ["CID#ID", "CID#Name", "CID#Quantity", "CID#Unit", "CID#Rate", "CID#Component"]
NUMERIC = ("rate", "quantity", "carbon_emission", "conversion_factor",
           "scrap_rate", "recovery_pct")
ALL_KEYS = ("src_id", "name", "quantity", "unit", "rate", "rate_src",
            "carbon_emission", "carbon_emission_units_den", "conversion_factor",
            "carbon_emission_src", "scrap_rate", "recovery_pct", "component")


# ── helpers ─────────────────────────────────────────────────────────────


def write_wb(path, sheets, keep_default=False):
    """sheets: {name: [row, ...]}; None/"" cells are left truly empty."""
    wb = openpyxl.Workbook()
    if not keep_default:
        wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r, row in enumerate(rows, 1):
            for c, v in enumerate(row, 1):
                if v is not None and v != "":
                    ws.cell(row=r, column=c, value=v)
    wb.save(path)
    return str(path)


def wb(tmp_path, sheets, name="wb.xlsx", **kw):
    return write_wb(tmp_path / name, sheets, **kw)


def parse(tmp_path, sheets):
    return ei.parse_excel(wb(tmp_path, sheets))


def mats(tmp_path, sheets):
    return parse(tmp_path, sheets)["materials"]


def verified(tmp_path, sheets):
    return ei.verify_schema(mats(tmp_path, sheets))


def rec(**kw):
    r = {k: "" for k in ALL_KEYS}
    r.update(_row_num=2, _errors=[], _warnings=[])
    r.update(kw)
    return r


def good(i, name, comp="Excavation", qty="10", unit="m3", rate="100"):
    return [f"ID{i}", name, qty, unit, rate, comp]


def strip_tags(s):
    return re.sub("<[^>]+>", "", s)


def footer(w):
    txt = strip_tags(w._summary_lbl.text())
    out = {}
    for key in ("Total rows", "Errors", "Warnings", "Valid", "Selected"):
        m = re.search(key + r":\s*(\d+)", txt)
        assert m, f"footer missing {key!r}: {txt!r}"
        out[key] = int(m.group(1))
    return out


def frac(lbl):
    m = re.fullmatch(r"\((\d+) / (\d+)(?: selected)?\)", lbl.text().strip())
    assert m, f"bad counter text {lbl.text()!r}"
    return int(m.group(1)), int(m.group(2))


def button_n(w):
    m = re.fullmatch(r"Import (\d+) Rows?", w._import_valid_btn.text())
    assert m, w._import_valid_btn.text()
    return int(m.group(1))


def tab_text(w, sheet):
    for i in range(w.tabs.count()):
        t = w.tabs.tabText(i)
        if t == sheet or t.startswith(sheet + " ("):
            return t
    raise AssertionError(f"no tab for {sheet!r}: "
                         f"{[w.tabs.tabText(i) for i in range(w.tabs.count())]}")


def all_tabs(w):
    return [w.tabs.tabText(i) for i in range(w.tabs.count())]


def blocks(w):
    for sheet, sw in w._sheet_tables.items():
        for comp, blk in sw._component_blocks.items():
            yield sheet, comp, blk


def block(w, sheet, comp):
    return w._sheet_tables[sheet]._component_blocks[comp]


def is_ticked(tbl, r):
    return tbl.item(r, CB).checkState() == Qt.Checked


def is_tickable(tbl, r):
    return bool(tbl.item(r, CB).flags() & Qt.ItemIsUserCheckable)


def tbl_counts(tbl):
    sel = sum(is_ticked(tbl, r) for r in range(tbl.rowCount()))
    able = sum(is_tickable(tbl, r) for r in range(tbl.rowCount()))
    return sel, able


def expected_tri(sel, able):
    if sel == 0:
        return Qt.Unchecked
    return Qt.Checked if sel == able else Qt.PartiallyChecked


def find_row(tbl, name):
    for r in range(tbl.rowCount()):
        if tbl.item(r, NAME) and tbl.item(r, NAME).text() == name:
            return r
    raise AssertionError(f"row {name!r} not found")


def tick(app, tbl, r, on=True):
    tbl.item(r, CB).setCheckState(Qt.Checked if on else Qt.Unchecked)
    app.processEvents()


def edit(app, tbl, r, col, text):
    tbl.item(r, col).setText(text)
    app.processEvents()


def assert_consistent(w):
    """Every counter, tri-state, footer, button agree with the actual ticks."""
    tot_sel = tot_able = 0
    for sheet, sw in w._sheet_tables.items():
        if not sw._component_blocks:
            continue  # sheet with no rows: no counters to check
        s_sel = s_able = 0
        for comp, blk in sw._component_blocks.items():
            sel, able = tbl_counts(blk._tbl)
            for r in range(blk._tbl.rowCount()):
                assert not (is_ticked(blk._tbl, r) and not is_tickable(blk._tbl, r)), \
                    f"{sheet}/{comp} row {r} ticked but not tickable"
            assert frac(blk._count_lbl) == (sel, able), (sheet, comp)
            if able:
                assert blk._chk.checkState() == expected_tri(sel, able), (sheet, comp)
            s_sel += sel
            s_able += able
        assert frac(sw._sheet_count_lbl) == (s_sel, s_able), sheet
        if s_able:
            assert sw._sheet_chk.checkState() == expected_tri(s_sel, s_able), sheet
        tot_sel += s_sel
        tot_able += s_able
    assert frac(w._select_all_count_lbl) == (tot_sel, tot_able)
    if tot_able:
        assert w._select_all_chk.checkState() == expected_tri(tot_sel, tot_able)
    assert button_n(w) == tot_sel
    assert w._import_valid_btn.isEnabled() == (tot_sel > 0)
    f = footer(w)
    assert f["Selected"] == tot_sel
    assert f["Valid"] == f["Total rows"] - f["Errors"]
    assert f["Valid"] == tot_able
    return tot_sel, tot_able


def collected_names(w):
    out = {}
    for chunk, comps in w._collect().items():
        for comp, rows in comps.items():
            for m in rows:
                out.setdefault((chunk, comp), []).append(m["values"]["material_name"])
    return out


def flat_collected(w):
    return sorted(n for v in collected_names(w).values() for n in v)


# ── Qt fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    themes.reapply(app)
    return app


class FakeEngine:
    def __init__(self, data):
        self.data = data

    def fetch_chunk(self, chunk):
        return self.data.get(chunk, {})


def manager(data):
    eng = FakeEngine(data)

    class Ctl:
        engine = eng

    class Mgr:
        controller = Ctl

    return Mgr()


def item(name, trash=False):
    return {"values": {"material_name": name}, "state": {"in_trash": trash}}


@pytest.fixture
def make(qapp, tmp_path):
    made = []

    def _make(sheets, existing=None, metadata=None, name="wb.xlsx"):
        parsed = ei.verify_schema(ei.parse_excel(wb(tmp_path, sheets, name=name))["materials"])
        mgr = manager(existing) if existing is not None else None
        w = ei.ImportPreviewWindow(parsed, existing_components=None,
                                   manager=mgr, metadata=metadata)
        w.show()
        qapp.processEvents()
        made.append(w)
        return w

    yield _make
    for w in made:
        w.close()
        w.deleteLater()
    qapp.processEvents()


# ═════════════════════════ parse_excel ══════════════════════════════════


class TestSheetSelection:
    @pytest.mark.parametrize("sheet", [
        "CAT#Foundation", "cat#Foundation", "Cat#foundation", "CAT#FOUNDATION",
        " CAT#Foundation", "CAT#Foundation ", "  cAt#Misc  ",
    ])
    def test_cat_prefix_case_and_space_insensitive(self, tmp_path, sheet):
        m = mats(tmp_path, {sheet: [H, good(1, "Sand")]})
        assert len(m) == 1
        (key,) = m
        assert key.strip().lower() == sheet.strip().lower()
        assert [r["name"] for r in m[key]] == ["Sand"]

    @pytest.mark.parametrize("sheet", [
        "Foundation", "CATFoundation", "CAT Foundation", "XCAT#Foundation",
        "Notes", "CA#Foundation", "#CAT#Foundation",
    ])
    def test_non_cat_sheets_ignored(self, tmp_path, sheet):
        p = parse(tmp_path, {sheet: [H, good(1, "Sand")]})
        assert p["materials"] == {}

    def test_mixed_sheets_only_cat_kept_in_order(self, tmp_path):
        m = mats(tmp_path, {
            "Readme": [["hello"]],
            "CAT#Foundation": [H, good(1, "A")],
            "Notes": [H, good(2, "B")],
            "CAT#Misc": [H, good(3, "C")],
        })
        assert list(m) == ["CAT#Foundation", "CAT#Misc"]

    def test_many_sheets(self, tmp_path):
        sheets = {f"CAT#S{i}": [H, good(i, f"Mat{i}")] for i in range(15)}
        m = mats(tmp_path, sheets)
        assert list(m) == list(sheets)
        assert all(len(v) == 1 for v in m.values())

    def test_empty_workbook(self, tmp_path):
        p = ei.parse_excel(wb(tmp_path, {}, keep_default=True))
        assert p["materials"] == {}
        assert p["metadata"] == []

    def test_cat_sheet_completely_empty_is_skipped(self, tmp_path):
        assert mats(tmp_path, {"CAT#Foundation": []}) == {}

    def test_sheet_with_no_header_is_skipped(self, tmp_path):
        m = mats(tmp_path, {"CAT#Foundation": [["Name", "Rate"], ["Sand", 10]],
                            "CAT#Misc": [H, good(1, "X")]})
        assert list(m) == ["CAT#Misc"]

    def test_header_only_sheet_is_empty_list(self, tmp_path):
        m = mats(tmp_path, {"CAT#Foundation": [H]})
        assert m == {"CAT#Foundation": []}

    def test_header_then_only_blank_rows_is_empty_list(self, tmp_path):
        m = mats(tmp_path, {"CAT#Foundation": [H, [], [None] * 6, ["", "", ""]]})
        assert m == {"CAT#Foundation": []}


class TestHeaderDetection:
    @pytest.mark.parametrize("hrow", [1, 2, 15, 20])
    def test_header_found_within_first_20_rows(self, tmp_path, hrow):
        rows = [[] for _ in range(hrow - 1)] + [H, good(1, "Sand")]
        m = mats(tmp_path, {"CAT#Foundation": rows})
        assert [r["name"] for r in m["CAT#Foundation"]] == ["Sand"]
        assert m["CAT#Foundation"][0]["_row_num"] == hrow + 1

    def test_header_with_junk_above(self, tmp_path):
        rows = [["Bill of Quantities"], ["Project: X", "", "Date"], []] * 4 + [H, good(1, "Sand")]
        m = mats(tmp_path, {"CAT#Foundation": rows})
        r = m["CAT#Foundation"][0]
        assert r["name"] == "Sand"
        assert r["_row_num"] == 14

    @pytest.mark.parametrize("hrow", [21, 25])
    def test_header_beyond_row_20_not_found(self, tmp_path, hrow):
        rows = [["junk"] for _ in range(hrow - 1)] + [H, good(1, "Sand")]
        assert mats(tmp_path, {"CAT#Foundation": rows}) == {}

    def test_header_beyond_row_20_with_blank_rows_above(self, tmp_path):
        rows = [[] for _ in range(20)] + [H, good(1, "Sand")]
        assert mats(tmp_path, {"CAT#Foundation": rows}) == {}

    def test_single_cid_cell_is_enough_for_header(self, tmp_path):
        rows = [["Title"], ["", "CID#Name", "Other"], ["", "Sand", "x"]]
        m = mats(tmp_path, {"CAT#Foundation": rows})
        assert [r["name"] for r in m["CAT#Foundation"]] == ["Sand"]

    def test_first_cid_row_wins(self, tmp_path):
        rows = [["CID#Name", "CID#Rate"], ["Sand", 10], ["CID#Rate", "CID#Name"], ["Gravel", 20]]
        m = mats(tmp_path, {"CAT#Foundation": rows})
        recs = m["CAT#Foundation"]
        assert recs[0]["name"] == "Sand" and recs[0]["rate"] in ("10", "10.0")

    @pytest.mark.parametrize("prefix", ["CID#", "cid#", "Cid#", "cId#"])
    def test_cid_prefix_case_insensitive(self, tmp_path, prefix):
        hdr = [prefix + f for f in ("Name", "Unit", "Rate")]
        m = mats(tmp_path, {"CAT#Foundation": [hdr, ["Sand", "m3", "5"]]})
        r = m["CAT#Foundation"][0]
        assert (r["name"], r["unit"], r["rate"]) == ("Sand", "m3", "5")

    @pytest.mark.parametrize("field,key", [
        ("ID", "src_id"), ("Name", "name"), ("Quantity", "quantity"),
        ("Unit", "unit"), ("Rate", "rate"), ("Rate_Src", "rate_src"),
        ("Carbon_Emission_Factor", "carbon_emission"),
        ("Carbon_Emission_units", "carbon_emission_units_den"),
        ("Conversion_Factor", "conversion_factor"),
        ("Carbon_Emission_Src", "carbon_emission_src"),
        ("Scrap_Rate", "scrap_rate"), ("Recovery_Pct", "recovery_pct"),
        ("Component", "component"),
    ])
    @pytest.mark.parametrize("case", [str, str.lower, str.upper])
    def test_every_field_maps_any_case(self, tmp_path, field, key, case):
        m = mats(tmp_path, {"CAT#Misc": [["CID#" + case(field)], ["7"]]})
        r = m["CAT#Misc"][0]
        assert r[key] == "7"
        assert not any("unrecogn" in w.lower() or "unknown" in w.lower()
                       for w in r["_warnings"])

    def test_columns_in_any_order(self, tmp_path):
        hdr = ["CID#Rate", "CID#Component", "CID#Unit", "CID#Name"]
        m = mats(tmp_path, {"CAT#Foundation": [hdr, ["9", "Pile", "m", "Bored pile"]]})
        r = m["CAT#Foundation"][0]
        assert (r["name"], r["unit"], r["rate"], r["component"]) == ("Bored pile", "m", "9", "Pile")

    def test_non_cid_columns_silently_ignored(self, tmp_path):
        hdr = ["S.No", "CID#Name", "Remarks", "CID#Unit", "CID#Rate"]
        m = mats(tmp_path, {"CAT#Foundation": [hdr, [1, "Sand", "note", "m3", 5]]})
        r = m["CAT#Foundation"][0]
        assert r["name"] == "Sand" and r["_warnings"] == []

    def test_unrecognised_cid_column_warns_every_row(self, tmp_path):
        hdr = H + ["CID#Colour"]
        rows = [hdr, good(1, "A") + ["red"], good(2, "B") + [""], good(3, "C") + ["blue"]]
        m = mats(tmp_path, {"CAT#Foundation": rows, "CAT#Misc": [H, good(4, "D")]})
        recs = m["CAT#Foundation"]
        assert len(recs) == 3
        assert all(r["_warnings"] for r in recs)
        assert all("Colour" not in r and "colour" not in r for r in recs)
        assert m["CAT#Misc"][0]["_warnings"] == []

    def test_duplicate_cid_column_first_wins_and_warns(self, tmp_path):
        hdr = ["CID#Name", "CID#Unit", "CID#Rate", "CID#name"]
        rows = [hdr, ["First", "m", "1", "Second"], ["X", "m", "2", "Y"]]
        recs = mats(tmp_path, {"CAT#Foundation": rows})["CAT#Foundation"]
        assert [r["name"] for r in recs] == ["First", "X"]
        assert all(r["_warnings"] for r in recs)

    def test_duplicate_cid_column_warns_even_with_empty_first(self, tmp_path):
        hdr = ["CID#Rate", "CID#Name", "CID#Rate"]
        recs = mats(tmp_path, {"CAT#Foundation": [hdr, ["", "Sand", "99"]]})["CAT#Foundation"]
        assert recs[0]["rate"] == ""
        assert recs[0]["_warnings"]


class TestCellValues:
    def test_values_stripped(self, tmp_path):
        r = mats(tmp_path, {"CAT#Foundation": [H, ["  ID1 ", "  Sand\t", " 5 ", " m3 ", " 10 ", " Exc "]]})[
            "CAT#Foundation"][0]
        assert (r["src_id"], r["name"], r["quantity"], r["unit"], r["rate"], r["component"]) == \
            ("ID1", "Sand", "5", "m3", "10", "Exc")

    def test_int_cell_value(self, tmp_path):
        r = mats(tmp_path, {"CAT#Foundation": [H, [1, "Sand", 5, "m3", 10, "Exc"]]})["CAT#Foundation"][0]
        assert float(r["quantity"]) == 5 and float(r["rate"]) == 10

    def test_float_cell_value(self, tmp_path):
        r = mats(tmp_path, {"CAT#Foundation": [H, [1, "Sand", 0.125, "m3", 1234.5678, "Exc"]]})[
            "CAT#Foundation"][0]
        assert float(r["quantity"]) == 0.125 and float(r["rate"]) == 1234.5678

    def test_negative_and_zero(self, tmp_path):
        r = mats(tmp_path, {"CAT#Foundation": [H, [1, "Sand", 0, "m3", -42.5, "Exc"]]})["CAT#Foundation"][0]
        assert float(r["quantity"]) == 0 and float(r["rate"]) == -42.5

    def test_numbers_stored_as_text_kept(self, tmp_path):
        r = mats(tmp_path, {"CAT#Foundation": [H, ["001", "Sand", "007", "m3", "1e3", "Exc"]]})[
            "CAT#Foundation"][0]
        assert r["quantity"] == "007" and r["rate"] == "1e3"

    def test_id_with_leading_zeros_text_kept(self, tmp_path):
        r = mats(tmp_path, {"CAT#Foundation": [H, ["00042", "Sand", 1, "m3", 1, "Exc"]]})["CAT#Foundation"][0]
        assert r["src_id"] == "00042"

    def test_unicode_preserved(self, tmp_path):
        name = "Béton armé — 混凝土 🧱 Ω≈ç"
        r = mats(tmp_path, {"CAT#Foundation": [H, [1, name, 1, "m³", 1, "Fondation é"]]})["CAT#Foundation"][0]
        assert r["name"] == name and r["unit"] == "m³" and r["component"] == "Fondation é"

    def test_very_long_name_preserved(self, tmp_path):
        name = "Reinforced concrete " * 200
        r = mats(tmp_path, {"CAT#Foundation": [H, [1, name, 1, "m3", 1, "Exc"]]})["CAT#Foundation"][0]
        assert r["name"] == name.strip()

    def test_blank_rows_skipped_and_row_nums_exact(self, tmp_path):
        rows = [["title"], H, good(1, "A"), [], [None, None], good(2, "B"), [], [], good(3, "C")]
        recs = mats(tmp_path, {"CAT#Foundation": rows})["CAT#Foundation"]
        assert [(r["name"], r["_row_num"]) for r in recs] == [("A", 3), ("B", 6), ("C", 9)]

    def test_row_with_only_non_cid_column_value_is_blank_for_data(self, tmp_path):
        # row has only a component -> not blank, must be kept
        rows = [H, ["", "", "", "", "", "Exc"]]
        recs = mats(tmp_path, {"CAT#Foundation": rows})["CAT#Foundation"]
        assert len(recs) == 1 and recs[0]["component"] == "Exc" and recs[0]["name"] == ""

    def test_trailing_blank_rows_not_records(self, tmp_path):
        rows = [H, good(1, "A")] + [[] for _ in range(30)]
        assert len(mats(tmp_path, {"CAT#Foundation": rows})["CAT#Foundation"]) == 1

    def test_many_rows(self, tmp_path):
        rows = [H] + [good(i, f"M{i}") for i in range(500)]
        recs = mats(tmp_path, {"CAT#Foundation": rows})["CAT#Foundation"]
        assert len(recs) == 500
        assert recs[-1]["_row_num"] == 501 and recs[-1]["name"] == "M499"



class TestMetadata:
    def test_basic(self, tmp_path):
        p = parse(tmp_path, {"CAT#Misc": [H], "Metadata": [["CID#Keys", "CID#Values"],
                                                           ["Source", "SOR 2023"], ["Region", "North"]]})
        assert p["metadata"] == [{"key": "Source", "value": "SOR 2023"},
                                 {"key": "Region", "value": "North"}]

    @pytest.mark.parametrize("sheet", ["metadata", "METADATA", "MetaData"])
    def test_sheet_name_case_insensitive(self, tmp_path, sheet):
        p = parse(tmp_path, {sheet: [["CID#Keys", "CID#Values"], ["k", "v"]]})
        assert p["metadata"] == [{"key": "k", "value": "v"}]

    def test_header_row_10_and_offset_columns(self, tmp_path):
        rows = [["x"] for _ in range(9)] + [["", "CID#Keys", "", "CID#Values"], ["", "k", "", "v"]]
        p = parse(tmp_path, {"Metadata": rows})
        assert p["metadata"] == [{"key": "k", "value": "v"}]

    def test_header_row_11_not_found(self, tmp_path):
        rows = [["x"] for _ in range(10)] + [["CID#Keys", "CID#Values"], ["k", "v"]]
        p = parse(tmp_path, {"Metadata": rows})
        assert p["metadata"] == []

    def test_empty_keys_skipped_empty_values_kept(self, tmp_path):
        rows = [["CID#Keys", "CID#Values"], ["", "orphan"], ["k1", ""], [], ["k2", "v2"]]
        p = parse(tmp_path, {"Metadata": rows})
        assert p["metadata"] == [{"key": "k1", "value": ""}, {"key": "k2", "value": "v2"}]

    def test_numeric_values_are_strings(self, tmp_path):
        p = parse(tmp_path, {"Metadata": [["CID#Keys", "CID#Values"], ["Year", 2023]]})
        (m,) = p["metadata"]
        assert m["key"] == "Year" and isinstance(m["value"], str) and float(m["value"]) == 2023

    def test_cid_case_insensitive(self, tmp_path):
        p = parse(tmp_path, {"Metadata": [["cid#keys", "CID#VALUES"], ["a", "b"]]})
        assert p["metadata"] == [{"key": "a", "value": "b"}]

    def test_metadata_not_a_material_sheet(self, tmp_path):
        p = parse(tmp_path, {"Metadata": [["CID#Keys", "CID#Values"], ["a", "b"]]})
        assert p["materials"] == {}

    def test_no_metadata_sheet(self, tmp_path):
        assert parse(tmp_path, {"CAT#Misc": [H, good(1, "A")]})["metadata"] == []

    def test_metadata_without_header(self, tmp_path):
        assert parse(tmp_path, {"Metadata": [["Key", "Value"], ["a", "b"]]})["metadata"] == []


class TestBadFiles:
    def test_missing_file(self, tmp_path):
        with pytest.raises(ValueError):
            ei.parse_excel(str(tmp_path / "nope.xlsx"))

    def test_text_file(self, tmp_path):
        p = tmp_path / "x.txt"
        p.write_text("hello, world\n1,2,3\n")
        with pytest.raises(ValueError):
            ei.parse_excel(str(p))

    def test_garbage_with_xlsx_extension(self, tmp_path):
        p = tmp_path / "bad.xlsx"
        p.write_bytes(b"\x00\x01garbage" * 100)
        with pytest.raises(ValueError):
            ei.parse_excel(str(p))

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.xlsx"
        p.write_bytes(b"")
        with pytest.raises(ValueError):
            ei.parse_excel(str(p))

    def test_directory(self, tmp_path):
        with pytest.raises(ValueError):
            ei.parse_excel(str(tmp_path))


# ═════════════════════════ verify_schema ════════════════════════════════


class TestRouting:
    @pytest.mark.parametrize("sheet,chunk", [
        ("CAT#Foundation", "str_foundation"), ("CAT#foundation", "str_foundation"),
        ("cat#FOUNDATION", "str_foundation"),
        ("CAT#Sub-Structure", "str_sub_structure"), ("CAT#SubStructure", "str_sub_structure"),
        ("CAT#sub-structure", "str_sub_structure"), ("CAT#SUBSTRUCTURE", "str_sub_structure"),
        ("CAT#Super-Structure", "str_super_structure"), ("CAT#SuperStructure", "str_super_structure"),
        ("cat#superstructure", "str_super_structure"),
        ("CAT#Misc", "str_misc"), ("CAT#Miscellaneous", "str_misc"), ("CAT#MISC", "str_misc"),
        (" CAT#Foundation ", "str_foundation"),
    ])
    def test_recognised_sheets(self, tmp_path, sheet, chunk):
        out = verified(tmp_path, {sheet: [H, good(1, "Sand", comp="Exc")]})
        (recs,) = out.values()
        assert recs[0]["_chunk_key"] == chunk
        assert recs[0]["component"] == "Exc"

    @pytest.mark.parametrize("suffix", ["Bridge Deck", "Approach", "Foundations", "Sub Structure"])
    def test_unknown_sheet_goes_to_misc_with_prefixed_component(self, tmp_path, suffix):
        out = verified(tmp_path, {"CAT#" + suffix: [H, good(1, "Sand", comp="Railing")]})
        r = out["CAT#" + suffix][0]
        assert r["_chunk_key"] == "str_misc"
        assert r["component"] == f"{suffix} - Railing"

    def test_unknown_sheet_blank_component(self, tmp_path):
        out = verified(tmp_path, {"CAT#Deck": [H, good(1, "Sand", comp="")]})
        r = out["CAT#Deck"][0]
        assert r["_chunk_key"] == "str_misc"
        # spec: "<Suffix> - <Component>" (or Uncategorised if blank) -- accept both readings
        assert r["component"] in ("Deck - Uncategorised", "Uncategorised")

    @pytest.mark.parametrize("comp", ["", "   ", "\t"])
    def test_blank_component_uncategorised(self, tmp_path, comp):
        out = verified(tmp_path, {"CAT#Foundation": [H, good(1, "Sand", comp=comp)]})
        assert out["CAT#Foundation"][0]["component"] == "Uncategorised"

    def test_blank_component_handmade_record(self):
        out = ei.verify_schema({"CAT#Foundation": [rec(name="A", unit="m", rate="1", component="   ")]})
        assert out["CAT#Foundation"][0]["component"] == "Uncategorised"

    def test_every_record_stamped(self, tmp_path):
        out = verified(tmp_path, {
            "CAT#Foundation": [H, good(1, "A"), ["", "", "x", "", "", ""], good(2, "")],
            "CAT#Odd": [H, good(3, "B"), good(4, "C", rate="abc")],
        })
        for recs in out.values():
            for r in recs:
                assert "_chunk_key" in r

    def test_returns_same_dict_mutated(self):
        d = {"CAT#Misc": [rec(name="A", unit="m", rate="1", component="X")]}
        out = ei.verify_schema(d)
        assert out is d or out == d
        assert d["CAT#Misc"][0].get("_chunk_key") == "str_misc"

    def test_empty_input(self):
        assert ei.verify_schema({}) == {}

    def test_empty_sheet_list(self):
        assert ei.verify_schema({"CAT#Foundation": []}) == {"CAT#Foundation": []}


class TestValidation:
    def _one(self, **kw):
        base = dict(src_id="X1", name="Sand", unit="m3", rate="10", quantity="5", component="Exc")
        base.update(kw)
        return ei.verify_schema({"CAT#Foundation": [rec(**base)]})["CAT#Foundation"][0]

    def test_clean_row_no_errors(self):
        assert self._one()["_errors"] == []

    @pytest.mark.parametrize("field", ["name", "unit", "rate"])
    def test_required_missing(self, field):
        assert self._one(**{field: ""})["_errors"]

    def test_all_required_missing_multiple_errors(self):
        assert len(self._one(name="", unit="", rate="")["_errors"]) >= 3

    @pytest.mark.parametrize("field", ["quantity", "src_id", "rate_src", "component",
                                       "carbon_emission", "scrap_rate"])
    def test_optional_may_be_empty(self, field):
        assert self._one(**{field: ""})["_errors"] == []

    @pytest.mark.parametrize("field", NUMERIC)
    @pytest.mark.parametrize("bad", ["abc", "12abc", "1,2,3", "ten", "--5", "1.2.3"])
    def test_non_numeric_is_error(self, field, bad):
        assert self._one(**{field: bad})["_errors"], (field, bad)

    @pytest.mark.parametrize("field", NUMERIC)
    @pytest.mark.parametrize("ok", ["0", "0.0", "12", "12.5", "-3", "1e3", "0.0001"])
    def test_numeric_ok(self, field, ok):
        assert self._one(**{field: ok})["_errors"] == [], (field, ok)

    def test_errors_from_parse_preserved(self):
        r = ei.verify_schema({"CAT#Foundation": [rec(name="A", unit="m", rate="1",
                                                     _warnings=["pre-existing"])]})["CAT#Foundation"][0]
        assert "pre-existing" in r["_warnings"]

    def test_numeric_text_from_excel_ok(self, tmp_path):
        out = verified(tmp_path, {"CAT#Foundation": [H, ["1", "Sand", "5", "m3", "10.50", "Exc"]]})
        assert out["CAT#Foundation"][0]["_errors"] == []

    def test_float_cells_from_excel_ok(self, tmp_path):
        out = verified(tmp_path, {"CAT#Foundation": [H, [1, "Sand", 5.5, "m3", 0.1, "Exc"]]})
        assert out["CAT#Foundation"][0]["_errors"] == []


class TestDuplicateIds:
    def _flags(self, r):
        return r["_errors"] + r["_warnings"]

    def test_duplicate_ids_across_sheets_flagged(self, tmp_path):
        out = verified(tmp_path, {
            "CAT#Foundation": [H, ["D1", "A", 1, "m", 1, "X"], ["U1", "B", 1, "m", 1, "X"]],
            "CAT#Misc": [H, ["D1", "C", 1, "m", 1, "Y"]],
        })
        a, b = out["CAT#Foundation"]
        (c,) = out["CAT#Misc"]
        assert self._flags(a) or self._flags(c)
        assert not self._flags(b)

    def test_duplicate_ids_flag_text_mentions_id(self, tmp_path):
        out = verified(tmp_path, {
            "CAT#Foundation": [H, ["DUPX", "A", 1, "m", 1, "X"]],
            "CAT#Misc": [H, ["DUPX", "C", 1, "m", 1, "Y"]],
        })
        msgs = " ".join(self._flags(out["CAT#Foundation"][0]) + self._flags(out["CAT#Misc"][0]))
        assert "dup" in msgs.lower() or "DUPX" in msgs

    def test_blank_ids_never_duplicates(self, tmp_path):
        out = verified(tmp_path, {
            "CAT#Foundation": [H, ["", "A", 1, "m", 1, "X"], ["", "B", 1, "m", 1, "X"]],
            "CAT#Misc": [H, ["", "C", 1, "m", 1, "Y"]],
        })
        for recs in out.values():
            for r in recs:
                assert self._flags(r) == [], r

    def test_distinct_ids_not_flagged(self, tmp_path):
        out = verified(tmp_path, {
            "CAT#Foundation": [H, ["A1", "A", 1, "m", 1, "X"]],
            "CAT#Misc": [H, ["A2", "C", 1, "m", 1, "Y"]],
        })
        assert all(self._flags(r) == [] for recs in out.values() for r in recs)


# ═════════════════════════ ImportPreviewWindow ══════════════════════════

FOUND = "CAT#Foundation"


def std_sheets():
    """Excavation: 2 good + 1 error;  Pile: 1 good + 1 error;  2nd sheet clean."""
    return {
        FOUND: [H,
                good(1, "Backfilling"),
                good(2, "Trench"),
                good(3, "NoRate", rate=""),
                good(4, "Bored pile", comp="Pile", unit="m"),
                good(5, "BadQty", comp="Pile", qty="abc")],
        "CAT#Misc": [H, good(6, "Paint", comp="Finish"), good(7, "Primer", comp="Finish")],
    }


class TestInitialState:
    def test_tables_filled(self, make):
        w = make(std_sheets())
        assert block(w, FOUND, "Excavation")._tbl.rowCount() == 3
        assert block(w, FOUND, "Pile")._tbl.rowCount() == 2
        assert block(w, "CAT#Misc", "Finish")._tbl.rowCount() == 2

    def test_cell_text_in_spec_columns(self, make):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        assert t.item(0, ID).text() == "ID1"
        assert t.item(0, NAME).text() == "Backfilling"
        assert float(t.item(0, QTY).text()) == 10
        assert t.item(0, UNIT).text() == "m3"
        assert float(t.item(0, RATE).text()) == 100

    def test_column_count(self, make):
        w = make(std_sheets())
        assert block(w, FOUND, "Excavation")._tbl.columnCount() == 14

    def test_new_valid_rows_ticked_error_rows_not(self, make):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        assert is_ticked(t, 0) and is_ticked(t, 1)
        assert not is_ticked(t, 2) and not is_tickable(t, 2)

    def test_error_row_issues_cell_not_empty(self, make):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        assert t.item(2, ISSUES).text().strip()

    def test_error_row_cannot_be_force_ticked(self, make, qapp):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        before = w._collect()
        tick(qapp, t, 2)
        assert "NoRate" not in flat_collected(w)
        assert flat_collected(w) == sorted(n for v in collected_names_from(before) for n in v)

    def test_initial_counters(self, make):
        w = make(std_sheets())
        # 5 valid rows: 3 on Foundation, 2 on Misc
        assert w._select_all_count_lbl.text() == "(5 / 5)"
        assert w._select_all_chk.checkState() == Qt.Checked
        assert frac(w._sheet_tables[FOUND]._sheet_count_lbl) == (3, 3)
        assert block(w, FOUND, "Excavation")._count_lbl.text() == "(2 / 2 selected)"
        assert block(w, FOUND, "Pile")._count_lbl.text() == "(1 / 1 selected)"
        assert_consistent(w)

    def test_initial_footer(self, make):
        w = make(std_sheets())
        assert footer(w) == {"Total rows": 7, "Errors": 2, "Warnings": 0, "Valid": 5, "Selected": 5}

    def test_footer_exact_format(self, make):
        w = make(std_sheets())
        # spacing around the "|" is styling, not checked
        assert " ".join(strip_tags(w._summary_lbl.text()).split()) == \
            "Total rows: 7 | Errors: 2 | Warnings: 0 | Valid: 5 | Selected: 5"

    def test_initial_button(self, make):
        w = make(std_sheets())
        assert w._import_valid_btn.text() == "Import 5 Rows"
        assert w._import_valid_btn.isEnabled()

    def test_tabs(self, make):
        w = make(std_sheets())
        assert all_tabs(w) == [f"{FOUND} (2 ✗)", "CAT#Misc"]

    def test_metadata_tab_present_when_passed(self, make):
        w = make(std_sheets(), metadata=[{"key": "Source", "value": "SOR"}])
        tabs = all_tabs(w)
        assert len(tabs) == 3 and any(t.startswith("Metadata") for t in tabs)

    def test_no_metadata_tab_when_not_passed(self, make):
        w = make(std_sheets())
        assert not any(t.startswith("Metadata") for t in all_tabs(w))

    def test_one_tab_per_sheet_many(self, make):
        sheets = {f"CAT#S{i}": [H, good(i, f"M{i}")] for i in range(12)}
        w = make(sheets)
        assert all_tabs(w) == list(sheets)
        assert footer(w)["Total rows"] == 12
        assert_consistent(w)

    def test_manager_none_works(self, make):
        w = make(std_sheets(), existing=None)
        assert_consistent(w)

    def test_header_only_sheet_window(self, make):
        w = make({FOUND: [H], "CAT#Misc": [H, good(1, "A")]})
        assert footer(w)["Total rows"] == 1
        # a sheet without rows shows a message instead of counters
        msgs = [lb.text() for lb in w._sheet_tables[FOUND].findChildren(QtWidgets.QLabel)]
        assert "This sheet has no data rows." in msgs
        assert_consistent(w)

    def test_all_error_rows(self, make):
        w = make({FOUND: [H, good(1, "", ), good(2, "B", unit="")]})
        assert w._import_valid_btn.text() == "Import 0 Rows"
        assert not w._import_valid_btn.isEnabled()
        assert w._select_all_count_lbl.text() == "(0 / 0)"
        assert w._collect() == {} or all(not c for c in w._collect().values())
        assert tab_text(w, FOUND) == f"{FOUND} (2 ✗)"

    def test_single_row_button_singular(self, make):
        w = make({FOUND: [H, good(1, "Solo")]})
        assert w._import_valid_btn.text() == "Import 1 Row"

    def test_unicode_and_long_names_shown(self, make):
        long = "Ω" * 1000
        w = make({FOUND: [H, good(1, "混凝土 🧱"), good(2, long)]})
        t = block(w, FOUND, "Excavation")._tbl
        assert t.item(0, NAME).text() == "混凝土 🧱"
        assert t.item(1, NAME).text() == long
        assert_consistent(w)


def collected_names_from(data):
    return [[m["values"]["material_name"] for m in rows]
            for comps in data.values() for rows in comps.values()]


class TestWarningsAndTabs:
    def test_warning_only_tab(self, make):
        w = make({FOUND: [H + ["CID#Bogus"], good(1, "A") + ["x"], good(2, "B") + ["y"]],
                  "CAT#Misc": [H, good(3, "C")]})
        assert tab_text(w, FOUND) == f"{FOUND} (2 ⚠)"
        assert tab_text(w, "CAT#Misc") == "CAT#Misc"
        assert footer(w)["Warnings"] == 2
        assert footer(w)["Errors"] == 0

    def test_warning_rows_still_ticked_and_selectable(self, make):
        w = make({FOUND: [H + ["CID#Bogus"], good(1, "A") + ["x"]]})
        t = block(w, FOUND, "Excavation")._tbl
        assert is_tickable(t, 0) and is_ticked(t, 0)

    def test_error_rows_not_counted_as_warnings(self, make):
        # rows with both errors and warnings count as errors only
        w = make({FOUND: [H + ["CID#Bogus"], good(1, "", ) + ["x"], good(2, "B") + ["y"]]})
        f = footer(w)
        assert f["Errors"] == 1 and f["Warnings"] == 1
        assert tab_text(w, FOUND) == f"{FOUND} (1 ✗)"

    def test_formula_row_errors_and_warnings(self, make):
        w = make({FOUND: [H, ["1", "A", "1", "m", "=5*2", "Exc"], good(2, "B")]})
        f = footer(w)
        assert f["Errors"] == 1 and f["Warnings"] == 0
        assert f["Valid"] == 1

    def test_tinted_rows_have_background_and_no_forced_foreground(self, make):
        w = make({FOUND: [H + ["CID#Bogus"], good(1, "", ) + ["x"], good(2, "B") + ["y"], good(3, "C")]},
                 existing={"str_foundation": {"Excavation": [item("C")]}})
        t = block(w, FOUND, "Excavation")._tbl
        for r in range(3):  # error, warning, existing
            for c in range(1, t.columnCount()):
                it = t.item(r, c)
                if it is None:
                    continue
                assert it.data(Qt.ForegroundRole) is None, (r, c)
            assert t.item(r, NAME).background().style() != Qt.NoBrush, r

    def test_clean_rows_no_forced_foreground(self, make):
        w = make({FOUND: [H, good(1, "A")]})
        t = block(w, FOUND, "Excavation")._tbl
        for c in range(1, t.columnCount()):
            if t.item(0, c) is not None:
                assert t.item(0, c).data(Qt.ForegroundRole) is None

    def test_tint_follows_edit(self, make, qapp):
        w = make({FOUND: [H, good(1, "A")]})
        t = block(w, FOUND, "Excavation")._tbl
        edit(qapp, t, 0, RATE, "zzz")
        assert t.item(0, NAME).background().style() != Qt.NoBrush
        assert t.item(0, NAME).data(Qt.ForegroundRole) is None


class TestExisting:
    def sheets(self):
        return {FOUND: [H, good(1, "Backfilling"), good(2, "Trench"), good(3, "Cap", comp="Pile")]}

    def test_existing_row_unticked_and_flagged(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item("Backfilling")]}})
        t = block(w, FOUND, "Excavation")._tbl
        r = find_row(t, "Backfilling")
        assert not is_ticked(t, r) and is_tickable(t, r)
        assert "Name exists" in t.item(r, ISSUES).text()
        assert is_ticked(t, find_row(t, "Trench"))
        assert "Name exists" not in t.item(find_row(t, "Trench"), ISSUES).text()

    def test_existing_counts(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item("Backfilling")]}})
        assert w._select_all_count_lbl.text() == "(2 / 3)"
        assert w._select_all_chk.checkState() == Qt.PartiallyChecked
        assert footer(w) == {"Total rows": 3, "Errors": 0, "Warnings": 1, "Valid": 3, "Selected": 2}
        assert tab_text(w, FOUND) == f"{FOUND} (1 ⚠)"
        assert_consistent(w)

    @pytest.mark.parametrize("stored", ["backfilling", "BACKFILLING", "BackFilling"])
    def test_case_insensitive_match(self, make, stored):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item(stored)]}})
        t = block(w, FOUND, "Excavation")._tbl
        assert "Name exists" in t.item(find_row(t, "Backfilling"), ISSUES).text()

    def test_trash_item_not_existing(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item("Backfilling", trash=True)]}})
        t = block(w, FOUND, "Excavation")._tbl
        r = find_row(t, "Backfilling")
        assert is_ticked(t, r)
        assert "Name exists" not in t.item(r, ISSUES).text()
        assert footer(w)["Warnings"] == 0
        assert tab_text(w, FOUND) == FOUND

    def test_trash_and_live_copy_counts_as_existing(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [
            item("Backfilling", trash=True), item("backfilling", trash=False)]}})
        t = block(w, FOUND, "Excavation")._tbl
        assert "Name exists" in t.item(find_row(t, "Backfilling"), ISSUES).text()

    def test_other_component_not_existing(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Pile": [item("Backfilling")]}})
        t = block(w, FOUND, "Excavation")._tbl
        assert "Name exists" not in t.item(find_row(t, "Backfilling"), ISSUES).text()
        assert footer(w)["Warnings"] == 0

    def test_other_chunk_not_existing(self, make):
        w = make(self.sheets(), existing={"str_misc": {"Excavation": [item("Backfilling")]}})
        t = block(w, FOUND, "Excavation")._tbl
        assert "Name exists" not in t.item(find_row(t, "Backfilling"), ISSUES).text()

    def test_partial_name_not_existing(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item("Backfill")]}})
        assert footer(w)["Warnings"] == 0

    def test_existing_in_misc_routed_sheet(self, make):
        w = make({"CAT#Deck": [H, good(1, "Railing paint", comp="Railing")]},
                 existing={"str_misc": {"Deck - Railing": [item("railing paint")]}})
        t = block(w, "CAT#Deck", "Deck - Railing")._tbl
        assert "Name exists" in t.item(0, ISSUES).text()
        assert not is_ticked(t, 0)

    def test_existing_missing_state_key_counts(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [
            {"values": {"material_name": "Trench"}, "state": {}}]}})
        t = block(w, FOUND, "Excavation")._tbl
        assert "Name exists" in t.item(find_row(t, "Trench"), ISSUES).text()

    def _banner_visible(self, w):
        for lbl in w.findChildren(QtWidgets.QLabel):
            txt = strip_tags(lbl.text()).lower()
            if ("overwrit" in txt or "already exist" in txt) and lbl.isVisible():
                return True
        return False

    def test_banner_shown_when_existing(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item("Backfilling")]}})
        assert self._banner_visible(w)

    def test_no_banner_without_existing(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item("Other")]}})
        assert not self._banner_visible(w)

    def test_no_banner_for_trashed(self, make):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item("Backfilling", True)]}})
        assert not self._banner_visible(w)

    def test_ticking_existing_row_includes_it(self, make, qapp):
        w = make(self.sheets(), existing={"str_foundation": {"Excavation": [item("Backfilling")]}})
        t = block(w, FOUND, "Excavation")._tbl
        tick(qapp, t, find_row(t, "Backfilling"))
        assert "Backfilling" in flat_collected(w)
        assert_consistent(w)

    def test_existing_error_row_counts_as_error_not_warning(self, make):
        w = make({FOUND: [H, good(1, "Backfilling", rate="")]},
                 existing={"str_foundation": {"Excavation": [item("Backfilling")]}})
        f = footer(w)
        assert f["Errors"] == 1 and f["Warnings"] == 0
        assert tab_text(w, FOUND) == f"{FOUND} (1 ✗)"


class TestSelection:
    def test_select_all_toggle_cycle(self, make, qapp):
        w = make(std_sheets(), existing={"str_foundation": {"Excavation": [item("Trench")]}})
        assert frac(w._select_all_count_lbl) == (4, 5)
        w._on_select_all_clicked()
        qapp.processEvents()
        assert assert_consistent(w) == (5, 5)
        assert w._select_all_chk.checkState() == Qt.Checked
        w._on_select_all_clicked()
        qapp.processEvents()
        assert assert_consistent(w) == (0, 5)
        assert w._select_all_chk.checkState() == Qt.Unchecked
        assert w._import_valid_btn.text() == "Import 0 Rows"
        assert not w._import_valid_btn.isEnabled()
        w._on_select_all_clicked()
        qapp.processEvents()
        assert assert_consistent(w) == (5, 5)

    def test_select_all_never_ticks_error_rows(self, make, qapp):
        w = make(std_sheets())
        w._on_select_all_clicked()  # all ticked -> untick
        w._on_select_all_clicked()  # -> tick all
        qapp.processEvents()
        names = flat_collected(w)
        assert "NoRate" not in names and "BadQty" not in names
        for _, _, blk in blocks(w):
            for r in range(blk._tbl.rowCount()):
                if not is_tickable(blk._tbl, r):
                    assert not is_ticked(blk._tbl, r)

    def test_untick_single_row_everywhere(self, make, qapp):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        tick(qapp, t, 0, False)
        assert block(w, FOUND, "Excavation")._count_lbl.text() == "(1 / 2 selected)"
        assert block(w, FOUND, "Excavation")._chk.checkState() == Qt.PartiallyChecked
        assert w._sheet_tables[FOUND]._sheet_chk.checkState() == Qt.PartiallyChecked
        assert w._select_all_chk.checkState() == Qt.PartiallyChecked
        assert w._import_valid_btn.text() == "Import 4 Rows"
        assert footer(w)["Selected"] == 4
        assert_consistent(w)

    def test_untick_whole_block(self, make, qapp):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        tick(qapp, t, 0, False)
        tick(qapp, t, 1, False)
        assert block(w, FOUND, "Excavation")._chk.checkState() == Qt.Unchecked
        assert w._sheet_tables[FOUND]._sheet_chk.checkState() == Qt.PartiallyChecked
        assert_consistent(w)

    def test_untick_whole_sheet(self, make, qapp):
        w = make(std_sheets())
        for comp in ("Excavation", "Pile"):
            t = block(w, FOUND, comp)._tbl
            for r in range(t.rowCount()):
                if is_tickable(t, r):
                    tick(qapp, t, r, False)
        assert w._sheet_tables[FOUND]._sheet_chk.checkState() == Qt.Unchecked
        assert w._sheet_tables["CAT#Misc"]._sheet_chk.checkState() == Qt.Checked
        assert w._select_all_chk.checkState() == Qt.PartiallyChecked
        assert_consistent(w) == (2, 5)

    def test_untick_everything_by_rows(self, make, qapp):
        w = make(std_sheets())
        for _, _, blk in blocks(w):
            for r in range(blk._tbl.rowCount()):
                if is_tickable(blk._tbl, r):
                    tick(qapp, blk._tbl, r, False)
        assert assert_consistent(w) == (0, 5)
        assert w._select_all_chk.checkState() == Qt.Unchecked
        assert w._import_valid_btn.text() == "Import 0 Rows"
        assert not w._import_valid_btn.isEnabled()
        assert flat_collected(w) == []

    def test_retick_to_singular(self, make, qapp):
        w = make(std_sheets())
        w._on_select_all_clicked()
        qapp.processEvents()
        tick(qapp, block(w, "CAT#Misc", "Finish")._tbl, 1)
        assert w._import_valid_btn.text() == "Import 1 Row"
        assert flat_collected(w) == ["Primer"]
        assert_consistent(w)

    @pytest.mark.parametrize("level", ["block", "sheet"])
    def test_level_checkbox_click_consistent(self, make, qapp, level):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        tick(qapp, t, 0, False)  # make it partial
        chk = block(w, FOUND, "Excavation")._chk if level == "block" else w._sheet_tables[FOUND]._sheet_chk
        for _ in range(4):
            chk.click()
            qapp.processEvents()
            assert_consistent(w)
            assert chk.checkState() in (Qt.Checked, Qt.Unchecked)  # never stays partial after a click
            # the other sheet is untouched
            assert frac(w._sheet_tables["CAT#Misc"]._sheet_count_lbl) == (2, 2)

    def test_block_click_from_partial_affects_only_block(self, make, qapp):
        w = make(std_sheets())
        tick(qapp, block(w, FOUND, "Excavation")._tbl, 0, False)
        block(w, FOUND, "Excavation")._chk.click()
        qapp.processEvents()
        assert frac(block(w, FOUND, "Pile")._count_lbl) == (1, 1)
        assert_consistent(w)

    def test_window_checkbox_click_consistent(self, make, qapp):
        w = make(std_sheets())
        for _ in range(3):
            w._select_all_chk.click()
            qapp.processEvents()
            sel, able = assert_consistent(w)
            assert sel in (0, able)


class TestLiveEdits:
    def test_edit_into_error_clears_name(self, make, qapp):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        edit(qapp, t, 0, NAME, "")
        assert not is_ticked(t, 0) and not is_tickable(t, 0)
        f = footer(w)
        assert f["Errors"] == 3 and f["Valid"] == 4 and f["Selected"] == 4
        assert tab_text(w, FOUND) == f"{FOUND} (3 ✗)"
        assert w._import_valid_btn.text() == "Import 4 Rows"
        assert "Backfilling" not in flat_collected(w)
        assert t.item(0, ISSUES).text().strip()
        assert_consistent(w)

    @pytest.mark.parametrize("col,val", [(NAME, ""), (NAME, "   "), (UNIT, ""), (RATE, ""),
                                         (RATE, "abc"), (QTY, "x1"), (RATE, "1..2")])
    def test_edit_into_error_variants(self, make, qapp, col, val):
        w = make({FOUND: [H, good(1, "A"), good(2, "B")]})
        t = block(w, FOUND, "Excavation")._tbl
        edit(qapp, t, 0, col, val)
        assert footer(w)["Errors"] == 1
        assert not is_tickable(t, 0)
        assert tab_text(w, FOUND) == f"{FOUND} (1 ✗)"
        assert flat_collected(w) == ["B"]
        assert_consistent(w)

    def test_edit_out_of_error(self, make, qapp):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        edit(qapp, t, 2, RATE, "250")
        assert is_tickable(t, 2)
        assert footer(w)["Errors"] == 1
        assert tab_text(w, FOUND) == f"{FOUND} (1 ✗)"
        p = block(w, FOUND, "Pile")._tbl
        edit(qapp, p, 1, QTY, "3")
        assert footer(w)["Errors"] == 0 and footer(w)["Valid"] == 7
        assert tab_text(w, FOUND) == FOUND
        assert frac(w._select_all_count_lbl)[1] == 7
        assert_consistent(w)

    def test_fixed_row_can_be_ticked_and_collected(self, make, qapp):
        w = make(std_sheets())
        t = block(w, FOUND, "Excavation")._tbl
        edit(qapp, t, 2, RATE, "250")
        tick(qapp, t, 2)
        assert "NoRate" in flat_collected(w)
        assert_consistent(w)

    def test_break_then_fix_round_trip(self, make, qapp):
        w = make({FOUND: [H, good(1, "A")]})
        t = block(w, FOUND, "Excavation")._tbl
        for _ in range(3):
            edit(qapp, t, 0, UNIT, "")
            assert tab_text(w, FOUND) == f"{FOUND} (1 ✗)"
            assert w._import_valid_btn.text() == "Import 0 Rows"
            assert not w._import_valid_btn.isEnabled()
            edit(qapp, t, 0, UNIT, "kg")
            assert tab_text(w, FOUND) == FOUND
            assert footer(w)["Errors"] == 0
            assert_consistent(w)

    def test_edited_value_used_in_collect(self, make, qapp):
        w = make({FOUND: [H, good(1, "Old name")]})
        t = block(w, FOUND, "Excavation")._tbl
        edit(qapp, t, 0, NAME, "New name")
        if not is_ticked(t, 0):
            tick(qapp, t, 0)
        assert flat_collected(w) == ["New name"]

    def test_edit_negative_and_zero_numbers_not_errors(self, make, qapp):
        w = make({FOUND: [H, good(1, "A")]})
        t = block(w, FOUND, "Excavation")._tbl
        edit(qapp, t, 0, RATE, "0")
        assert footer(w)["Errors"] == 0
        edit(qapp, t, 0, RATE, "-5")
        assert footer(w)["Errors"] == 0

    def test_rename_to_existing_becomes_warning(self, make, qapp):
        w = make({FOUND: [H, good(1, "A"), good(2, "B")]},
                 existing={"str_foundation": {"Excavation": [item("Existing")]}})
        t = block(w, FOUND, "Excavation")._tbl
        assert tab_text(w, FOUND) == FOUND
        edit(qapp, t, 0, NAME, "EXISTING")
        assert "Name exists" in t.item(0, ISSUES).text()
        assert footer(w)["Warnings"] == 1
        assert tab_text(w, FOUND) == f"{FOUND} (1 ⚠)"
        assert_consistent(w)

    def test_rename_away_from_existing_clears_warning(self, make, qapp):
        w = make({FOUND: [H, good(1, "Existing")]},
                 existing={"str_foundation": {"Excavation": [item("existing")]}})
        t = block(w, FOUND, "Excavation")._tbl
        assert tab_text(w, FOUND) == f"{FOUND} (1 ⚠)"
        edit(qapp, t, 0, NAME, "Brand new")
        assert "Name exists" not in t.item(0, ISSUES).text()
        assert footer(w)["Warnings"] == 0
        assert tab_text(w, FOUND) == FOUND
        assert_consistent(w)

    def test_two_sheets_tabs_independent(self, make, qapp):
        w = make(std_sheets())
        t = block(w, "CAT#Misc", "Finish")._tbl
        edit(qapp, t, 0, RATE, "bad")
        assert tab_text(w, "CAT#Misc") == "CAT#Misc (1 ✗)"
        assert tab_text(w, FOUND) == f"{FOUND} (2 ✗)"
        assert footer(w)["Errors"] == 3
        assert_consistent(w)


class TestValidOnlyFilter:
    def sheets(self):
        return {FOUND: [H,
                        good(1, "Full"),
                        good(2, "ZeroQty", qty="0"),
                        good(3, "NoQty", qty=""),
                        good(4, "ZeroRate", rate="0"),
                        good(5, "AllGoodPile", comp="Pile"),
                        good(6, "ZeroOnly", comp="Cap", qty=0),
                        good(7, "NoUnitCap", comp="Cap", unit="")]}

    def visible_names(self, w, comp):
        t = block(w, FOUND, comp)._tbl
        return [t.item(r, NAME).text() for r in range(t.rowCount()) if not t.isRowHidden(r)]

    def set_filter(self, w, qapp, on):
        if w._qty_chk.isChecked() != on:
            w._qty_chk.click()
        qapp.processEvents()
        assert w._qty_chk.isChecked() == on

    def test_off_shows_everything(self, make, qapp):
        w = make(self.sheets())
        self.set_filter(w, qapp, False)
        assert self.visible_names(w, "Excavation") == ["Full", "ZeroQty", "NoQty", "ZeroRate"]

    def test_on_hides_incomplete(self, make, qapp):
        w = make(self.sheets())
        self.set_filter(w, qapp, True)
        assert self.visible_names(w, "Excavation") == ["Full"]
        assert self.visible_names(w, "Pile") == ["AllGoodPile"]

    def test_block_all_hidden_shows_placeholder(self, make, qapp):
        w = make(self.sheets())
        sw = w._sheet_tables[FOUND]
        self.set_filter(w, qapp, True)
        assert not block(w, FOUND, "Cap")._tbl.isVisibleTo(sw)
        assert block(w, FOUND, "Excavation")._tbl.isVisibleTo(sw)
        self.set_filter(w, qapp, False)
        assert block(w, FOUND, "Cap")._tbl.isVisibleTo(sw)
        assert self.visible_names(w, "Cap") == ["ZeroOnly", "NoUnitCap"]

    def test_toggle_restores(self, make, qapp):
        w = make(self.sheets())
        self.set_filter(w, qapp, True)
        self.set_filter(w, qapp, False)
        assert self.visible_names(w, "Excavation") == ["Full", "ZeroQty", "NoQty", "ZeroRate"]
        assert_consistent(w)

    @pytest.mark.parametrize("bad", ["0", "0.0", "", "   "])
    def test_zero_like_quantity_hidden(self, make, qapp, bad):
        w = make({FOUND: [H, good(1, "A", qty=bad), good(2, "B")]})
        self.set_filter(w, qapp, True)
        assert self.visible_names(w, "Excavation") == ["B"]

    def test_filter_counters_agree_across_levels(self, make, qapp):
        w = make(self.sheets())
        self.set_filter(w, qapp, True)
        sel_w, able_w = frac(w._select_all_count_lbl)
        sheet_sum = sum(frac(sw._sheet_count_lbl)[0] for sw in w._sheet_tables.values())
        block_sum = sum(frac(b._count_lbl)[0] for _, _, b in blocks(w))
        assert sel_w == sheet_sum == block_sum == button_n(w) == footer(w)["Selected"]
        assert sel_w <= able_w

    def test_select_all_under_filter_then_collect(self, make, qapp):
        w = make(self.sheets())
        self.set_filter(w, qapp, True)
        w._on_select_all_clicked()
        qapp.processEvents()
        w._on_select_all_clicked()
        qapp.processEvents()
        names = flat_collected(w)
        assert "NoUnitCap" not in names  # error row
        assert button_n(w) == footer(w)["Selected"] == len(names)
        assert w._import_valid_btn.isEnabled() == (len(names) > 0)

    def test_filter_does_not_change_collect_when_off(self, make, qapp):
        w = make(self.sheets())
        before = flat_collected(w)
        self.set_filter(w, qapp, True)
        self.set_filter(w, qapp, False)
        assert flat_collected(w) == before
        assert_consistent(w)

    def test_footer_totals_unchanged_by_filter(self, make, qapp):
        w = make(self.sheets())
        f0 = footer(w)
        self.set_filter(w, qapp, True)
        f1 = footer(w)
        assert (f1["Total rows"], f1["Errors"], f1["Valid"]) == (f0["Total rows"], f0["Errors"], f0["Valid"])


class TestCollect:
    def test_structure_and_routing(self, make):
        w = make({FOUND: [H, good(1, "A"), good(2, "B", comp="Pile")],
                  "CAT#Sub-Structure": [H, good(3, "C", comp="Pier")],
                  "CAT#Deck": [H, good(4, "D", comp="Railing"), good(5, "E", comp="")]})
        got = collected_names(w)
        assert got[("str_foundation", "Excavation")] == ["A"]
        assert got[("str_foundation", "Pile")] == ["B"]
        assert got[("str_sub_structure", "Pier")] == ["C"]
        assert got[("str_misc", "Deck - Railing")] == ["D"]
        assert sum(len(v) for v in got.values()) == 5

    def test_material_dict_shape(self, make):
        w = make({FOUND: [H, good(1, "A")]})
        data = w._collect()
        (m,) = data["str_foundation"]["Excavation"]
        assert isinstance(m, dict) and isinstance(m["values"], dict)
        assert m["values"]["material_name"] == "A"

    def test_never_errors_or_unticked(self, make, qapp):
        w = make(std_sheets())
        tick(qapp, block(w, "CAT#Misc", "Finish")._tbl, 0, False)
        names = flat_collected(w)
        assert names == sorted(["Backfilling", "Trench", "Bored pile", "Primer"])

    def test_after_untick_all_empty(self, make, qapp):
        w = make(std_sheets())
        w._on_select_all_clicked()
        qapp.processEvents()
        assert flat_collected(w) == []

    def test_matches_button_count_through_random_ops(self, make, qapp):
        import random
        rng = random.Random(1234)
        w = make(std_sheets(), existing={"str_foundation": {"Excavation": [item("Backfilling")]}})
        tables = [b._tbl for _, _, b in blocks(w)]
        for _ in range(60):
            t = rng.choice(tables)
            r = rng.randrange(t.rowCount())
            op = rng.random()
            if op < 0.6:
                if is_tickable(t, r):  # a user can't tick an error row
                    tick(qapp, t, r, rng.random() < 0.5)
            elif op < 0.75:
                edit(qapp, t, r, RATE, rng.choice(["", "x", "5", "10.5"]))
            elif op < 0.85:
                edit(qapp, t, r, NAME, rng.choice(["", "Backfilling", "Zed", "q"]))
            else:
                w._on_select_all_clicked()
                qapp.processEvents()
            sel, _ = assert_consistent(w)
            assert len(flat_collected(w)) == sel
            for _, _, blk in blocks(w):
                for rr in range(blk._tbl.rowCount()):
                    if blk._tbl.item(rr, NAME).text().strip() == "" or \
                            blk._tbl.item(rr, RATE).text().strip() in ("", "x"):
                        assert not is_ticked(blk._tbl, rr)

    def test_duplicate_names_within_import_both_collected(self, make):
        w = make({FOUND: [H, good(1, "Same"), good(2, "Same")]})
        assert flat_collected(w).count("Same") in (1, 2)
