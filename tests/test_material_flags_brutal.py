"""Brutal black-box tests for material_flag(item).

Written from the usage contract only (the function's source was not read).
Items are shaped like real saved project materials: Excel ones are built from
real Excel cells via build_excel_snapshot / record_to_material_dict, database
ones mirror MaterialDialog.get_values() + a raw DB item snapshot.
"""

import copy

import pytest

from three_ps_lcca_gui.gui.components.structure.material_flags import (
    FLAGS,
    material_flag,
)

EXPECTED_FLAGS = (
    "db", "db_modified", "custom_db", "custom_db_modified",
    "excel", "excel_modified", "manual",
)

CO2 = "kgCO₂e/"


# ── builders ────────────────────────────────────────────────────────────────

def excel_record(**over):
    """A parsed Excel row: every cell is text, as parse_excel gives it."""
    rec = {
        "src_id": "1.2.3",
        "name": "Cement OPC 53",
        "quantity": "120",
        "unit": "t",
        "rate": "6500.00",
        "rate_src": "DSR 2023",
        "carbon_emission": "0.93",
        "carbon_emission_units_den": "kg",
        "conversion_factor": "1000",
        "carbon_emission_src": "ICE v3",
        "scrap_rate": "2",
        "recovery_pct": "10",
        "component": "Foundation",
    }
    rec.update(over)
    return rec


def excel_snapshot(rec):
    snap = {k: (None if isinstance(v, str) and v.strip() == "" else v)
            for k, v in rec.items()}
    snap["action"] = "excel"
    return snap


def _num(s):
    if s is None or (isinstance(s, str) and not s.strip()):
        return None
    return float(s)


def excel_values(rec):
    """values as the importer / dialog would save the row unchanged."""
    den = (rec.get("carbon_emission_units_den") or "").strip()
    return {
        "src_id": (rec.get("src_id") or "").strip() or None,
        "material_name": (rec.get("name") or "").strip(),
        "quantity": _num(rec.get("quantity")),
        "unit": (rec.get("unit") or "").strip(),
        "unit_to_si": 1000.0,
        "rate": _num(rec.get("rate")),
        "rate_source": (rec.get("rate_src") or "").strip() or None,
        "carbon_emission": _num(rec.get("carbon_emission")),
        "carbon_unit": f"{CO2}{den}" if den else None,
        "carbon_emission_src": (rec.get("carbon_emission_src") or "").strip() or None,
        "conversion_factor": _num(rec.get("conversion_factor")),
        "scrap_rate": _num(rec.get("scrap_rate")),
        "post_demolition_recovery_percentage": _num(rec.get("recovery_pct")),
    }


def excel_item(rec=None, source="excel", **value_over):
    rec = rec or excel_record()
    values = excel_values(rec)
    values.update(value_over)
    return {
        "values": values,
        "meta": {"source": source, "source_db_key": "",
                 "db_original": excel_snapshot(rec)},
        "state": {"included_in_carbon_emission": True,
                  "included_in_recyclability": True},
    }


def db_raw(origin="internal_db", **over):
    raw = {
        "name": "Steel TMT Fe500",
        "src_id": "5.22.6",
        "unit": "t",
        "rate": "78000.50",
        "rate_src": "DSR 2023",
        "carbon_emission": 2.5,
        "carbon_emission_units_den": "kg",
        "conversion_factor": 1000,
        "carbon_emission_src": "ICE v3.0",
        "db_key": "custom::MyLib" if origin == "custom_db" else "dsr_2023",
    }
    raw.update(over)
    raw["action"] = origin
    return raw


def db_values(raw):
    def _f(v):
        try:
            if v in (None, "", 0, 0.0) or (isinstance(v, str) and _num(v) == 0):
                return None
            return float(v)
        except (TypeError, ValueError):
            return v  # garbage cell: saved as-is (only used by never-raise tests)

    ef = _f(raw.get("carbon_emission"))
    den = raw.get("carbon_emission_units_den") or None
    carbon = ef is not None and den is not None
    return {
        "src_id": raw.get("src_id") or None,
        "material_name": raw.get("name", ""),
        "quantity": 25.0,
        "unit": raw.get("unit") or "",
        "unit_to_si": 1000.0,
        "rate": _f(raw.get("rate")),
        "rate_source": raw.get("rate_src") or None,
        "carbon_emission": ef if carbon else None,
        "carbon_unit": f"{CO2}{den}" if carbon else None,
        "carbon_emission_src": (raw.get("carbon_emission_src") or None) if carbon else None,
        "conversion_factor": _f(raw.get("conversion_factor")),
        "scrap_rate": None,
        "post_demolition_recovery_percentage": None,
    }


def db_item(origin="internal_db", raw=None, source=None, **value_over):
    raw = raw if raw is not None else db_raw(origin)
    values = db_values(raw)
    values.update(value_over)
    if source is None:
        source = "custom_db" if origin == "custom_db" else "db"
    return {
        "values": values,
        "meta": {"source": source,
                 "source_db_key": raw.get("db_key", "").removeprefix("custom::"),
                 "db_original": raw},
        "state": {"included_in_carbon_emission": True,
                  "included_in_recyclability": False,
                  "allow_edit_checked": False},
    }


