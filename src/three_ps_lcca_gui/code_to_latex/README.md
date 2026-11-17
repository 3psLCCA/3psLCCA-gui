# code_to_latex

Turns a project's data into LaTeX and compiles it to PDF. Read this before
editing anything in this folder. It applies to people and to AI agents alike.

These rules are the only ones. Code that breaks them is either listed under
[Known exceptions](#known-exceptions-not-yet-converted), and must not be
copied, or it is a bug. If a rule itself turns out to be wrong, change it here
in the same change that needs it, so the rules and the code never disagree.

## What this folder produces

| Output | Entry point | Called from |
|---|---|---|
| LCCA report PDF | `pdf_generation_v3/lcca_report_builder.py`: `compile_lcca_report_pdf()` | Outputs, report dialog (`gui/components/outputs/report_section_dialog.py`) and Dev menu, *LCCA PDF Report* |
| Bill of Quantities PDF | `boq_latex.py`: `build_boq_pdf()` | Structure, Excel/PDF export (`gui/components/structure/excel_exporter.py`) |
| Single-component `.tex` files | each `<component>_to_latex(controller)` | Dev menu, LaTeX (`gui/devmode.py`, `_LATEX_ENTRIES`) |

The BOQ is built from the same pieces as the LCCA report (cover, preamble,
header, footer), so a change to a shared piece changes both PDFs.

## Folder map

```
SETTINGS.py              decimals, font size, required packages, table column layouts
common_code.py           shared table helpers: fields_to_latex, longtable_head, entered_value_block, latex_layout
html_to_latex.py         rich-text remarks to LaTeX (format_remarks_latex)
<component>_latex.py     one file per report part: bridge, financial, maintenance,
                         structure work, material/transport/machinery emissions,
                         recycling, social cost, results
traffic_and_road_data_latex/   traffic parts; get_all_data.py exposes their *_to_latex functions
boq_latex.py             Bill of Quantities document
final_report.py          Dev-menu-only document (own preamble); NOT the shipped LCCA report
pdf_generation_v3/
  latex_helpers.py       preamble, document shell, header and footer, cmd(), section(), front_matter()
  lcca_report_builder.py REPORT_SCHEMA (what goes in the report, in order), pdflatex runs
  appendix_*_content.py  fixed appendix text
  sections/              title_page.py (cover, shared with the BOQ), introduction.py, appendices.py
  sections/title_page_v1_archived.py   old cover, unused; do not edit or import
```

Report plots are drawn in `../report/plot_exporter.py`, outside this folder.

## How the LCCA report is built

1. `REPORT_SCHEMA` in `lcca_report_builder.py` lists every part in order. Each
   entry has a `key` (the user's on/off toggle in the report dialog) and a
   `render` function that returns LaTeX.
2. `lcca_report_body()` renders the enabled parts. `build_report_v3_document()`
   wraps them in the preamble from `latex_helpers.py`.
3. `compile_report_pdf()` runs pdflatex: a draft pass for cross-references,
   then the final pass, retried once on failure.

To add a report part, write its `render` function, then add one entry to
`REPORT_SCHEMA`. To show it in the Dev menu as well, add one row to
`_LATEX_ENTRIES` in `gui/devmode.py`. Don't copy the save/wrap logic there.

## Rules: what to use

### Generating LaTeX
- Build LaTeX only with **pylatex**, or with **pandas `Styler.to_latex()`** for
  flat tables (the same columns on every row).
- Pick the pylatex class that matches what you are making:

  | You need | Use |
  |---|---|
  | one command, e.g. `\section{..}`, `\setlength{..}{..}` | `Command`, or `cmd()` from `latex_helpers.py` (arguments not escaped) |
  | a package | `Package` (add it to `REQUIRED_LATEX_PACKAGES`, see below) |
  | a small table | `Table` + `Tabular` |
  | a table that can run onto the next page | `LongTable` with `common_code.longtable_head()` |
  | a cell spanning columns | `MultiColumn` |
  | a box of text | `MiniPage` |
  | drawing | `TikZ`, `TikZNode`, `TikZPath`, `TikZCoordinate`, `TikZOptions` |
  | `\newcommand` | `UnsafeCommand("newcommand", ...)` |
  | an environment pylatex lacks | subclass `pylatex.base_classes.Environment` with `_latex_name` |
  | bold text | `pylatex.utils.bold` |
- Joining pylatex output is fine, e.g. `"\n".join([...dumps()...])`.
- Raw LaTeX text is allowed only where pylatex has no class for it:
  - row ends `\\` and `\\[8pt]`
  - column specs
  - dimension expressions (`\dimexpr...\relax`)
  - booktabs rules appended as `NoEscape(r"\toprule")`
  - TeX conditionals (`\ifdim ... \fi`)
  - a bare number after a primitive, e.g. `\penalty0`

  Keep each such fragment short and say why in a comment.

### Escaping
- Escape user text: pass it to pylatex as a plain `str`, which escapes it, or
  through `pylatex.utils.escape_latex` when you combine it yourself.
- Wrap something in `NoEscape` only when it is LaTeX you built yourself, never
  raw user input.
- Don't write your own escaping helpers.

### Tables
- Use booktabs rules (`\toprule`, `\midrule`, `\bottomrule`). Never `\hline`.
- Give every report table a caption and a `\label{tab:...}`. For a `LongTable`,
  use `longtable_head()`. It repeats the caption on later pages without a
  second List of Tables entry or a duplicate label.
- Put small tables in a `table` float with `\centering`. Use `LongTable` for
  anything that can be longer than a page. Only the cover page uses bare
  `tabular`s.
- Column widths live in `SETTINGS.LATEX_TABLE_LAYOUTS` and are read with
  `latex_layout(name)`. Don't hard-code a column spec in a component file.
  Widths must leave the table inside the text width: a build must report no
  `Overfull \hbox`.
- Right-align numbers (`r`, or `\raggedleft` in a `p{}` column).
- Show a missing value as `\textemdash`. Not blank, zero or `N/A`.
- Put units in the column header or the field label, not in each cell.

### Settings and data
- Decimal places: `DECIMAL_PLACES_FOR_LATEX`, or `DECIMAL_PLACES_FOR_LATEX_RATIO`
  for ratios and indices, from `SETTINGS.py`. Never hard-code a count.
- Font size: the document size is `LATEX_FONT_SIZE`, applied once after
  `\begin{document}`. Don't set body font sizes in component files. Smaller
  local annotations (legends, "continued on next page", wide-table blocks) are
  the exception.
- Currency: call `get_currency()` (from
  `gui/components/utils/common_requested_data.py`) when the function runs, never
  at module level, and never hard-code `"INR"`.
- Units from chunk data: resolve them with `UNIT_DISPLAY.get(code, code)` from
  `gui/components/utils/definitions.py`. `FieldDef.unit` strings are already
  readable.

### LaTeX packages: only from the bundle
The app compiles with the bundled TeX distribution (`osdag_latex_env`), not a
full TeX install. A package missing from the bundle makes PDF export fail on
users' machines, even though it works on a developer machine with MiKTeX or
TeX Live.
- Use only packages listed in `list_of_lib_av` in
  `devtools/osdag_latex_bundle_packages.py`. If a package isn't listed, don't
  use it. Find another way with a listed package, or ask for it to be added to
  the bundle first.
- Check the options too: some options load more packages. For example,
  `tcolorbox` with `most` pulls in `listingsutf8`, which isn't bundled, so
  `SETTINGS.py` uses `many`.
- Load packages only through `REQUIRED_LATEX_PACKAGES` in `SETTINGS.py`. Never
  write a `\usepackage` or `\RequirePackage` line anywhere else.
- pylatex classes such as `TikZ` and `MiniPage` declare packages, but those are
  added only when pylatex builds the whole document. This code calls `dumps()`,
  so a package a class needs must already be in `REQUIRED_LATEX_PACKAGES`.
- After adding a package, build the report and check every `.sty` the `.log`
  shows was loaded. Packages load other packages, and those must be bundled
  too. Where the bundle is installed, `SETTINGS.verify_packages()` checks
  `REQUIRED_LATEX_PACKAGES` against it, but not the packages they load.

### Code layout
- Each report part has its own file with one public
  `<component>_to_latex(controller)` function. Keep other functions private
  (`_name`) unless another module needs them.
- Don't generalise away per-component choices. `common_code.py` is for shared
  low-level helpers only.
- Put every import at the top of the module and import only what you use. The
  one exception is a guarded optional dependency: a module-level `try/except`
  import is fine.

## Rules: what not to use

- Hand-built command or environment strings, such as `r"\textbf{" + x + "}"` or
  `r"\begin{tabular}{..}"`. Use the pylatex classes above.
- `\hline`, tables without captions, and column specs written into component
  files.
- Hard-coded decimals, font sizes, currency or unit strings.
- Any package not in `devtools/osdag_latex_bundle_packages.py`, and
  `\usepackage` outside `SETTINGS.REQUIRED_LATEX_PACKAGES`.
- Imports inside functions, and unused imports.
- `title_page_v1_archived.py`. It is kept for reference only.

## Known exceptions (not yet converted)

This older code still breaks the rules above. Don't copy it. When you convert
any of it, remove its line here.

- `pdf_generation_v3/appendix_B_content.py` and the remark tables in
  `lcca_report_builder.py` use hand-written `tabular`s with vertical rules.
- `pdf_generation_v3/lcca_report_builder.py` builds much of its text, such as
  `\noindent Table~\ref{...}` sentences and the landscape appendix block, as
  raw strings.
- `final_report.py` (Dev menu only) has its own hand-written preamble with
  `\usepackage` lines.
- `latex_helpers.py` still has the unused `simple_table()`, `format_value()`
  and `_cell()`. Don't call them.

## Checking a change

1. Run the tests: `.venv/Scripts/python.exe -m pytest -q tests` (from the repo
   root).
2. Build the PDF. Use a copy of a project, never a live project folder. Open
   the `.log` and confirm there are no lines starting with `!` (errors) and none
   starting with `Overfull` (content running past the margin).
3. For a refactor that should not change the output, compare the `.tex` from
   before and after. Plot file names are random, so ignore them. The rest must
   be byte-identical.
4. If the `.tex` text changes but the page should look the same (for example,
   switching to a pylatex class that writes slightly different LaTeX), render
   the PDF pages before and after with `pdftoppm -png` and compare the images
   pixel by pixel.
5. Look at the pages you touched in the PDF itself.
