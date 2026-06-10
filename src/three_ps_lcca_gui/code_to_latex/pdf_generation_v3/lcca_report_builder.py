from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

try:
    from three_ps_lcca_gui.gui.components.utils.common_requested_data import set_controller as _set_controller
except Exception:
    _set_controller = None

try:
    from osdag_latex_env import OsdagLatexEnv as _OsdagLatexEnv
    _PDFLATEX = str(getattr(_OsdagLatexEnv(), "pdflatex", "pdflatex"))
except Exception:
    _PDFLATEX = "pdflatex"

from pylatex.utils import escape_latex
from three_ps_lcca_gui.gui._CONFIG import ALLOW_TEX

# ─────────────────────────────────────────────────────────────────────────────
# Report Configuration Keys
# ─────────────────────────────────────────────────────────────────────────────
KEY_SHOW_TITLE_PAGE         = "show_title_page"
KEY_SHOW_INTRODUCTION       = "show_introduction"
KEY_SHOW_BRIDGE_DESC        = "show_bridge_desc"
KEY_SHOW_FINANCIAL          = "show_financial"
KEY_SHOW_CONSTRUCTION       = "show_construction"
KEY_SHOW_USE_STAGE          = "show_use_stage"
KEY_SHOW_AVG_TRAFFIC        = "show_avg_traffic"
KEY_SHOW_ROAD_TRAFFIC       = "show_road_traffic"
KEY_SHOW_PEAK_HOUR          = "show_peak_hour"
KEY_SHOW_VEHICLE_EMISSION   = "show_vehicle_emission"
KEY_SHOW_SOCIAL_CARBON      = "show_social_carbon"
KEY_SHOW_MATERIAL_EMISSION  = "show_material_emission"
KEY_SHOW_TRANSPORT_EMISSION = "show_transport_emission"
KEY_SHOW_ONSITE_EMISSION    = "show_onsite_emission"
KEY_SHOW_RECYCLING          = "show_recycling"
KEY_SHOW_TOC                = "show_toc"
KEY_SHOW_LCCA_RESULTS       = "show_lcca_results"
KEY_SHOW_SUMMARY            = "show_summary"
KEY_SHOW_APPENDIX_A         = "show_appendix_a"
KEY_SHOW_APPENDIX_B         = "show_appendix_b"
KEY_SHOW_APPENDIX_C         = "show_appendix_c"

# Plot Keys
KEY_PLOT_PILLAR_DONUT          = "plot_pillar_donut"
KEY_PLOT_SUSTAINABILITY_MATRIX = "plot_sustainability_matrix"
KEY_PLOT_STAGE_BARS            = "plot_stage_bars"
KEY_PLOT_PILLAR_BARS           = "plot_pillar_bars"


from ..bridge_data_latex import bridge_data_to_latex
from ..financial_data_latex import financial_data_to_latex
from ..maintenance_data_latex import maintenance_data_to_latex
from ..structure_work_data_latex import structure_work_data_to_latex
from ..traffic_and_road_data_latex.get_all_data import (
    diversion_emissions_to_latex,
    peak_hour_distribution_to_latex,
    traffic_fields_to_latex,
    vehicle_data_to_latex,
    wpi_tables_to_latex,
)
from ..material_emissions_latex import material_emissions_to_latex
from ..transport_emissions_latex import transport_emissions_to_latex
from ..machinery_emissions_latex import machinery_emissions_to_latex
from ..recycling_latex import recycling_to_latex
from ..results_latex import results_to_latex
from .appendix_A_content import APPENDIX_A_LATEX
from .latex_helpers import (
    build_report_v3_document,
    clearpage,
    front_matter,
    section,
    subsection,
    title_page,
    wide_block,
)
from .sections.appendices import appendices_to_latex
from .sections.introduction import introduction_to_latex
from ..social_cost_data_latex import social_cost_data_to_latex
from ...report.plot_exporter import generate_plots


