"""Black-box tests for Equipment validation in machinery_emissions (spec-only)."""
import copy
import math

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

import three_ps_lcca_gui.gui.components.carbon_emission.widgets.machinery_emissions as m

APP = QApplication.instance() or QApplication([])

SOLAR = "Electricity (Solar/Renewable)"
GRID = "Electricity (Grid)"


def row(**kw):
    r = {"name": "Excavator", "source": "Diesel", "rate": 10.0, "hrs": 8.0,
         "days": 30, "ef": 2.69}
    r.update(kw)
    return r


def errors(res):
    return [p for p in res if p[0] == "error"]


def fields(res, level=None):
    return [p[1] for p in res if level is None or p[0] == level]


class Calls:
    def __init__(self):
        self.critical = []
        self.warning = []
        self.question = []
        self.warning_answer = QMessageBox.No
        self.question_answer = QMessageBox.No


@pytest.fixture(autouse=True)
def boxes(monkeypatch):
    c = Calls()

    def crit(*a, **k):
        c.critical.append(a)
        return QMessageBox.Ok

    def warn(*a, **k):
        c.warning.append(a)
        return c.warning_answer

    def ques(*a, **k):
        c.question.append(a)
        return c.question_answer

    monkeypatch.setattr(m.QMessageBox, "critical", staticmethod(crit))
    monkeypatch.setattr(m.QMessageBox, "warning", staticmethod(warn))
    monkeypatch.setattr(m.QMessageBox, "question", staticmethod(ques))
    monkeypatch.setattr(m.QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.Ok))
    return c


@pytest.fixture
def bridge(monkeypatch):
    data = {}
    monkeypatch.setattr(m, "get_bridge_data", lambda *a, **k: data)
    return data


# ---------------------------------------------------------------- constants
def test_constants():
    assert m.ENERGY_SOURCES == ["Diesel", GRID, SOLAR, "Other"]
    assert m.EF_DEFAULTS == {"Diesel": 2.69, GRID: 0.71, SOLAR: 0.0, "Other": 0.0}
    assert m.NAME_MAX_LEN == 100


# ---------------------------------------------------------------- valid rows
@pytest.mark.parametrize("src", ["Diesel", GRID])
def test_valid_default_rows(src):
    assert m.check_equipment(row(source=src, ef=m.EF_DEFAULTS[src]), [], None) == []


def test_valid_solar_zero_ef():
    assert m.check_equipment(row(source=SOLAR, ef=0.0), [], None) == []


def test_other_positive_ef_no_warning():
    assert m.check_equipment(row(source="Other", ef=5.0), [], None) == []


def test_returns_list_of_triples():
    res = m.check_equipment(row(name="", rate=0), [], None)
    assert isinstance(res, list)
    for p in res:
        assert isinstance(p, tuple) and len(p) == 3
        assert p[0] in ("error", "warning")
        assert p[1] in ("name", "source", "rate", "hrs", "days", "ef")
        assert isinstance(p[2], str) and p[2]


# ---------------------------------------------------------------- name
@pytest.mark.parametrize("name", ["", " ", "   ", "\t", "\n", " \t\n "])
def test_name_required(name):
    res = m.check_equipment(row(name=name), [], None)
    assert res == [("error", "name", "Equipment Name is required.")]


@pytest.mark.parametrize("n,ok", [(1, True), (99, True), (100, True), (101, False), (500, False)])
def test_name_length(n, ok):
    res = m.check_equipment(row(name="a" * n), [], None)
    assert (res == []) is ok
    if not ok:
        assert fields(res) == ["name"] and res[0][0] == "error"


def test_name_length_after_strip():
    assert m.check_equipment(row(name="  " + "a" * 100 + "   "), [], None) == []


@pytest.mark.parametrize("name", [
    "Excavator", "JCB 3DX", "Roller-10t", "Crane_2", "Mixer/Pump", "Ver. 2.0",
    "Pump (small)", "Bagger Ä", "Грейдер", "ショベル", "Ñandú", "123", "a-_/.()b",
    "Straße", "Ø ø", "élan",
])
def test_name_allowed(name):
    assert m.check_equipment(row(name=name), [], None) == []


