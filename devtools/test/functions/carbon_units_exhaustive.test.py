"""
devtools/test/functions/carbon_units_exhaustive.test.py

Exhaustive test of the carbon_emission_units / carbon_emission_units_den
"co2" validation rule, run against BOTH independent implementations that
enforce it:

  1. src/three_ps_lcca_gui/gui/components/structure/excel_importer.py
     - parse_excel() + verify_schema() - rejection = non-empty "_errors"
       on the row (row still appears in the parsed dict, just marked).

  2. devtools/sor_json_generator.py
     - parse_excel() + build_sor_json() - rejection = the row is silently
       DROPPED from the output entirely (a [warn] line is printed, but
       this test only checks the output, not stdout).

These are two hand-written, independent copies of the identical rule (see
conversation history - this is exactly the duplication that motivates
eventually extracting a single shared, Qt-free module). Until that
extraction happens, this test is the thing that catches them disagreeing.

Consumes carbon_units_exhaustive_test.xlsx, built by
build_carbon_units_exhaustive_xlsx.py. Re-run that builder first if the
fixture's ROWS list changes - this test imports ROWS directly from it so
the fixture and its expectations can never drift out of hand-copied sync.

Run:

    python "devtools/test/functions/carbon_units_exhaustive.test.py"
"""

import sys
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
DEVTOOLS_ROOT = REPO_ROOT / "devtools"
THIS_DIR = Path(__file__).resolve().parent

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(DEVTOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(DEVTOOLS_ROOT))

XLSX_PATH = THIS_DIR / "carbon_units_exhaustive_test.xlsx"

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
    print(f"Fixture not found: {XLSX_PATH}\nRun build_carbon_units_exhaustive_xlsx.py first.")
    sys.exit(1)

# --- Load ROWS (with expected outcomes) from the builder module directly ---
spec = importlib.util.spec_from_file_location(
    "build_carbon_units_exhaustive_xlsx",
    THIS_DIR / "build_carbon_units_exhaustive_xlsx.py",
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
ROWS = builder.ROWS  # (name, unit, rate, ef, units, den, comp, expect_valid)
expected = {r[0]: r[7] for r in ROWS}

# --- Pipeline 1: excel_importer.py ---
try:
    from three_ps_lcca_gui.gui.components.structure.excel_importer import (
        parse_excel as importer_parse_excel,
        verify_schema,
    )
except ImportError as e:
    print(f"Could not import excel_importer - is PySide6/pandas installed? ({e})")
    sys.exit(1)

importer_parsed = verify_schema(importer_parse_excel(str(XLSX_PATH))["materials"])
importer_rows = importer_parsed.get("CAT#Foundation", [])
importer_by_name = {r.get("name", ""): r for r in importer_rows}

# --- Pipeline 2: devtools/sor_json_generator.py ---
try:
    import sor_json_generator
except ImportError as e:
    print(f"Could not import sor_json_generator - is pandas installed? ({e})")
    sys.exit(1)

gen_parsed = sor_json_generator.parse_excel(str(XLSX_PATH))
gen_sor = sor_json_generator.build_sor_json(gen_parsed)
gen_accepted_names = {
    entry["name"] for section in gen_sor for entry in section["data"]
}

step(f"fixture sanity - all {len(ROWS)} rows present in both pipelines' input")

ok(
    "excel_importer sees all rows (accepted or rejected, none silently dropped)",
    len(importer_by_name) == len(ROWS),
    f"got {len(importer_by_name)} of {len(ROWS)}: missing "
    f"{set(expected) - set(importer_by_name)}",
)

step("excel_importer.py - accept/reject matches expectation")

for name, expect_valid in expected.items():
    errs = importer_by_name.get(name, {}).get("_errors", [])
    is_valid = errs == []
    ok(
        f"'{name}' -> {'accepted' if expect_valid else 'rejected'}",
        is_valid == expect_valid,
        f"expected {'accepted' if expect_valid else 'rejected'}, "
        f"got {'accepted' if is_valid else 'rejected'} (errors: {errs})",
    )

step("sor_json_generator.py - accept/reject matches expectation")

for name, expect_valid in expected.items():
    is_valid = name in gen_accepted_names
    ok(
        f"'{name}' -> {'included' if expect_valid else 'dropped'}",
        is_valid == expect_valid,
        f"expected {'included' if expect_valid else 'dropped'}, "
        f"got {'included' if is_valid else 'dropped'}",
    )

step("cross-check - both pipelines agree with EACH OTHER on every row")

for name in expected:
    importer_valid = importer_by_name.get(name, {}).get("_errors", []) == []
    gen_valid = name in gen_accepted_names
    ok(
        f"'{name}' - importer and generator agree",
        importer_valid == gen_valid,
        f"importer={'accept' if importer_valid else 'reject'}, "
        f"generator={'accept' if gen_valid else 'reject'}",
    )

sys.exit(summary())