REPORT_SCHEMA = [
    {
        "title": "Title page",
        "key": KEY_SHOW_TITLE_PAGE,
        "render": lambda ctrl, config, paths, logo: title_page(_project_name(ctrl), logo_path=logo)
    },
    {
        "title": "Table of contents",
        "key": KEY_SHOW_TOC,
        "render": lambda ctrl, config, paths, logo: front_matter()
    },
    {
        "title": "Introduction",
        "key": KEY_SHOW_INTRODUCTION,
        "render": lambda ctrl, config, paths, logo: introduction_to_latex()
    },
    {
        "title": "Input data",
        "key": None,
        "render_header": lambda: clearpage() + "\n" + section("Input data"),
        "children": [
            {
                "title": "Bridge geometry and description",
                "key": KEY_SHOW_BRIDGE_DESC,
                "render": lambda ctrl, config, paths, logo: subsection("Bridge geometry and description") + "\n" + _part(ctrl, "Bridge Data", bridge_data_to_latex)
            },
            {
                "title": "Financial inputs",
                "key": KEY_SHOW_FINANCIAL,
                "render": lambda ctrl, config, paths, logo: subsection("Financial inputs") + "\n" + _part(ctrl, "Financial Data", financial_data_to_latex)
            },
            {
                "title": "Construction data",
                "key": KEY_SHOW_CONSTRUCTION,
                "render": lambda ctrl, config, paths, logo: subsection("Construction data") + "\n" + _part(ctrl, "Structure Work Data", structure_work_data_to_latex, wide=True, size=r"\footnotesize")
            },
            {
                "title": "Maintenance data",
                "key": KEY_SHOW_USE_STAGE,
                "render": lambda ctrl, config, paths, logo: subsection("Maintenance data") + "\n" + _part(ctrl, "Maintenance Data", maintenance_data_to_latex)
            },
            {
                "title": "Traffic data",
                "key": None,
                "render_header": lambda: subsection("Traffic data"),
                "children": [
                    {
                        "title": "Traffic and road data",
                        "key": KEY_SHOW_ROAD_TRAFFIC,
                        "render": lambda ctrl, config, paths, logo: _part(ctrl, "Traffic and Road Data", traffic_fields_to_latex)
                    },
                    {
                        "title": "Average daily traffic",
                        "key": KEY_SHOW_AVG_TRAFFIC,
                        "render": lambda ctrl, config, paths, logo: _part(ctrl, "Vehicle Traffic Data", vehicle_data_to_latex)
                    },
                    {
                        "title": "Traffic diversion emissions",
                        "key": KEY_SHOW_VEHICLE_EMISSION,
                        "render": lambda ctrl, config, paths, logo: _part(ctrl, "Traffic Diversion Emissions", diversion_emissions_to_latex)
                    },
                    {
                        "title": "Peak hour distribution",
                        "key": KEY_SHOW_PEAK_HOUR,
                        "render": lambda ctrl, config, paths, logo: _part(ctrl, "Peak Hour Distribution", peak_hour_distribution_to_latex)
                    },
                ]
            },
            {
                "title": "Environmental input data",
                "key": None,
                "render_header": lambda: subsection("Environmental input data"),
                "children": [
                    {
                        "title": "Social cost of carbon",
                        "key": KEY_SHOW_SOCIAL_CARBON,
                        "render": lambda ctrl, config, paths, logo: _part(ctrl, "Social Cost Data", social_cost_data_to_latex)
                    },
                    {
                        "title": "Material emission factors",
                        "key": KEY_SHOW_MATERIAL_EMISSION,
                        "render": lambda ctrl, config, paths, logo: _part(ctrl, "Material Emissions", material_emissions_to_latex, wide=True, size=r"\footnotesize")
                    },
                    {
                        "title": "Transport emissions",
                        "key": KEY_SHOW_TRANSPORT_EMISSION,
                        "render": lambda ctrl, config, paths, logo: _part(ctrl, "Transport Emissions", transport_emissions_to_latex, wide=True, size=r"\footnotesize")
                    },
                    {
                        "title": "On-site emissions",
                        "key": KEY_SHOW_ONSITE_EMISSION,
                        "render": lambda ctrl, config, paths, logo: _part(ctrl, "Machinery and Equipment Emissions", machinery_emissions_to_latex, wide=True, size=r"\footnotesize")
                    },
                ]
            },
            {
                "title": "Recycling data",
                "key": KEY_SHOW_RECYCLING,
                "render": lambda ctrl, config, paths, logo: subsection("Recycling data") + "\n" + _part(ctrl, "Recycling", recycling_to_latex, wide=True, size=r"\footnotesize")
            },
        ]
    },
    {
        "title": "LCCA results",
        "key": KEY_SHOW_LCCA_RESULTS,
        "render": lambda ctrl, config, paths, logo: clearpage() + "\n" + section("LCCA results") + "\n" + subsection("Life cycle cost results") + "\n" + _results_part(ctrl) + "\n" + _result_figures(paths)
    },
    {
        "title": "Summary and conclusions",
        "key": KEY_SHOW_SUMMARY,
        "render": lambda ctrl, config, paths, logo: clearpage() + "\n" + _summary_from_v3_content(ctrl)
    },
    {
        "title": "Appendices",
        "key": None,
        "children": [
            {
                "title": "Appendix A: Assumptions",
                "key": KEY_SHOW_APPENDIX_A,
                "render": lambda ctrl, config, paths, logo: clearpage() + "\n" + appendices_to_latex({KEY_SHOW_APPENDIX_A: True, KEY_SHOW_APPENDIX_B: False})
            },
            {
                "title": "Appendix B: Calculation methodology",
                "key": KEY_SHOW_APPENDIX_B,
                "render": lambda ctrl, config, paths, logo: clearpage() + "\n" + _fit_appendix_b_tables(appendices_to_latex({KEY_SHOW_APPENDIX_A: False, KEY_SHOW_APPENDIX_B: True}))
            },
            {
                "title": "Appendix C: Miscellaneous data",
                "key": KEY_SHOW_APPENDIX_C,
                "render": lambda ctrl, config, paths, logo: _appendix_c_wpi(ctrl)
            },
        ]
    },
]


