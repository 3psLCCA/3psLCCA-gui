from __future__ import annotations

import re
from pathlib import Path

from pylatex import Command, NoEscape, Package
from pylatex.utils import escape_latex

from ..SETTINGS import LATEX_FONT_SIZE, REQUIRED_LATEX_PACKAGES, LATEX_TABLE_COLUMN_BG_ENABLED, LATEX_TABLE_COLUMN_BG_COLORS



EMDASH = r"\textemdash"
# 3psLCCA icon: page header and cover of every report (LCCA and Bill of Quantities).
DEFAULT_LOGO = Path(__file__).resolve().parents[2] / "gui" / "assets" / "logo" / "logo-3psLCCA.png"


def controller_chunk(controller, name: str) -> dict:
    """Chunk *name* from *controller* ({} if there is none or it cannot be read)."""
    for method_name in ("get_fresh_chunk", "get_chunk", "fetch_chunk"):
        method = getattr(controller, method_name, None)
        if callable(method):
            try:
                return method(name) or {}
            except Exception:
                pass
    return {}

def cmd(name: str, *arguments, options=None) -> str:
    """One LaTeX command via pylatex. Arguments and options are trusted
    LaTeX (not escaped); "" gives an empty {} argument."""
    return Command(
        name,
        [NoEscape(str(a)) for a in arguments] or None,
        options=NoEscape(options) if options else None,
    ).dumps()


def _generate_package_imports() -> list[str]:
    return [
        Package(pkg, options=options or None).dumps()
        for pkg, options in REQUIRED_LATEX_PACKAGES.items()
    ]


def _footer(with_total: bool) -> str:
    """Centre footer: "Page N of M" (M = last body page), or just "Page N"."""
    text = r"\small Page~\thepage"
    if with_total:
        text += r"~of~\pageref*{LastPage}"
    return cmd("fancyfoot", text, options="C")


def _header_logo() -> str:
    """Right header: the report logo, or "3PS LCCA" when the file is missing."""
    logo = cmd("includegraphics", r"\ReportHeaderLogo", options="height=0.65cm")
    return cmd("IfFileExists", r"\ReportHeaderLogo", logo, r"\small 3PS LCCA")


_CAPTION_SETUP = "font=small, labelfont=bf, labelsep=period, skip=4pt"


def _heading_format(level: str, size: str) -> str:
    return cmd("titleformat", "\\" + level, size + r"\bfseries\color{blue!55!black}",
               r"\the" + level, "0.75em", "")


