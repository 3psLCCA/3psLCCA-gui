"""Black-box tests for the "percent or value" input (per_or_val field type).

The widget lets the user enter an amount either as a percentage of some base
(e.g. initial construction cost) or as an absolute value. It stores
{"type": "percent"|"value", "value": float|None}; resolve_per_or_val gives
its % and absolute amount.
"""
import math

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QFormLayout  # noqa: E402

from three_ps_lcca_gui.gui.components.utils.form_builder.percent_or_value import (  # noqa: E402
    PERCENT,
    VALUE,
    PercentOrValueInput,
    resolve_per_or_val,
)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def w(app):
    widget = PercentOrValueInput(unit="INR", percent_of="initial_construction_cost")
    yield widget
    widget.deleteLater()


def _set_mode(widget, mode):
    """Pick a mode in the dropdown the way a user would (by index)."""
    for i in range(widget.mode.count()):
        widget.mode.setCurrentIndex(i)
        if widget.current_mode() == mode:
            return
    raise AssertionError(f"mode {mode!r} not found in dropdown")


def _type(widget, text):
    widget.line.setFocus()
    widget.line.clear()
    QTest.keyClicks(widget.line, text)


# ── constants ───────────────────────────────────────────────────────────────

def test_constants():
    assert PERCENT == "percent"
    assert VALUE == "value"


# ── defaults / basic round trips ───────────────────────────────────────────

def test_default_is_blank_percent(w):
    assert w.get_value() == {"type": PERCENT, "value": None}
    assert w.current_mode() == PERCENT
    assert w.number() is None


def test_parts_returns_mode_and_line(w):
    mode, line = w.parts()
    assert mode is w.mode
    assert line is w.line


def test_mode_dropdown_has_two_entries(w):
    assert w.mode.count() == 2


@pytest.mark.parametrize("data", [
    {"type": PERCENT, "value": 5.0},
    {"type": PERCENT, "value": 0.0},
    {"type": PERCENT, "value": 100.0},
    {"type": PERCENT, "value": 12.5},
    {"type": VALUE, "value": 0.0},
    {"type": VALUE, "value": 1234567.89},
    {"type": VALUE, "value": 42.0},
    {"type": PERCENT, "value": None},
    {"type": VALUE, "value": None},
])
def test_round_trip(w, data):
    w.set_value(data)
    assert w.get_value() == data
    assert w.current_mode() == data["type"]


def test_set_value_int_comes_back_as_float(w):
    w.set_value({"type": VALUE, "value": 7})
    out = w.get_value()
    assert out == {"type": VALUE, "value": 7.0}
    assert isinstance(out["value"], float)


def test_set_value_numeric_string_is_accepted_or_blank(w):
    # Either interpretation is defensible; it must not crash or yield a str.
    w.set_value({"type": VALUE, "value": "12.5"})
    v = w.get_value()["value"]
    assert v is None or (isinstance(v, float) and v == 12.5)


def test_set_value_switching_mode_keeps_loaded_number(w):
    """set_value must not be undone by the "switching mode clears the number" rule."""
    w.set_value({"type": PERCENT, "value": 10.0})
    w.set_value({"type": VALUE, "value": 500.0})
    assert w.get_value() == {"type": VALUE, "value": 500.0}
    w.set_value({"type": PERCENT, "value": 3.0})
    assert w.get_value() == {"type": PERCENT, "value": 3.0}


def test_set_value_same_mode_replaces_number(w):
    w.set_value({"type": VALUE, "value": 1.0})
    w.set_value({"type": VALUE, "value": 2.0})
    assert w.get_value() == {"type": VALUE, "value": 2.0}


def test_set_value_blank_after_value_clears(w):
    w.set_value({"type": VALUE, "value": 99.0})
    w.set_value({"type": VALUE, "value": None})
    assert w.get_value() == {"type": VALUE, "value": None}
    assert w.line.text() == ""


def test_decimals_round_trip_does_not_lose_precision_badly(w):
    w.set_value({"type": VALUE, "value": 0.1})
    assert w.get_value()["value"] == pytest.approx(0.1)


# ── garbage input ───────────────────────────────────────────────────────────

BLANK_PCT = {"type": PERCENT, "value": None}