DB_ORIGINS = [("internal_db", "db"), ("custom_db", "custom_db")]


def flag(item):
    before = copy.deepcopy(item)
    out = material_flag(item)
    assert out in FLAGS, f"returned {out!r}, not a member of FLAGS"
    assert item == before, "material_flag mutated its input"
    return out


# ── FLAGS constant ──────────────────────────────────────────────────────────

def test_flags_constant():
    assert tuple(FLAGS) == EXPECTED_FLAGS


# ── Excel origin ────────────────────────────────────────────────────────────

def test_excel_unchanged():
    assert flag(excel_item()) == "excel"


EXCEL_CHANGES = [
    ("src_id", "9.9.9"),
    ("src_id", None),
    ("material_name", "Cement PPC"),
    ("material_name", "cement opc 53"),   # text compare is not case-blind
    ("material_name", ""),
    ("quantity", 121.0),
    ("quantity", None),
    ("quantity", 120.5),
    ("unit", "m3"),
    ("unit", "kg"),
    ("unit", ""),
    ("rate", 6600.0),
    ("rate", None),
    ("rate", 6500.01),
    ("rate_source", "DSR 2024"),
    ("rate_source", None),
    ("carbon_emission", 0.95),
    ("carbon_emission", None),
    ("carbon_unit", f"{CO2}t"),
    ("carbon_unit", None),
    ("carbon_emission_src", "ICE v4"),
    ("carbon_emission_src", None),
    ("conversion_factor", 999.0),
    ("conversion_factor", 1.0),
    ("scrap_rate", 3.0),
    ("scrap_rate", None),
    ("scrap_rate", 0.0),
    ("post_demolition_recovery_percentage", 11.0),
    ("post_demolition_recovery_percentage", None),
]


@pytest.mark.parametrize("field,new", EXCEL_CHANGES)
def test_excel_every_field_counts(field, new):
    assert flag(excel_item(**{field: new})) == "excel_modified"


@pytest.mark.parametrize("field,new", EXCEL_CHANGES)
def test_excel_stale_unmodified_source_does_not_hide_change(field, new):
    assert flag(excel_item(source="excel", **{field: new})) == "excel_modified"


@pytest.mark.parametrize("stale", ["excel_modified", "db", "db_modified",
                                   "custom_db_modified", "manual", None, "junk"])
def test_excel_stale_source_ignored_when_unchanged(stale):
    assert flag(excel_item(source=stale)) == "excel"


@pytest.mark.parametrize("field,new", EXCEL_CHANGES)
def test_excel_change_and_back(field, new):
    item = excel_item(source="excel_modified")
    original = item["values"][field]
    item["values"][field] = new
    assert flag(item) == "excel_modified"
    item["values"][field] = original
    assert flag(item) == "excel"


@pytest.mark.parametrize("cells,over", [
    ({"rate": "4500.00"}, {"rate": 4500.0}),
    ({"rate": " 4500 "}, {"rate": 4500}),
    ({"rate": "4.5e3"}, {"rate": 4500.0}),
    ({"rate": "0.3"}, {"rate": 0.1 + 0.2}),
    ({"quantity": "120.000"}, {"quantity": 120}),
    ({"conversion_factor": "1000.0"}, {"conversion_factor": 1000}),
    ({"carbon_emission": "0.930"}, {"carbon_emission": 0.93}),
    ({"scrap_rate": "2.0"}, {"scrap_rate": 2}),
    ({"recovery_pct": "10.00"}, {"post_demolition_recovery_percentage": 10.0}),
])
def test_excel_numbers_compare_as_numbers(cells, over):
    item = excel_item(excel_record(**cells), **over)
    assert flag(item) == "excel"


@pytest.mark.parametrize("cells,over", [
    ({"name": "  Cement OPC 53  "}, {"material_name": "Cement OPC 53"}),
    ({}, {"material_name": "  Cement OPC 53 "}),
    ({"src_id": " 1.2.3 "}, {"src_id": "1.2.3"}),
    ({"rate_src": "DSR 2023  "}, {"rate_source": " DSR 2023"}),
    ({"carbon_emission_src": " ICE v3"}, {"carbon_emission_src": "ICE v3 "}),
    ({"src_id": ""}, {"src_id": None}),
    ({"src_id": ""}, {"src_id": ""}),
    ({"src_id": "   "}, {"src_id": None}),
    ({"rate_src": ""}, {"rate_source": ""}),
    ({"rate_src": ""}, {"rate_source": None}),
    ({"carbon_emission_src": ""}, {"carbon_emission_src": ""}),
])
def test_excel_text_trim_and_none_equals_empty(cells, over):
    assert flag(excel_item(excel_record(**cells), **over)) == "excel"


def test_excel_snapshot_missing_text_keys_equal_blank_values():
    item = excel_item(excel_record(src_id="", rate_src=""))
    snap = item["meta"]["db_original"]
    del snap["src_id"]
    del snap["rate_src"]
    item["values"]["src_id"] = ""
    item["values"]["rate_source"] = None
    assert flag(item) == "excel"


