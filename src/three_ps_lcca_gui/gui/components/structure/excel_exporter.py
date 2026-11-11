"""
excel_exporter.py
=================
Export construction materials from engine chunks in multiple file formats.

Supported formats
-----------------
  xlsx  openpyxl  MIT       installed
  csv   pandas    BSD-3     installed (built-in)
  ods   odfpy     Apache-2  optional  (pip install odfpy)

Adding a new format
-------------------
Add an entry to EXPORT_FORMATS.  If the format requires an optional
dependency, set "requires" to the pip package name - the UI will check
for it at runtime and show an install hint if missing.
"""

from __future__ import annotations

import importlib
import datetime as _dt
import pandas as pd

CHUNKS = [
    ("CAT#Foundation",      "str_foundation"),
    ("CAT#Sub-Structure",   "str_sub_structure"),
    ("CAT#Super-Structure", "str_super_structure"),
    ("CAT#Misc",            "str_misc"),
]

METADATA_KEYS = ["Date"]

CID_COLUMNS = [
    "CID#ID",
    "CID#Name",
    "CID#Quantity",
    "CID#Unit",
    "CID#Rate",
    "CID#Rate_Src",
    "CID#Carbon_Emission_Factor",
    "CID#Carbon_Emission_units",
    "CID#Conversion_Factor",
    "CID#Carbon_Emission_Src",
    "CID#Scrap_Rate",
    "CID#Recovery_Pct",
    "CID#Component",
]

# ---------------------------------------------------------------------------
# Format registry
# Each entry:
#   label    - shown in the dropdown menu
#   ext      - file extension (with dot)
#   filter   - QFileDialog filter string
#   engine   - pandas ExcelWriter engine, or None for CSV
#   requires - pip package to check at runtime, or None
# ---------------------------------------------------------------------------
EXPORT_FORMATS: list[dict] = [
    {
        "label":    "Excel (.xlsx)",
        "ext":      ".xlsx",
        "filter":   "Excel Files (*.xlsx)",
        "engine":   "openpyxl",
        "requires": None,           # openpyxl is a core dependency
    },
    {
        "label":    "OpenDocument (.ods)",
        "ext":      ".ods",
        "filter":   "OpenDocument Spreadsheet (*.ods)",
        "engine":   "odf",
        "requires": "odf",           # pip install odfpy  (Apache-2 licence)
    },
]


def format_available(fmt: dict) -> tuple[bool, str]:
    """
    Return (True, '') if the format can be used, or (False, hint) if not.
    *hint* is a human-readable install instruction.
    """
    pkg = fmt.get("requires")
    if pkg and importlib.util.find_spec(pkg) is None:
        return False, f"pip install {pkg}"
    return True, ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _carbon_denom(carbon_unit: str) -> str:
    """'kgCO₂e/kg' → 'kg'.  Returns '' if blank or no slash."""
    if not carbon_unit:
        return ""
    parts = carbon_unit.split("/", 1)
    return parts[1].strip() if len(parts) == 2 else ""


def _blank_if_zero(val) -> object:
    """Return '' for 0/0.0 so optional numeric fields export as blank cells."""
    try:
        return "" if float(val) == 0.0 else val
    except (TypeError, ValueError):
        return val if val is not None else ""


def _chunk_to_rows(engine, chunk_key: str) -> list[dict]:
    data = engine.fetch_chunk(chunk_key) or {}
    rows = []
    for comp_name, items in data.items():
        for item in items:
            if item.get("state", {}).get("in_trash", False):
                continue
            v = item.get("values", {})
            db_orig = item.get("meta", {}).get("db_original", {})
            rows.append({
                "CID#ID":                     v.get("src_id") or db_orig.get("src_id") or "",
                "CID#Name":                   v.get("material_name", ""),
                "CID#Quantity":               v.get("quantity", ""),
                "CID#Unit":                   v.get("unit", ""),
                "CID#Rate":                   v.get("rate", ""),
                "CID#Rate_Src":               v.get("rate_source", ""),
                "CID#Carbon_Emission_Factor": _blank_if_zero(v.get("carbon_emission")),
                "CID#Carbon_Emission_units":  _carbon_denom(v.get("carbon_unit", "")),
                "CID#Conversion_Factor":      _blank_if_zero(v.get("conversion_factor")),
                "CID#Carbon_Emission_Src":    db_orig.get("carbon_emission_src") or "",
                "CID#Scrap_Rate":             _blank_if_zero(v.get("scrap_rate")),
                "CID#Recovery_Pct":           _blank_if_zero(v.get("post_demolition_recovery_percentage")),
                "CID#Component":              comp_name,
            })
    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def count_active_all(engine) -> int:
    """Return total number of non-trashed materials across all 4 chunks."""
    return sum(
        1
        for _, chunk_key in CHUNKS
        for items in (engine.fetch_chunk(chunk_key) or {}).values()
        for item in items
        if not item.get("state", {}).get("in_trash", False)
    )