@pytest.mark.parametrize("garbage", [
    None,
    {},
    "percent",
    "",
    42,
    3.5,
    [PERCENT, 5],
    {"type": "bogus", "value": 5},
    {"type": None, "value": 5},
    {"value": 5},
    {"type": PERCENT, "value": "abc"},
    {"type": VALUE, "value": "abc"},
    {"type": VALUE, "value": [1]},
    {"type": VALUE, "value": {"x": 1}},
    {"type": VALUE, "value": float("nan")},
    {"type": VALUE, "value": float("inf")},
    {"type": PERCENT, "value": float("-inf")},
])
def test_garbage_loads_as_blank_percent(w, garbage):
    # start from a non-default state so "blank percent" really is a reset
    w.set_value({"type": VALUE, "value": 77.0})
    w.set_value(garbage)
    assert w.get_value() == BLANK_PCT


def test_bool_value_is_not_treated_as_number(w):
    w.set_value({"type": VALUE, "value": True})
    out = w.get_value()
    # True is an int subclass; storing 1.0 silently would be surprising.
    assert out["value"] is None


def test_garbage_type_with_valid_number(w):
    """Unknown type -> blank percent, not 'percent with the number kept'."""
    w.set_value({"type": "VALUE", "value": 10})
    assert w.get_value()["type"] in (PERCENT, VALUE)
    # Must at least not crash; if the type isn't recognised it should be blank.
    if w.get_value()["type"] == PERCENT:
        assert w.get_value()["value"] is None


# ── mode switching ──────────────────────────────────────────────────────────

def test_switching_mode_clears_number(w):
    w.set_value({"type": PERCENT, "value": 10.0})
    _set_mode(w, VALUE)
    assert w.get_value() == {"type": VALUE, "value": None}
    w.line.setText("500")
    _set_mode(w, PERCENT)
    assert w.get_value() == {"type": PERCENT, "value": None}


def test_placeholder_differs_by_mode(w):
    _set_mode(w, PERCENT)
    p_pct = w.line.placeholderText()
    _set_mode(w, VALUE)
    p_val = w.line.placeholderText()
    assert p_pct and p_val
    assert p_pct != p_val


def test_placeholder_updated_by_set_value(w):
    _set_mode(w, PERCENT)
    p_pct = w.line.placeholderText()
    w.set_value({"type": VALUE, "value": 1.0})
    assert w.line.placeholderText() != p_pct
    w.set_value({"type": PERCENT, "value": 1.0})
    assert w.line.placeholderText() == p_pct


def test_value_placeholder_mentions_unit(app):
    widget = PercentOrValueInput(unit="INR", percent_of="cost")
    _set_mode(widget, VALUE)
    assert "INR" in widget.line.placeholderText()


# ── typing / validator ──────────────────────────────────────────────────────

def test_typing_number(w):
    _set_mode(w, VALUE)
    _type(w, "1500.25")
    assert w.get_value() == {"type": VALUE, "value": 1500.25}


def test_typing_letters_rejected(w):
    _set_mode(w, VALUE)
    _type(w, "abc")
    assert w.line.text() == ""
    assert w.get_value()["value"] is None


def test_typing_more_decimals_than_allowed(app):
    widget = PercentOrValueInput(decimals=2)
    _set_mode(widget, VALUE)
    _type(widget, "1.23456")
    v = widget.get_value()["value"]
    # Either the validator blocks extra digits, or they're kept; never garbage.
    assert v is not None
    assert v == pytest.approx(1.23, abs=1e-9) or v == pytest.approx(1.23456)


def test_typing_lone_minus_or_dot_is_blank_not_crash(w):
    _set_mode(w, VALUE)
    for txt in ["-", ".", "-.", "+"]:
        w.line.setText(txt)
        assert w.get_value()["value"] is None, txt
        assert w.number() is None, txt


def test_set_text_garbage_directly_gives_none(w):
    # bypassing the validator (paste/setText) must not crash get_value
    _set_mode(w, VALUE)
    w.line.setText("12abc")
    assert w.get_value()["value"] in (None,)


def test_scientific_notation(w):
    _set_mode(w, VALUE)
    _type(w, "1e5")
    v = w.get_value()["value"]
    # If the validator lets "1e5" through, it must read as 100000.
    if w.line.text() == "1e5":
        assert v == 100000.0
    else:
        assert v is None or isinstance(v, float)


def test_whitespace_text(w):
    _set_mode(w, VALUE)
    w.line.setText("  12  ")
    v = w.get_value()["value"]
    assert v is None or v == 12.0


def test_number_matches_get_value(w):
    w.set_value({"type": PERCENT, "value": 7.5})
    assert w.number() == 7.5
    w.set_value({"type": VALUE, "value": None})
    assert w.number() is None


# ── changed signal ─────────────────────────────────────────────────────────

