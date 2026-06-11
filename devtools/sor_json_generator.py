"""
sor_json_generator.py
=====================
Converts a CID#-formatted SOR Excel file to the MumbaiSOR.json schema.

Output format (array of section objects, one per sheet):
  [
    {
      "sheetName": "Foundation",
      "data": [
        {
          "name": "...",
          "unit": "...",
          "rate": 239,
          "rate_src": "...",
          "carbon_emission": null | <float>,
          "carbon_emission_units_den": null | "<unit>",
          "conversion_factor": null | <float>,
          "carbon_emission_src": null | "IFC" | "ICE" | ...,
          "component": "Excavation" | ["Pier", "Pier Cap"],
          "description": null | "..."
        },
        ...
      ]
    },
    ...
  ]

  Sections are grouped by sheetName only. "type" has been eliminated — component
  on each entry is the sole authority. Single component → plain string (backward
  compat). Multiple components → array.

Usage:
  python devtools/sor_json_generator.py <path/to/file.xlsx> [output.json]

  If output path is omitted, the JSON is written next to the Excel file
  with the same stem and a .json extension.

Column format expected in Excel (same as excel_importer.py):
  Row 1 (or first row with CID# headers):
    CID#Name*, CID#Unit*, CID#Rate*, CID#Component,
    CID#ID (optional), CID#Quantity, CID#Rate_Src,
    CID#Carbon_Emission_Factor, CID#Carbon_Emission_units,
    CID#Conversion_Factor, CID#Carbon_Emission_Src,
    CID#Description (optional)
  (* = required; all other columns are optional)

Sheet name → sheetName mapping:
  Strips optional "CAT#" prefix, normalises hyphens to spaces, then:
  "Foundation"      → "Foundation"
  "Sub Structure"   → "Sub Structure"
  "Super Structure" → "Super Structure"
  "Misc"            → "Miscellaneous"
  (anything else)   → "Miscellaneous"
  "Metadata" sheet  → optional; skipped with [warn] if absent, [skip] if present

CID#Component multi-value syntax:
  "{Pier}, {Pier Cap}" → component stored as ["Pier", "Pier Cap"] (array)
  "Excavation"         → component stored as "Excavation" (string, backward compat)

Type comes from CID#Component column.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required: pip install pandas openpyxl")

# ---------------------------------------------------------------------------
# Constants (mirrors excel_importer.py)
# ---------------------------------------------------------------------------

CID_PREFIX = "cid#"
CAT_PREFIX = "cat#"
METADATA_SHEET = "metadata"

# All keys are lowercase - lookup uses field_part.lower() for case-insensitive matching.
# Required columns: name, unit, rate.  All others (including id) are optional.
CID_TO_INTERNAL: dict[str, str] = {
    "id": "src_id",  # optional
    "name": "name",
    "quantity": "quantity",
    "unit": "unit",
    "rate": "rate",
    "rate_src": "rate_src",
    "carbon_emission_factor": "carbon_emission",
    "carbon_emission_units": "carbon_emission_units_den",
    "carbon_emission_units_den": "carbon_emission_units_den",
    "conversion_factor": "conversion_factor",
    "carbon_emission_src": "carbon_emission_src",
    "scrap_rate": "scrap_rate",
    "recovery_pct": "recovery_pct",
    "grade": "grade",
    "type": "type",
    "component": "component",
    "description": "description",
}

# Strings that are recognised as a carbon emission source.
# Used to recover the source value when the CID#Carbon_Emission_Src column
# is missing from a sheet and the value ended up in the next column.
KNOWN_CARBON_SRCS: set[str] = {"ifc", "ice", "ecoinvent", "ecoinvent database"}

SHEET_TO_SHEET_NAME: dict[str, str] = {
    "foundation": "Foundation",
    "sub structure": "Sub Structure",
    "substructure": "Sub Structure",
    "super structure": "Super Structure",
    "superstructure": "Super Structure",
    "misc": "Miscellaneous",
    "miscellaneous": "Miscellaneous",
}

NA = None

# ---------------------------------------------------------------------------
# Sheet name normalisation
# ---------------------------------------------------------------------------


def _normalise_sheet_name(raw: str) -> str:
    """
    Strip optional CAT# prefix, normalise hyphens to spaces, then look up
    in SHEET_TO_SHEET_NAME. Falls back to "Miscellaneous" for unknown names.
    """
    name = raw.strip()
    if name.lower().startswith(CAT_PREFIX):
        name = name[len(CAT_PREFIX):]
    name_key = name.replace("-", " ").strip().lower()
    return SHEET_TO_SHEET_NAME.get(name_key, "Miscellaneous")


# ---------------------------------------------------------------------------
# Multi-component parsing
# ---------------------------------------------------------------------------

_BRACE_RE = re.compile(r"\{([^}]+)\}")


def _parse_component(raw: str) -> str | list[str]:
    """
    Parse CID#Component cell value.
    "{Pier}, {Pier Cap}" → ["Pier", "Pier Cap"]  (array when 2+ components)
    "Excavation"         → "Excavation"           (plain str for backward compat)
    """
    tokens = [m.group(1).strip() for m in _BRACE_RE.finditer(raw)]
    if len(tokens) >= 2:
        return tokens
    if len(tokens) == 1:
        return tokens[0]
    # No braces - treat whole value as single component
    return raw.strip() or "Uncategorised"


# ---------------------------------------------------------------------------
# CID# parsing helpers (same logic as excel_importer.py, no PySide6)
# ---------------------------------------------------------------------------


def _parse_cid_header(raw: str) -> str | None:
    """Return internal key if raw is a valid CID# column header, else None."""
    stripped = str(raw).strip().lower()
    if not stripped.startswith(CID_PREFIX):
        return None
    field_part = stripped[len(CID_PREFIX):]
    return CID_TO_INTERNAL.get(field_part)