def export_all_chunks(engine, path: str, fmt: dict) -> tuple[int, list[str]]:
    """
    Export all chunks to *path* as a multi-sheet spreadsheet.
    Sheet names use the CAT# prefix (e.g. CAT#Foundation) to match the import format.
    A Metadata sheet is always written first containing the export date.
    Returns (total_rows_written, [sheet_names_with_data]).
    """
    total = 0
    sheets_with_data: list[str] = []

    # Pre-fetch all chunk rows so counts are available for the Metadata sheet
    chunk_rows: list[tuple[str, list[dict]]] = [
        (sheet_name, _chunk_to_rows(engine, chunk_key))
        for sheet_name, chunk_key in CHUNKS
    ]

    # Pull project identity fields from general_info
    gi = engine.fetch_chunk("general_info") or {}

    # Build metadata: project info + date + per-sheet material counts
    meta_rows = [
        {"CID#Keys": "Project Name",     "CID#Values": gi.get("project_name", "")},
        {"CID#Keys": "Project Code",     "CID#Values": gi.get("project_code", "")},
        {"CID#Keys": "Country",          "CID#Values": gi.get("project_country", "")},
        {"CID#Keys": "Currency",         "CID#Values": gi.get("project_currency", "")},
        {"CID#Keys": "Date",             "CID#Values": _dt.date.today().isoformat()},
    ]
    for sheet_name, rows in chunk_rows:
        meta_rows.append({"CID#Keys": f"{sheet_name} Total", "CID#Values": len(rows)})

    with pd.ExcelWriter(path, engine=fmt["engine"]) as writer:
        # Metadata sheet first
        pd.DataFrame(meta_rows, columns=["CID#Keys", "CID#Values"]).to_excel(
            writer, sheet_name="Metadata", index=False
        )

        for sheet_name, rows in chunk_rows:
            df = pd.DataFrame(rows if rows else [], columns=CID_COLUMNS)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            if rows:
                sheets_with_data.append(sheet_name)
                total += len(rows)

    return total, sheets_with_data


# ---------------------------------------------------------------------------
# Bill of Quantities (BOQ)
# ---------------------------------------------------------------------------

BOQ_FORMATS: list[dict] = [
    {
        "label":    "Excel (.xlsx)",
        "ext":      ".xlsx",
        "filter":   "Excel Files (*.xlsx)",
        "requires": None,
    },
    {
        "label":    "OpenDocument (.ods)",
        "ext":      ".ods",
        "filter":   "OpenDocument Spreadsheet (*.ods)",
        "requires": "odf",           # pip install odfpy
    },
]

_BOQ_COLS = 6
_CAT_FILL = "EDEDED"
_HEAD_FILL = "D9D9D9"