@pytest.mark.parametrize("name", [
    "<b>x</b>", "a<b", "a>b", "a&b", "a;b", "a'b", 'a"b', "Robert'); DROP TABLE x;--",
    "a\x00b", "a\x1bb", "a%b", "a$b", "a#b", "a@b", "a!b",
    "a,b", "a:b", "a*b", "a+b", "a=b", "a\\b", "a[b]", "a{b}", "a|b", "a~b", "a`b",
    "a^b", "a?b", "{{7*7}}", "${x}", "<script>alert(1)</script>", "a\u200bb",
    "a\u202eb", "\U0001F600", "a\x7fb",
])
def test_name_rejected_chars(name):
    res = m.check_equipment(row(name=name), [], None)
    assert len(res) == 1, res
    assert res[0][:2] == ("error", "name")


@pytest.mark.parametrize("name", ["a\nb", "a\tb", "a\rb", "a\x0bb", "a\x0cb", "a\r\nb"])
def test_name_rejected_whitespace_control(name):
    res = m.check_equipment(row(name=name), [], None)
    assert len(res) == 1 and res[0][:2] == ("error", "name")


@pytest.mark.parametrize("name,others", [
    ("Excavator", ["Excavator"]),
    ("Excavator", ["excavator"]),
    ("excavator", ["EXCAVATOR"]),
    ("  Excavator ", ["Excavator"]),
    ("Excavator", ["  EXCAVATOR  "]),
    ("Excavator", ["Crane", "Roller", "excaVATOR"]),
])
def test_name_duplicate(name, others):
    res = m.check_equipment(row(name=name), others, None)
    assert len(res) == 1 and res[0][:2] == ("error", "name")
    assert name.strip().lower() in res[0][2].lower()


@pytest.mark.parametrize("others", [[], ["Crane"], ["Excavator2"], ["Excav ator"], ("Crane",)])
def test_name_not_duplicate(others):
    assert m.check_equipment(row(name="Excavator"), others, None) == []


def test_duplicate_huge_other_names():
    others = [f"Machine {i}" for i in range(20000)]
    assert m.check_equipment(row(), others, None) == []
    assert errors(m.check_equipment(row(name="machine 19999"), others, None))


def test_duplicate_casefold_strasse():
    # Expectation: case-insensitive via casefold -> "STRASSE" duplicates "straße".
    res = m.check_equipment(row(name="STRASSE"), ["straße"], None)
    assert fields(res) == ["name"]


def test_other_names_empty_entry_not_dup():
    assert m.check_equipment(row(), ["", "  "], None) == []


def test_only_one_name_problem_long_and_bad():
    res = m.check_equipment(row(name="<" * 101), ["<" * 101], None)
    assert fields(res) == ["name"]


def test_only_one_name_problem_bad_and_dup():
    res = m.check_equipment(row(name="a<b"), ["a<b"], None)
    assert fields(res) == ["name"]


# ---------------------------------------------------------------- source
@pytest.mark.parametrize("src", ["", "diesel", "DIESEL", "Petrol", " Diesel", None, "Electricity"])
def test_source_invalid(src):
    res = m.check_equipment(row(source=src, ef=5.0), [], None)
    assert ("error", "source") in [p[:2] for p in res]
    assert fields(res, "error")[0] == "source"


# ---------------------------------------------------------------- rate
@pytest.mark.parametrize("v", [0, 0.0, -0.0, -1, -1e-9, float("nan"), float("-inf")])
def test_rate_invalid(v):
    res = m.check_equipment(row(rate=v), [], None)
    assert fields(res, "error")[:1] == ["rate"]


@pytest.mark.parametrize("v", [1e-9, 0.001, 1, 1e6])
def test_rate_valid(v):
    assert m.check_equipment(row(rate=v), [], None) == []


# ---------------------------------------------------------------- hrs
@pytest.mark.parametrize("v", [0, -0.0, -1, 24.0001, 24 + 1e-9, 25, 1e9,
                               float("nan"), float("inf"), float("-inf")])
