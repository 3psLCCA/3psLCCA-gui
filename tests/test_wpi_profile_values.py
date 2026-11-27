"""Black-box tests: a user creates / edits a WPI profile by typing values into
the editor dialog's table (Duplicate… -> type -> Create, Edit… -> type -> Save).

Setup style mirrors tests/test_wpi_profile_menu.py. Expected behaviour comes
from the spec, not from the table implementation."""
import copy
import math
import re

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox,
                               QDialog, QDialogButtonBox, QMessageBox)

import three_ps_lcca_gui.gui.components.carbon_emission.widgets.traffic_emissions  # noqa: F401  (import-order quirk)
from three_ps_lcca_gui.gui.components.traffic_data import main as tm
from three_ps_lcca_gui.gui.components.traffic_data import wpi_selector as ws
from three_ps_lcca_gui.gui.components.utils.wpi_manager import WPIManager

APP = QApplication.instance() or QApplication([])
_KEEP = []   # pages built in tests: keep alive so Python GC never deletes them mid-run

VEHICLES = {
    "Small Car": "small_cars", "Big Car": "big_cars",
    "Two Wheeler": "two_wheelers", "Ordinary Bus": "o_buses",
    "Deluxe Bus": "d_buses", "LCV": "lcv", "HCV": "hcv", "MCV": "mcv",
}
VEH_ORDER = list(VEHICLES)
COLS = {"Petrol Cost": "petrol", "Diesel Cost": "diesel",
        "Tyre Cost": "tyre_cost", "Grease Cost": "grease"}


# ---------------------------------------------------------------- fixtures
class Calls:
    def __init__(self):
        self.critical = []
        self.warning = []
        self.question = []
        self.saved = []
        self.deleted = []


@pytest.fixture(autouse=True)
def boxes(monkeypatch):
    c = Calls()

    def rec(lst):
        def f(*a, **k):
            lst.append(a)
            return QMessageBox.Ok
        return staticmethod(f)

    monkeypatch.setattr(QMessageBox, "critical", rec(c.critical))
    monkeypatch.setattr(QMessageBox, "warning", rec(c.warning))
    monkeypatch.setattr(QMessageBox, "question", rec(c.question))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(ws, "save_to_user_library",
                        lambda p: c.saved.append(copy.deepcopy(p)))
    monkeypatch.setattr(ws, "delete_from_user_library",
                        lambda pid: c.deleted.append(pid))
    return c


@pytest.fixture
def mgr():
    return WPIManager(tm._WPI_DB_PATH)


@pytest.fixture
def sel(mgr):
    s = ws._WPISelector(mgr)
    s.signals = {"saved": []}
    s.profile_saved.connect(lambda p: s.signals["saved"].append(p))
    return s


class DialogDriver:
    """Replaces _WPIEditorDialog.exec; shows the dialog, runs `fn(dialog)`."""

    def __init__(self, monkeypatch):
        self.fn = None
        self.seen = []
        driver = self

        def fake_exec(d):
            driver.seen.append(d)
            d.show()
            QApplication.processEvents()
            try:
                if driver.fn is None:
                    return QDialog.Rejected
                return driver.fn(d)
            finally:
                d.hide()

        monkeypatch.setattr(ws._WPIEditorDialog, "exec", fake_exec)


@pytest.fixture
def dlg(monkeypatch):
    return DialogDriver(monkeypatch)


# ---------------------------------------------------------------- user helpers
def col_of(table, label):
    for c in range(table.columnCount()):
        if " ".join(table.horizontalHeaderItem(c).text().split()) == label:
            return c
    raise AssertionError(f"column {label!r} not found")


def row_of(table, vehicle):
    for r in range(table.rowCount()):
        it = table.verticalHeaderItem(r)
        if it and " ".join(it.text().split()) == vehicle:
            return r
    raise AssertionError(f"row {vehicle!r} not found")


def cell(table, vehicle, label):
    w = table.cellWidget(row_of(table, vehicle), col_of(table, label))
    assert isinstance(w, QAbstractSpinBox), f"no input widget at {vehicle}/{label}"
    return w