def _num(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _build_boq(engine):
    """
    Build the BOQ as a format-neutral grid.
    Returns (cells, bold_rows, fills, widths, count):
      cells[(row, col)] = value | ("=FORMULA", cached_value)   (1-based)
      fills[row] = hex colour; widths = column widths in characters.
    """
    gi = engine.fetch_chunk("general_info") or {}
    cur = gi.get("project_currency", "")
    cells: dict = {}
    bold: set = set()
    fills: dict = {}

    cells[(1, 1)] = "BILL OF QUANTITIES"
    cells[(2, 1)] = f"Project: {gi.get('project_name', '')}"
    cells[(3, 1)] = f"Date: {_dt.date.today().isoformat()}"
    bold.add(1)
    hdr = 5
    heads = [
        "Sr. No.", "Description of Item", "Unit", "Quantity",
        f"Rate ({cur})" if cur else "Rate",
        f"Amount ({cur})" if cur else "Amount",
    ]
    for c, t in enumerate(heads, 1):
        cells[(hdr, c)] = t
    bold.add(hdr)
    fills[hdr] = _HEAD_FILL

    row, count = hdr + 1, 0
    cat_totals: list[tuple[str, float]] = []
    for cat_no, (sheet_name, chunk_key) in enumerate(CHUNKS, 1):
        cat = sheet_name.split("#", 1)[-1]
        comps = {
            n: [i for i in items if not i.get("state", {}).get("in_trash", False)]
            for n, items in (engine.fetch_chunk(chunk_key) or {}).items()
        }
        comps = {n: it for n, it in comps.items() if it}
        if not comps:
            continue
        cells[(row, 1)], cells[(row, 2)] = cat_no, cat.upper()
        bold.add(row)
        fills[row] = _CAT_FILL
        row += 1
        comp_totals: list[tuple[str, float]] = []
        for comp_no, (comp_name, items) in enumerate(comps.items(), 1):
            cells[(row, 1)], cells[(row, 2)] = f"{cat_no}.{comp_no}", comp_name
            bold.add(row)
            row += 1
            first, sub = row, 0.0
            for n, item in enumerate(items, 1):
                v = item.get("values", {})
                q, r = _num(v.get("quantity")), _num(v.get("rate"))
                cells[(row, 1)] = f"{cat_no}.{comp_no}.{n}"
                cells[(row, 2)] = v.get("material_name", "")
                cells[(row, 3)] = v.get("unit", "")
                cells[(row, 4)], cells[(row, 5)] = q, r
                cells[(row, 6)] = (f"=D{row}*E{row}", q * r)
                sub += q * r
                row += 1
                count += 1
            cells[(row, 2)] = f"Subtotal - {comp_name}"
            cells[(row, 6)] = (f"=SUM(F{first}:F{row - 1})", sub)
            bold.add(row)
            comp_totals.append((f"F{row}", sub))
            row += 1
        cells[(row, 2)] = f"Total - {cat}"
        cells[(row, 6)] = (
            "=" + "+".join(r for r, _ in comp_totals),
            sum(v for _, v in comp_totals),
        )
        bold.add(row)
        fills[row] = _CAT_FILL
        cat_totals.append((f"F{row}", sum(v for _, v in comp_totals)))
        row += 1
    if cat_totals:
        row += 1
        cells[(row, 2)] = "GRAND TOTAL"
        cells[(row, 6)] = (
            "=" + "+".join(r for r, _ in cat_totals),
            sum(v for _, v in cat_totals),
        )
        bold.add(row)
    return cells, bold, fills, (10, 50, 10, 14, 16, 18), count


def _write_boq_xlsx(path, cells, bold, fills, widths):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "BOQ"
    for (r, c), val in cells.items():
        cell = ws.cell(row=r, column=c, value=val[0] if isinstance(val, tuple) else val)
        if r in bold:
            cell.font = Font(bold=True, size=14 if r == 1 else 11)
        if c >= 4 and r > 5:
            cell.number_format = "#,##0.00"
    for r, colour in fills.items():
        for c in range(1, _BOQ_COLS + 1):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=colour)
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    wb.save(path)


def _write_boq_ods(path, cells, bold, fills, widths):
    import re
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.style import Style, TextProperties, TableCellProperties, TableColumnProperties
    from odf.table import Table, TableColumn, TableRow, TableCell
    from odf.text import P

    doc = OpenDocumentSpreadsheet()
    styles: dict = {}

    def style(is_bold, fill):
        key = (is_bold, fill)
        if key not in styles:
            st = Style(name=f"c{len(styles)}", family="table-cell")
            if is_bold:
                st.addElement(TextProperties(fontweight="bold"))
            if fill:
                st.addElement(TableCellProperties(backgroundcolor=f"#{fill}"))
            doc.automaticstyles.addElement(st)
            styles[key] = st
        return styles[key]

    def to_of(formula):
        body = re.sub(
            r"([A-F]\d+)(?::([A-F]\d+))?",
            lambda m: f"[.{m.group(1)}" + (f":.{m.group(2)}" if m.group(2) else "") + "]",
            formula,
        )
        return "of:" + body

    table = Table(name="BOQ")
    for w in widths:
        cs = Style(name=f"w{w}", family="table-column")
        cs.addElement(TableColumnProperties(columnwidth=f"{w * 0.19:.2f}cm"))
        doc.automaticstyles.addElement(cs)
        table.addElement(TableColumn(stylename=cs))

    for r in range(1, max(r for r, _ in cells) + 1):
        tr = TableRow()
        st = style(r in bold, fills.get(r))
        for c in range(1, _BOQ_COLS + 1):
            val = cells.get((r, c))
            if isinstance(val, tuple):
                tc = TableCell(valuetype="float", value=val[1],
                               formula=to_of(val[0]), stylename=st)
                tc.addElement(P(text=f"{val[1]:,.2f}"))
            elif isinstance(val, (int, float)):
                tc = TableCell(valuetype="float", value=val, stylename=st)
                tc.addElement(P(text=str(val)))
            elif val not in (None, ""):
                tc = TableCell(valuetype="string", stylename=st)
                tc.addElement(P(text=str(val)))
            else:
                tc = TableCell(stylename=st)
            tr.addElement(tc)
        table.addElement(tr)
    doc.spreadsheet.addElement(table)
    doc.save(path)


def export_boq(engine, path: str) -> int:
    """
    Export active materials as a single-sheet Bill of Quantities
    (category > component > items, subtotals, grand total; Amount = Quantity x Rate
    as live formulas). Format follows the file extension (.xlsx or .ods).
    Returns the number of item rows written.
    """
    cells, bold, fills, widths, count = _build_boq(engine)
    if path.lower().endswith(".ods"):
        _write_boq_ods(path, cells, bold, fills, widths)
    else:
        _write_boq_xlsx(path, cells, bold, fills, widths)
    return count
