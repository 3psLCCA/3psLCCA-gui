DECIMAL_PLACES_FOR_LATEX       = 2
DECIMAL_PLACES_FOR_LATEX_RATIO = 4

# LaTeX font size declaration applied to the whole devmode document.
# Valid values: \tiny \scriptsize \footnotesize \small \normalsize \large \Large \LARGE \huge \Huge
LATEX_FONT_SIZE = r"\small"

# ─────────────────────────────────────────────────────────────────────────────
# LaTeX Packages (Single Source of Truth)
# ─────────────────────────────────────────────────────────────────────────────
# Key: package name, Value: list of options or None
REQUIRED_LATEX_PACKAGES = {
    "inputenc":   ["utf8"],
    "fontenc":    ["T1"],
    "mathptmx":   None,
    "microtype":  None,
    "geometry":   ["a4paper", "top=2.5cm", "bottom=2.5cm", "left=2.5cm", "right=2.5cm"],
    "setspace":   None,
    "booktabs":   None,
    "array":      None,
    "longtable":  None,
    "tabularx":   None,
    "multirow":   None,
    "makecell":   None,
    "graphicx":   None,
    "float":      None,
    "pdflscape":  None,
    "adjustbox":  None,
    "caption":    None,
    "amsmath":    None,
    "xcolor":     None,
    "enumitem":   None,
    "fancyhdr":   None,
    "lastpage":   None,
    "tocloft":    None,
    "titlesec":   None,
    "etoolbox":   None,
    "hyperref":   ["hidelinks", "hypertexnames=false"],
    "bookmark":   None,
}