def _project_name(controller=None) -> str:
    for method_name in ("get_fresh_chunk", "get_chunk", "fetch_chunk"):
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                data = method("general_info") or {}
                if data.get("project_name"):
                    return str(data["project_name"])
            except Exception:
                pass
    return "Unnamed Project"


def _call_exporter(controller, exporter: Callable, title: str) -> str:
    try:
        latex = exporter(controller)
    except Exception as exc:
        print(f"[structured_code_to_latex_report] {title} failed: {exc}")
        return ""
    return latex if latex and latex.strip() else ""


def _chunk(controller, name: str) -> dict:
    for method_name in ("get_fresh_chunk", "get_chunk", "fetch_chunk"):
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                return method(name) or {}
            except Exception:
                pass
    return {}





def _part(controller, title: str, exporter: Callable, wide: bool = False, size: str = r"\scriptsize") -> str:
    latex = _call_exporter(controller, exporter, title)
    latex = latex.replace(r"\begin{table}[h!]", r"\begin{table}[H]")
    latex = latex.replace(r"\begin{table}[htbp]", r"\begin{table}[H]")
    if wide:
        latex = wide_block(latex, size=size)
    return latex


def _sum_result_numbers(value, key: str = "") -> float:
    if isinstance(value, (int, float)):
        number = float(value)
        return -number if key == "total_scrap_value" else number
    if isinstance(value, dict):
        return sum(_sum_result_numbers(v, k) for k, v in value.items())
    if isinstance(value, list):
        return sum(_sum_result_numbers(v) for v in value)
    return 0.0


def _summary_replacements(controller) -> tuple[str, str, str, str]:
    cache = _valid_result_cache(controller)
    results = cache.get("results", {}) if isinstance(cache, dict) else {}
    if not results:
        return "", "", "", ""

    stages = [
        ("initial_stage", "Initial stage"),
        ("use_stage", "Use stage"),
        ("reconstruction", "Reconstruction"),
        ("end_of_life", "End-of-life"),
    ]
    pillars = [
        ("economic", "Economic"),
        ("environmental", "Environmental"),
        ("social", "Social"),
    ]

    stage_totals = {
        label: _sum_result_numbers(results.get(key, {}))
        for key, label in stages
        if results.get(key)
    }
    pillar_totals = {
        label: sum(_sum_result_numbers(results.get(stage_key, {}).get(key, {})) for stage_key, _ in stages)
        for key, label in pillars
    }
    grand_total = sum(stage_totals.values())
    if not grand_total:
        return "", "", "", ""

    stage_label, stage_value = max(stage_totals.items(), key=lambda item: item[1])
    pillar_label, pillar_value = max(pillar_totals.items(), key=lambda item: item[1])
    return (
        escape_latex(stage_label),
        f"{(stage_value / grand_total) * 100:.2f}",
        escape_latex(pillar_label),
        f"{(pillar_value / grand_total) * 100:.2f}",
    )


