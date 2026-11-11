import shutil
import tempfile
from datetime import date
from pathlib import Path

from pylatex import LongTable, NoEscape
from pylatex.utils import bold, escape_latex

from ..gui.components.utils.common_requested_data import (
    get_currency, get_general_info, set_controller,
)
from ..gui.components.utils.definitions import STRUCTURE_CHUNKS, UNIT_DISPLAY
from .common_code import latex_layout
from .pdf_generation_v3.latex_helpers import (
    apply_table_column_backgrounds, build_report_v3_document,
    clearpage, section, subsection,
)
from .bridge_data_latex import bridge_data_to_latex
from .pdf_generation_v3.lcca_report_builder import _part, run_pdflatex
from .pdf_generation_v3.sections.title_page import (
    DISCLAIMER_BOQ, official_date as _official_date, title_page,
)
from .structure_work_data_latex import (
    _fmt, _legend, _mat_cell, get_all_structure_chunks, longtable_sections,
)

_N_COLS = 6
_COL_SPEC = latex_layout("boq")
_SUMMARY_SPEC = latex_layout("boq_summary")
_LOGO = Path(__file__).resolve().parents[1] / "gui" / "assets" / "logo" / "logo-3psLCCA.png"


def _num(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _strong(text: str) -> NoEscape:
    return NoEscape(r"\textbf{" + text + "}")


def _total_row(label: str, amount: float) -> list:
    return ["", _strong(escape_latex(label)), "", "", "", _strong(_fmt(amount))]


def _summary_table(totals: list, grand: float, currency: str, captioned: bool = True) -> str:
    """Category totals and the grand total, as a table of their own."""
    table = LongTable(_SUMMARY_SPEC)
    if captioned:
        table.append(NoEscape(r"\caption{Bill of Quantities: Summary} \label{tab:boq_summary} \\"))
    table.append(NoEscape(r"\toprule"))
    table.add_row([bold("Sr. No."), bold("Category"), bold(f"Amount ({currency})")])
    table.append(NoEscape(r"\midrule"))
    table.append(NoEscape(r"\endhead"))
    table.append(NoEscape(r"\bottomrule"))
    table.append(NoEscape(r"\endlastfoot"))
    for n, (name, amount) in enumerate(totals, 1):
        table.add_row([str(n), name, _fmt(amount)])
    table.append(NoEscape(r"\midrule"))
    table.add_row(["", _strong("GRAND TOTAL"), _strong(_fmt(grand))])
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
                source = item.get("meta", {}).get("source", "db")
                qty, rate = _num(v.get("quantity")), _num(v.get("rate"))
                sub += qty * rate
                rows.append([
                    f"{cat_no}.{comp_no}.{n}",
                    _mat_cell(v.get("material_name", ""), source),
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
        "legend": str(_legend(currency)),
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


def _cover_page(controller) -> str:
    """Cover page (title page v2) for the Bill of Quantities."""
    return title_page(controller, "Bill of Quantities", general=get_general_info(),
                         disclaimer=DISCLAIMER_BOQ, app_logo_path=str(_LOGO))


def boq_document(controller=None) -> str:
    """Complete LaTeX document: title page, contents, bridge data, detailed BOQ, summary of costs."""
    parts = boq_parts(controller)
    body = [_cover_page(controller), r"\tableofcontents", clearpage()]
    bridge = _part(controller, "Bridge Data", bridge_data_to_latex)
    if bridge.strip():
        body += [
            section("Bridge geometry and description"),
            bridge,
            clearpage(),
        ]
    if parts:
        body += [
            section("Detailed bill of quantities"),
            apply_table_column_backgrounds(parts["tables"]),
            parts["legend"],
            subsection("Summary of costs"),
            apply_table_column_backgrounds(parts["summary"]),
        ]
    return build_report_v3_document("\n\n".join(body), logo_path=_LOGO.as_posix())


def build_boq_pdf(controller, path: str) -> None:
    """Compile the BOQ to a PDF at *path* (needs pdflatex, not calculated results)."""
    set_controller(controller)
    with tempfile.TemporaryDirectory(prefix="3psLCCA_boq_") as tmp:
        work = Path(tmp)
        tex_path = work / "boq.tex"
        tex_path.write_text(boq_document(controller), encoding="utf-8")
        run_pdflatex(tex_path, work, "-draftmode")
        run_pdflatex(tex_path, work)
        pdf = tex_path.with_suffix(".pdf")
        if not pdf.exists():
            raise FileNotFoundError(f"PDF was not generated: {pdf}")
        shutil.copy2(pdf, path)