def common_box(table, label):
    c = col_of(table, label)
    w = table.cellWidget(0, c)
    cb = w if isinstance(w, QCheckBox) else w.findChild(QCheckBox)
    assert cb is not None, f"no Common checkbox for {label}"
    return cb


def is_common(table, label):
    return common_box(table, label).isChecked()


def set_common(table, label, on):
    cb = common_box(table, label)
    if cb.isChecked() != on:
        QTest.mouseClick(cb, Qt.LeftButton, Qt.NoModifier, cb.rect().center())
        QApplication.processEvents()


def type_into(table, vehicle, label, text):
    """Click the cell, select all, type `text`, press Enter, leave the cell."""
    w = cell(table, vehicle, label)
    le = w.lineEdit()
    QTest.mouseClick(le, Qt.LeftButton, Qt.NoModifier, le.rect().center())
    w.setFocus()
    QTest.keyClick(w, Qt.Key_A, Qt.ControlModifier)
    if text:
        QTest.keyClicks(w, text)
    else:
        QTest.keyClick(w, Qt.Key_Delete)
    QTest.keyClick(w, Qt.Key_Return)
    w.clearFocus()
    QApplication.processEvents()


def shown(table, vehicle, label):
    return cell(table, vehicle, label).text().strip()


def accept(d):
    d.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
    return d.result()


def val(data, vehicle, label):
    return data[VEHICLES[vehicle]][COLS[label]]


def run_dup(sel, dlg, fn):
    dlg.fn = fn
    sel._act_duplicate.trigger()
    return sel.current_profile()


def run_edit(sel, dlg, fn):
    dlg.fn = fn
    sel._act_edit.trigger()
    return sel.current_profile()


def make_custom(sel, dlg, name="Mine"):
    def fn(d):
        d._name.setText(name)
        return accept(d)
    return run_dup(sel, dlg, fn)


# ---------------------------------------------------------------- 1. duplicate + values
def test_noncommon_cell_stored_for_that_vehicle_only(sel, dlg):
    src = copy.deepcopy(sel.current_profile().data)

    def fn(d):
        t = d._table
        set_common(t, "Diesel Cost", False)
        type_into(t, "HCV", "Diesel Cost", "2.5")
        return accept(d)

    new = run_dup(sel, dlg, fn)
    assert new.is_custom
    assert val(new.data, "HCV", "Diesel Cost") == pytest.approx(2.5)
    for v in VEH_ORDER:
        if v != "HCV":
            assert val(new.data, v, "Diesel Cost") == pytest.approx(
                val(src, v, "Diesel Cost"), abs=1e-4)


def test_common_first_row_applies_to_all_vehicles(sel, dlg):
    def fn(d):
        set_common(d._table, "Petrol Cost", True)
        type_into(d._table, "Small Car", "Petrol Cost", "3.25")
        return accept(d)

    new = run_dup(sel, dlg, fn)
    assert [val(new.data, v, "Petrol Cost") for v in VEH_ORDER] == \
        [pytest.approx(3.25)] * len(VEH_ORDER)


def test_common_other_rows_show_value_and_are_not_editable(sel, dlg):
    seen = {}

    def fn(d):
        t = d._table
        set_common(t, "Petrol Cost", True)
        type_into(t, "Small Car", "Petrol Cost", "3.25")
        seen["first_ro"] = cell(t, "Small Car", "Petrol Cost").isReadOnly()
        seen["others_ro"] = [cell(t, v, "Petrol Cost").isReadOnly() for v in VEH_ORDER[1:]]
        seen["others_txt"] = [shown(t, v, "Petrol Cost") for v in VEH_ORDER[1:]]
        type_into(t, "LCV", "Petrol Cost", "9")   # should be ignored
        seen["lcv_after"] = shown(t, "LCV", "Petrol Cost")
        return QDialog.Rejected

    run_dup(sel, dlg, fn)
    assert seen["first_ro"] is False
    assert all(seen["others_ro"])
    assert seen["others_txt"] == ["3.2500"] * 7
    assert seen["lcv_after"] == "3.2500"


