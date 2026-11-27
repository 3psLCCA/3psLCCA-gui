from __future__ import annotations

import base64
import errno
import tempfile
from datetime import date
from itertools import combinations
from pathlib import Path

from pylatex import (
    MiniPage, MultiColumn, NoEscape, Tabular, TikZ, TikZCoordinate,
    TikZNode, TikZOptions, TikZPath, UnsafeCommand,
)
from pylatex.base_classes import Environment
from pylatex.utils import bold, escape_latex

from ..latex_helpers import DEFAULT_LOGO, cmd as _c, controller_chunk as _chunk



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

_PERSON_FIELDS = ("Name", "Organization", "Address", "Email", "Phone")
_COVER_GEOMETRY = "left=2.6cm,right=2.2cm,top={top},bottom=1.4cm"


class _TitlePage(Environment):
    _latex_name = "titlepage"


def _colors() -> str:
    """Cover palette: band, hairline, the three pillar colours, ink and muted text."""
    palette = {"band": "EEF0F8", "hair": "D9DCE8", "lp": "8F8FFF", "lg": "84D400",
               "lo": "FF5A2D", "ink": "14172B", "mute": "3F4558"}
    return "\n".join(_c("definecolor", name, "HTML", hex_) for name, hex_ in palette.items())


def _new_command(name: str, body: str, args: int = 0) -> str:
    return UnsafeCommand("newcommand", "\\" + name, options=args or None,
                         extra_arguments=NoEscape(body)).dumps()


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
        out.append(_c("allowbreak", "").join(escape_latex(word[i:i + chunk]) for i in range(0, len(word), chunk))
                   if len(word) > chunk else escape_latex(word))
    return " ".join(out)


# Both cover tables (Project information, Evaluated by / Reviewed by) share one style:
# a bold heading row, no rules, the same row height and the same label column, so
# their values line up from one table to the next.
_ROW_STRETCH = _c("renewcommand", r"\arraystretch", "1.15")
_LABEL_WIDTH = "2.2cm"


def _head(title: str) -> str:
    return MultiColumn(2, align=NoEscape("@{}l@{}"), data=NoEscape(title)).dumps()


def _sect(title: str) -> str:
    return _c("sect", escape_latex(title))


def _lab(field: str) -> str:
    return _c("lab", escape_latex(field))


def _cell(value, limit: int, chunk: int = 14) -> str:
    return (_c("raggedright") + _c("arraybackslash") + _c("leavevmode") + _c("color", "ink")
            + fit(value, limit, chunk) + _c("strut"))


def _row(*cells: str) -> NoEscape:
    return NoEscape(" & ".join(cells) + r" \\")


def _project_info(rows: list[tuple[str, str]]) -> str:
    """Project information: label/value rows in the shared cover table style."""
    value_width = rf"\dimexpr\linewidth-{_LABEL_WIDTH}-2\tabcolsep\relax"
    table = Tabular(NoEscape(f"@{{}}p{{{_LABEL_WIDTH}}}p{{{value_width}}}@{{}}"))
    table.append(NoEscape(_head(_sect("Project information")) + r" \\"))
    for field, value in rows:
        table.append(_row(_lab(field), _cell(value, 80, 24)))
    return "%\n".join([
        _c("noindent") + _c("begingroup") + _ROW_STRETCH,
        table.dumps(),
        _c("endgroup"),
    ])