def test_hrs_invalid(v):
    res = m.check_equipment(row(hrs=v), [], None)
    assert fields(res, "error")[:1] == ["hrs"]


@pytest.mark.parametrize("v", [1e-9, 0.5, 1, 23.9999, 24, 24.0])
def test_hrs_valid(v):
    assert m.check_equipment(row(hrs=v), [], None) == []


# ---------------------------------------------------------------- days
@pytest.mark.parametrize("v", [0, -1, -100])
def test_days_min(v):
    res = m.check_equipment(row(days=v), [], None)
    assert ("error", "days", "No. of Days must be at least 1.") in res


@pytest.mark.parametrize("v", [1, 365, 100000])
def test_days_no_period_check(v):
    assert m.check_equipment(row(days=v), [], None) == []
    assert m.check_equipment(row(days=v), [], 0) == []


@pytest.mark.parametrize("days,maxd,ok", [(1, 1, True), (30, 30, True), (31, 30, False),
                                          (29, 30, True), (1000, 365, False)])
def test_days_max(days, maxd, ok):
    res = m.check_equipment(row(days=days), [], maxd)
    if ok:
        assert res == []
    else:
        assert len(res) == 1 and res[0][:2] == ("error", "days")
        assert str(days) in res[0][2] and str(maxd) in res[0][2]


def test_days_zero_with_max_reports_min():
    res = m.check_equipment(row(days=0), [], 30)
    assert res == [("error", "days", "No. of Days must be at least 1.")]


# ---------------------------------------------------------------- ef
@pytest.mark.parametrize("src", m.ENERGY_SOURCES)
def test_ef_negative(src):
    res = m.check_equipment(row(source=src, ef=-0.01), [], None)
    assert fields(res, "error") == ["ef"]


@pytest.mark.parametrize("src,bad", [("Diesel", True), (GRID, True), ("Other", True), (SOLAR, False)])
def test_ef_zero(src, bad):
    res = m.check_equipment(row(source=src, ef=0.0), [], None)
    assert (fields(res, "error") == ["ef"]) is bad
    if not bad:
        assert res == []


def test_ef_negative_zero_diesel_is_zero():
    res = m.check_equipment(row(ef=-0.0), [], None)
    assert fields(res, "error") == ["ef"]


def test_ef_nan_error():
    res = m.check_equipment(row(ef=float("nan")), [], None)
    assert errors(res)


@pytest.mark.parametrize("src,ef", [("Diesel", 2.7), ("Diesel", 1.0), (GRID, 0.72), (SOLAR, 0.1)])
def test_ef_non_default_warning(src, ef):
    res = m.check_equipment(row(source=src, ef=ef), [], None)
    assert len(res) == 1 and res[0][:2] == ("warning", "ef")


@pytest.mark.parametrize("ef", [0.001, 2.69, 100.0])
def test_ef_other_no_warning(ef):
    assert m.check_equipment(row(source="Other", ef=ef), [], None) == []


# ---------------------------------------------------------------- finite
@pytest.mark.parametrize("kw", [{"rate": float("inf")}, {"ef": float("inf")},
                                {"rate": 1e300, "ef": 1e300, "source": "Other"}])
def test_product_not_finite(kw):
    res = m.check_equipment(row(**kw), [], None)
    assert errors(res)


def test_finite_overflow_error_last():
    r = row(rate=1e300, ef=1e300, source="Other", days=10)
    res = m.check_equipment(r, [], None)
    assert len(res) == 1 and res[0][0] == "error"


# ---------------------------------------------------------------- ordering
def test_all_errors_order():
    r = {"name": "", "source": "Coal", "rate": 0, "hrs": 25, "days": 0, "ef": -1}
    res = m.check_equipment(r, [], 10)
    assert fields(res) == ["name", "source", "rate", "hrs", "days", "ef"]
    assert all(p[0] == "error" for p in res)


def test_order_with_warning_and_errors():
    r = row(name="x<y", hrs=30, ef=3.0)
    res = m.check_equipment(r, [], None)
    assert [p[:2] for p in res] == [("error", "name"), ("error", "hrs"), ("warning", "ef")]