def _build_column_map(headers: list[str]) -> dict[str, int]:
    """Return {internal_key: col_index} for recognised CID# columns."""
    col_map: dict[str, int] = {}
    for col_idx, raw in enumerate(headers):
        internal = _parse_cid_header(raw)
        if internal is not None and internal not in col_map:
            col_map[internal] = col_idx
    return col_map


def _find_header_row(df: "pd.DataFrame") -> int | None:
    """Return index of the first row that contains at least one CID# column."""
    for row_idx in range(min(20, len(df))):
        row_vals = [str(v).strip() for v in df.iloc[row_idx].tolist()]
        if any(_parse_cid_header(v) is not None for v in row_vals):
            return row_idx
    return None


def _clean(raw: Any) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    return "" if s.lower() in ("nan", "none", "") else s


def _to_num(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Main parse
# ---------------------------------------------------------------------------


def parse_excel(path: str) -> dict[str, list[dict]]:
    """
    Read all sheets.
    Returns { sheet_name: [record_dict, ...] }
    where each record_dict has internal keys (name, unit, rate, component, ...).

    Metadata sheet is optional — warns if absent, silently skipped if present.
    """
    try:
        all_sheets: dict[str, "pd.DataFrame"] = pd.read_excel(
            path, sheet_name=None, header=None, dtype=str
        )
    except Exception as exc:
        sys.exit(f"Could not open file: {exc}")

    sheet_names_lower = {s.strip().lower(): s for s in all_sheets}
    if METADATA_SHEET not in sheet_names_lower:
        print(f"  [warn] 'Metadata' sheet not found in '{Path(path).name}' - skipping metadata")

    result: dict[str, list[dict]] = {}

    for sheet_name, df in all_sheets.items():
        # Metadata sheet: skip silently (no data rows for SOR)
        if sheet_name.strip().lower() == METADATA_SHEET:
            print(f"  [skip] '{sheet_name}': metadata sheet")
            continue

        if df.empty:
            continue

        header_row_idx = _find_header_row(df)
        if header_row_idx is None:
            print(f"  [skip] '{sheet_name}': no CID# headers found")
            continue

        headers = [str(c) for c in df.iloc[header_row_idx].tolist()]
        col_map = _build_column_map(headers)
        data_rows = df.iloc[header_row_idx + 1:].reset_index(drop=True)

        has_carbon_src_col = "carbon_emission_src" in col_map

        rows: list[dict] = []
        for _, row in data_rows.iterrows():
            raw_values = row.tolist()

            if all(_clean(v) == "" for v in raw_values):
                continue  # skip blank rows

            record: dict[str, str] = {}
            for field, col_idx in col_map.items():
                raw = raw_values[col_idx] if col_idx < len(raw_values) else None
                record[field] = _clean(raw)

            # If CID#Carbon_Emission_Src was absent from this sheet's headers,
            # try to recover it from the scrap_rate column - the Excel data
            # sometimes has the source string (e.g. "IFC") shifted left by one.
            if not has_carbon_src_col:
                candidate = record.get("scrap_rate", "")
                if candidate.lower() in KNOWN_CARBON_SRCS:
                    record["carbon_emission_src"] = candidate
                    record["scrap_rate"] = ""

            rows.append(record)

        result[sheet_name] = rows
        print(f"  [ok]   '{sheet_name}': {len(rows)} data rows")

    return result


# ---------------------------------------------------------------------------
# Convert to MumbaiSOR-style JSON
# ---------------------------------------------------------------------------


def _make_field(value: str) -> Any:
    """
    Return a numeric value if the string is a valid number, else the string
    itself, or None if empty or explicitly 'not_available'.
    """
    if not value or value.strip().lower() == "not_available":
        return NA
    num = _to_num(value)
    if num is not None:
        # Keep as int when the value is a whole number (e.g. 239 not 239.0)
        return int(num) if num == int(num) else num
    return value


def build_sor_json(parsed: dict[str, list[dict]]) -> list[dict]:
    """
    Group records by sheetName only and build the output array.
    One section object per sheet; component on each entry is the sole authority.
    Ordering: sections appear in the order first encountered, preserving
    within-section row order.
    """
    sheet_order: list[str] = []
    sections: dict[str, list[dict]] = {}

    for sheet_name, rows in parsed.items():
        sheet_label = _normalise_sheet_name(sheet_name)

        for record in rows:
            name = record.get("name", "").strip()
            if not name:
                continue  # skip rows with no name

            unit = record.get("unit", "").strip()
            rate_str = record.get("rate", "")
            rate_num = _to_num(rate_str)
            if rate_num is None:
                print(f"  [warn] skipping '{name}': non-numeric rate '{rate_str}'")
                continue

            raw_component = record.get("component", "").strip()
            component_val = _parse_component(raw_component) if raw_component else "Uncategorised"

            if sheet_label not in sections:
                sheet_order.append(sheet_label)
                sections[sheet_label] = []

            id_val = record.get("src_id", "").strip()
            desc_val = _make_field(record.get("description", ""))
            entry: dict[str, Any] = {
                **({"src_id": id_val} if id_val else {}),
                "name": name,
                "unit": unit,
                "rate": int(rate_num) if rate_num == int(rate_num) else rate_num,
                "rate_src": _make_field(record.get("rate_src", "").strip()),
                "carbon_emission": _make_field(record.get("carbon_emission", "")),
                "carbon_emission_units_den": _make_field(record.get("carbon_emission_units_den", "")),
                "conversion_factor": _make_field(record.get("conversion_factor", "")),
                "carbon_emission_src": _make_field(record.get("carbon_emission_src", "")),
                "component": component_val,
                **({"description": desc_val} if desc_val is not None else {}),
            }
            sections[sheet_label].append(entry)

    return [{"sheetName": s, "data": sections[s]} for s in sheet_order]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(xlsx_path: str, out_path: str | None = None) -> None:
    src = Path(xlsx_path)
    if not src.exists():
        sys.exit(f"File not found: {src}")

    dest = Path(out_path) if out_path else src.with_suffix(".json")

    print(f"Parsing: {src}")
    parsed = parse_excel(str(src))

    total_rows = sum(len(v) for v in parsed.values())
    print(f"Total data rows: {total_rows}")

    sor = build_sor_json(parsed)

    total_entries = sum(len(s["data"]) for s in sor)
    print(f"\nSheets generated: {len(sor)}")
    for s in sor:
        print(f"  {s['sheetName']}: {len(s['data'])} entries")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(sor, f, indent=4, ensure_ascii=False)

    print(f"\nWritten {total_entries} entries -> {dest}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
