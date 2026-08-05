"""
devtools/test/functions/build_carbon_units_exhaustive_xlsx.py

Generates carbon_units_exhaustive_test.xlsx next to this script - a larger,
exhaustive CID#-formatted workbook exercising the carbon_emission_units /
carbon_emission_units_den "co2" validation rule that now lives independently
in BOTH:

  - src/three_ps_lcca_gui/gui/components/structure/excel_importer.py
    (verify_schema - rejects via _errors)
  - devtools/sor_json_generator.py (build_sor_json - rejects by skipping
    the row and printing a [warn] line)

Since both are hand-written, separate implementations of the identical
rule, this fixture is deliberately consumed by BOTH pipelines in
carbon_units_exhaustive.test.py so any disagreement between them shows up
as a test failure, not a silent drift.

Re-run this script whenever the fixture needs to change.

Run:

    python "devtools/test/functions/build_carbon_units_exhaustive_xlsx.py"
"""

import pandas as pd
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent / "carbon_units_exhaustive_test.xlsx"

HEADERS = [
    "CID#Name",
    "CID#Unit",
    "CID#Rate",
    "CID#Carbon_Emission_Factor",
    "CID#Carbon_Emission_units",
    "CID#Carbon_Emission_units_Den",
    "CID#Component",
]

# expect_valid is NOT written to the sheet - it's exported alongside for the
# test script to import directly, so the fixture and its expectations can
# never drift apart from hand-copying row order.
# (name, unit, rate, carbon_ef, units, den, component, expect_valid)
ROWS: list[tuple] = [
    # --- bare denominator, valid: no "co2" substring anywhere ---
    ("bare_kg_den",                 "cum", 100, 0.5, "",  "kg",       "Foundation", True),
    ("bare_m2_den",                 "cum", 100, 0.5, "",  "m2",       "Foundation", True),
    ("bare_m3_den",                 "cum", 100, 0.5, "",  "m3",       "Foundation", True),
    ("bare_litre_den",              "cum", 100, 0.5, "",  "litre",    "Foundation", True),
    ("bare_hyphen_compound_den",    "cum", 100, 0.5, "",  "m²-mm",    "Foundation", True),

    # --- full ratio in the "units" field, valid: does contain "co2" ---
    ("full_ratio_standard",         "cum", 100, 0.5, "kgCO2e/kg",        "", "Foundation", True),
    ("full_ratio_no_e_suffix",      "cum", 100, 0.5, "kgCO2/kg",         "", "Foundation", True),
    ("full_ratio_unicode_subscript","cum", 100, 0.5, "kgCO₂e/litre",     "", "Foundation", True),
    ("full_ratio_uppercase",        "cum", 100, 0.5, "KGCO2E/KG",        "", "Foundation", True),
    ("full_ratio_lowercase",        "cum", 100, 0.5, "kgco2e/kg",        "", "Foundation", True),
    ("full_ratio_whitespace_padded","cum", 100, 0.5, "  kgCO2e/kg  ",    "", "Foundation", True),

    # --- den field invalid: contains "co2", belongs in units instead ---
    ("den_invalid_co2_ascii",       "cum", 100, 0.5, "", "kgCO2/kg", "Foundation", False),
    ("den_invalid_co2_unicode",     "cum", 100, 0.5, "", "kgCO₂/kg", "Foundation", False),
    ("den_invalid_co2_uppercase",   "cum", 100, 0.5, "", "KGCO2/KG", "Foundation", False),

    # --- units field invalid: no "co2" substring, belongs in den instead ---
    ("units_invalid_bare_kg",       "cum", 100, 0.5, "kg",  "", "Foundation", False),
    ("units_invalid_garbage_number","cum", 100, 0.5, "123", "", "Foundation", False),
    # NOTE: NOT "N/A" - pandas' read_excel treats "N/A" as a default NA
    # sentinel string and silently converts the cell to NaN regardless of
    # dtype=str, which both _clean_value()/_clean() then normalize to "" -
    # so the co2 check never even fires (nothing to reject). Confirmed by
    # running this fixture, not assumed. "not_a_unit" is a plain string
    # pandas won't intercept, so it actually reaches the validation rule.
    ("units_invalid_garbage_text",  "cum", 100, 0.5, "not_a_unit", "", "Foundation", False),

    # --- both fields present ---
    ("both_present_both_valid",     "cum", 100, 0.5, "kgCO2e/litre", "kg",       "Foundation", True),
    ("both_present_den_invalid",    "cum", 100, 0.5, "kgCO2e/kg",    "kgCO2/kg", "Foundation", False),

    # --- neither field present ---
    ("neither_present_no_carbon_ef","cum", 100, "",  "", "", "Foundation", True),
    ("neither_present_with_carbon_ef", "cum", 100, 0.3, "", "", "Foundation", True),
]

def build() -> None:
    df = pd.DataFrame(
        [(name, unit, rate, ef, units, den, comp) for name, unit, rate, ef, units, den, comp, _ in ROWS],
        columns=[h.replace("CID#", "") for h in HEADERS],
    )
    with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
        header_df = pd.DataFrame([HEADERS])
        header_df.to_excel(writer, sheet_name="CAT#Foundation", index=False, header=False, startrow=0)
        df.to_excel(writer, sheet_name="CAT#Foundation", index=False, header=False, startrow=1)
    print(f"Wrote {OUT_PATH} ({len(ROWS)} data rows)")


if __name__ == "__main__":
    build()