def test_common_checked_after_typing_copies_first_row(sel, dlg):
    def fn(d):
        t = d._table
        set_common(t, "Grease Cost", False)
        type_into(t, "Small Car", "Grease Cost", "1.75")
        type_into(t, "MCV", "Grease Cost", "4")
        set_common(t, "Grease Cost", True)
        return accept(d)

    new = run_dup(sel, dlg, fn)
    assert [val(new.data, v, "Grease Cost") for v in VEH_ORDER] == \
        [pytest.approx(1.75)] * len(VEH_ORDER)


def test_unchecking_common_allows_different_values(sel, dlg):
    entered = {v: 1.0 + i * 0.5 for i, v in enumerate(VEH_ORDER)}

    def fn(d):
        t = d._table
        set_common(t, "Petrol Cost", False)
        for v, x in entered.items():
            type_into(t, v, "Petrol Cost", f"{x}")
        return accept(d)

    new = run_dup(sel, dlg, fn)
    for v, x in entered.items():
        assert val(new.data, v, "Petrol Cost") == pytest.approx(x), v


def test_unchecked_rows_become_editable(sel, dlg):
    seen = {}

    def fn(d):
        t = d._table
        set_common(t, "Petrol Cost", False)
        seen["ro"] = [cell(t, v, "Petrol Cost").isReadOnly() for v in VEH_ORDER]
        return QDialog.Rejected

    run_dup(sel, dlg, fn)
    assert seen["ro"] == [False] * len(VEH_ORDER)


def test_saved_data_exactly_entered_rest_from_source(sel, dlg):
    src = copy.deepcopy(sel.current_profile().data)

    def fn(d):
        t = d._table
        set_common(t, "Petrol Cost", True)
        type_into(t, "Small Car", "Petrol Cost", "2")
        set_common(t, "Tyre Cost", False)
        type_into(t, "Big Car", "Tyre Cost", "1.5")
        type_into(t, "Two Wheeler", "Tyre Cost", "0.75")
        return accept(d)

    new = run_dup(sel, dlg, fn)
    expected = copy.deepcopy(src)
    for v in VEH_ORDER:
        expected[VEHICLES[v]]["petrol"] = 2.0
    expected["big_cars"]["tyre_cost"] = 1.5
    expected["two_wheelers"]["tyre_cost"] = 0.75
    assert set(new.data) == set(expected)
    for vk in expected:
        assert set(new.data[vk]) == set(expected[vk]), vk
        for k in expected[vk]:
            assert new.data[vk][k] == pytest.approx(expected[vk][k], abs=5e-5), (vk, k)


def test_source_builtin_unchanged(sel, dlg, mgr):
    src = sel.current_profile()
    snap = copy.deepcopy((src.name, src.year, src.remark, src.data))

    def fn(d):
        t = d._table
        set_common(t, "Petrol Cost", False)
        type_into(t, "Small Car", "Petrol Cost", "7")
        type_into(t, "HCV", "Petrol Cost", "8")
        d._remark.setText("x")
        return accept(d)

    run_dup(sel, dlg, fn)
    again = mgr.get_by_id(src.id)
    assert (again.name, again.year, again.remark, again.data) == snap


