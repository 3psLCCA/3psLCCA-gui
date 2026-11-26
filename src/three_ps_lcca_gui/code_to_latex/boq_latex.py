from pathlib import Path

from pylatex import LongTable, NoEscape
from pylatex.utils import bold

from ..gui.components.utils.common_requested_data import get_currency
from ..gui.components.structure.material_flags import material_flag
from ..gui.components.utils.definitions import STRUCTURE_CHUNKS, UNIT_DISPLAY
from ..gui.components.utils.display_format import to_number
from .common_code import latex_layout, longtable_head
from .pdf_generation_v3.latex_helpers import (
    apply_table_column_backgrounds, build_report_v3_document,
    clearpage, front_matter, section, subsection,
)
from .pdf_generation_v3.lcca_report_builder import (
    bridge_description, compile_report_pdf, input_data_heading,
)
from .pdf_generation_v3.sections.title_page import DISCLAIMER_BOQ, title_page
from .structure_work_data_latex import (
    _db_number, _fmt, _legend, _mat_cell, get_all_structure_chunks, longtable_sections,
    report_databases_of,
)

_N_COLS = 6
_COL_SPEC = latex_layout("boq")
_SUMMARY_SPEC = latex_layout("boq_summary")


def _total_row(label: str, amount: float) -> list:
    return ["", bold(label), "", "", "", bold(_fmt(amount))]


def _summary_table(totals: list, grand: float, currency: str, captioned: bool = True) -> str:
    """Category totals and the grand total, as a table of their own."""
    table = LongTable(_SUMMARY_SPEC)

    def head(t):
        t.append(NoEscape(r"\toprule"))
        t.add_row([bold("Sr. No."), bold("Category"), bold(f"Amount ({currency})")])
        t.append(NoEscape(r"\midrule"))

    if captioned:
        longtable_head(table, "Bill of Quantities: Summary", "tab:boq_summary", head)
    else:
        head(table)
        table.end_table_header()
    table.append(NoEscape(r"\bottomrule"))
    table.append(NoEscape(r"\endlastfoot"))
    for n, (name, amount) in enumerate(totals, 1):
        table.add_row([str(n), name, _fmt(amount)])
    table.append(NoEscape(r"\midrule"))
    table.add_row(["", bold("GRAND TOTAL"), bold(_fmt(grand))])
    return table.dumps()


def boq_parts(controller=None) -> dict | None:
    """
    Bill of Quantities pieces: one longtable per category (component blocks with
    Sr. No., item, unit, quantity, rate, amount, component subtotals and a category
    total), a legend, and a summary table with the grand total. Reads only the saved
    structure data, so no calculated results are needed. None if there are no items.
    """
    currency = get_currency()
    all_chunks = get_all_structure_chunks()
    databases = report_databases_of(all_chunks)
    headers = ["Sr. No.", "Description of Item", "Unit", "Quantity",
               f"Rate ({currency})", f"Amount ({currency})"]

    tables: list = []
    totals: list = []
    cat_no = 0
    n_items = 0
    for chunk_id, category in STRUCTURE_CHUNKS:
        comps = {
            name: [i for i in items if not i.get("state", {}).get("in_trash", False)]
            for name, items in (all_chunks.get(chunk_id) or {}).items()
        }
        comps = {name: items for name, items in comps.items() if items}
        if not comps:
            continue
        cat_no += 1
        sections: list = []
        cat_total = 0.0
        for comp_no, (comp, items) in enumerate(comps.items(), 1):
            rows, sub = [], 0.0
            n_items += len(items)
            for n, item in enumerate(items, 1):
                v = item.get("values", {})
                source = material_flag(item)
                qty, rate = to_number(v.get("quantity")), to_number(v.get("rate"))
                sub += qty * rate
                rows.append([
                    f"{cat_no}.{comp_no}.{n}",
                    _mat_cell(v.get("material_name", ""), source,
                              _db_number(item, databases)),
                    UNIT_DISPLAY.get(v.get("unit", ""), v.get("unit")) or "",
                    _fmt(qty), _fmt(rate), _fmt(qty * rate),
                ])
            rows.append(_total_row(f"Subtotal - {comp}", sub))
            cat_total += sub
            sections.append((f"{cat_no}.{comp_no}  {comp}", rows))
        sections[-1][1].append(_total_row(f"Total - {category}", cat_total))
        totals.append((category, cat_total))
        tables.append(longtable_sections(
            _COL_SPEC, _N_COLS, f"Bill of Quantities: {category}",
            f"tab:boq_{chunk_id}", headers, sections))
    if not tables:
        return None
    grand = sum(t for _, t in totals)
    return {
        "tables": "\n\n".join(tables),
        "legend": str(_legend(currency, databases)),
        "summary": _summary_table(totals, grand, currency),
        "summary_plain": _summary_table(totals, grand, currency, captioned=False),
        "grand": grand,
        "currency": currency,
        "n_categories": len(totals),
        "n_items": n_items,
    }


def boq_to_latex(controller=None) -> str:
    """The detailed BOQ tables, legend and summary table as one block ("" if empty)."""
    parts = boq_parts(controller)
    if not parts:
        return ""
    return "\n\n".join([
        parts["tables"], parts["legend"],
        subsection("Summary of costs"), parts["summary"],
    ])


def boq_document(controller=None) -> str:
    """Complete LaTeX document. A subset of the LCCA report: the same cover, front
    matter, bridge data section, header and footer, plus the detailed BOQ."""
    parts = boq_parts(controller)
    body = [
        title_page(controller, "Bill of Quantities", disclaimer=DISCLAIMER_BOQ),
        front_matter(figures=False),
        input_data_heading(),
        bridge_description(controller),
    ]
    if parts:
        body += [
            clearpage(),
            section("Detailed bill of quantities"),
            apply_table_column_backgrounds(parts["tables"]),
            parts["legend"],
            subsection("Summary of costs"),
            apply_table_column_backgrounds(parts["summary"]),
        ]
    return build_report_v3_document("\n\n".join(body))


def build_boq_pdf(controller, path: str) -> None:
    """Compile the BOQ to a PDF at *path* (needs pdflatex, not calculated results)."""
    out = Path(path)
    compile_report_pdf(controller, lambda _work_dir: boq_document(controller),
                       out.parent, out.stem)