def _summary_from_v3_content(controller=None) -> str:
    marker = "Appendix A: Assumptions"
    marker_pos = APPENDIX_A_LATEX.find(marker)
    if marker_pos == -1:
        return ""
    end = APPENDIX_A_LATEX.rfind(r"\section*", 0, marker_pos)
    if end == -1:
        return ""
    content = APPENDIX_A_LATEX[:end]
    remove_from = content.find(r"\begin{itemize}")
    if remove_from != -1:
        content = content[:remove_from]
    content = content.replace(r"\clearpage", r"\clearpage")
    content = content.replace(
        r"\section*{\fontsize{14pt}{16pt}\selectfont\bfseries Summary and Conclusions}",
        r"\section{Summary and conclusions}",
    )
    content = content.replace(
        r"\addcontentsline{toc}{section}{Summary and Conclusions}",
        "",
    )
    stage_label, stage_pct, pillar_label, pillar_pct = _summary_replacements(controller)
    if stage_label:
        content = content.replace(
            r"The most contributing stage of the life cycle is \underline{\hspace{3cm}} "
            "\n"
            r"contributing to around \underline{\hspace{2cm}}\% of the total life cycle cost.",
            rf"The most contributing stage of the life cycle is \textbf{{{stage_label}}} "
            rf"contributing to around \textbf{{{stage_pct}\%}} of the total life cycle cost.",
        )
    if pillar_label:
        content = content.replace(
            r"The most contributing pillar is \underline{\hspace{3cm}} contributing to around \underline{\hspace{2cm}}\% of the total life cycle cost.",
            rf"The most contributing pillar is \textbf{{{pillar_label}}} contributing to around \textbf{{{pillar_pct}\%}} of the total life cycle cost.",
        )
    return content


def _fit_appendix_b_tables(latex: str) -> str:
    marker = "Appendix B: Calculation"
    marker_pos = latex.find(marker)
    if marker_pos == -1:
        return latex

    prefix = latex[:marker_pos]
    appendix_b = latex[marker_pos:]
    appendix_b = appendix_b.replace(
        r"{\fontsize{9pt}{11pt}\selectfont",
        r"{\fontsize{7pt}{8.5pt}\selectfont",
    )
    appendix_b = appendix_b.replace(
        r"\everymath{\fontsize{9pt}{11pt}\selectfont}",
        r"\everymath{\fontsize{7pt}{8.5pt}\selectfont}",
    )
    appendix_b = appendix_b.replace(
        r"\everydisplay{\fontsize{9pt}{11pt}\selectfont}",
        r"\everydisplay{\fontsize{7pt}{8.5pt}\selectfont}",
    )
    appendix_b = appendix_b.replace(
        r"\setlength{\tabcolsep}{3pt}",
        r"\setlength{\tabcolsep}{1.5pt}",
    )
    appendix_b = appendix_b.replace(
        r"\begin{tabular}{|p{0.18\linewidth}|p{0.72\linewidth}|}",
        r"\begin{tabular}{|p{0.15\linewidth}|p{0.79\linewidth}|}",
    )
    appendix_b = appendix_b.replace(r"\makebox[\linewidth][c]{$", r"$")
    appendix_b = appendix_b.replace(r"$} \\ \hline", r"$ \\ \hline")
    return prefix + appendix_b


class _ResultCacheController:
    def __init__(self, controller, cache: dict):
        self._controller = controller
        self._cache = cache

    def get_chunk(self, name: str):
        if name == "comparison_cache":
            return self._cache
        return _chunk(self._controller, name)


def _valid_result_cache(controller) -> dict:
    cache = _chunk(controller, "comparison_cache")
    if isinstance(cache, dict) and cache.get("is_valid") and cache.get("results"):
        return cache
    return {}


