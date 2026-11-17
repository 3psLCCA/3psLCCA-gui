from __future__ import annotations

import base64
import errno
import tempfile
from datetime import date
from itertools import combinations
from pathlib import Path

from pylatex.utils import escape_latex

from ..latex_helpers import DEFAULT_LOGO, controller_chunk as _chunk



def _first(data: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _image_value_to_path(value: str, name: str) -> str:
    if not value:
        return ""
    # A base64-encoded image is far longer than any real path, so probing it
    # with Path.exists() raises OSError (ENAMETOOLONG). Treat that as "not a
    # path" and fall through to base64 decoding; re-raise anything else.
    try:
        if Path(value).exists():
            return str(Path(value))
    except OSError as exc:
        if exc.errno != errno.ENAMETOOLONG:
            raise
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        return ""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif raw.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    else:
        return ""
    out_path = Path(tempfile.gettempdir()) / f"3ps_lcca_{name}{suffix}"
    out_path.write_bytes(raw)
    return str(out_path)



DISCLAIMER_BOQ = (
    "Generated using 3psLCCA. Quantities, rates and amounts are taken from the "
    "user-provided structure data. The evaluating agency is solely responsible for "
    "the accuracy of the input data and for any use of this document."
)
DISCLAIMER_REPORT = (
    "Generated using 3psLCCA. The software is provided without any warranty, express or "
    "implied. The life cycle cost analysis (LCCA) results depend on user-provided inputs. "
    "The evaluating agency is solely responsible for the accuracy of the input data and "
    "for any use of the results."
)

_COLORS = "\n".join([
    r"\definecolor{band}{HTML}{EEF0F8}\definecolor{hair}{HTML}{D9DCE8}",
    r"\definecolor{lp}{HTML}{8F8FFF}\definecolor{lg}{HTML}{84D400}\definecolor{lo}{HTML}{FF5A2D}",
    r"\definecolor{ink}{HTML}{14172B}\definecolor{mute}{HTML}{3F4558}",
])
_PERSON_FIELDS = ("Name", "Organization", "Address", "Email", "Phone")


def official_date(today: date | None = None) -> str:
    """Date as written on official documents, e.g. '11 November 2026'."""
    d = today or date.today()
    return f"{d.day} {d:%B %Y}"


def fit(value: str, limit: int, chunk: int = 14) -> str:
    """Escape a value so it can never break the page: clip to ``limit`` characters and
    allow a line break inside any unbroken run longer than ``chunk``."""
    value = " ".join(str(value or "").split())
    if len(value) > limit:
        value = value[:limit - 3].rstrip() + "..."
    out = []
    for word in value.split(" "):
        out.append(r"\allowbreak{}".join(escape_latex(word[i:i + chunk]) for i in range(0, len(word), chunk))
                   if len(word) > chunk else escape_latex(word))
    return " ".join(out)


# Both cover tables (Project information, Evaluated by / Reviewed by) share one style:
# a bold heading row, no rules, the same row height and the same label column, so
# their values line up from one table to the next.
_ROW_STRETCH = r"\renewcommand{\arraystretch}{1.15}"
_HEAD = r"\multicolumn{2}{@{}l@{}}"


def _lab(field: str) -> str:
    return r"\lab{" + escape_latex(field) + "}"


def _cell(value, limit: int, chunk: int = 14) -> str:
    return r"\raggedright\arraybackslash\leavevmode\color{ink}" + fit(value, limit, chunk) + r"\strut"


def _project_info(rows: list[tuple[str, str]]) -> str:
    """Project information: label/value rows in the shared cover table style."""
    body = "".join(_lab(f) + " & " + _cell(v, 80, 24) + r" \\" + "\n" for f, v in rows)
    return "\n".join([
        r"\noindent{" + _ROW_STRETCH + "%",
        r"\begin{tabular}{@{}p{2.2cm}p{\dimexpr\linewidth-2.2cm-2\tabcolsep\relax}@{}}",
        _HEAD + r"{\sect{Project information}} \\",
        body + r"\end{tabular}}",
    ])


def _people(evaluated: tuple, reviewed: tuple) -> str:
    """Evaluated by / Reviewed by as ONE table whose rows run side by side. It is
    measured first: when it does not fit in what is left of the cover it moves, whole,
    to a continuation page."""
    cell = lambda v: _cell(v, 160, 14)  # noqa: E731
    lab = _lab
    gap = r"{\color{hair}\vrule width 0.5pt}"
    # Both halves are the same width with the same edges. The 5 mm either side of the
    # divider belongs to the divider column, so neither half's rules run into it.
    half = _HEAD
    rows = "".join(
        lab(f) + " & " + cell(a) + " & " + gap + " & " + lab(f) + " & " + cell(b)
        + r" \\" + "\n"
        for f, a, b in zip(_PERSON_FIELDS, evaluated, reviewed))
    # Signature line: full width of its half, same grey and weight as the table rules.
    sig = (r"\parbox{\dimexpr2.2cm+\vw+2\tabcolsep\relax}{\vspace{1.3cm}"
           r"{\color{hair}\rule{\linewidth}{\arrayrulewidth}}\\[-1pt]\lab{Signature}}")
    return "\n".join([
        r"\newlength{\vw}\setlength{\vw}{\dimexpr(\linewidth-4.4cm-10mm-4\tabcolsep-0.5pt)/2\relax}",
        r"\newsavebox{\peoplebox}",
        r"\sbox{\peoplebox}{" + _ROW_STRETCH + "%",
        r"\begin{tabular}{@{}p{2.2cm}p{\vw}@{}>{\hspace{5mm}}c<{\hspace{5mm}}@{}p{2.2cm}p{\vw}@{}}",
        half + r"{\sect{Evaluated by}} & " + gap + r" & " + half + r"{\sect{Reviewed by}} \\",
        rows,
        half + "{" + sig + r"} & " + gap + r" & " + half + "{" + sig + r"} \\",
        r"\end{tabular}}",
        r"\newsavebox{\footbox}\sbox{\footbox}{\begin{minipage}{\linewidth}\covfooter\end{minipage}}",
        r"\par\penalty0",
        r"\ifdim\dimexpr\ht\peoplebox+\dp\peoplebox+\ht\footbox+\dp\footbox+0.3cm\relax>\dimexpr\pagegoal-\pagetotal\relax",
        r"  \vfill\covfooter\newgeometry{left=2.6cm,right=2.2cm,top=2.2cm,bottom=1.4cm}\thispagestyle{empty}",
        r"\fi",
        r"\noindent\usebox{\peoplebox}",
    ])


_WORD_MAX = 20        # a single word longer than this is split
_HEADING_LIMIT = 60   # longer headings are clipped
_TITLE_WIDTH_PT = 455  # width of the title block (16.0 cm)
_EM = 0.46            # average bold-serif character width, in em
_MAX_PT, _MIN_PT = 50, 36


def _size_for(lines: list[str]) -> float:
    """Largest font size at which the widest line still fills (but fits) the title block."""
    return min(_MAX_PT, _TITLE_WIDTH_PT / (_EM * max(len(s) for s in lines)))


def _split(words: list[str], n: int) -> list[str]:
    """Split ``words`` into ``n`` consecutive lines minimising the widest line."""
    best, best_w = None, None
    for cuts in combinations(range(1, len(words)), n - 1):
        bounds = (0, *cuts, len(words))
        lines = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
        w = max(len(s) for s in lines)
        if best_w is None or w < best_w:
            best, best_w = lines, w
    return best


def heading_lines(heading: str) -> list[str]:
    """Break a plain-text heading into the fewest balanced lines that still allow a
    large title; a word longer than a line is split so it can never run off the band."""
    text = " ".join(str(heading or "").split())
    if len(text) > _HEADING_LIMIT:
        text = text[:_HEADING_LIMIT - 3].rstrip() + "..."
    words: list[str] = []
    for word in text.split(" "):
        while len(word) > _WORD_MAX:
            words.append(word[:_WORD_MAX])
            word = word[_WORD_MAX:]
        if word:
            words.append(word)
    if not words:
        return [""]
    fallback = None
    for n in range(1, min(3, len(words)) + 1):
        fallback = _split(words, n)
        if _size_for(fallback) >= _MIN_PT:
            return fallback
    return fallback


def _heading_tex(lines: list[str]) -> tuple[str, int]:
    """LaTeX for the title lines and the font size that makes them fill the band."""
    size = int(max(_MIN_PT - 4, _size_for(lines)))
    words = lambda s: r"\hspace{0.25em}".join(escape_latex(w) for w in s.split(" "))  # noqa: E731
    return r"\\".join(words(s) for s in lines), size


def title_page(controller=None, heading: str = "Bill of Quantities", *,
               kicker: str = "", disclaimer: str = DISCLAIMER_REPORT,
               app_logo_path: str = "", general: dict | None = None) -> str:
    """LaTeX for the cover page (title page v2).

    ``heading`` is plain text, e.g. "Bill of Quantities" or "Bridge Life Cycle Cost
    Analysis Report"; it is wrapped and sized automatically. ``kicker`` is an optional
    small line above it (none by default).
    """
    title, title_size = _heading_tex(heading_lines(heading))
    g = general if general is not None else _chunk(controller, "general_info")
    name = _first(g, "project_name", default="Unnamed Project")
    agency = _image_value_to_path(_first(g, "agency_logo", "logo_path", "agency_logo_path"), "agency_logo")
    logo = Path(app_logo_path) if app_logo_path and Path(app_logo_path).is_file() else DEFAULT_LOGO
    pick = lambda *keys: _first(g, *keys)  # noqa: E731
    evaluated = (pick("contact_person", "agency_contact_person", "evaluated_by"),
                 pick("agency_name", "evaluating_agency"), pick("agency_address"),
                 pick("agency_email"), pick("agency_phone"))
    reviewed = (pick("reviewed_by", "reviewer_name"),
                pick("reviewer_organization", "review_agency"), pick("reviewer_address"),
                pick("reviewer_email"), pick("reviewer_phone"))
    if agency:
        agency_node = (r"\node[anchor=north west, inner sep=0pt] at (2.6,28.7) "
                       r"{\includegraphics[height=1.8cm,width=7cm,keepaspectratio]{" + Path(agency).as_posix() + r"}};")
    else:
        agency_node = (r"\node[anchor=north west, draw=mute!60, dashed, rounded corners=2pt, inner sep=9pt, "
                       r"minimum height=1.8cm, text=mute] at (2.6,28.7) {\itshape [Agency Logo]};")
    return "\n".join([
        r"\newgeometry{left=2.6cm,right=2.2cm,top=12.4cm,bottom=1.4cm}",
        r"\begin{titlepage}",
        r"\thispagestyle{empty}",
        _COLORS,
        # field labels plain grey, section headings bold sentence case (no small caps)
        r"\newcommand{\lab}[1]{\textcolor{mute}{\small #1}}",
        r"\newcommand{\sect}[1]{\textcolor{ink}{\bfseries #1}}",
        # footer shared by every page of the cover (page 1 and the continuation page)
        r"\newcommand{\covfooter}{\par\noindent\rule{\linewidth}{0.5pt}\par\vspace{6pt}"
        r"\noindent\begin{minipage}[t]{0.40\linewidth}\small\textbf{3psLCCA}\\ Osdag, IIT Bombay\\ "
        r"\href{https://3pslcca.github.io/}{\textit{3pslcca.github.io}}\end{minipage}\hfill"
        r"\begin{minipage}[t]{0.54\linewidth}\footnotesize\color{mute}\raggedright "
        + escape_latex(disclaimer) + r"\end{minipage}\par}",
        # \noindent and % keep the overlay from indenting "Project information"
        r"\noindent\begin{tikzpicture}[remember picture,overlay,shift={(current page.south west)}]%",
        r"  \fill[band] (0,17.8) rectangle (21,25.9);",
        r"  \fill[lp] (0.32,17.67) rectangle (7.213,17.8);",
        r"  \fill[lg] (7.213,17.67) rectangle (14.107,17.8);",
        r"  \fill[lo] (14.107,17.67) rectangle (21,17.8);",
        r"  \fill[lp] (0,19.8) rectangle (0.32,29.7);",
        r"  \fill[lg] (0,9.9) rectangle (0.32,19.8);",
        r"  \fill[lo] (0,0) rectangle (0.32,9.9);",
        r"  \node[anchor=north east, inner sep=0pt] at (18.8,28.7) "
        r"{\includegraphics[height=1.8cm]{" + logo.as_posix() + r"}};",
        "  " + agency_node,
        r"  \node[anchor=west, text=ink, align=left, text width=16cm] at (2.6,21.85)",
        r"    {" + (r"{\color{lg!70!black}\large\bfseries " + escape_latex(kicker) + r"}\\[10pt]"
                    if kicker else ""),
        r"     {\bfseries\fontsize{" + str(title_size) + "}{" + str(title_size + 2) + r"}\selectfont " + title + r"}\\[12pt]",
        r"     \rule{2.5cm}{0.8pt}\\[8pt]",
        r"     {\color{mute}\Large\itshape " + fit(name, 80, 22) + r"}};",
        r"\end{tikzpicture}%",
        r"\color{ink}%",
        _project_info([
            ("Project code", pick("project_code")),
            ("Description", pick("project_description", "remarks")),
            ("Date", official_date()),
        ]),
        r"\par\vspace{0.8cm}",
        _people(evaluated, reviewed),
        r"\vfill\covfooter",
        r"\end{titlepage}",
        r"\restoregeometry",
    ])
