"""
devtools/test/functions/resolve_carbon_denom.test.py

Standalone, no-server unit test for
`resolve_carbon_denom()` in
src/three_ps_lcca_gui/gui/components/structure/registry/material_entry.py
(the Qt-free canonical implementation - material_dialog.py imports it from
here, and it's what the local HTTP API's add-from-catalog path actually
uses via convert_sor_item_to_material()).

Background (see conversation history / API_plan.md carbon-unit notes):
SOR catalog rows carry the carbon-emission denominator in one of two
distinct fields, which are NEVER aliased onto each other:

  - "carbon_emission_units_den" - the unambiguous field, always a bare
    denominator (e.g. "kg"). Wins whenever present.
  - "carbon_emission_units" - the older/ambiguous field. Historically
    filled by data preparers with the FULL ratio (e.g. "kgCO2/kg") because
    the column name reads as "the units", not "just the denominator".
    resolve_carbon_denom() strips a leading numerator segment (up to the
    first "/") so a full ratio still resolves to a bare unit.

Run (no running app / project needed - pure function test):

    python "devtools/test/functions/resolve_carbon_denom.test.py"
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

_pass = 0
_fail = 0


def ok(label: str, condition: bool, detail: str = "") -> bool:
    global _pass, _fail
    if condition:
        _pass += 1
        print(f"  [PASS] {label}")
    else:
        _fail += 1
        print(f"  [FAIL] {label}" + (f"  ({detail})" if detail else ""))
    return condition


def step(label: str) -> None:
    print(f"\n--- {label} ---")


def summary() -> int:
    print(f"\n{'=' * 60}")
    print(f"RESULT: {_pass} passed, {_fail} failed")
    print(f"{'=' * 60}")
    return 1 if _fail else 0


try:
    from three_ps_lcca_gui.gui.components.structure.registry.material_entry import (
        resolve_carbon_denom,
    )
except ImportError as e:
    print(f"Could not import resolve_carbon_denom ({e})")
    sys.exit(1)


def check(label: str, item: dict, expected: str | None):
    result = resolve_carbon_denom(item)
    ok(label, result == expected, f"got {result!r}, expected {expected!r}")


step("carbon_emission_units_den present - used as-is, no parsing")
check(
    "bare denominator, den field only",
    {"carbon_emission_units_den": "kg"},
    "kg",
)
check(
    "den field wins even if units field also present and different",
    {"carbon_emission_units_den": "kg", "carbon_emission_units": "litre"},
    "kg",
)
check(
    "den field wins even if it also happens to contain a slash",
    {"carbon_emission_units_den": "kg/m3", "carbon_emission_units": "litre"},
    "kg/m3",
)

step("only carbon_emission_units present - the ambiguous/legacy field")
check(
    "already-bare value in the ambiguous field - passed through unchanged",
    {"carbon_emission_units": "kg"},
    "kg",
)
check(
    "full ratio in the ambiguous field - numerator prefix stripped",
    {"carbon_emission_units": "kgCO₂/kg"},
    "kg",
)
check(
    "full ratio with 'e' in numerator - numerator prefix stripped",
    {"carbon_emission_units": "kgCO₂e/litre"},
    "litre",
)
check(
    "full ratio with a compound-looking suffix unit (m²-mm, hyphen not slash)",
    {"carbon_emission_units": "kgCO₂e/m²-mm"},
    "m²-mm",
)

step("neither field present / blank / falsy - None")
check("both fields missing", {}, None)
check("den field blank string", {"carbon_emission_units_den": ""}, None)
check(
    "den field blank, falls back to units field",
    {"carbon_emission_units_den": "", "carbon_emission_units": "kg"},
    "kg",
)
check("den field is 0 (falsy, not a real unit) - falls through", {"carbon_emission_units_den": 0}, None)
check("units field None explicitly", {"carbon_emission_units": None}, None)

step(
    "KNOWN LIMITATION - compound denominator using '/' inside the ambiguous "
    "field is not distinguishable from a doubled numerator prefix"
)
# "kgCO2-kg/m" is deliberately ambiguous: is the numerator "kgCO2" and the
# denominator the compound unit "kg/m"? Or is "kgCO2-kg" a mangled
# numerator and the denominator just "m"? resolve_carbon_denom() takes
# everything after the LAST "/" (rsplit), so today it resolves to just
# "m" - silently discarding the "kg" half if "kg/m" was ever the intended
# compound denominator. Documented here as current behavior, NOT a
# verified-correct outcome - see discussion in conversation history: this
# needs the real unit vocabulary (unit_resolver.py) to disambiguate
# properly, not a positional split. If this assertion ever needs to
# change to "kg/m", that's a deliberate fix, not a regression.
check(
    "hyphen+slash mixed separator - current (unverified, lossy) behavior",
    {"carbon_emission_units": "kgCO2-kg/m"},
    "m",
)

step("random/fuzz cases - every expected value below was captured by "
     "actually running resolve_carbon_denom(), not predicted by hand")

check(
    "den field - whitespace padding stripped",
    {"carbon_emission_units_den": "  kg  "},
    "kg",
)
check(
    "units field - whitespace padding around a full ratio, still parses",
    {"carbon_emission_units": "  kgCO₂e/kg  "},
    "kg",
)
check(
    "units field - three segments (double slash), only the LAST wins",
    {"carbon_emission_units": "kgCO2e/kg/kg"},
    "kg",
)
check(
    "units field - trailing slash with nothing after it -> empty string, "
    "NOT None (the falsy-check only gates entry, not the parsed result)",
    {"carbon_emission_units": "kgCO2e/"},
    "",
)
check(
    "units field - leading slash, nothing before it",
    {"carbon_emission_units": "/kg"},
    "kg",
)
check(
    "units field - bare '/' with nothing on either side -> empty string",
    {"carbon_emission_units": "/"},
    "",
)
check(
    "units field - no case normalization, original casing preserved",
    {"carbon_emission_units": "KGCO2E/KG"},
    "KG",
)
check(
    "units field - fully lowercase ascii (no subscript, no 'e')",
    {"carbon_emission_units": "kgco2e/kg"},
    "kg",
)
check(
    "den field - whitespace-only string is non-empty (truthy) so it PASSES "
    "the falsy-check, then strips down to an empty string - a quirk, not None",
    {"carbon_emission_units_den": "   "},
    "",
)
check(
    "den field - negative number coerced to string, no numeric validation",
    {"carbon_emission_units_den": -1},
    "-1",
)
check(
    "units field - non-string int, no slash, coerced to string as-is",
    {"carbon_emission_units": 123},
    "123",
)
check(
    "units field - bool True is truthy AND != 0, so it's treated as a real "
    "value and stringified - a real (if unlikely) type-confusion trap",
    {"carbon_emission_units": True},
    "True",
)
check(
    "den field - bool False IS treated as falsy/absent (False == 0) - "
    "unlike True above, this one correctly falls through to None",
    {"carbon_emission_units_den": False},
    None,
)
check(
    "units field - a list is falsy-checked as non-empty (any non-empty "
    "container passes the 'not in (None, \"\", 0)' check) then stringified",
    {"carbon_emission_units": []},
    "[]",
)
check(
    "den present but units explicitly None - den still wins as before",
    {"carbon_emission_units_den": "kg", "carbon_emission_units": None},
    "kg",
)

sys.exit(summary())