def _people(evaluated: tuple, reviewed: tuple) -> str:
    """Evaluated by / Reviewed by as ONE table whose rows run side by side. It is
    measured first: when it does not fit in what is left of the cover it moves, whole,
    to a continuation page."""
    gap = _c("textcolor", "hair", r"\vrule width 0.5pt")
    # Both halves are the same width with the same edges. The 5 mm either side of the
    # divider belongs to the divider column, so neither half's rules run into it.
    divider = ">" + "{" + _c("hspace", "5mm") + "}c<{" + _c("hspace", "5mm") + "}"
    half = f"p{{{_LABEL_WIDTH}}}p{{\\vw}}"
    table = Tabular(NoEscape(f"@{{}}{half}@{{}}{divider}@{{}}{half}@{{}}"))
    table.append(_row(_head(_sect("Evaluated by")), gap, _head(_sect("Reviewed by"))))
    for field, a, b in zip(_PERSON_FIELDS, evaluated, reviewed):
        table.append(_row(_lab(field), _cell(a, 160), gap, _lab(field), _cell(b, 160)))
    # Signature line: full width of its half, same grey and weight as the table rules.
    sig = _c("parbox", rf"\dimexpr{_LABEL_WIDTH}+\vw+2\tabcolsep\relax",
             _c("vspace", "1.3cm")
             + _c("textcolor", "hair", _c("rule", r"\linewidth", r"\arrayrulewidth"))
             + r"\\[-1pt]" + _lab("Signature"))
    table.append(_row(_head(sig), gap, _head(sig)))

    footer = MiniPage(width=NoEscape(r"\linewidth"), data=NoEscape(_c("covfooter")))
    fits = (r"\ifdim\dimexpr\ht\peoplebox+\dp\peoplebox+\ht\footbox+\dp\footbox+0.3cm\relax"
            r">\dimexpr\pagegoal-\pagetotal\relax")
    return "\n".join([
        _c("newlength", r"\vw")
        + _c("setlength", r"\vw", r"\dimexpr(\linewidth-4.4cm-10mm-4\tabcolsep-0.5pt)/2\relax"),
        _c("newsavebox", r"\peoplebox"),
        _c("sbox", r"\peoplebox", _ROW_STRETCH + "%\n" + table.dumps()),
        _c("newsavebox", r"\footbox") + _c("sbox", r"\footbox", footer.dumps()),
        _c("par") + _c("penalty") + "0",  # \penalty takes a bare number, not {0}
        # Not enough room left: finish this page with the footer and continue on a new one.
        fits,
        "  " + _c("vfill") + _c("covfooter")
        + _c("newgeometry", _COVER_GEOMETRY.format(top="2.2cm"))
        + _c("thispagestyle", "empty"),
        _c("fi"),
        _c("noindent") + _c("usebox", r"\peoplebox"),
    ])


_WORD_MAX = 20        # a single word longer than this is split
_HEADING_LIMIT = 60   # longer headings are clipped
_TITLE_WIDTH_PT = 455  # width of the title block (16.0 cm)
_EM = 0.46            # average bold-serif character width, in em
_MAX_PT, _MIN_PT = 40, 36


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
    space = _c("hspace", "0.25em")
    words = lambda s: space.join(escape_latex(w) for w in s.split(" "))  # noqa: E731
    return r"\\".join(words(s) for s in lines), size


def _cover_footer(disclaimer: str) -> str:
    """Footer shared by every page of the cover (page 1 and the continuation page)."""
    credit = MiniPage(width=NoEscape(r"0.40\linewidth"), pos="t", data=NoEscape(
        _c("small") + " " + bold("3psLCCA") + r"\\ Osdag, IIT Bombay\\ "
        + _c("href", "https://3pslcca.github.io/", _c("textit", "3pslcca.github.io"))))
    note = MiniPage(width=NoEscape(r"0.54\linewidth"), pos="t", data=NoEscape(
        _c("footnotesize") + _c("color", "mute") + _c("raggedright") + " "
        + escape_latex(disclaimer)))
    return (_c("par") + _c("noindent") + _c("rule", r"\linewidth", "0.5pt") + _c("par")
            + _c("vspace", "6pt") + _c("noindent") + credit.dumps() + _c("hfill")
            + note.dumps() + _c("par"))


def _bar(colour: str, x0: float, y0: float, x1: float, y1: float) -> TikZPath:
    return TikZPath([TikZCoordinate(x0, y0), "rectangle", TikZCoordinate(x1, y1)],
                    options=TikZOptions("fill=" + colour))


