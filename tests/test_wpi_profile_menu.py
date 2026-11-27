"""Black-box tests for the WPI profile menu (Duplicate / Edit / Delete) in the
Traffic Data WPI selector (spec-only)."""
import copy

import pytest
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                               QMessageBox)

import three_ps_lcca_gui.gui.components.carbon_emission.widgets.traffic_emissions  # noqa: F401  (import-order quirk)
from three_ps_lcca_gui.gui.components.traffic_data import main as tm
from three_ps_lcca_gui.gui.components.traffic_data import wpi_selector as ws
from three_ps_lcca_gui.gui.components.utils.wpi_manager import WPIManager

APP = QApplication.instance() or QApplication([])

ELL = "…"
DUP = "Duplicate" + ELL
EDIT = "Edit" + ELL
DEL = "Delete"


# ---------------------------------------------------------------- fixtures
class Calls:
    def __init__(self):
        self.critical = []
        self.warning = []
        self.question = []
        self.question_answer = QMessageBox.No
        self.saved = []      # save_to_user_library
        self.deleted = []    # delete_from_user_library


@pytest.fixture(autouse=True)
def boxes(monkeypatch):
    c = Calls()

    def crit(*a, **k):
        c.critical.append(a)
        return QMessageBox.Ok

    def warn(*a, **k):
        c.warning.append(a)
        return QMessageBox.Ok

    def ques(*a, **k):
        c.question.append(a)
        return c.question_answer

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(crit))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(warn))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(ques))
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
    s.signals = {"selected": [], "saved": [], "deleted": []}
    s.profile_selected.connect(lambda p: s.signals["selected"].append(p))
    s.profile_saved.connect(lambda p: s.signals["saved"].append(p))
    s.profile_deleted.connect(lambda i: s.signals["deleted"].append(i))
    return s


class DialogDriver:
    """Replaces _WPIEditorDialog.exec; runs `fn(dialog)` then returns."""

    def __init__(self, monkeypatch):
        self.fn = None
        self.seen = []
        driver = self

        def fake_exec(dlg):
            driver.seen.append(dlg)
            if driver.fn is None:
                return QDialog.Rejected
            return driver.fn(dlg)

        monkeypatch.setattr(ws._WPIEditorDialog, "exec", fake_exec)


@pytest.fixture
def dlg(monkeypatch):
    return DialogDriver(monkeypatch)


# ---------------------------------------------------------------- helpers
def actions(sel):
    return {a.text(): a for a in sel.menu.actions() if not a.isSeparator()}


def button_box(d):
    return d.findChild(QDialogButtonBox)


def accept_button(d):
    return button_box(d).button(QDialogButtonBox.Save)


def save(d):
    accept_button(d).click()
    return d.result()


def cancel(d):
    return QDialog.Rejected


def save_with(**fields):
    def fn(d):
        if "name" in fields:
            d._name.setText(fields["name"])
        if "year" in fields:
            d._year.setValue(fields["year"])
        if "remark" in fields:
            d._remark.setText(fields["remark"])
        if "shared" in fields:
            d._shared.setChecked(fields["shared"])
        if "data" in fields:
            d._table.load_from_data(fields["data"])
        return save(d)
    return fn


def make_custom(sel, dlg, **fields):
    """Duplicate the current profile and save; return the new profile."""
    dlg.fn = save_with(**fields)
    actions(sel)[DUP].trigger()
    return sel.current_profile()


def tweak(data):
    """Return a copy of a WPI data dict with one numeric leaf changed."""
    d = copy.deepcopy(data)

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)):
                    o[k] = v + 1.5
                    return True
                if walk(v):
                    return True
        elif isinstance(o, list):
            for i, v in enumerate(o):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    o[i] = v + 1.5
                    return True
                if walk(v):
                    return True
        return False

    assert walk(d), "no numeric value found in WPI data"
    return d


def enabled(sel):
    a = actions(sel)
    return (a[DUP].isEnabled(), a[EDIT].isEnabled(), a[DEL].isEnabled())


# ---------------------------------------------------------------- 1. menu shape
def test_menu_has_exactly_three_actions(sel):
    texts = [a.text() for a in sel.menu.actions() if not a.isSeparator()]
    assert texts == [DUP, EDIT, DEL]