def test_changed_emitted_on_typing(w):
    hits = []
    w.changed.connect(lambda *a: hits.append(a))
    _set_mode(w, VALUE)
    hits.clear()
    _type(w, "5")
    assert hits


def test_changed_emitted_on_mode_switch(w):
    hits = []
    w.changed.connect(lambda *a: hits.append(a))
    _set_mode(w, PERCENT)
    hits.clear()
    _set_mode(w, VALUE)
    assert hits


# ── range_error ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data", [
    {"type": PERCENT, "value": 0.0},
    {"type": PERCENT, "value": 50.0},
    {"type": PERCENT, "value": 100.0},
    {"type": VALUE, "value": 0.0},
    {"type": VALUE, "value": 1e12},
    {"type": PERCENT, "value": None},
    {"type": VALUE, "value": None},
])
def test_range_ok(w, data):
    w.set_value(data)
    assert w.range_error("Contingency") is None


@pytest.mark.parametrize("data", [
    {"type": PERCENT, "value": 100.01},
    {"type": PERCENT, "value": 150.0},
    {"type": PERCENT, "value": -1.0},
    {"type": VALUE, "value": -0.01},
    {"type": VALUE, "value": -1000.0},
])
def test_range_errors(w, data):
    w.set_value(data)
    msg = w.range_error("Contingency")
    assert isinstance(msg, str) and msg
    assert "Contingency" in msg


def test_range_error_value_max(app):
    widget = PercentOrValueInput(min_val=10, max_val=20)
    widget.set_value({"type": VALUE, "value": 25.0})
    assert widget.range_error("X")
    widget.set_value({"type": VALUE, "value": 5.0})
    assert widget.range_error("X")
    widget.set_value({"type": VALUE, "value": 15.0})
    assert widget.range_error("X") is None
    widget.set_value({"type": VALUE, "value": 20.0})
    assert widget.range_error("X") is None


def test_range_error_custom_pct_bounds(app):
    widget = PercentOrValueInput(min_pct=5, max_pct=10)
    widget.set_value({"type": PERCENT, "value": 4.99})
    assert widget.range_error("X")
    widget.set_value({"type": PERCENT, "value": 10.5})
    assert widget.range_error("X")
    widget.set_value({"type": PERCENT, "value": 7.0})
    assert widget.range_error("X") is None


def test_percent_bounds_dont_apply_to_value(app):
    widget = PercentOrValueInput(max_pct=100, max_val=None)
    widget.set_value({"type": VALUE, "value": 5000.0})
    assert widget.range_error("X") is None


def test_value_bounds_dont_apply_to_percent(app):
    widget = PercentOrValueInput(min_val=1000, max_val=2000)
    widget.set_value({"type": PERCENT, "value": 50.0})
    assert widget.range_error("X") is None


def test_typed_out_of_range_percent_is_flagged_or_blocked(w):
    _set_mode(w, PERCENT)
    _type(w, "250")
    v = w.get_value()["value"]
    if v is not None and v > 100:
        assert w.range_error("X")


def test_typed_negative_is_flagged_or_blocked(w):
    _set_mode(w, VALUE)
    _type(w, "-50")
    v = w.get_value()["value"]
    if v is not None and v < 0:
        assert w.range_error("X")


def test_value_mode_allows_typing_above_100(w):
    """The percent cap (100) must not leak into value mode's validator."""
    _set_mode(w, PERCENT)
    _set_mode(w, VALUE)
    _type(w, "250000")
    assert w.get_value() == {"type": VALUE, "value": 250000.0}


def test_value_mode_after_set_value_allows_large(w):
    w.set_value({"type": PERCENT, "value": 5.0})
    w.set_value({"type": VALUE, "value": None})
    _type(w, "99999")
    assert w.get_value()["value"] == 99999.0


# ── read only ───────────────────────────────────────────────────────────────

def test_set_read_only(w):
    w.set_value({"type": VALUE, "value": 3.0})
    w.setReadOnly(True)
    assert w.line.isReadOnly()
    assert not w.mode.isEnabled()
    # value preserved
    assert w.get_value() == {"type": VALUE, "value": 3.0}
    w.setReadOnly(False)
    assert not w.line.isReadOnly()
    assert w.mode.isEnabled()


def test_read_only_blocks_typing(w):
    w.set_value({"type": VALUE, "value": 3.0})
    w.setReadOnly(True)
    _type_no_clear = QTest.keyClicks
    w.line.setFocus()
    _type_no_clear(w.line, "9")
    assert w.get_value() == {"type": VALUE, "value": 3.0}