V3_PREAMBLE = [
    cmd("documentclass", "article", options="12pt,a4paper"),
    "",
    *(_generate_package_imports()),
    cmd("usetikzlibrary", "calc"),
    "",
    # ── Captions setup ────────────────────────────────────────────────────────
    cmd("captionsetup", _CAPTION_SETUP),

    # ── List setup ────────────────────────────────────────────────────────────
    cmd("setlist", "noitemsep, topsep=4pt, partopsep=0pt"),

    # ── Core layout overrides ─────────────────────────────────────────────────
    cmd("setstretch", "1.15"),                 # comfortable reading spacing
    cmd("setlength", r"\parskip", "6pt"),      # space between paragraphs
    cmd("setlength", r"\parindent", "0pt"),    # no first-line indent (modern style)

    # ── Captions ──────────────────────────────────────────────────────────────
    Package("caption").dumps(),
    cmd("captionsetup", _CAPTION_SETUP),


    # ── Headers / footers ─────────────────────────────────────────────────────
    cmd("fancyhf", ""),
    cmd("providecommand", r"\ReportHeaderLogo", ""),
    # The 0.65cm header logo plus the text line need about 22.9pt; less makes
    # fancyhdr warn on every page.
    cmd("setlength", r"\headheight", "24pt"),
    cmd("renewcommand", r"\headrulewidth", "0.4pt"),
    cmd("renewcommand", r"\footrulewidth", "0.4pt"),
    cmd("fancyhead", r"\small\nouppercase{\leftmark}", options="L"),
    cmd("fancyhead", _header_logo(), options="R"),
    _footer(with_total=True),
    cmd("AtBeginDocument", cmd("pagestyle", "fancy")),

    # ── Section / ToC styling ─────────────────────────────────────────────────
    _heading_format("section", r"\Large"),
    _heading_format("subsection", r"\large"),
    _heading_format("subsubsection", r"\normalsize"),
    cmd("titlespacing*", r"\section", "0pt", "18pt", "8pt"),
    cmd("titlespacing*", r"\subsection", "0pt", "14pt", "6pt"),
    cmd("titlespacing*", r"\subsubsection", "0pt", "10pt", "4pt"),
    cmd("renewcommand", r"\contentsname", "Table of Contents"),
    cmd("renewcommand", r"\listtablename", "List of Tables"),
    cmd("renewcommand", r"\listfigurename", "List of Figures"),

    # ── Unicode shorthands ────────────────────────────────────────────────────
    cmd("DeclareUnicodeCharacter", "20B9", "Rs."),
    cmd("DeclareUnicodeCharacter", "2082", r"\textsubscript{2}"),
    cmd("DeclareUnicodeCharacter", "2013", "--"),
    cmd("DeclareUnicodeCharacter", "2014", "--"),
    # maths signs have no text glyph: without these, a name like
    # "Depth ≤3m" (in the SOR databases) stops pdflatex
    cmd("DeclareUnicodeCharacter", "2264", r"\ensuremath{\leq}"),
    cmd("DeclareUnicodeCharacter", "2265", r"\ensuremath{\geq}"),

    # ── Global table defaults ─────────────────────────────────────────────────
    cmd("setlength", r"\tabcolsep", "4pt"),
    cmd("renewcommand", r"\arraystretch", "1.18"),
    cmd("setlength", r"\LTleft", "0pt"),
    cmd("setlength", r"\LTright", "0pt"),
    cmd("setlength", r"\LTcapwidth", r"\textwidth"),
    cmd("BeforeBeginEnvironment", "tabular",
        cmd("begin", "adjustbox", r"max width=\linewidth")),
    cmd("AfterEndEnvironment", "tabular", cmd("end", "adjustbox")),
    cmd("AtBeginEnvironment", "tabular", cmd("footnotesize")),
    cmd("sloppy"),
]


def apply_table_column_backgrounds(latex: str) -> str:
    if not LATEX_TABLE_COLUMN_BG_ENABLED or not latex:
        return latex

    def _shade_spec(spec: str) -> str:
        colors = LATEX_TABLE_COLUMN_BG_COLORS
        column_pattern = r"(?P<modifier>>\{[^{}]*\})?(?P<column>[lcr]|p\{[^{}]+\})"
        if "".join(spec.split()) == "lll":
            return spec
        if len(list(re.finditer(column_pattern, spec))) <= 2:
            return spec
        idx = 0

        def repl(match):
            nonlocal idx
            modifier = match.group("modifier") or ""
            column = match.group("column")
            color = colors[idx % len(colors)]
            idx += 1
            marker = r"\columncolor{" + color + r"}"
            if modifier:
                return modifier.replace(r">{", r">{" + marker, 1) + column
            return r">{" + marker + r"}" + column

        return re.sub(column_pattern, repl, spec)

    def _replace_begin_specs(text: str, env: str) -> str:
        pattern = r"\begin{" + env + r"}{"
        pos = 0
        out = []
        while True:
            start = text.find(pattern, pos)
            if start == -1:
                out.append(text[pos:])
                return "".join(out)
            spec_start = start + len(pattern)
            depth = 1
            i = spec_start
            while i < len(text) and depth:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
            if depth:
                out.append(text[pos:])
                return "".join(out)
            spec = text[spec_start:i - 1]
            out.append(text[pos:spec_start])
            out.append(_shade_spec(spec))
            out.append("}")
            pos = i

    return _replace_begin_specs(_replace_begin_specs(latex, "longtable"), "tabular")





def build_report_v3_document(body: str, logo_path: str = "") -> str:
    """Wrap report body in the V3 LaTeX document shell (shared header and footer)."""
    logo_path = logo_path or DEFAULT_LOGO.as_posix()
    return "\n".join([
        *V3_PREAMBLE,
        cmd("renewcommand", r"\ReportHeaderLogo", logo_path),
        cmd("begin", "document"),
        LATEX_FONT_SIZE,
        body,
        cmd("end", "document"),
    ])


