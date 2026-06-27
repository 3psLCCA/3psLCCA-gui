from pylatex import LongTable, MultiColumn, NoEscape
from pylatex.utils import bold, escape_latex
from ..gui.components.outputs.lcc_data import _MASTER_ROWS, _CREDIT_KEYS, _get
from .SETTINGS import DECIMAL_PLACES_FOR_LATEX

_N_COLS  = 3
_COL_SPEC = "p{10cm}lr"

_CAT_LABELS = {
    "economic":      "Economic",
    "environmental": "Environmental",
    "social":        "Social",
}


def _fmt(val: float) -> str:
    return f"{val:,.{DECIMAL_PLACES_FOR_LATEX}f}"


def _bold_val(val: float) -> NoEscape:
    return NoEscape(r"\textbf{" + _fmt(val) + r"}")


def _stage_header(title: str) -> NoEscape:
    return NoEscape(
        MultiColumn(_N_COLS, align="l", data=bold(title)).dumps() + r" \\"
    )


def _cat_header(cat: str) -> NoEscape:
    label = escape_latex(_CAT_LABELS.get(cat, cat))
    return NoEscape(
        MultiColumn(_N_COLS, align="l",
                    data=NoEscape(r"\quad\textit{" + label + r"}")).dumps() + r" \\"
    )


def _item_row(label: str, cat: str, val: float) -> list:
    return [
        NoEscape(r"\hangindent=2em\hangafter=1 \quad\quad " + escape_latex(label)),
        escape_latex(_CAT_LABELS.get(cat, cat)),
        _fmt(val),
    ]


def results_to_latex(controller) -> str:
    cache = (controller.get_chunk("comparison_cache") or {}) if controller else {}
    if not cache.get("is_valid"):
        return ""

    results  = cache.get("results", {})
    currency = cache.get("currency", "")

    has_recon = bool(results.get("reconstruction"))

    table = LongTable(_COL_SPEC)

    # ── Caption (inside longtable so it repeats on continued pages) ───────────
    table.append(NoEscape(r"\caption{Life Cycle Cost Analysis Results} "
                          r"\label{tab:lcca_results} \\"))

    # ── Repeating header ──────────────────────────────────────────────────────
    table.append(NoEscape(r"\toprule"))
    table.add_row(["Description", "Category", f"Present Value ({currency})"])
    table.append(NoEscape(r"\midrule"))
    table.append(NoEscape(r"\endhead"))

    # ── Continued footer (every page except last) ─────────────────────────────
    table.append(NoEscape(r"\midrule"))
    table.append(NoEscape(
        rf"\multicolumn{{{_N_COLS}}}{{r}}{{\footnotesize\textit{{continued on next page}}}} \\"
    ))
    table.append(NoEscape(r"\endfoot"))

    # ── Last footer ───────────────────────────────────────────────────────────
    table.append(NoEscape(r"\bottomrule"))
    table.append(NoEscape(r"\endlastfoot"))

    # ── Data rows ─────────────────────────────────────────────────────────────
    grand_total = 0.0
    first_stage = True

    report_stages = [
        ("initial_stage", "Initial Stage"),
        ("use_stage", "Use Stage"),
        ("end_of_life", "End-of-Life Stage"),
    ]

    for sk, chart_title in report_stages:

        if not first_stage:
            table.append(NoEscape(r"\midrule"))
        first_stage = False

        table.append(_stage_header(chart_title))
        table.append(NoEscape(r"\midrule"))

        source_stages = [sk, "reconstruction"] if sk == "end_of_life" and has_recon else [sk]
        stage_rows = [(s, cat, key, lbl) for s, cat, key, lbl in _MASTER_ROWS if s in source_stages]
        current_cat = None
        stage_total = 0.0

        for source_sk, cat, key, label in stage_rows:
            if cat != current_cat:
                table.append(_cat_header(cat))
                current_cat = cat

            val = _get(results, source_sk, cat, key)
            display_val = -val if key in _CREDIT_KEYS else val
            stage_total += display_val
            grand_total += display_val
            if source_sk == "reconstruction":
                label = f"Reconstruction | {label}"
            table.add_row(_item_row(label, cat, display_val))

        table.append(NoEscape(r"\cmidrule(l){1-3}"))
        table.add_row([bold(f"Stage Total — {chart_title}"), "", _bold_val(stage_total)])

    # ── Grand total ───────────────────────────────────────────────────────────
    table.append(NoEscape(r"\midrule"))
    table.add_row([bold("Total life cycle cost"), "", _bold_val(grand_total)])

    return table.dumps()
