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
    "inputenc":   ["utf8"],       # base LaTeX
    "fontenc":    ["T1"],         # base LaTeX
    "mathptmx":   None,           # psnfss
    "microtype":  None,
    "geometry":   ["a4paper", "top=2.5cm", "bottom=2.5cm", "left=2.5cm", "right=2.5cm"],
    "setspace":   None,
    "booktabs":   None,
    "array":      None,           # tools
    "longtable":  None,           # tools
    "tabularx":   None,           # tools
    "multirow":   None,
    "makecell":   None,
    "graphicx":   None,           # graphics
    "float":      None,
    "pdflscape":  None,
    "adjustbox":  None,
    "caption":    None,
    "amsmath":    None,
    "xcolor":     None,
    "colortbl":   None,
    "enumitem":   None,
    "fancyhdr":   None,
    "lastpage":   None,
    "titlesec":   None,
    "etoolbox":   None,
    "hyperref":   ["hidelinks", "hypertexnames=false"],
    "bookmark":   None,
    "booktabs": None,
    "array": None,
    "longtable": None,
    "tabularx": None,
    "multirow": None,
    "makecell": None,
    "graphicx": None,
    "float": None,
    "pdflscape": None,
    "adjustbox": None,
    "caption": None,
    "amsmath": None,
    "xcolor": None,
    "colortbl": None,
    "enumitem": None,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Known MISSING from bundle (do not add to REQUIRED_LATEX_PACKAGES):
#   tocloft
# Use verify_packages() / list_bundle_packages() at runtime for ground truth.
# ─────────────────────────────────────────────────────────────────────────────


def _find_texmf_latex():
    """Return the texmf-dist/tex/latex Path inside the active env, or None."""
    import sys
    from pathlib import Path
    candidates = [
        Path(sys.prefix) / "Library" / "share" / "osdag_latex_env" / "texmf-dist" / "tex" / "latex",
        Path(sys.prefix) / "share"   / "osdag_latex_env" / "texmf-dist" / "tex" / "latex",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def list_bundle_packages() -> list:
    """
    Scan the bundled osdag_latex_env and return every .sty stem found.
    Returns an empty list if the bundle is not present.
    """
    texmf = _find_texmf_latex()
    if texmf is None:
        return []
    return sorted({sty.stem for sty in texmf.rglob("*.sty")})


def verify_packages() -> dict:
    """
    Check REQUIRED_LATEX_PACKAGES against the bundle by scanning all .sty files.
    Returns:
      {
        "bundle_path":     Path or None,
        "bundle_packages": sorted list of all .sty stems in the bundle,
        "available":       required packages found in the bundle,
        "missing":         required packages NOT found in the bundle,
      }
    Does not run pdflatex — purely a filesystem check.
    """
    texmf = _find_texmf_latex()
    bundle_set = set(list_bundle_packages())

    available, missing = [], []
    for pkg in REQUIRED_LATEX_PACKAGES:
        (available if pkg in bundle_set else missing).append(pkg)

    return {
        "bundle_path":     texmf,
        "bundle_packages": sorted(bundle_set),
        "available":       available,
        "missing":         missing,
    }


# Optional light column backgrounds for generated tables.
LATEX_TABLE_COLUMN_BG_ENABLED = False
LATEX_TABLE_COLUMN_BG_COLORS = ("gray!4", "blue!3")
