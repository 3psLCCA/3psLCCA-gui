"""
devtools/test/functions/carbon_units_import.test.py

Runs the REAL excel_importer.py pipeline (parse_excel -> verify_schema)
against devtools/test/functions/carbon_units_test.xlsx and checks that each
row is accepted/rejected/warned exactly as the carbon_emission_units /
carbon_emission_units_den validation rule intends:

  - carbon_emission_units_den must be a bare denominator - rejected
    (_errors, blocks import) if it contains "co2" (case/subscript-insensitive).
  - carbon_emission_units must be the full ratio - rejected if it does
    NOT contain "co2".
  - carbon_emission provided but neither field filled in -> warning only,
    row still imports.

No running app / project needed - this loads the .xlsx straight off disk
and calls the pure parsing/validation functions directly.

If the fixture needs to change, edit and re-run
build_carbon_units_test_xlsx.py first, then this file.

Run:

    python "devtools/test/functions/carbon_units_import.test.py"
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

XLSX_PATH = Path(__file__).resolve().parent / "carbon_units_test.xlsx"

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


if not XLSX_PATH.exists():
    print(
        f"Fixture not found: {XLSX_PATH}\n"
        f"Run build_carbon_units_test_xlsx.py first."
    )
    sys.exit(1)

try:
    from three_ps_lcca_gui.gui.components.structure.excel_importer import (
        parse_excel,
        verify_schema,
    )
except ImportError as e:
    print(f"Could not import excel_importer - is PySide6/pandas installed? ({e})")
    sys.exit(1)

parsed = parse_excel(str(XLSX_PATH))
materials = verify_schema(parsed["materials"])

rows = materials.get("CAT#Foundation", [])
by_name = {r.get("name", ""): r for r in rows}

ok(
    "fixture loaded with all 9 expected rows",
    len(by_name) == 9,
    f"got {len(by_name)} rows: {sorted(by_name)}",
)


def row_errors(name: str) -> list[str]:
    return by_name[name].get("_errors", [])


def row_warnings(name: str) -> list[str]:
    return by_name[name].get("_warnings", [])


step("rows that must be ACCEPTED (no _errors)")

for name in [
    "Valid - bare denom only",
    "Valid - full ratio only",
    "Valid - no carbon data at all",
    "Valid - den wins when both present",
    "Valid - uppercase full ratio",
]:
    errs = row_errors(name)
    ok(f"'{name}' has no errors", errs == [], f"errors: {errs}")

step("rows that must be REJECTED (_errors non-empty)")

for name in [
    "Invalid - den contains co2",
    "Invalid - units missing co2",
    "Invalid - den has unicode subscript CO2",
]:
    errs = row_errors(name)
    ok(f"'{name}' is rejected with an error", len(errs) > 0, f"errors: {errs}")

step("row that must WARN but still be accepted")

name = "Warn - carbon_ef but no unit field"
errs = row_errors(name)
warns = row_warnings(name)
ok(f"'{name}' has no errors (still imports)", errs == [], f"errors: {errs}")
ok(
    f"'{name}' has a warning about the missing unit field",
    any("carbon_emission" in w for w in warns),
    f"warnings: {warns}",
)

step("spot-check error messages point at the right field")

den_err = row_errors("Invalid - den contains co2")
ok(
    "den-contains-co2 error mentions 'carbon_emission_units_den'",
    any("carbon_emission_units_den" in e for e in den_err),
    f"errors: {den_err}",
)

units_err = row_errors("Invalid - units missing co2")
ok(
    "units-missing-co2 error mentions 'carbon_emission_units'",
    any("carbon_emission_units" in e for e in units_err),
    f"errors: {units_err}",
)

sys.exit(summary())