def test_days_over_period_plus_others():
    res = m.check_equipment(row(rate=-1, days=31), [], 30)
    assert fields(res) == ["rate", "days"]


def test_no_mutation():
    r = row(name="  Exc  ", rate=float("nan"))
    others = ["exc", "B"]
    r0 = dict(r)
    o0 = list(others)
    m.check_equipment(r, others, 5)
    assert r.keys() == r0.keys()
    for k in r0:
        assert (r[k] == r0[k]) or (r[k] != r[k] and r0[k] != r0[k])
    assert others == o0


def test_tuple_other_names_and_generator():
    assert errors(m.check_equipment(row(), ("excavator",), None))


# ---------------------------------------------------------------- _construction_days
@pytest.mark.parametrize("data,exp", [
    ({"duration_construction_months": 12, "days_per_month": 30}, 360),
    ({"duration_construction_months": "12", "days_per_month": "30"}, 360),
    ({"duration_construction_months": 1.5, "days_per_month": 30}, 45),
    ({"duration_construction_months": "2.5", "days_per_month": 25}, 62),
    ({"duration_construction_months": 0.1, "days_per_month": 26}, 2),
    ({"duration_construction_months": 12}, None),
    ({"days_per_month": 30}, None),
    ({}, None),
    ({"duration_construction_months": None, "days_per_month": 30}, None),
    ({"duration_construction_months": 12, "days_per_month": None}, None),
    ({"duration_construction_months": "abc", "days_per_month": 30}, None),
    ({"duration_construction_months": "", "days_per_month": 30}, None),
    ({"duration_construction_months": 0, "days_per_month": 30}, None),
    ({"duration_construction_months": -12, "days_per_month": 30}, None),
    ({"duration_construction_months": -12, "days_per_month": -30}, None),
    ({"duration_construction_months": -1, "days_per_month": 30}, None),
    ({"duration_construction_months": 12, "days_per_month": "x"}, None),
    ({"duration_construction_months": "1e1", "days_per_month": "3"}, 30),
    ({"duration_construction_months": 0.001, "days_per_month": 30}, 0),  # product 0.03 > 0 -> int() == 0 per spec
    ({"duration_construction_months": 12, "days_per_month": 0}, None),
])
def test_construction_days(monkeypatch, data, exp):
    monkeypatch.setattr(m, "get_bridge_data", lambda *a, **k: data)
    got = m._construction_days()
    assert got == exp
    if exp is not None:
        assert type(got) is int


# ---------------------------------------------------------------- _clean_row
def test_clean_row_empty():
    r = m._clean_row({})
    assert r == {"name": "", "source": "Diesel", "rate": 0.0, "hrs": 0.0, "days": 0, "ef": 2.69}
    assert type(r["rate"]) is float and type(r["hrs"]) is float
    assert type(r["days"]) is int and type(r["ef"]) is float and type(r["name"]) is str


def test_clean_row_none_numerics():
    r = m._clean_row({"name": "X", "source": GRID, "rate": None, "hrs": None, "days": None, "ef": None})
    assert r["rate"] == 0.0 and r["hrs"] == 0.0 and r["days"] == 0
    assert type(r["days"]) is int and type(r["ef"]) is float


@pytest.mark.parametrize("src", m.ENERGY_SOURCES)
def test_clean_row_missing_ef_defaults(src):
    assert m._clean_row({"source": src})["ef"] == m.EF_DEFAULTS[src]


def test_clean_row_empty_source():
    assert m._clean_row({"source": ""})["source"] == "Diesel"


def test_clean_row_types_from_strings():
    r = m._clean_row({"name": "A", "source": "Diesel", "rate": "5", "hrs": "8", "days": "3", "ef": "2.69"})
    assert r == {"name": "A", "source": "Diesel", "rate": 5.0, "hrs": 8.0, "days": 3, "ef": 2.69}
    assert type(r["days"]) is int


def test_clean_row_float_days_int():
    r = m._clean_row(row(days=5.0))
    assert r["days"] == 5 and type(r["days"]) is int