def test_separator_before_delete(sel):
    acts = sel.menu.actions()
    i = [a.text() for a in acts].index(DEL)
    assert i > 0 and acts[i - 1].isSeparator()


def test_no_new_profile_action(sel):
    texts = [a.text().lower() for a in sel.menu.actions()]
    assert not any("new" in t for t in texts)


# ---------------------------------------------------------------- 2-4. enablement
def test_builtin_selected_by_default(sel):
    p = sel.current_profile()
    assert p is not None and not p.is_custom
    assert not sel.current_is_custom()


def test_builtin_enablement(sel):
    assert enabled(sel) == (True, False, False)


def test_custom_enablement(sel, dlg):
    make_custom(sel, dlg)
    assert sel.current_is_custom()
    assert enabled(sel) == (True, True, True)


def test_freeze_disables_all_builtin(sel):
    sel.freeze(True)
    assert enabled(sel) == (False, False, False)
    sel.freeze(False)
    assert enabled(sel) == (True, False, False)


def test_freeze_disables_all_custom(sel, dlg):
    make_custom(sel, dlg)
    sel.freeze(True)
    assert enabled(sel) == (False, False, False)
    sel.freeze(False)
    assert enabled(sel) == (True, True, True)


def test_enablement_follows_selection(sel, dlg, mgr):
    builtin = sel.current_profile()
    make_custom(sel, dlg)
    sel.select_by_id(builtin.id)
    assert enabled(sel) == (True, False, False)


# ---------------------------------------------------------------- 5. duplicate dialog
def test_duplicate_dialog_prefill(sel, dlg):
    src = sel.current_profile()
    seen = {}

    def inspect(d):
        seen["title"] = d.windowTitle()
        seen["btn"] = accept_button(d).text() if accept_button(d) else None
        seen["name"] = d._name.text()
        seen["year"] = d._year.value()
        seen["remark"] = d._remark.text()
        seen["data"] = d._table.collect_to_data()
        return QDialog.Rejected

    dlg.fn = inspect
    actions(sel)[DUP].trigger()
    assert seen["title"] == f"Duplicate {src.name}"
    assert seen["btn"] == "Create"
    assert seen["name"] == f"{src.name}-user"
    assert seen["year"] == src.year
    assert src.remark  # built-ins carry a remark ...
    assert seen["remark"] == ""  # ... which a copy does not inherit
    assert seen["data"] == src.data


def test_duplicate_name_suggestion_increments(sel, dlg):
    src = sel.current_profile()
    make_custom(sel, dlg)                 # takes "<name>-user"
    sel.select_by_id(src.id)
    names = []
    dlg.fn = lambda d: (names.append(d._name.text()), QDialog.Rejected)[1]
    actions(sel)[DUP].trigger()
    assert names == [f"{src.name}-user-2"]


def test_duplicate_dialog_has_no_template_selector(sel, dlg):
    from PySide6.QtWidgets import QComboBox, QLabel
    found = {}

    def inspect(d):
        found["combos"] = d.findChildren(QComboBox)
        found["labels"] = [l.text() for l in d.findChildren(QLabel)]
        return QDialog.Rejected

    dlg.fn = inspect
    actions(sel)[DUP].trigger()
    assert not any("based on" in t.lower() or "template" in t.lower()
                   for t in found["labels"])
    # the only combos allowed are ones inside the data table
    outside = [c for c in found["combos"] if not dlg.seen[0]._table.isAncestorOf(c)]
    assert outside == []


# ---------------------------------------------------------------- 6. saving duplicate
def test_duplicate_save_adds_new_custom_profile(sel, dlg, mgr):
    src = sel.current_profile()
    before = len(mgr.all_listed())
    new = make_custom(sel, dlg)
    assert len(mgr.all_listed()) == before + 1
    assert new.id != src.id
    assert new.is_custom
    assert new.name == f"{src.name}-user"
    assert new.data == src.data


def test_duplicate_selected_with_star_prefix(sel, dlg):
    new = make_custom(sel, dlg)
    assert sel.current_profile().id == new.id
    assert sel._combo.currentText() == f"★ {new.name}"


def test_duplicate_emits_profile_saved(sel, dlg):
    new = make_custom(sel, dlg)
    assert len(sel.signals["saved"]) == 1
    assert sel.signals["saved"][0].id == new.id