@pytest.mark.parametrize("snap_unit,val_unit", [
    ("M.T.", "t"), ("t", "M.T."), ("MT", "t"), ("mt", "t"),
    (" t ", "t"), ("T", "t"),
])
def test_excel_unit_aliases_equal(snap_unit, val_unit):
    item = excel_item(excel_record(unit=snap_unit), unit=val_unit)
    assert flag(item) == "excel"


@pytest.mark.parametrize("snap_unit,val_unit,den", [
    ("cum", "m3", "m3"), ("CUM", "m3", "m3"), ("Cu.M", "m3", "m3"),
    ("Sqm.", "m2", "m2"), ("sq.m", "m2", "m2"), ("SQM", "m2", "m2"),
    ("Nos.", "nos", "nos"), ("KG", "kg", "kg"), ("kg", "Kg", "kg"),
])
def test_excel_unit_aliases_other_dimensions(snap_unit, val_unit, den):
    rec = excel_record(unit=snap_unit, carbon_emission_units_den=den,
                       conversion_factor="1")
    item = excel_item(rec, unit=val_unit)
    assert flag(item) == "excel"


@pytest.mark.parametrize("snap_den,val_den", [
    ("kg", "kg"), ("KG", "kg"), ("kg", "Kg"), (" kg ", "kg"),
])
def test_excel_carbon_denominator_by_unit(snap_den, val_den):
    rec = excel_record(carbon_emission_units_den=snap_den)
    item = excel_item(rec, carbon_unit=f"{CO2}{val_den}")
    assert flag(item) == "excel"


def test_excel_denominator_alias_cum():
    rec = excel_record(unit="m3", carbon_emission_units_den="cum",
                       conversion_factor="1")
    item = excel_item(rec, carbon_unit=f"{CO2}m3")
    assert flag(item) == "excel"


def test_excel_unknown_unit_changed_is_modified():
    rec = excel_record(unit="bag", carbon_emission="", carbon_emission_units_den="",
                       conversion_factor="", carbon_emission_src="")
    assert flag(excel_item(rec)) == "excel"
    assert flag(excel_item(rec, unit="box")) == "excel_modified"


def test_excel_blank_quantity_saved_as_zero():
    rec = excel_record(quantity="")
    assert flag(excel_item(rec, quantity=0.0)) == "excel"
    assert flag(excel_item(rec, quantity=0)) == "excel"
    assert flag(excel_item(rec, quantity=None)) == "excel"
    assert flag(excel_item(rec, quantity=3.0)) == "excel_modified"


def test_excel_nonblank_quantity_to_zero_is_modified():
    assert flag(excel_item(quantity=0.0)) == "excel_modified"


@pytest.mark.parametrize("unit,den,saved_cf,expected", [
    ("t", "kg", None, "excel"),
    ("t", "kg", 1000.0, "excel"),
    ("t", "kg", 1.0, "excel_modified"),
    ("t", "kg", 999.0, "excel_modified"),
    ("kg", "kg", None, "excel"),
    ("kg", "kg", 1.0, "excel"),
    ("kg", "kg", 2.0, "excel_modified"),
    ("kg", "t", 0.001, "excel"),
    ("m3", "m3", 1.0, "excel"),
    ("m3", "kg", None, "excel"),
    ("m3", "kg", 2400.0, "excel_modified"),
    ("nos", "kg", 7.5, "excel_modified"),
    ("M.T.", "kg", 1000.0, "excel"),
])
def test_excel_blank_cf_automatic_rules(unit, den, saved_cf, expected):
    rec = excel_record(unit=unit, carbon_emission_units_den=den, conversion_factor="")
    assert flag(excel_item(rec, conversion_factor=saved_cf)) == expected


def test_excel_non_blank_cf_must_match_even_if_automatic():
    rec = excel_record(unit="t", carbon_emission_units_den="kg", conversion_factor="500")
    assert flag(excel_item(rec, conversion_factor=1000.0)) == "excel_modified"
    assert flag(excel_item(rec, conversion_factor=None)) == "excel_modified"


def test_excel_blank_row_cells_saved_as_none():
    rec = excel_record(src_id="", rate="", rate_src="", carbon_emission="",
                       carbon_emission_units_den="", conversion_factor="",
                       carbon_emission_src="", scrap_rate="", recovery_pct="")
    assert flag(excel_item(rec)) == "excel"
    assert flag(excel_item(rec, rate=10.0)) == "excel_modified"
    assert flag(excel_item(rec, scrap_rate=1.0)) == "excel_modified"
    assert flag(excel_item(rec, post_demolition_recovery_percentage=5.0)) == "excel_modified"
    assert flag(excel_item(rec, src_id="X1")) == "excel_modified"


# real importer output ----------------------------------------------------------

def _real_excel_item(rec):
    from three_ps_lcca_gui.gui.components.structure.excel_importer import (
        record_to_material_dict,
    )
    return record_to_material_dict(dict(rec))