def test_clean_row_no_mutation():
    d = {"name": "A"}
    m._clean_row(d)
    assert d == {"name": "A"}


# ---------------------------------------------------------------- dialog
def make_dlg(bridge_data=None, r=None, others=(), monkeypatch=None):
    d = m._EquipmentDialog(r or row(), "Edit Equipment", "Save", other_names=others)
    return d


@pytest.fixture
def dlg(bridge):
    d = m._EquipmentDialog(row(), "Edit Equipment", "Save", other_names=["Crane"])
    yield d
    d.hide()
    d.deleteLater()


def test_dialog_widgets(dlg):
    assert dlg._name.maxLength() == 100
    assert [dlg._source.itemText(i) for i in range(dlg._source.count())] == m.ENERGY_SOURCES
    assert dlg.values() == row()


def test_dialog_buttons(dlg):
    btns = {b.text().replace("&", ""): b for b in dlg.findChildren(QPushButton)}
    assert "Save" in btns and "Cancel" in btns
    ok, cancel = btns["Save"], btns["Cancel"]
    assert ok.isDefault()
    dlg.show()
    APP.processEvents()
    assert cancel.mapToGlobal(cancel.rect().topLeft()).x() < ok.mapToGlobal(ok.rect().topLeft()).x()


def test_dialog_values_strips_name(dlg):
    dlg._name.setText("   Loader  ")
    assert dlg.values()["name"] == "Loader"


@pytest.mark.parametrize("src", m.ENERGY_SOURCES)
def test_dialog_source_change_sets_ef(dlg, src):
    dlg._ef.setValue(9.99)
    other = "Other" if src != "Other" else "Diesel"
    dlg._source.setCurrentText(other)
    dlg._ef.setValue(9.99)
    dlg._source.setCurrentText(src)
    assert dlg._ef.value() == pytest.approx(m.EF_DEFAULTS[src])


def test_dialog_valid_accepts(dlg, boxes):
    dlg.validate_and_accept()
    assert dlg.result() == QDialog.Accepted
    assert boxes.critical == [] and boxes.warning == []


@pytest.mark.parametrize("field,setter", [
    ("name", lambda d: d._name.setText("")),
    ("name", lambda d: d._name.setText("crane")),
    ("name", lambda d: d._name.setText("a<b")),
    ("rate", lambda d: d._rate.setValue(0)),
    ("hrs", lambda d: d._hrs.setValue(0)),
    ("days", lambda d: d._days.setValue(0)),
    ("ef", lambda d: d._ef.setValue(0)),
])
def test_dialog_error_focus(dlg, boxes, field, setter):
    setter(dlg)
    dlg.show()
    APP.processEvents()
    dlg.validate_and_accept()
    APP.processEvents()
    assert len(boxes.critical) == 1
    assert dlg.result() != QDialog.Accepted
    assert dlg.isVisible()
    w = getattr(dlg, "_" + field)
    fw = APP.focusWidget()
    assert fw is w or (fw is not None and w.isAncestorOf(fw))


def test_dialog_days_over_period(bridge, boxes):
    bridge.update({"duration_construction_months": 1, "days_per_month": 20})
    d = m._EquipmentDialog(row(days=21), "Edit", "Save")
    d.show(); APP.processEvents()
    d.validate_and_accept(); APP.processEvents()
    assert len(boxes.critical) == 1 and d.result() != QDialog.Accepted
    fw = APP.focusWidget()
    assert fw is d._days or d._days.isAncestorOf(fw)
    d._days.setValue(20)
    d.validate_and_accept()
    assert d.result() == QDialog.Accepted
    d.hide()


def test_dialog_warning_no_keeps_open(dlg, boxes):
    dlg._ef.setValue(3.0)
    dlg.show(); APP.processEvents()
    boxes.warning_answer = QMessageBox.No
    dlg.validate_and_accept()
    assert len(boxes.warning) == 1 and boxes.critical == []
    assert dlg.result() != QDialog.Accepted and dlg.isVisible()


def test_dialog_warning_yes_accepts(dlg, boxes):
    dlg._ef.setValue(3.0)
    boxes.warning_answer = QMessageBox.Yes
    dlg.validate_and_accept()
    assert len(boxes.warning) == 1
    assert dlg.result() == QDialog.Accepted