def test_duplicate_leaves_builtin_untouched(sel, dlg, mgr):
    src = sel.current_profile()
    snap = copy.deepcopy((src.name, src.year, src.remark, src.data, src.is_custom))
    make_custom(sel, dlg, data=tweak(src.data), remark="changed", year=src.year + 1)
    again = mgr.get_by_id(src.id)
    assert (again.name, again.year, again.remark, again.data, again.is_custom) == snap


def test_duplicate_of_builtin_shared_by_default_and_saved_to_library(sel, dlg, boxes):
    flags = []

    def fn(d):
        flags.append(d._shared.isChecked())
        return save(d)

    dlg.fn = fn
    actions(sel)[DUP].trigger()
    new = sel.current_profile()
    assert flags == [True]
    assert [p.id for p in boxes.saved] == [new.id]


def test_duplicate_of_custom_keeps_source_shared_setting(sel, dlg, boxes):
    make_custom(sel, dlg, shared=False)
    boxes.saved.clear()
    flags = []

    def fn(d):
        flags.append(d._shared.isChecked())
        return save(d)

    dlg.fn = fn
    actions(sel)[DUP].trigger()
    assert flags == [False]
    assert boxes.saved == []


def test_duplicate_unticked_not_saved_to_library(sel, dlg, boxes):
    make_custom(sel, dlg, shared=False)
    assert boxes.saved == []


# ---------------------------------------------------------------- 7. cancel
def test_duplicate_cancel_changes_nothing(sel, dlg, mgr, boxes):
    src = sel.current_profile()
    before = [p.id for p in mgr.all_listed()]
    dlg.fn = cancel
    actions(sel)[DUP].trigger()
    assert [p.id for p in mgr.all_listed()] == before
    assert sel.current_profile().id == src.id
    assert sel.signals["saved"] == []
    assert boxes.saved == [] and boxes.deleted == []


def test_edit_cancel_changes_nothing(sel, dlg, mgr, boxes):
    p = make_custom(sel, dlg)
    snap = copy.deepcopy((p.name, p.year, p.remark, p.data))
    sel.signals["saved"].clear()
    boxes.saved.clear()

    def fn(d):
        d._name.setText("Something else")
        return QDialog.Rejected

    dlg.fn = fn
    actions(sel)[EDIT].trigger()
    q = mgr.get_by_id(p.id)
    assert (q.name, q.year, q.remark, q.data) == snap
    assert sel.signals["saved"] == []
    assert boxes.saved == [] and boxes.deleted == []


# ---------------------------------------------------------------- 8-9. edit
def test_edit_dialog_prefill(sel, dlg):
    p = make_custom(sel, dlg, remark="my remark")
    seen = {}

    def inspect(d):
        seen.update(title=d.windowTitle(), btn=accept_button(d).text(),
                    name=d._name.text(), year=d._year.value(),
                    remark=d._remark.text(), shared=d._shared.isChecked(),
                    data=d._table.collect_to_data())
        return QDialog.Rejected

    dlg.fn = inspect
    actions(sel)[EDIT].trigger()
    assert seen["title"] == f"Edit {p.name}"
    assert seen["btn"] == "Save"
    assert seen["name"] == p.name
    assert seen["year"] == p.year
    assert seen["remark"] == "my remark"
    assert seen["shared"] is True
    assert seen["data"] == p.data


def test_edit_saves_in_place(sel, dlg, mgr):
    p = make_custom(sel, dlg)
    count = len(mgr.all_listed())
    sel.signals["saved"].clear()
    new_data = tweak(p.data)
    dlg.fn = save_with(name="Renamed profile", data=new_data, remark="r2")
    actions(sel)[EDIT].trigger()
    assert len(mgr.all_listed()) == count
    q = mgr.get_by_id(p.id)
    assert q is not None
    assert q.name == "Renamed profile"
    assert q.remark == "r2"
    assert q.data == new_data
    assert sel.current_profile().id == p.id
    assert [s.id for s in sel.signals["saved"]] == [p.id]


def test_edit_ticked_saves_to_library(sel, dlg, boxes):
    p = make_custom(sel, dlg, shared=False)
    boxes.saved.clear()
    dlg.fn = save_with(shared=True)
    actions(sel)[EDIT].trigger()
    assert [s.id for s in boxes.saved] == [p.id]
    assert boxes.deleted == []