@pytest.mark.parametrize("rec", [
    excel_record(),
    excel_record(conversion_factor=""),
    excel_record(unit="kg", carbon_emission_units_den="kg", conversion_factor=""),
    excel_record(quantity=""),
    excel_record(src_id="", rate_src="", carbon_emission_src=""),
    excel_record(unit="Sqm.", carbon_emission_units_den="m2", conversion_factor="1"),
    excel_record(rate="4500.00", scrap_rate="", recovery_pct=""),
])
def test_real_importer_item_is_excel(rec):
    item = _real_excel_item(rec)
    assert flag(item) == "excel"
    item["meta"]["source"] = "excel_modified"
    assert flag(item) == "excel"


@pytest.mark.parametrize("field,new", [
    ("rate", 1.0), ("material_name", "Other"), ("quantity", 999.0),
    ("scrap_rate", 50.0), ("unit", "kg"), ("conversion_factor", 3.0),
])
def test_real_importer_item_edited_is_modified(field, new):
    item = _real_excel_item(excel_record())
    item["values"][field] = new
    assert flag(item) == "excel_modified"


# ── database / custom database origin ──────────────────────────────────────

@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_db_unchanged(origin, base):
    assert flag(db_item(origin)) == base


DB_COUNTED = [
    ("src_id", "5.22.7"),
    ("src_id", None),
    ("unit", "kg"),
    ("unit", "m3"),
    ("unit", ""),
    ("rate", 78001.0),
    ("rate", None),
    ("rate_source", "My quote"),
    ("rate_source", None),
    ("carbon_emission", 2.6),
    ("carbon_emission", None),
    ("carbon_unit", f"{CO2}t"),
    ("carbon_unit", None),
    ("carbon_emission_src", "EPD 2024"),
    ("carbon_emission_src", None),
    ("conversion_factor", 999.0),
    ("conversion_factor", None),
    ("conversion_factor", 1.0),
]

DB_NOT_COUNTED = [
    ("material_name", "My renamed steel"),
    ("material_name", ""),
    ("quantity", 0.0),
    ("quantity", 1e9),
    ("quantity", None),
    ("scrap_rate", 5.0),
    ("post_demolition_recovery_percentage", 90.0),
]


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("field,new", DB_COUNTED)
def test_db_counted_fields(origin, base, field, new):
    assert flag(db_item(origin, **{field: new})) == base + "_modified"


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("field,new", DB_NOT_COUNTED)
def test_db_user_fields_never_modify(origin, base, field, new):
    assert flag(db_item(origin, source=base + "_modified", **{field: new})) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_db_all_user_fields_at_once(origin, base):
    item = db_item(origin, material_name="X", quantity=3.0, scrap_rate=1.0,
                   post_demolition_recovery_percentage=2.0)
    assert flag(item) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("field,new", DB_COUNTED)
def test_db_change_and_back(origin, base, field, new):
    item = db_item(origin)
    orig = item["values"][field]
    item["values"][field] = new
    assert flag(item) == base + "_modified"
    item["values"][field] = orig
    item["meta"]["source"] = base + "_modified"
    assert flag(item) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("stale", ["excel", "excel_modified", "db", "custom_db",
                                   "manual", None, 42])
def test_db_stale_source_ignored(origin, base, stale):
    assert flag(db_item(origin, source=stale)) == base
    assert flag(db_item(origin, source=stale, rate=1.0)) == base + "_modified"