def test_dialog_error_beats_warning(dlg, boxes):
    dlg._ef.setValue(3.0)
    dlg._rate.setValue(0)
    dlg.validate_and_accept()
    assert len(boxes.critical) == 1 and boxes.warning == []
    assert dlg.result() != QDialog.Accepted


def test_dialog_reject_unchanged(dlg, boxes):
    dlg.show(); APP.processEvents()
    dlg.reject()
    assert boxes.question == []
    assert dlg.result() == QDialog.Rejected and not dlg.isVisible()


def test_dialog_reject_changed_no(dlg, boxes):
    dlg.show(); APP.processEvents()
    dlg._name.setText("Loader")
    boxes.question_answer = QMessageBox.No
    dlg.reject()
    assert len(boxes.question) == 1
    assert dlg.isVisible()


def test_dialog_reject_changed_yes(dlg, boxes):
    dlg.show(); APP.processEvents()
    dlg._hrs.setValue(5)
    boxes.question_answer = QMessageBox.Yes
    dlg.reject()
    assert len(boxes.question) == 1
    assert dlg.result() == QDialog.Rejected and not dlg.isVisible()


def test_dialog_reject_changed_back_no_ask(dlg, boxes):
    dlg.show(); APP.processEvents()
    dlg._name.setText("Loader")
    dlg._name.setText("Excavator")
    dlg.reject()
    assert boxes.question == []


def test_dialog_new_name_injection_rejected(bridge, boxes):
    d = m._EquipmentDialog(row(name="<b>x</b>"), "Add", "Add")
    d.validate_and_accept()
    assert len(boxes.critical) == 1 and d.result() != QDialog.Accepted


def test_dialog_name_max_len_truncates(dlg):
    dlg._name.setText("a" * 150)
    assert len(dlg.values()["name"]) == 100


# ---------------------------------------------------------------- page
@pytest.fixture
def page(bridge):
    p = m.MachineryEmissions(controller=None)
    yield p
    p.deleteLater()


def test_page_defaults(page):
    rows = page._detailed_table.collect()["rows"]
    assert len(rows) == 20


def test_page_defaults_validate_clean(page):
    res = page.validate()
    assert res["errors"] == []


def test_page_load_collect_roundtrip(page):
    rows = [row(name="A"), row(name="B", source=GRID, ef=0.71, rate=2.5, hrs=24, days=1),
            row(name="C", source=SOLAR, ef=0.0)]
    page._detailed_table.load({"rows": copy.deepcopy(rows)})
    got = page._detailed_table.collect()["rows"]
    assert len(got) == 3
    for g, r in zip(got, rows):
        for k in r:
            assert g[k] == pytest.approx(r[k]) if isinstance(r[k], float) else g[k] == r[k]


def test_page_total(page):
    rows = [row(name="A", rate=2, hrs=3, days=4, ef=2.69),
            row(name="B", source=GRID, rate=1.5, hrs=10, days=7, ef=0.71)]
    page._detailed_table.load({"rows": rows})
    assert page._detailed_table.get_total() == pytest.approx(2 * 3 * 4 * 2.69 + 1.5 * 10 * 7 * 0.71)


def test_page_total_empty(page):
    page._detailed_table.load({"rows": []})
    assert page._detailed_table.get_total() == pytest.approx(0)
    assert page._detailed_table.collect()["rows"] == []


def test_page_delete_row(page):
    page._detailed_table.load({"rows": [row(name="A"), row(name="B"), row(name="C")]})
    page._detailed_table.delete_row(1)
    assert [r["name"] for r in page._detailed_table.collect()["rows"]] == ["A", "C"]


def test_page_load_defaults(page):
    page._detailed_table.load({"rows": [row(name="A")]})
    page._detailed_table.load_defaults()
    assert len(page._detailed_table.collect()["rows"]) == 20


def test_page_freeze_no_crash(page):
    page._detailed_table.freeze(True)
    page._detailed_table.freeze(False)