def front_matter(figures: bool = True) -> str:
    """TOC, list of tables, and list of figures (left out when *figures* is False)."""
    lof = [
        cmd("addcontentsline", "toc", "section", "List of Figures"),
        cmd("listoffigures"),
        clearpage(),
    ] if figures else []
    return "\n".join([
        clearpage(),
        cmd("pagenumbering", "roman"),
        # The page total counts only the arabic-numbered body, so the roman
        # front-matter pages show just their own number.
        _footer(with_total=False),
        cmd("tableofcontents"),
        clearpage(),
        cmd("addcontentsline", "toc", "section", "List of Tables"),
        cmd("listoftables"),
        clearpage(),
        *lof,
        cmd("pagenumbering", "arabic"),
        _footer(with_total=True),
    ])


def section(title: str) -> str:
    return Command("section", title).dumps()


def subsection(title: str) -> str:
    return Command("subsection", title).dumps()


def subsubsection(title: str) -> str:
    return Command("subsubsection", title).dumps()


def paragraph(text: str) -> str:
    gap = Command("par").dumps() + Command("medskip").dumps()
    return gap + " " + escape_latex(text) + gap


def clearpage() -> str:
    return Command("clearpage").dumps()


def appendix_counter(letter: str) -> str:
    letter = letter.upper()
    section_number = ord(letter) - ord("A") + 1
    lines = []
    if letter == "A":
        lines.append(cmd("appendix"))
    lines.extend([
        cmd("setcounter", "section", section_number),
        cmd("setcounter", "table", 0),
        cmd("setcounter", "figure", 0),
        cmd("renewcommand", r"\thetable", letter + "-" + cmd("arabic", "table")),
        cmd("renewcommand", r"\thefigure", letter + "-" + cmd("arabic", "figure")),
    ])
    return "\n".join(lines)


def appendix_heading(title: str) -> str:
    """Unnumbered appendix heading: the heading, its contents entry, and the
    running header mark. Without the mark a starred section leaves the page
    header showing the last numbered section."""
    return "\n".join([
        Command("section*", title).dumps(),
        Command("addcontentsline", ["toc", "section", title]).dumps(),
        Command("markboth", [title, title]).dumps(),
    ])


def format_value(value, decimals: int | None = None) -> str:
    if value in (None, ""):
        return EMDASH
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals is not None:
        return f"{number:,.{decimals}f}"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def simple_table(
    caption: str,
    label: str,
    headers: list[str],
    rows: list[list],
    col_spec: str,
) -> str:
    if not rows:
        rows = [[EMDASH for _ in headers]]

    header = " & ".join(r"\textbf{" + escape_latex(h) + "}" for h in headers) + r" \\"
    body = [
        " & ".join(_cell(c) for c in row) + r" \\"
        for row in rows
    ]

    return "\n".join([
        r"\begin{longtable}{" + col_spec + r"}",
        r"\caption{" + escape_latex(caption) + r"}\label{" + label + r"}\\",
        r"\toprule",
        header,
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        header,
        r"\midrule",
        r"\endhead",
        r"\midrule",
        r"\multicolumn{" + str(len(headers)) + r"}{r}{\footnotesize\textit{continued on next page}} \\",
        r"\endfoot",
        r"\bottomrule",
        r"\endlastfoot",
        *body,
        r"\end{longtable}",
    ])


def wide_block(latex: str, size: str = r"\scriptsize") -> str:
    if not latex:
        return ""
    latex = latex.replace(r"\begin{landscape}", "").replace(r"\end{landscape}", "")
    return "\n".join([
        cmd("begingroup"),
        size,
        cmd("centering"),
        cmd("setlength", r"\tabcolsep", "4pt"),
        cmd("setlength", r"\LTleft", r"\fill"),
        cmd("setlength", r"\LTright", r"\fill"),
        latex,
        cmd("normalsize"),
        cmd("endgroup"),
    ])


def _cell(value) -> str:
    if value in (None, ""):
        return EMDASH
    if value == EMDASH:
        return EMDASH
    return escape_latex(str(value))