def test_action_decides_origin_not_db_key():
    raw = db_raw("internal_db", db_key="custom::Lib")
    assert flag(db_item(raw=raw, source="custom_db")) == "db"
    raw = db_raw("custom_db", db_key="dsr_2023")
    assert flag(db_item(raw=raw, source="db")) == "custom_db"


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("raw_over,val_over", [
    ({"rate": "78000.50"}, {"rate": 78000.5}),
    ({"rate": 78000.5}, {"rate": 78000.5}),
    ({"rate": " 78000.5 "}, {"rate": 78000.50}),
    ({"conversion_factor": "1000.00"}, {"conversion_factor": 1000.0}),
    ({"carbon_emission": "2.50"}, {"carbon_emission": 2.5}),
    ({"carbon_emission": 0.3}, {"carbon_emission": 0.1 + 0.2}),
    ({"src_id": " 5.22.6 "}, {"src_id": "5.22.6"}),
    ({"rate_src": "DSR 2023 "}, {"rate_source": "DSR 2023"}),
    ({"rate_src": ""}, {"rate_source": None}),
    ({"rate_src": None}, {"rate_source": ""}),
    ({"src_id": ""}, {"src_id": None}),
])
def test_db_meaning_equality(origin, base, raw_over, val_over):
    item = db_item(origin, raw=db_raw(origin, **raw_over), **val_over)
    assert flag(item) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_db_missing_text_key_equals_blank(origin, base):
    raw = db_raw(origin)
    del raw["rate_src"]
    del raw["src_id"]
    assert flag(db_item(origin, raw=raw, rate_source="", src_id=None)) == base
    assert flag(db_item(origin, raw=raw, rate_source="x", src_id=None)) == base + "_modified"


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("snap_unit,val_unit,den,cf", [
    ("M.T.", "t", "kg", 1000), ("MT", "t", "kg", 1000),
    ("cum", "m3", "m3", 1), ("Cu.M", "m3", "m3", 1),
    ("Sqm.", "m2", "m2", 1), ("sq.m", "m2", "m2", 1),
    ("Nos.", "nos", "nos", 1), ("KG", "kg", "kg", 1),
])
def test_db_unit_aliases(origin, base, snap_unit, val_unit, den, cf):
    raw = db_raw(origin, unit=snap_unit, carbon_emission_units_den=den,
                 conversion_factor=cf)
    assert flag(db_item(origin, raw=raw, unit=val_unit)) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("snap_den,val_den", [
    ("KG", "kg"), ("kg", "Kg"), ("Kg", "KG"),
])
def test_db_carbon_denominator_case(origin, base, snap_den, val_den):
    raw = db_raw(origin, carbon_emission_units_den=snap_den)
    assert flag(db_item(origin, raw=raw, carbon_unit=f"{CO2}{val_den}")) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_db_carbon_denominator_alias(origin, base):
    raw = db_raw(origin, unit="m3", carbon_emission_units_den="cum",
                 conversion_factor=1)
    assert flag(db_item(origin, raw=raw, carbon_unit=f"{CO2}m3")) == base
    assert flag(db_item(origin, raw=raw, carbon_unit=f"{CO2}m2")) == base + "_modified"


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("cf0", [0, 0.0, "0", "0.0", "0.00"])
def test_db_zero_cf_saved_blank(origin, base, cf0):
    raw = db_raw(origin, conversion_factor=cf0)
    assert flag(db_item(origin, raw=raw, conversion_factor=None)) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("raw_over", [
    {"carbon_emission": None},
    {"carbon_emission": ""},
    {"carbon_emission_units_den": None},
    {"carbon_emission_units_den": ""},
    {"carbon_emission": None, "carbon_emission_units_den": None},
])
def test_db_no_carbon_filled(origin, base, raw_over):
    raw = db_raw(origin, **raw_over)
    item = db_item(origin, raw=raw, carbon_emission=None, carbon_unit=None,
                   carbon_emission_src=None)
    assert flag(item) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_db_missing_carbon_keys_no_carbon(origin, base):
    raw = db_raw(origin)
    for k in ("carbon_emission", "carbon_emission_units_den", "carbon_emission_src"):
        del raw[k]
    item = db_item(origin, raw=raw, carbon_emission=None, carbon_unit=None,
                   carbon_emission_src=None)
    assert flag(item) == base


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_db_user_adds_carbon_where_db_had_none(origin, base):
    raw = db_raw(origin, carbon_emission=None)
    item = db_item(origin, raw=raw, carbon_emission=1.8, carbon_unit=f"{CO2}kg",
                   carbon_emission_src="EPD")
    assert flag(item) == base + "_modified"


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_db_carbon_dropped_is_modified(origin, base):
    item = db_item(origin, carbon_emission=None, carbon_unit=None,
                   carbon_emission_src=None)
    assert flag(item) == base + "_modified"


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
@pytest.mark.parametrize("unit,den,saved_cf,modified", [
    ("t", "kg", None, False),
    ("t", "kg", 1000.0, False),
    ("t", "kg", 1.0, True),
    ("t", "kg", 500.0, True),
    ("M.T.", "kg", 1000.0, False),
    ("kg", "kg", None, False),
    ("kg", "kg", 1.0, False),
    ("kg", "kg", 2.0, True),
    ("kg", "t", 0.001, False),
    ("m3", "m3", 1.0, False),
    ("m3", "kg", None, False),
    ("m3", "kg", 2400.0, True),
    ("nos", "kg", 7.5, True),
    ("m2", "kg", 1.0, True),
])
def test_db_blank_cf_automatic_rules(origin, base, unit, den, saved_cf, modified):
    for blank in (None, ""):
        raw = db_raw(origin, unit=unit, carbon_emission_units_den=den,
                     conversion_factor=blank)
        item = db_item(origin, raw=raw, conversion_factor=saved_cf)
        assert flag(item) == base + ("_modified" if modified else ""), blank


@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_db_missing_cf_key_is_blank(origin, base):
    raw = db_raw(origin)
    del raw["conversion_factor"]
    assert flag(db_item(origin, raw=raw, conversion_factor=None)) == base
    assert flag(db_item(origin, raw=raw, conversion_factor=1000.0)) == base
    assert flag(db_item(origin, raw=raw, conversion_factor=7.0)) == base + "_modified"


# real convert_sor_item_to_material output ------------------------------------

@pytest.mark.parametrize("origin,base", DB_ORIGINS)
def test_real_converted_db_item(origin, base):
    from three_ps_lcca_gui.gui.components.structure.widgets.material_dialog import (
        convert_sor_item_to_material,
    )
    raw = db_raw(origin)
    raw.pop("action")
    raw.pop("src_id")  # the converter does not fill the ID
    item = convert_sor_item_to_material(raw)
    assert flag(item) == base
    item["values"]["quantity"] = 40.0
    item["values"]["material_name"] = "Renamed"
    assert flag(item) == base
    item["values"]["rate"] = 1.0
    assert flag(item) == base + "_modified"