def test_set_value_works_while_read_only(w):
    w.setReadOnly(True)
    w.set_value({"type": VALUE, "value": 8.0})
    assert w.get_value() == {"type": VALUE, "value": 8.0}


# ── resolve_per_or_val ──────────────────────────────────────────────────────

@pytest.mark.parametrize("data, base, expected", [
    ({"type": VALUE, "value": 500.0}, 10000, 500.0),
    ({"type": VALUE, "value": 500.0}, None, 500.0),
    ({"type": VALUE, "value": 0.0}, None, 0.0),
    ({"type": PERCENT, "value": 10.0}, 10000, 1000.0),
    ({"type": PERCENT, "value": 0.0}, 10000, 0.0),
    ({"type": PERCENT, "value": 100.0}, 250.0, 250.0),
    ({"type": PERCENT, "value": 12.5}, 80, 10.0),
    ({"type": PERCENT, "value": 10.0}, 0, 0.0),
    ({"type": VALUE, "value": 7}, None, 7.0),
])
def test_resolve(data, base, expected):
    assert resolve_per_or_val(data, base).amount == pytest.approx(expected)


@pytest.mark.parametrize("data, base, expected", [
    ({"type": PERCENT, "value": 12.5}, None, 12.5),
    ({"type": VALUE, "value": 500.0}, 10000, 5.0),
    ({"type": VALUE, "value": 500.0}, 0, None),
    ({"type": VALUE, "value": 500.0}, None, None),
])
def test_resolve_percent(data, base, expected):
    pct = resolve_per_or_val(data, base).percent
    assert pct == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize("data, base", [
    ({"type": PERCENT, "value": 10.0}, None),
    ({"type": PERCENT, "value": None}, 1000),
    ({"type": VALUE, "value": None}, 1000),
    (None, 1000),
    ({}, 1000),
    ("garbage", 1000),
    (5, 1000),
    ({"type": "bogus", "value": 10}, 1000),
    ({"value": 10}, 1000),
    ({"type": VALUE, "value": "abc"}, 1000),
    ({"type": PERCENT, "value": "abc"}, 1000),
    ({"type": PERCENT, "value": 10}, "abc"),
])
def test_resolve_returns_none(data, base):
    assert resolve_per_or_val(data, base).amount is None


def test_resolve_does_not_mutate_input():
    data = {"type": PERCENT, "value": 10.0}
    resolve_per_or_val(data, 100)
    assert data == {"type": PERCENT, "value": 10.0}


def test_resolve_numeric_string_base():
    r = resolve_per_or_val({"type": PERCENT, "value": 10}, "1000").amount
    assert r is None or r == pytest.approx(100.0)


def test_resolve_nan_value():
    r = resolve_per_or_val({"type": VALUE, "value": float("nan")}, None).amount
    assert r is None or not math.isnan(r), "NaN should resolve to None, not propagate"


def test_resolve_round_trips_widget_output(w):
    w.set_value({"type": PERCENT, "value": 5.0})
    assert resolve_per_or_val(w.get_value(), 2000).amount == pytest.approx(100.0)
    w.set_value({"type": VALUE, "value": 300.0})
    assert resolve_per_or_val(w.get_value(), 2000).amount == pytest.approx(300.0)


# ── form integration ────────────────────────────────────────────────────────

from three_ps_lcca_gui.gui.components.base_widget import BaseDataWidget  # noqa: E402
from three_ps_lcca_gui.gui.components.utils.form_builder.form_builder import build_form  # noqa: E402
from three_ps_lcca_gui.gui.components.utils.form_builder.form_definitions import FieldDef  # noqa: E402
from three_ps_lcca_gui.gui.components.utils.validation_helpers import (  # noqa: E402
    freeze_form,
    validate_form,
)


class _Form(BaseDataWidget):
    def __init__(self):
        super().__init__()
        self.form = QFormLayout(self)


def _fields(required=True, **kw):
    params = dict(unit="INR", percent_of="initial_construction_cost",
                  min_pct=0, max_pct=100, min_val=0, max_val=None)
    params.update(kw)
    return [FieldDef("cont", "Contingency", "", "per_or_val",
                     required=required, **params)]


@pytest.fixture
def form(app):
    fields = _fields()
    f = _Form()
    build_form(f, fields)
    yield f, fields
    f.deleteLater()


def test_form_builds_widget(form):
    f, _ = form
    assert isinstance(f.cont, PercentOrValueInput)


def test_form_get_data_dict_blank(form):
    f, _ = form
    d = f.get_data_dict()
    assert d["cont"] == {"type": PERCENT, "value": None}