# ---------------------------------------------------------------- 2. metadata
def test_name_year_remark_typed_by_user_are_saved(sel, dlg):
    def fn(d):
        for w, text in ((d._name, "My Profile 2031"), (d._remark, "from field survey")):
            w.setFocus()
            QTest.keyClick(w, Qt.Key_A, Qt.ControlModifier)
            QTest.keyClicks(w, text)
        d._year.setFocus()
        QTest.keyClick(d._year, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClicks(d._year, "2031")
        QTest.keyClick(d._year, Qt.Key_Return)
        return accept(d)

    new = run_dup(sel, dlg, fn)
    assert new.name == "My Profile 2031"
    assert new.year == 2031
    assert new.remark == "from field survey"


def test_duplicate_starts_with_empty_remark_but_copies_year(sel, dlg):
    src = sel.current_profile()
    seen = {}
    run_dup(sel, dlg, lambda d: (seen.update(
        remark=d._remark.text(), year=d._year.value()), QDialog.Rejected)[1])
    assert seen["remark"] == ""
    assert seen["year"] == src.year


def test_duplicate_without_typing_remark_saves_empty_remark(sel, dlg):
    new = run_dup(sel, dlg, accept)
    assert new.remark == ""


# ---------------------------------------------------------------- 3. selection / page
def test_new_profile_selected_and_signal_carries_data(sel, dlg):
    def fn(d):
        set_common(d._table, "Diesel Cost", True)
        type_into(d._table, "Small Car", "Diesel Cost", "1.2345")
        return accept(d)

    new = run_dup(sel, dlg, fn)
    assert sel._combo.currentText() == f"★ {new.name}"
    assert len(sel.signals["saved"]) == 1
    emitted = sel.signals["saved"][0]
    assert emitted.id == new.id
    assert [val(emitted.data, v, "Diesel Cost") for v in VEH_ORDER] == \
        [pytest.approx(1.2345)] * 8


def test_traffic_page_shows_new_values(dlg):
    page = tm.TrafficData()
    _KEEP.append(page)
    psel = page._wpi_selector
    ptable = page._wpi_table

    def fn(d):
        t = d._table
        set_common(t, "Petrol Cost", True)
        type_into(t, "Small Car", "Petrol Cost", "2.2222")
        set_common(t, "Tyre Cost", False)
        type_into(t, "Deluxe Bus", "Tyre Cost", "6.5")
        return accept(d)

    new = run_dup(psel, dlg, fn)
    assert psel.current_profile().id == new.id and new.is_custom
    assert [shown(ptable, v, "Petrol Cost") for v in VEH_ORDER] == ["2.2222"] * 8
    assert shown(ptable, "Deluxe Bus", "Tyre Cost") == "6.5000"
    assert not is_common(ptable, "Tyre Cost")
    assert ptable.collect_to_data() == new.data
    # the page table stays read-only
    assert cell(ptable, "Small Car", "Petrol Cost").isReadOnly()


# ---------------------------------------------------------------- 4. edit custom
def test_edit_changes_value_same_id(sel, dlg, mgr):
    p = make_custom(sel, dlg)
    count = len(mgr.all_listed())

    def fn(d):
        set_common(d._table, "Tyre Cost", False)
        type_into(d._table, "LCV", "Tyre Cost", "5.125")
        return accept(d)

    q = run_edit(sel, dlg, fn)
    assert q.id == p.id
    assert len(mgr.all_listed()) == count
    assert val(mgr.get_by_id(p.id).data, "LCV", "Tyre Cost") == pytest.approx(5.125)


def test_reopen_edit_shows_saved_value(sel, dlg):
    make_custom(sel, dlg)

    def fn(d):
        set_common(d._table, "Tyre Cost", False)
        type_into(d._table, "LCV", "Tyre Cost", "5.125")
        set_common(d._table, "Diesel Cost", True)
        type_into(d._table, "Small Car", "Diesel Cost", "0.5")
        return accept(d)

    run_edit(sel, dlg, fn)
    seen = {}

    def look(d):
        t = d._table
        seen["lcv"] = shown(t, "LCV", "Tyre Cost")
        seen["tyre_common"] = is_common(t, "Tyre Cost")
        seen["diesel"] = [shown(t, v, "Diesel Cost") for v in VEH_ORDER]
        seen["diesel_common"] = is_common(t, "Diesel Cost")
        return QDialog.Rejected

    run_edit(sel, dlg, look)
    assert seen["lcv"] == "5.1250"
    assert seen["tyre_common"] is False
    assert seen["diesel"] == ["0.5000"] * 8
    assert seen["diesel_common"] is True


def test_edit_cancel_discards_typed_values(sel, dlg, mgr, boxes):
    p = make_custom(sel, dlg)
    snap = copy.deepcopy(p.data)
    sel.signals["saved"].clear()
    boxes.saved.clear()

    def fn(d):
        set_common(d._table, "Petrol Cost", False)
        type_into(d._table, "HCV", "Petrol Cost", "99")
        type_into(d._table, "Small Car", "Grease Cost", "42")
        return QDialog.Rejected

    run_edit(sel, dlg, fn)
    assert mgr.get_by_id(p.id).data == snap
    assert sel.signals["saved"] == [] and boxes.saved == []
    seen = {}
    run_edit(sel, dlg, lambda d: (seen.update(
        hcv=val(d._table.collect_to_data(), "HCV", "Petrol Cost")), QDialog.Rejected)[1])
    assert seen["hcv"] == pytest.approx(val(snap, "HCV", "Petrol Cost"))


def test_duplicate_cancel_discards_typed_values(sel, dlg, mgr):
    before = [p.id for p in mgr.all_listed()]
    src = sel.current_profile()
    snap = copy.deepcopy(src.data)

    def fn(d):
        type_into(d._table, "Small Car", "Petrol Cost", "77")
        return QDialog.Rejected

    run_dup(sel, dlg, fn)
    assert [p.id for p in mgr.all_listed()] == before
    assert mgr.get_by_id(src.id).data == snap
    assert sel.signals["saved"] == []


# ---------------------------------------------------------------- 5. invalid input
INVALID = {"text": "abc", "negative": "-5", "empty": "", "mixed": "1.2x3"}


@pytest.mark.parametrize("kind", list(INVALID))
def test_invalid_input_never_saved_as_garbage(sel, dlg, kind):
    seen = {}

    def fn(d):
        t = d._table
        set_common(t, "Tyre Cost", False)
        seen["before"] = cell(t, "HCV", "Tyre Cost").value()
        type_into(t, "HCV", "Tyre Cost", INVALID[kind])
        seen["text"] = shown(t, "HCV", "Tyre Cost")
        return accept(d)

    new = run_dup(sel, dlg, fn)
    x = val(new.data, "HCV", "Tyre Cost")
    print(f"[invalid {kind!r}] before={seen['before']} shown={seen['text']!r} "
          f"saved={x!r} new_profile={new.is_custom}")
    assert isinstance(x, (int, float)) and not isinstance(x, bool)
    assert math.isfinite(x) and x >= 0


@pytest.mark.parametrize("kind", ["text", "negative"])
def test_invalid_input_rejected_keeps_previous_value(sel, dlg, kind):
    seen = {}

    def fn(d):
        t = d._table
        set_common(t, "Tyre Cost", False)
        type_into(t, "HCV", "Tyre Cost", "2.5")
        type_into(t, "HCV", "Tyre Cost", INVALID[kind])
        seen["v"] = cell(t, "HCV", "Tyre Cost").value()
        return accept(d)

    new = run_dup(sel, dlg, fn)
    assert seen["v"] == pytest.approx(2.5)
    assert val(new.data, "HCV", "Tyre Cost") == pytest.approx(2.5)


# ---------------------------------------------------------------- 6. precision
def test_precision_display_and_storage(sel, dlg):
    seen = {}

    def fn(d):
        t = d._table
        set_common(t, "Tyre Cost", False)
        type_into(t, "Big Car", "Tyre Cost", "123.45678")
        seen["text"] = shown(t, "Big Car", "Tyre Cost")
        return accept(d)

    new = run_dup(sel, dlg, fn)
    x = val(new.data, "Big Car", "Tyre Cost")
    print(f"[precision] shown={seen['text']!r} stored={x!r}")
    assert re.fullmatch(r"\d+(\.\d{1,4})?", seen["text"].replace(",", ""))
    assert abs(x - 123.45678) < 1e-3
    assert x == round(x, 4)           # no float noise past 4 dp
    assert repr(x) == repr(round(x, 4))


def test_precision_survives_reopen(sel, dlg):
    def fn(d):
        set_common(d._table, "Tyre Cost", False)
        type_into(d._table, "Big Car", "Tyre Cost", "0.1234")
        return accept(d)

    run_dup(sel, dlg, fn)
    seen = {}
    run_edit(sel, dlg, lambda d: (seen.update(
        t=shown(d._table, "Big Car", "Tyre Cost")), QDialog.Rejected)[1])
    assert seen["t"] == "0.1234"
    assert val(sel.current_profile().data, "Big Car", "Tyre Cost") == 0.1234