# ── no snapshot / legacy ────────────────────────────────────────────────────

LEGACY_SNAPSHOTS = [None, {}, {"action": None}, {"action": ""},
                    {"action": "manual"}, {"action": "weird"},
                    {"name": "Steel", "rate": 1}, "excel", 5, []]


@pytest.mark.parametrize("snap", LEGACY_SNAPSHOTS)
@pytest.mark.parametrize("stored", list(EXPECTED_FLAGS) + [
    None, "", "DB", "Excel", "internal_db", "custom", 1, True, ["db"], {"x": 1}])
def test_no_snapshot_is_manual_whatever_is_stored(snap, stored):
    item = {"values": {"material_name": "Old"},
            "meta": {"source": stored, "db_original": snap}, "state": {}}
    assert flag(item) == "manual"


def test_no_snapshot_no_source_key():
    assert flag({"values": {}, "meta": {}, "state": {}}) == "manual"
    assert flag({"values": {}, "meta": {"db_original": None}}) == "manual"


def test_missing_db_original_key_ignores_source():
    assert flag({"values": {}, "meta": {"source": "db_modified"}}) == "manual"


# ── malformed input never raises ────────────────────────────────────────────

MALFORMED = [
    None, {}, [], "excel", 0, 1.5, True,
    {"values": None, "meta": None},
    {"values": "x", "meta": "y"},
    {"values": [], "meta": []},
    {"meta": {"source": "excel", "db_original": excel_snapshot(excel_record())}},
    {"values": None, "meta": {"db_original": db_raw()}},
    {"values": {}, "meta": {"db_original": db_raw()}},
    {"values": {}, "meta": {"db_original": excel_snapshot(excel_record())}},
    {"values": {"rate": "abc", "quantity": "xyz", "conversion_factor": "n/a"},
     "meta": {"db_original": db_raw(rate="abc", conversion_factor="??")}},
    {"values": {"rate": True, "quantity": False, "unit": 5, "carbon_unit": 7},
     "meta": {"db_original": excel_snapshot(excel_record())}},
    {"values": {"unit": None, "carbon_unit": "kgCO₂e/"},
     "meta": {"db_original": db_raw(unit=None, carbon_emission_units_den=None)}},
    {"values": {"carbon_unit": "garbage", "conversion_factor": float("nan")},
     "meta": {"db_original": db_raw(conversion_factor=float("inf"))}},
    {"values": {"rate": [1], "src_id": {"a": 1}, "material_name": 12},
     "meta": {"db_original": db_raw(src_id=[1], rate={"x": 1}, unit=3)}},
    {"values": {}, "meta": {"db_original": {"action": "excel", "quantity": "12abc",
                                            "unit": "???", "rate": "1e999"}}},
    {"values": {}, "meta": {"db_original": {"action": ["excel"]}}},
    {"values": {}, "meta": {"db_original": {"action": {"k": 1}}}},
]


@pytest.mark.parametrize("item", MALFORMED, ids=range(len(MALFORMED)))
def test_malformed_never_raises(item):
    flag(item)


@pytest.mark.parametrize("field", ["rate", "quantity", "conversion_factor",
                                   "carbon_emission", "scrap_rate"])
@pytest.mark.parametrize("bad", ["abc", "", "  ", True, False, [], {}, "1,000"])
def test_excel_bad_numbers_never_raise(field, bad):
    flag(excel_item(**{field: bad}))


@pytest.mark.parametrize("field", ["rate", "conversion_factor", "carbon_emission"])
@pytest.mark.parametrize("bad", ["abc", True, [], "--"])
def test_db_bad_numbers_never_raise(field, bad):
    raw = db_raw(**{field: bad})
    flag(db_item(raw=raw))
    flag(db_item(raw=raw, **{field: 5.0}))


@pytest.mark.parametrize("field", ["rate", "carbon_emission", "conversion_factor"])
def test_db_non_numeric_value_vs_number_is_modified(field):
    assert flag(db_item(**{field: "abc"})) == "db_modified"


def test_bool_is_not_a_number_match():
    # rate True must not be read as 1 matching rate 1
    raw = db_raw(rate=1)
    assert flag(db_item(raw=raw, rate=True)) in FLAGS


def test_does_not_mutate_nested():
    item = excel_item(quantity=None, conversion_factor=None)
    item["meta"]["db_original"]["quantity"] = None
    snap = copy.deepcopy(item)
    material_flag(item)
    assert item == snap
    item = db_item("custom_db", raw=db_raw("custom_db", conversion_factor=0),
                   conversion_factor=None)
    snap = copy.deepcopy(item)
    material_flag(item)
    assert item == snap


# ── custom units (user-defined, from unit_resolver's cache) ────────────────

CUSTOM_UNITS = [
    {"symbol": "bag50", "name": "50 kg bag", "dimension": "Mass",
     "to_si": 50.0, "si_unit": "kg"},
    {"symbol": "brass", "name": "brass (100 cft)", "dimension": "Volume",
     "to_si": 2.8317, "si_unit": "m3"},
    {"symbol": "Drum", "name": "200 l drum", "dimension": "Volume",
     "to_si": 0.2, "si_unit": "m3"},
]