def test_edit_unticked_removes_from_library(sel, dlg, boxes):
    p = make_custom(sel, dlg)          # shared by default
    boxes.saved.clear()
    dlg.fn = save_with(shared=False)
    actions(sel)[EDIT].trigger()
    assert boxes.deleted == [p.id]
    assert boxes.saved == []


# ---------------------------------------------------------------- 10. names
def test_duplicate_empty_name_rejected(sel, dlg, mgr, boxes):
    before = len(mgr.all_listed())
    results = []

    def fn(d):
        d._name.setText("   ")
        r = save(d)
        results.append(r)
        return r

    dlg.fn = fn
    actions(sel)[DUP].trigger()
    assert len(boxes.warning) == 1
    assert results == [0] or results[0] != QDialog.Accepted
    assert len(mgr.all_listed()) == before
    assert sel.signals["saved"] == [] and boxes.saved == []


@pytest.mark.parametrize("mangle", [str.upper, lambda s: f"  {s}  "])
def test_duplicate_name_clash_with_builtin_rejected(sel, dlg, mgr, boxes, mangle):
    src = sel.current_profile()
    before = len(mgr.all_listed())
    results = []

    def fn(d):
        d._name.setText(mangle(src.name))
        r = save(d)
        results.append(r)
        return r

    dlg.fn = fn
    actions(sel)[DUP].trigger()
    assert len(boxes.warning) == 1
    assert results[0] != QDialog.Accepted
    assert len(mgr.all_listed()) == before
    assert sel.signals["saved"] == [] and boxes.saved == []


def test_edit_name_clash_with_other_profile_rejected(sel, dlg, mgr, boxes):
    a = make_custom(sel, dlg, name="Alpha")
    b = make_custom(sel, dlg, name="Beta")
    assert sel.current_profile().id == b.id
    sel.signals["saved"].clear()
    boxes.saved.clear()
    dlg.fn = save_with(name=" alpha ")
    actions(sel)[EDIT].trigger()
    assert len(boxes.warning) == 1
    assert mgr.get_by_id(b.id).name == "Beta"
    assert mgr.get_by_id(a.id).name == "Alpha"
    assert sel.signals["saved"] == [] and boxes.saved == []


def test_edit_keeping_own_name_allowed(sel, dlg, mgr, boxes):
    p = make_custom(sel, dlg, name="Gamma")
    sel.signals["saved"].clear()
    dlg.fn = save_with(name="Gamma", remark="kept name")
    actions(sel)[EDIT].trigger()
    assert boxes.warning == []
    assert mgr.get_by_id(p.id).remark == "kept name"
    assert [s.id for s in sel.signals["saved"]] == [p.id]


# ---------------------------------------------------------------- 11. delete
def test_delete_asks_and_no_does_nothing(sel, dlg, mgr, boxes):
    p = make_custom(sel, dlg)
    count = len(mgr.all_listed())
    boxes.question_answer = QMessageBox.No
    actions(sel)[DEL].trigger()
    assert len(boxes.question) == 1
    assert len(mgr.all_listed()) == count
    assert mgr.get_by_id(p.id) is not None
    assert sel.current_profile().id == p.id
    assert sel.signals["deleted"] == []
    assert boxes.deleted == []


def test_delete_yes_removes_profile(sel, dlg, mgr, boxes):
    first = mgr.all_listed()[0]
    p = make_custom(sel, dlg)
    count = len(mgr.all_listed())
    boxes.question_answer = QMessageBox.Yes
    actions(sel)[DEL].trigger()
    assert len(boxes.question) == 1
    assert len(mgr.all_listed()) == count - 1
    assert mgr.get_by_id(p.id) is None
    assert sel.signals["deleted"] == [p.id]
    assert sel.current_profile().id == first.id
    assert enabled(sel) == (True, False, False)


def test_delete_shared_removes_from_library(sel, dlg, boxes):
    p = make_custom(sel, dlg)          # shared by default
    boxes.question_answer = QMessageBox.Yes
    actions(sel)[DEL].trigger()
    assert boxes.deleted == [p.id]


def test_delete_builtin_not_possible(sel, mgr, boxes):
    src = sel.current_profile()
    assert not actions(sel)[DEL].isEnabled()
    boxes.question_answer = QMessageBox.Yes
    actions(sel)[DEL].trigger()       # disabled action: trigger is a no-op
    assert mgr.get_by_id(src.id) is not None
    assert sel.signals["deleted"] == []
