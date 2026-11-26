"""Every character in the shipped SOR databases that the reports print
(material name, rate source) must compile with the report preamble.

pdflatex stops at a Unicode character it has no definition for; ≤ and ≥
(e.g. "Depth ≤3m" in the Bihar SOR) did that until the preamble declared them.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pylatex.utils import escape_latex

from three_ps_lcca_gui.code_to_latex.pdf_generation_v3.latex_helpers import (
    build_report_v3_document,
)

DB_ROOT = (Path(__file__).resolve().parents[1] / "src" / "three_ps_lcca_gui" / "gui"
           / "components" / "structure" / "registry" / "material_database")
PRINTED = ("name", "rate_src")


def _walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in PRINTED and isinstance(value, str):
                yield value
            else:
                yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def printed_characters() -> str:
    chars = set()
    for path in DB_ROOT.rglob("*.json"):
        for text in _walk(json.loads(path.read_text(encoding="utf-8"))):
            chars.update(ch for ch in text if ord(ch) > 127)
    return "".join(sorted(chars))


def test_le_ge_are_among_them():
    chars = printed_characters()
    assert "≤" in chars and "≥" in chars


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_every_printed_character_compiles(tmp_path):
    chars = printed_characters()
    body = "\n\n".join(escape_latex(f"U+{ord(ch):04X}: a{ch}b") for ch in chars)
    body += "\n\n" + r"\begin{tabular}{l}" + escape_latex(chars) + r"\end{tabular}"
    (tmp_path / "chars.tex").write_text(build_report_v3_document(body), encoding="utf-8")
    run = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "chars.tex"],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180,
    )
    errors = [line for line in run.stdout.splitlines() if line.startswith("!")]
    assert run.returncode == 0, errors