@pytest.fixture
def custom_units(monkeypatch):
    from three_ps_lcca_gui.gui.components.utils import unit_resolver
    monkeypatch.setattr(unit_resolver, "_custom_units_cache",
                        copy.deepcopy(CUSTOM_UNITS))
    # never let anything reload from the real custom DB
    monkeypatch.setattr(unit_resolver, "load_custom_units", lambda: None)
    return unit_resolver


@pytest.fixture
def no_custom_units(monkeypatch):
    from three_ps_lcca_gui.gui.components.utils import unit_resolver
    monkeypatch.setattr(unit_resolver, "_custom_units_cache", [])
    monkeypatch.setattr(unit_resolver, "load_custom_units", lambda: None)


ALL_ORIGINS = [("excel", "excel")] + DB_ORIGINS


def any_item(origin, raw_over=None, **value_over):
    """An item of any origin with snapshot overrides (DB key names; the Excel
    snapshot uses the same names for unit / denominator / CF)."""
    raw_over = dict(raw_over or {})
    if origin == "excel":
        return excel_item(excel_record(**raw_over), source="excel_modified",
                          **value_over)
    return db_item(origin, raw=db_raw(origin, **raw_over), source="manual",
                   **value_over)


def _snap(unit, den, cf):
    return {"unit": unit, "carbon_emission_units_den": den,
            "conversion_factor": cf}


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("unit,den", [("bag50", "kg"), ("brass", "m3"),
                                      ("Drum", "m3")])
def test_custom_unit_unchanged(custom_units, origin, base, unit, den):
    item = any_item(origin, _snap(unit, den, "7"), unit=unit,
                    carbon_unit=f"{CO2}{den}", conversion_factor=7.0)
    assert flag(item) == base


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("snap_unit,val_unit", [
    ("bag50", "kg"), ("kg", "bag50"), ("bag50", "Drum"), ("brass", "m3"),
    ("m3", "brass"), ("bag50", "bags"), ("bags", "bag50"), ("bag50", ""),
])
def test_unit_changed_to_or_from_custom(custom_units, origin, base,
                                        snap_unit, val_unit):
    item = any_item(origin, _snap(snap_unit, "kg", "7"), unit=val_unit,
                    carbon_unit=f"{CO2}kg", conversion_factor=7.0)
    assert flag(item) == base + "_modified"


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("snap_unit,val_unit", [
    (" bag50 ", "bag50"), ("bag50", "  bag50"), ("\tDrum ", "Drum"),
])
def test_custom_unit_outer_spaces(custom_units, origin, base, snap_unit, val_unit):
    item = any_item(origin, _snap(snap_unit, "kg", "7"), unit=val_unit,
                    carbon_unit=f"{CO2}kg", conversion_factor=7.0)
    assert flag(item) == base


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
def test_custom_unit_case_difference_is_consistent(custom_units, origin, base):
    # The contract fixes case-blindness for aliases but not for custom symbols,
    # so either verdict is defensible - but it must be the same verdict for
    # every custom symbol and in both directions.
    verdicts = {}
    for a, b in [("bag50", "BAG50"), ("BAG50", "bag50"),
                 ("Drum", "drum"), ("drum", "Drum"), ("Drum", "DRUM")]:
        item = any_item(origin, _snap(a, "kg", "7"), unit=b,
                        carbon_unit=f"{CO2}kg", conversion_factor=7.0)
        verdicts[(a, b)] = flag(item)
    assert len(set(verdicts.values())) == 1, verdicts


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
def test_custom_unit_as_carbon_denominator(custom_units, origin, base):
    snap = _snap("kg", "bag50", "0.02")
    assert flag(any_item(origin, snap, unit="kg", carbon_unit=f"{CO2}bag50",
                         conversion_factor=0.02)) == base
    assert flag(any_item(origin, snap, unit="kg", carbon_unit=f"{CO2} bag50 ",
                         conversion_factor=0.02)) == base
    assert flag(any_item(origin, snap, unit="kg", carbon_unit=f"{CO2}kg",
                         conversion_factor=0.02)) == base + "_modified"
    assert flag(any_item(origin, snap, unit="kg", carbon_unit=f"{CO2}Drum",
                         conversion_factor=0.02)) == base + "_modified"


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("unit,den,saved_cf,modified", [
    ("bag50", "kg", None, False),
    ("bag50", "kg", 50.0, False),       # automatic: 50 kg per bag
    ("bag50", "kg", 1.0, True),
    ("bag50", "kg", 49.0, True),
    ("kg", "bag50", 0.02, False),
    ("bag50", "t", 0.05, False),
    ("bag50", "bag50", 1.0, False),
    ("brass", "m3", 2.8317, False),
    ("Drum", "m3", 0.2, False),
    ("Drum", "l", 200.0, False),
    ("bag50", "m3", None, False),
    ("bag50", "m3", 0.035, True),       # Mass vs Volume: no automatic CF
    ("brass", "kg", 4500.0, True),
])
def test_custom_unit_blank_cf_rules(custom_units, origin, base, unit, den,
                                    saved_cf, modified):
    item = any_item(origin, _snap(unit, den, ""), unit=unit,
                    carbon_unit=f"{CO2}{den}", conversion_factor=saved_cf)
    assert flag(item) == base + ("_modified" if modified else "")


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
def test_custom_unit_absent_from_cache_has_no_automatic_cf(no_custom_units,
                                                           origin, base):
    snap = _snap("bag50", "kg", "")
    assert flag(any_item(origin, snap, unit="bag50", carbon_unit=f"{CO2}kg",
                         conversion_factor=None)) == base
    assert flag(any_item(origin, snap, unit="bag50", carbon_unit=f"{CO2}kg",
                         conversion_factor=50.0)) == base + "_modified"


