"""Tests for the shared cover page (pdf_generation_v3/sections/title_page.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from three_ps_lcca_gui.code_to_latex.pdf_generation_v3.sections.title_page import (
    _heading_tex, heading_lines, title_page,
)


def test_short_heading_fills_one_line():
    assert heading_lines("Bill of Quantities") == ["Bill of Quantities"]


def test_report_heading_is_balanced_over_two_lines():
    assert heading_lines("Bridge Life Cycle Cost Analysis Report") == [
        "Bridge Life Cycle", "Cost Analysis Report"]


def test_size_fills_the_band_and_is_capped():
    assert _heading_tex(["Bill of Quantities"])[1] >= 46
    assert _heading_tex(["Hi"])[1] == 50
    assert _heading_tex(["x" * 20])[1] < 50


def test_long_heading_is_clipped_and_long_word_split():
    lines = heading_lines("x" * 200)
    assert all(len(s) <= 20 for s in lines) and "..." in "".join(lines)
    assert heading_lines("") == [""]


def test_heading_is_escaped():
    tex, _ = _heading_tex(heading_lines("R&D_1"))
    assert r"\&" in tex and r"\_" in tex


def test_no_kicker_by_default_but_can_be_set():
    g = {"project_name": "P"}
    assert "Life Cycle Cost Analysis}" not in title_page(None, "Bill of Quantities", general=g)
    assert "textsc{Custom" in title_page(None, "X", kicker="Custom", general=g)


def test_cover_has_footer_and_disclaimer():
    tex = title_page(None, "Bill of Quantities", general={}, disclaimer="Only this.")
    assert r"\begin{titlepage}" in tex and r"\covfooter" in tex and "Only this." in tex