def _cover_art(logo: Path, agency: str, kicker: str, title: str, title_size: int,
               name: str) -> str:
    """Page overlay: the title band, the pillar-colour edges, both logos and the title."""
    art = TikZ(options=NoEscape(
        "remember picture,overlay,shift={(current page.south west)}"))
    art.append(_bar("band", 0, 17.8, 21, 25.9))
    art.append(_bar("lp", 0.32, 17.67, 7.213, 17.8))
    art.append(_bar("lg", 7.213, 17.67, 14.107, 17.8))
    art.append(_bar("lo", 14.107, 17.67, 21, 17.8))
    art.append(_bar("lp", 0, 19.8, 0.32, 29.7))
    art.append(_bar("lg", 0, 9.9, 0.32, 19.8))
    art.append(_bar("lo", 0, 0, 0.32, 9.9))
    art.append(TikZNode(
        options=TikZOptions(NoEscape("anchor=north east, inner sep=0pt")),
        at=TikZCoordinate(18.8, 28.7),
        text=NoEscape(_c("includegraphics", logo.as_posix(), options="height=1.8cm"))))
    if agency:
        agency_options = "anchor=north west, inner sep=0pt"
        agency_text = _c("includegraphics", Path(agency).as_posix(),
                         options="height=1.8cm,width=7cm,keepaspectratio")
    else:
        agency_options = ("anchor=north west, draw=mute!60, dashed, rounded corners=2pt, "
                          "inner sep=9pt, minimum height=1.8cm, text=mute")
        agency_text = _c("itshape") + " [Agency Logo]"
    art.append(TikZNode(options=TikZOptions(NoEscape(agency_options)),
                        at=TikZCoordinate(2.6, 28.7), text=NoEscape(agency_text)))
    kicker_line = (
        _c("textcolor", "lg!70!black", _c("large") + _c("bfseries") + " " + escape_latex(kicker))
        + r"\\[10pt]" if kicker else "")
    # \par inside the group, so the title's own line height applies
    heading = ("{" + _c("bfseries") + _c("fontsize", title_size, title_size)
               + _c("selectfont") + " " + title + _c("par") + "}")
    subtitle = _c("textcolor", "mute", _c("Large") + _c("itshape") + " " + fit(name, 80, 22))
    art.append(TikZNode(
        options=TikZOptions(NoEscape("anchor=west, text=ink, align=left, text width=16cm")),
        at=TikZCoordinate(2.6, 21.85),
        text=NoEscape(kicker_line + heading + _c("vspace", "12pt")
                      + _c("rule", "2.5cm", "0.8pt") + r"\\[8pt]" + subtitle)))
    # \noindent and % keep the overlay from indenting "Project information"
    return _c("noindent") + art.dumps() + "%"


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

    page = _TitlePage()
    for part in [
        _c("thispagestyle", "empty"),
        _colors(),
        # field labels plain grey, section headings bold sentence case (no small caps)
        _new_command("lab", _c("textcolor", "mute", _c("small") + " #1"), args=1),
        _new_command("sect", _c("textcolor", "ink", _c("bfseries") + " #1"), args=1),
        _new_command("covfooter", _cover_footer(disclaimer)),
        _cover_art(logo, agency, kicker, title, title_size, name),
        _c("color", "ink") + "%",
        _project_info([
            ("Project code", pick("project_code")),
            ("Description", pick("project_description", "remarks")),
            ("Date", official_date()),
        ]),
        _c("par") + _c("vspace", "0.8cm"),
        _people(evaluated, reviewed),
        _c("vfill") + _c("covfooter"),
    ]:
        page.append(NoEscape(part))
    return "\n".join([
        _c("newgeometry", _COVER_GEOMETRY.format(top="12.4cm")),
        page.dumps(),
        _c("restoregeometry"),
    ])