@pytest.mark.parametrize("val", [
    {"type": PERCENT, "value": 5.0},
    {"type": VALUE, "value": 250000.0},
])
def test_form_load_then_get(form, val):
    f, _ = form
    f.load_data_dict({"cont": val})
    assert f.get_data_dict()["cont"] == val
    assert f.cont.get_value() == val


def test_form_load_missing_key_does_not_crash(form):
    f, _ = form
    f.load_data_dict({})
    assert f.get_data_dict()["cont"]["type"] in (PERCENT, VALUE)


@pytest.mark.parametrize("garbage", [None, "junk", 12, {"type": "x"}])
def test_form_load_garbage_is_blank_percent(form, garbage):
    f, _ = form
    f.load_data_dict({"cont": {"type": VALUE, "value": 9.0}})
    f.load_data_dict({"cont": garbage})
    assert f.get_data_dict()["cont"] == BLANK_PCT


def test_form_get_data_dict_is_independent_copy(form):
    f, _ = form
    f.load_data_dict({"cont": {"type": VALUE, "value": 1.0}})
    d = f.get_data_dict()
    d["cont"]["value"] = 999.0
    assert f.get_data_dict()["cont"]["value"] == 1.0


def _errs(fields, f):
    res = validate_form(fields, f)
    return res["errors"], res["warnings"]


def test_validate_required_blank_is_error(form):
    f, fields = form
    errs, _ = _errs(fields, f)
    assert errs
    assert any("Contingency" in str(e) for e in errs)


def test_validate_required_blank_value_mode_is_error(form):
    f, fields = form
    f.load_data_dict({"cont": {"type": VALUE, "value": None}})
    errs, _ = _errs(fields, f)
    assert errs


@pytest.mark.parametrize("val", [
    {"type": PERCENT, "value": 0.0},
    {"type": PERCENT, "value": 5.0},
    {"type": PERCENT, "value": 100.0},
    {"type": VALUE, "value": 0.0},
    {"type": VALUE, "value": 1e9},
])
def test_validate_ok(form, val):
    f, fields = form
    f.load_data_dict({"cont": val})
    errs, _ = _errs(fields, f)
    assert errs == []


@pytest.mark.parametrize("val", [
    {"type": PERCENT, "value": 101.0},
    {"type": PERCENT, "value": -1.0},
    {"type": VALUE, "value": -5.0},
])
def test_validate_out_of_range_is_error(form, val):
    f, fields = form
    f.load_data_dict({"cont": val})
    errs, _ = _errs(fields, f)
    assert errs


def test_validate_out_of_range_typed_text(form):
    """Text that bypasses the validator (setText) still gets range-checked."""
    f, fields = form
    _set_mode(f.cont, PERCENT)
    f.cont.line.setText("150")
    errs, _ = _errs(fields, f)
    assert errs


def test_validate_optional_blank_ok(app):
    fields = _fields(required=False)
    f = _Form()
    build_form(f, fields)
    errs, _ = _errs(fields, f)
    assert errs == []
    f.load_data_dict({"cont": {"type": PERCENT, "value": 200.0}})
    errs, _ = _errs(fields, f)
    assert errs, "optional field still range-checked when filled"


def test_validate_max_val(app):
    fields = _fields(max_val=1000)
    f = _Form()
    build_form(f, fields)
    f.load_data_dict({"cont": {"type": VALUE, "value": 1001.0}})
    errs, _ = _errs(fields, f)
    assert errs
    f.load_data_dict({"cont": {"type": VALUE, "value": 1000.0}})
    errs, _ = _errs(fields, f)
    assert errs == []


def test_freeze_form(form):
    f, fields = form
    f.load_data_dict({"cont": {"type": VALUE, "value": 10.0}})
    freeze_form(fields, f, True)
    assert f.cont.line.isReadOnly()
    assert not f.cont.mode.isEnabled()
    assert f.get_data_dict()["cont"] == {"type": VALUE, "value": 10.0}
    freeze_form(fields, f, False)
    assert not f.cont.line.isReadOnly()
    assert f.cont.mode.isEnabled()
    assert f.get_data_dict()["cont"] == {"type": VALUE, "value": 10.0}


def test_freeze_twice_then_unfreeze(form):
    f, fields = form
    freeze_form(fields, f, True)
    freeze_form(fields, f, True)
    freeze_form(fields, f, False)
    assert not f.cont.line.isReadOnly()
    assert f.cont.mode.isEnabled()