def _results_part(controller) -> str:
    cache = _valid_result_cache(controller)
    if not cache:
        return r"\textit{No calculated LCCA results available.}"
    latex = results_to_latex(_ResultCacheController(controller, cache))
    return wide_block(latex, size=r"\footnotesize")


def _plot_figure(plot_paths: dict | None, key: str, caption: str) -> str:
    filename = (plot_paths or {}).get(key)
    if not filename:
        return ""
    filename = str(filename).replace("\\", "/")
    return "\n".join([
        r"\begin{figure}[H]",
        r"\centering",
        r"\includegraphics[width=0.88\textwidth]{" + filename + r"}",
        r"\caption{" + escape_latex(caption) + r"}",
        r"\end{figure}",
    ])


def _result_figures(plot_paths: dict | None) -> str:
    return "\n\n".join(part for part in [
        _plot_figure(plot_paths, KEY_PLOT_PILLAR_DONUT, "LCC components results"),
        _plot_figure(plot_paths, KEY_PLOT_STAGE_BARS, "Distribution of 3PS and 3 stages of LCC"),
        _plot_figure(plot_paths, KEY_PLOT_SUSTAINABILITY_MATRIX, "Distribution of 3PS and sustainability pillars of LCC"),
        _plot_figure(plot_paths, KEY_PLOT_PILLAR_BARS, "Distribution of various components of road user cost during construction"),
    ] if part and part.strip())


def _appendix_c_wpi(controller) -> str:
    latex = _call_exporter(controller, wpi_tables_to_latex, "WPI Tables")
    if not latex:
        return ""
    latex = latex.replace(r"\begin{landscape}", "").replace(r"\end{landscape}", "")
    latex = latex.replace(r"\begin{table}[h!]", r"\begin{table}[H]")
    return "\n\n".join([
        r"\clearpage",
        r"\begin{landscape}",
        r"\section*{Appendix C: Miscellaneous data}",
        r"\addcontentsline{toc}{section}{Appendix C: Miscellaneous data}",
        r"\begingroup",
        r"\scriptsize",
        r"\centering",
        r"\setlength{\tabcolsep}{2pt}",
        r"\setlength{\LTleft}{\fill}",
        r"\setlength{\LTright}{\fill}",
        latex,
        r"\normalsize",
        r"\endgroup",
        r"\end{landscape}",
    ])


def _render_schema_item(item, controller, config, plot_paths, logo_path):
    """Recursively render schema items based on config toggles."""
    # If the item has a key, check if it's enabled
    key = item.get("key")
    if key and not config.get(key, True):
        return ""

    # If it's a parent (has children)
    if "children" in item:
        child_content = []
        for child in item["children"]:
            child_content.append(_render_schema_item(child, controller, config, plot_paths, logo_path))
        
        body = "\n\n".join(c for c in child_content if c.strip())
        if not body:
            return ""
            
        header = ""
        if "render_header" in item:
            header = item["render_header"]()
            
        return header + "\n" + body

    # It's a leaf node with a render function
    if "render" in item:
        return item["render"](controller, config, plot_paths, logo_path)
    
    return ""


def lcca_report_body(controller=None, plot_paths: dict | None = None, config: dict | None = None, logo_path: str = "") -> str:
    config = config or {}
    
    parts = []
    for item in REPORT_SCHEMA:
        parts.append(_render_schema_item(item, controller, config, plot_paths, logo_path))
        
    return "\n\n".join(part for part in parts if part and part.strip())


def build_structured_code_to_latex_report_document(controller=None,plot_paths: dict | None = None,config: dict | None = None,logo_path: str = "",) -> str:
    return build_report_v3_document(
        lcca_report_body(controller, plot_paths, config=config, logo_path=logo_path)
    )


def _dedupe_lot_entries(lot_path: Path) -> None:
    if not lot_path.exists():
        return
    seen = set()
    output = []
    pattern = re.compile(r"\\contentsline \{table\}\{\\numberline \{([^}]*)\}")
    for line in lot_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.search(line)
        if not match:
            output.append(line)
            continue
        table_no = match.group(1)
        if table_no in seen:
            continue
        seen.add(table_no)
        output.append(line)
    lot_path.write_text("\n".join(output) + "\n", encoding="utf-8")


