"""
Source flags for a structure material, worked out from its data.

A material is stored as ``{"values": ..., "meta": {"source", "db_original"}}``.
``db_original`` is the snapshot taken when the material came from the
database, the custom database or an Excel row, and its ``action`` says which.
The flag is decided here, by comparing ``values`` with that snapshot, so
editing a value and setting it back is not a modification.

Flags and the mark each one gets after the material name in the reports
(structure work and BOQ; the marks and legend are in
code_to_latex/structure_work_data_latex.py, _SOURCE_MARK and _legend):

    flag                 mark   meaning
    db                   (none) from the database, unchanged
    db_modified          §      from the database, then changed
    custom_db            ¶      from the user's custom database, unchanged
    custom_db_modified   ‖      from the user's custom database, then changed
    excel                †      imported from Excel, unchanged
    excel_modified       ‡      imported from Excel, then changed
    manual               #      typed in by hand (no snapshot)

When a report uses two or more databases, each database also gets a number
after the mark (abc¹, edf§²): see material_db_key and report_databases.

"Changed" means a value differs from the snapshot now: a value edited and
set back is unchanged. Which values count:
    excel             every field (ID, name, quantity, unit, rate, sources,
                      emission factor and unit, conversion factor, scrap,
                      recovery)
    db / custom_db    only what the database fills in (ID, unit, rate,
                      sources, emission factor and unit, conversion factor);
                      name, quantity, scrap and recovery are the user's

No Qt: safe to call from the report builders.
"""

import math

from ..utils.unit_resolver import _UNIT_ALIASES, get_known_units, suggest_cf

FLAGS = (
    "db", "db_modified",
    "custom_db", "custom_db_modified",
    "excel", "excel_modified",
    "manual",
)

# db_original["action"] -> (flag when unchanged, flag when modified)
_ORIGINS = {
    "internal_db": ("db", "db_modified"),
    "custom_db": ("custom_db", "custom_db_modified"),
    "excel": ("excel", "excel_modified"),
}

_CARBON_PREFIX = "kgCO₂e/"

# values key -> snapshot key, per origin.
# Excel rows fill every field; the databases fill only these (the name and
# quantity are the user's, so changing them is not a modification).
_TEXT_FIELDS = {
    "excel": {"src_id": "src_id", "material_name": "name",
              "rate_source": "rate_src", "carbon_emission_src": "carbon_emission_src"},
    "db": {"src_id": "src_id", "rate_source": "rate_src",
           "carbon_emission_src": "carbon_emission_src"},
}
_NUMBER_FIELDS = {
    "excel": {"quantity": "quantity", "rate": "rate", "carbon_emission": "carbon_emission",
              "scrap_rate": "scrap_rate",
              "post_demolition_recovery_percentage": "recovery_pct"},
    "db": {"rate": "rate", "carbon_emission": "carbon_emission"},
}


def material_flag(item: dict) -> str:
    """The source flag for one stored material (see the module docstring)."""
    item = _dict(item)
    meta = _dict(item.get("meta"))
    original = _dict(meta.get("db_original"))
    action = original.get("action")
    pair = _ORIGINS.get(action) if isinstance(action, str) else None
    if pair is None:
        return "manual"                   # no snapshot: typed in by hand
    values = _dict(item.get("values"))
    kind = "excel" if original.get("action") == "excel" else "db"
    return pair[1] if _differs(values, original, kind) else pair[0]


# ── which database ───────────────────────────────────────────────────────
# Each database (SOR or custom) in a report gets a number, in the order it
# first appears; the number follows the mark (abc¹, edf§²). Numbers are used
# only when the report has two or more databases; with one, the legend names
# it. Excel and manual rows have no database.

_CUSTOM_PREFIX = "custom::"


def material_db_key(item: dict) -> str:
    """The database a material came from (its db_key), '' for Excel and manual."""
    original = _dict(_dict(_dict(item).get("meta")).get("db_original"))
    if original.get("action") in ("internal_db", "custom_db"):
        key = original.get("db_key")
        return key.strip() if isinstance(key, str) else ""
    return ""


def report_databases(items) -> list:
    """The databases used by *items* (trashed ones skipped), in first-seen order."""
    keys = []
    for item in items:
        if _dict(_dict(item).get("state")).get("in_trash"):
            continue
        key = material_db_key(item)
        if key and key not in keys:
            keys.append(key)
    return keys


def db_label(db_key: str) -> str:
    """A database as the app shows it: 'INDIA/Madhya_Pradesh/MPPWD SOR 2025'
    -> 'Madhya Pradesh – MPPWD SOR 2025'; 'custom::My Rates' -> 'My Rates (Custom)'."""
    if db_key.startswith(_CUSTOM_PREFIX):
        return f"{db_key[len(_CUSTOM_PREFIX):]} (Custom)"
    parts = [p.replace("_", " ").strip() for p in db_key.split("/")[1:]]
    return " – ".join(p for p in parts if p) or db_key


# ── comparison ───────────────────────────────────────────────────────────


def _differs(values: dict, original: dict, kind: str) -> bool:
    if kind == "db" and (_number(original.get("carbon_emission")) is None
                         or not _text(original.get("carbon_emission_units_den"))):
        # the dialog fills carbon from the database only when both the factor
        # and its unit are there; otherwise it saves no factor, unit or source
        original = dict(original, carbon_emission=None,
                        carbon_emission_units_den=None, carbon_emission_src=None)

    for v_key, o_key in _TEXT_FIELDS[kind].items():
        if _text(values.get(v_key)) != _text(original.get(o_key)):
            return True

    for v_key, o_key in _NUMBER_FIELDS[kind].items():
        now, then = _number(values.get(v_key)), _number(original.get(o_key))
        if v_key == "quantity":
            # the dialog saves a blank quantity as 0
            now, then = now or 0.0, then or 0.0
        if not _same_number(now, then):
            return True

    unit, o_unit = _unit(values.get("unit")), _unit(original.get("unit"))
    if unit != o_unit:
        return True

    denom = _unit(_carbon_denom(values.get("carbon_unit")))
    o_denom = _unit(original.get("carbon_emission_units_den"))
    if denom != o_denom:
        return True

    cf, o_cf = _number(values.get("conversion_factor")), _number(original.get("conversion_factor"))
    if kind == "db" and o_cf == 0:
        o_cf = None                       # the dialog leaves a 0 CF blank
    if o_cf is None:
        # A blank CF is filled by the units: 1 for the same unit, the ratio
        # for the same dimension. That value, or still blank, is unchanged.
        if cf is None:
            return False
        auto = suggest_cf(o_unit, o_denom) if o_unit and o_denom else None
        return auto is None or not math.isclose(cf, auto, rel_tol=1e-5)
    return not _same_number(cf, o_cf)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value):
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_number(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def _carbon_denom(carbon_unit) -> str:
    text = _text(carbon_unit)
    return text[len(_CARBON_PREFIX):] if text.startswith(_CARBON_PREFIX) else text


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _unit(unit) -> str:
    """A unit as its code (cum -> m3, Sqm. -> m2, DRUM -> Drum); known units
    match ignoring case, an unknown unit stays as its own text."""
    text = _text(unit)
    if not text:
        return ""
    lower = text.lower()
    codes = {u.lower(): u for u in get_known_units() if u.lower() not in _UNIT_ALIASES}
    return codes.get(lower) or _UNIT_ALIASES.get(lower, text)
