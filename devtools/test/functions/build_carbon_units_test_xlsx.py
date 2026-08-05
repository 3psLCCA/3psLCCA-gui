"""
devtools/test/functions/build_carbon_units_test_xlsx.py

Generates carbon_units_test.xlsx next to this script - a small, hand-designed
CID#-formatted workbook exercising the carbon_emission_units /
carbon_emission_units_den validation added to excel_importer.py's
verify_schema() (and mirrored in devtools/sor_json_generator.py):

  - carbon_emission_units_den must be a bare denominator (e.g. "kg") -
    rejected if it contains "co2" (case/subscript-insensitive).
  - carbon_emission_units must be the full ratio (e.g. "kgCO2e/kg") -
    rejected if it does NOT contain "co2".

Re-run this script whenever the fixture needs to change - the .xlsx is a
build artifact, not something to hand-edit in Excel. Consumed by
carbon_units_import.test.py.

Run:

    python "devtools/test/functions/build_carbon_units_test_xlsx.py"
"""

import pandas as pd
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent / "carbon_units_test.xlsx"

HEADERS = [
    "CID#Name",
    "CID#Unit",
    "CID#Rate",
    "CID#Carbon_Emission_Factor",
    "CID#Carbon_Emission_units",
    "CID#Carbon_Emission_units_Den",
    "CID#Component",
]

# Each row name doubles as the test's row identifier - carbon_units_import.test.py
# looks rows up by name, not by position, so reordering here is safe.
ROWS = [
    # name,                                unit,  rate,  carbon_ef, units,            units_den,  component
    ["Valid - bare denom only",            "cum", 100,   0.5,       "",               "kg",       "Foundation"],
    ["Valid - full ratio only",            "cum", 100,   0.5,       "kgCO2e/kg",      "",         "Foundation"],
    ["Invalid - den contains co2",         "cum", 100,   0.5,       "",               "kgCO2/kg", "Foundation"],
    ["Invalid - units missing co2",        "cum", 100,   0.5,       "kg",             "",         "Foundation"],
    ["Valid - no carbon data at all",      "cum", 100,   "",        "",               "",         "Foundation"],
    ["Warn - carbon_ef but no unit field", "cum", 100,   0.3,       "",               "",         "Foundation"],
    ["Valid - den wins when both present", "cum", 100,   0.5,       "kgCO2e/litre",   "kg",       "Foundation"],
    ["Invalid - den has unicode subscript CO2", "cum", 100, 0.5,    "",               "kgCO₂/kg", "Foundation"],
    ["Valid - uppercase full ratio",       "cum", 100,   0.5,       "KGCO2E/KG",      "",         "Foundation"],
]

df = pd.DataFrame(ROWS, columns=[h.replace("CID#", "") for h in HEADERS])

with pd.ExcelWriter(OUT_PATH, engine="openpyxl") as writer:
    # Sheet name must start with "CAT#" for excel_importer.parse_excel to treat
    # it as a material sheet at all.
    header_df = pd.DataFrame([HEADERS])
    header_df.to_excel(writer, sheet_name="CAT#Foundation", index=False, header=False, startrow=0)
    df.to_excel(writer, sheet_name="CAT#Foundation", index=False, header=False, startrow=1)

print(f"Wrote {OUT_PATH} ({len(ROWS)} data rows)")