def _copy_static_assets(work_dir: Path) -> None:
    src = Path(__file__).resolve().parent / "images" / "image_1.png"
    if not src.exists():
        return

    dst = work_dir.parent / "pdf_generation_v3" / "images" / "image_1.png"
    dst.parent.mkdir(parents=True, exist_ok=True)

    if src.resolve() == dst.resolve():
        return

    shutil.copy2(src, dst)


def compile_lcca_report_pdf(
    controller=None,
    output_dir: str | Path | None = None,
    filename: str = "structured_code_to_latex_report",
    keep_artifacts: bool = False,
    config: dict | None = None,
) -> tuple[Path | None, Path]:
    if _set_controller is not None:
        try:
            _set_controller(controller)
        except Exception:
            pass

    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "tests"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    final_tex_path = output_dir / f"{filename}.tex"
    final_pdf_path = output_dir / f"{filename}.pdf"

    cleanup = None
    try:
        if keep_artifacts:
            work_dir = output_dir
        else:
            cleanup = tempfile.TemporaryDirectory(prefix="3psLCCA_report_")
            work_dir = Path(cleanup.name)

        tex_path = work_dir / f"{filename}.tex"
        pdf_path = work_dir / f"{filename}.pdf"
        _copy_static_assets(work_dir)

        plot_paths = {}
        try:
            cache = _valid_result_cache(controller)
            if cache.get("results"):
                currency = (
                    cache.get("currency")
                    or _chunk(controller, "general_info").get("project_currency")
                    or "INR"
                )
                plot_paths = generate_plots(cache["results"], str(work_dir), str(currency))
        except Exception as exc:
            print(f"[structured_code_to_latex_report] chart generation failed: {exc}")

        logo_file = Path(__file__).resolve().parents[2] / "gui" / "assets" / "logo" / "3pslcca_header.png"
        logo_path = os.path.relpath(logo_file, work_dir).replace("\\", "/")
        tex_content = build_structured_code_to_latex_report_document(
            controller,
            plot_paths,
            config=config,
            logo_path=logo_path,
        )
        tex_path.write_text(tex_content, encoding="utf-8")
        # Only write .tex to final output dir if ALLOW_TEX is True
        if ALLOW_TEX:
            final_tex_path.write_text(tex_content, encoding="utf-8")

        if not shutil.which(_PDFLATEX):
            raise RuntimeError(
                "pdflatex was not found. To generate PDF reports, please install a TeX distribution:\n"
                "  • Windows: MiKTeX — https://miktex.org\n"
                "  • Windows: TeX Live — https://tug.org/texlive\n"
                "  • macOS:   MacTeX — https://www.tug.org/mactex\n"
                "  • Linux:   sudo apt install texlive-latex-recommended\n\n"
                "After installation, restart the application."
            )

        def _run_pdflatex(*extra_args):
            result = subprocess.run(
                [_PDFLATEX, "-interaction=nonstopmode", *extra_args, tex_path.name],
                cwd=work_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                log_file = tex_path.with_suffix(".log")
                log_snippet = ""
                if log_file.exists():
                    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    error_lines = [l for l in lines if l.startswith("!") or "Error" in l or "error" in l]
                    log_snippet = "\n".join(error_lines[-30:]) if error_lines else "\n".join(lines[-40:])
                
                tex_msg = f"\n\nThe .tex file has been saved to:\n  {final_tex_path}" if ALLOW_TEX else ""
                raise RuntimeError(
                    f"pdflatex failed (exit {result.returncode}).\n\n"
                    f"LaTeX errors:\n{log_snippet or result.stdout[-3000:] or '(no output)'}{tex_msg}"
                )

        lot_path = tex_path.with_suffix(".lot")
        _run_pdflatex("-draftmode")
        _dedupe_lot_entries(lot_path)
        _run_pdflatex()

        _dedupe_lot_entries(lot_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF was not generated: {pdf_path}")

        if pdf_path.resolve() != final_pdf_path.resolve():
            shutil.copy2(pdf_path, final_pdf_path)

        return (final_tex_path if ALLOW_TEX else None), final_pdf_path

    finally:
        if cleanup is not None:
            cleanup.cleanup()
