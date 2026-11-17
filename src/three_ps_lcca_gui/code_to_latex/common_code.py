from pylatex import Command, Table, Tabular, MultiColumn, NoEscape
from pylatex.utils import bold, escape_latex
from ..gui.components.utils.form_builder.form_definitions import Section, FieldDef
from .html_to_latex import format_remarks_latex
from .SETTINGS import LATEX_TABLE_LAYOUTS


def longtable_head(table, caption: str, label: str, add_head) -> None:
    """Caption a pylatex LongTable and give it a head that repeats on every page.

    The caption and label are set once, on the first page. Continuation pages
    repeat the caption with an empty short title, so it neither adds a second
    List of Tables entry nor defines the label again. *add_head(table)* appends
    the column-heading rows (rules included) and is called once per head.
    """
    table.append(Command("caption", caption))
    table.append(Command("label", NoEscape(label)))
    table.append(NoEscape(r"\\"))
    add_head(table)
    table.append(Command("endfirsthead"))
    table.append(Command("caption", caption, options=NoEscape("")))
    table.append(NoEscape(r"\\"))
    add_head(table)
    table.end_table_header()


def entered_value_block(paragraph: str, details: list) -> str:
    """A summary paragraph followed by one bold "Label: value" line per detail.

    *paragraph* and each value are LaTeX; the labels are escaped.
    """
    medskip = Command("medskip").dumps()
    lines = "\n".join(
        "  " + Command("noindent").dumps() + bold(label + ":") + Command("quad").dumps()
        + " " + value + " " + Command("par").dumps() + Command("smallskip").dumps()
        for label, value in details
    )
    return (
        "\n" + medskip + "\n" + Command("noindent").dumps() + " " + paragraph
        + "\n\n" + medskip + "\n" + lines + "\n" + medskip + "\n"
    )


def latex_layout(name: str) -> str:
    return LATEX_TABLE_LAYOUTS[name]

def fields_to_latex(fields: list, data: dict, caption: str, label: str, unit_overrides: dict = None) -> str:
    """Build a pylatex table from a list of Section/FieldDef entries and a data dict.

    Columns: Title | Value and Unit
    Args:
        fields:         FIELDS list (mix of Section and FieldDef)
        data:           chunk dict {key: value}
        caption:        table caption string
        label:          LaTeX label string, e.g. "tab:bridge_data"
        unit_overrides: optional {field_key: unit_string} to replace FieldDef.unit at render time
    """
    tabular = Tabular(NoEscape(latex_layout("field_table")))
    tabular.append(NoEscape(r"\toprule"))

    first_section = True
    for entry in fields:
        if isinstance(entry, Section):
            if not first_section:
                tabular.append(NoEscape(r"\midrule"))
            first_section = False
            tabular.append(NoEscape(MultiColumn(2, align="l", data=bold(entry.title)).dumps() + r" \\"))
            tabular.append(NoEscape(r"\midrule"))
        elif isinstance(entry, FieldDef):
            raw = data.get(entry.key, "")
            if raw in ("", None):
                value = NoEscape(r"\textemdash")
            elif isinstance(raw, NoEscape):
                value = raw
            elif isinstance(raw, (int, float)):
                value = str(raw)
            else:
                value = str(raw)
            unit = (unit_overrides or {}).get(entry.key, entry.unit) or ""
            if unit:
                unit = unit if "\\" in unit else escape_latex(unit)
                value = NoEscape(f"{escape_latex(str(value))} {unit}")
            tabular.add_row(entry.title, value)

    tabular.append(NoEscape(r"\bottomrule"))

    table = Table(position="h!")
    table.append(NoEscape(r"\centering"))
    table.add_caption(caption)
    table.append(NoEscape(rf"\label{{{label}}}"))
    table.append(tabular)

    out = table.dumps()
    remarks = format_remarks_latex(data)
    if remarks:
        out += "\n\n" + remarks
    return out