def test_page_validate_bad_rows(page):
    page._detailed_table.load({"rows": [
        row(name="Good"),
        row(name="", rate=0),
        row(name="Bad", hrs=30),
    ]})
    res = page.validate()
    assert res["errors"] == []
    w = res["warnings"]
    assert 'Equipment "2": Equipment Name is required.' in w
    bad = [x for x in w if x.startswith('Equipment "Bad": ')]
    assert len(bad) == 1
    assert not any('"Good"' in x for x in w)


def test_page_validate_duplicates(page):
    page._detailed_table.load({"rows": [row(name="Dup"), row(name="dup"), row(name="X")]})
    w = page.validate()["warnings"]
    assert sum(1 for x in w if x.lower().startswith('equipment "dup"')) == 2
    assert not any(x.startswith('Equipment "X"') for x in w)


def test_page_validate_one_line_per_row(page):
    page._detailed_table.load({"rows": [{"name": "", "source": "Diesel", "rate": 0, "hrs": 0, "days": 0, "ef": 0}]})
    w = [x for x in page.validate()["warnings"] if x.startswith("Equipment ")]
    assert w == ['Equipment "1": Equipment Name is required.']


def test_page_validate_warning_only_row_not_listed(page):
    page._detailed_table.load({"rows": [row(name="A", ef=3.0)]})
    assert not any(x.startswith('Equipment "A"') for x in page.validate()["warnings"])


def test_page_validate_after_bridge_change(page, bridge):
    page._detailed_table.load({"rows": [row(name="A", days=100), row(name="B", days=10)]})
    assert not any(x.startswith('Equipment "') for x in page.validate()["warnings"])
    bridge.update({"duration_construction_months": 2, "days_per_month": 25})
    w = page.validate()["warnings"]
    a = [x for x in w if x.startswith('Equipment "A": ')]
    assert len(a) == 1 and "100" in a[0] and "50" in a[0]
    assert not any(x.startswith('Equipment "B"') for x in w)
    bridge.clear()
    assert not any(x.startswith('Equipment "') for x in page.validate()["warnings"])


def test_rate_inf_only_finite_error():
    res = m.check_equipment(row(rate=float("inf")), [], None)
    assert len(res) == 1 and res[0][0] == "error" and res[0][1] in m.ENERGY_SOURCES + ["rate", "hrs", "days", "ef"]


def test_finite_after_warning():
    res = m.check_equipment(row(rate=float("inf"), ef=3.0), [], None)
    assert [p[0] for p in res] == ["warning", "error"]


def test_name_error_does_not_hide_other_fields():
    res = m.check_equipment(row(name="", source="X", ef=1.0), [], None)
    assert fields(res)[:2] == ["name", "source"]


def test_epsilon_ef_diesel_warns_not_errors():
    res = m.check_equipment(row(ef=1e-12), [], None)
    assert [p[:2] for p in res] == [("warning", "ef")]


def test_dialog_source_change_does_not_touch_others(dlg):
    before = dlg.values()
    dlg._source.setCurrentText(GRID)
    after = dlg.values()
    for k in ("name", "rate", "hrs", "days"):
        assert after[k] == before[k]
    assert after["source"] == GRID and after["ef"] == pytest.approx(0.71)


def test_page_validate_uses_current_rows_after_delete(page):
    page._detailed_table.load({"rows": [row(name="Dup"), row(name="Dup")]})
    assert any(x.startswith('Equipment "Dup"') for x in page.validate()["warnings"])
    page._detailed_table.delete_row(0)
    assert not any(x.startswith('Equipment "Dup"') for x in page.validate()["warnings"])


def test_page_load_none_values_cleaned(page):
    page._detailed_table.load({"rows": [{"name": "A", "source": "Diesel", "rate": None, "hrs": None, "days": None}]})
    got = page._detailed_table.collect()["rows"]
    assert len(got) == 1
    assert got[0]["rate"] == 0 and got[0]["days"] == 0 and got[0]["ef"] == pytest.approx(2.69)
    w = page.validate()["warnings"]
    assert sum(1 for x in w if x.startswith('Equipment "A": ')) == 1