# ── unknown units (not in units.json, not custom) ──────────────────────────

UNKNOWN_UNITS = ["bags", "xyz", "Bag", "sqm-mm", "kg/mm", "बोरी", "µbag",
                 "Box of 10", "m³-ish"]


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("unit", UNKNOWN_UNITS)
def test_unknown_unit_same_is_unmodified(no_custom_units, origin, base, unit):
    for snap_unit in (unit, f"  {unit} "):
        item = any_item(origin, _snap(snap_unit, "kg", "3"), unit=unit,
                        carbon_unit=f"{CO2}kg", conversion_factor=3.0)
        assert flag(item) == base, snap_unit


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("snap_unit,val_unit", [
    ("bags", "bag"), ("Bag", "bag"), ("bags", "Bags"), ("xyz", "xyzz"),
    ("बोरी", "बोरा"), ("sqm-mm", "sqm-cm"), ("kg/mm", "kg/m"),
    ("kg/mm", "kg/cm"), ("Box of 10", "Box of 12"),
])
def test_unknown_unit_different_is_modified(no_custom_units, origin, base,
                                            snap_unit, val_unit):
    item = any_item(origin, _snap(snap_unit, "kg", "3"), unit=val_unit,
                    carbon_unit=f"{CO2}kg", conversion_factor=3.0)
    assert flag(item) == base + "_modified"


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("snap_unit,val_unit", [
    ("bags", "kg"), ("kg", "bags"), ("xyz", "m3"), ("t", "Bag"),
    ("Sqm.", "sqm-mm"), ("kg/mm", "kg"), ("m2", "बोरी"),
])
def test_unknown_vs_known_is_modified(no_custom_units, origin, base,
                                      snap_unit, val_unit):
    item = any_item(origin, _snap(snap_unit, "kg", "3"), unit=val_unit,
                    carbon_unit=f"{CO2}kg", conversion_factor=3.0)
    assert flag(item) == base + "_modified"


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("snap_unit", ["   ", "\t", " \n "])
def test_unit_empty_after_trim(no_custom_units, origin, base, snap_unit):
    snap = _snap(snap_unit, "kg", "3")
    for val in ("", None, "  "):
        assert flag(any_item(origin, snap, unit=val, carbon_unit=f"{CO2}kg",
                             conversion_factor=3.0)) == base, val
    assert flag(any_item(origin, snap, unit="bags", carbon_unit=f"{CO2}kg",
                         conversion_factor=3.0)) == base + "_modified"


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("den", ["bags", "xyz", "kg/mm", "बोरी"])
def test_unknown_carbon_denominator(no_custom_units, origin, base, den):
    snap = _snap("kg", den, "3")
    assert flag(any_item(origin, snap, unit="kg", carbon_unit=f"{CO2}{den}",
                         conversion_factor=3.0)) == base
    assert flag(any_item(origin, snap, unit="kg", carbon_unit=f"{CO2} {den} ",
                         conversion_factor=3.0)) == base
    assert flag(any_item(origin, snap, unit="kg", carbon_unit=f"{CO2}{den}2",
                         conversion_factor=3.0)) == base + "_modified"
    assert flag(any_item(origin, snap, unit="kg", carbon_unit=f"{CO2}kg",
                         conversion_factor=3.0)) == base + "_modified"


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("unit,den", [
    ("bags", "kg"), ("kg", "bags"), ("xyz", "abc"), ("sqm-mm", "kg"),
    ("kg/mm", "kg"), ("बोरी", "kg"),
])
def test_unknown_unit_blank_cf(no_custom_units, origin, base, unit, den):
    snap = _snap(unit, den, "")
    assert flag(any_item(origin, snap, unit=unit, carbon_unit=f"{CO2}{den}",
                         conversion_factor=None)) == base
    for typed in (1.0, 2.5, 1000.0):
        assert flag(any_item(origin, snap, unit=unit, carbon_unit=f"{CO2}{den}",
                             conversion_factor=typed)) == base + "_modified", typed


@pytest.mark.parametrize("origin,base", ALL_ORIGINS)
@pytest.mark.parametrize("unit", ["sqm-mm", "kg/mm", "m2-mm"])
def test_compound_units_same_text_unmodified(no_custom_units, origin, base, unit):
    item = any_item(origin, _snap(unit, unit, "1"), unit=unit,
                    carbon_unit=f"{CO2}{unit}", conversion_factor=1.0)
    assert flag(item) == base
