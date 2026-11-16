"""Tests for the BOQ PDF export (code_to_latex/boq_latex.py) and the shared run_pdflatex."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from three_ps_lcca_gui.code_to_latex import boq_latex
from three_ps_lcca_gui.code_to_latex.pdf_generation_v3 import lcca_report_builder as rb
from three_ps_lcca_gui.gui.components.utils.definitions import STRUCTURE_CHUNKS


def _item(name, qty, rate, unit="cum", trash=False, source="db"):
    return {
        "values": {"material_name": name, "quantity": qty, "rate": rate, "unit": unit},
        "state": {"in_trash": trash},
        "meta": {"source": source},
    }


class Ctrl:
    def __init__(self, chunks, info=None):
        self.chunks = chunks
        self.info = info or {"project_name": "Bridge & Co_1", "project_currency": "INR"}

    def get_fresh_chunk(self, name):
        return self.info if name == "general_info" else self.chunks.get(name, {})

    get_chunk = get_fresh_chunk


def _ctrl(**over):
    first = STRUCTURE_CHUNKS[0][0]
    chunks = {first: {
        "Pier": [_item("Concrete M30", 10, 100), _item("Steel & Bar", 2, 250.5, trash=False),
                 _item("Old", 5, 5, trash=True)],
        "Cap": [_item("Form_work", "3", "2")],
    }}
    chunks.update(over)
    return Ctrl(chunks)


@pytest.fixture
def tex(monkeypatch):
    c = _ctrl()
    boq_latex.set_controller(c)
    return boq_latex.boq_to_latex(c)


def test_numbering_and_totals(tex):
    assert "1.1.1" in tex and "1.1.2" in tex and "1.2.1" in tex
    assert "Subtotal {-} Pier" in tex and "Subtotal {-} Cap" in tex
    assert "Total {-} " in tex and "GRAND TOTAL" in tex
    # Pier 1000 + 501 ; Cap 6 ; grand 1,507.00
    assert "1,501.00" in tex and "1,507.00" in tex


def test_trashed_items_skipped(tex):
    assert "Old" not in tex


def test_special_chars_escaped(tex):
    assert r"Steel \& Bar" in tex
    assert r"Form\_work" in tex


def test_string_numbers_coerced(tex):
    assert "6.00" in tex


def test_bad_values_become_zero():
    first = STRUCTURE_CHUNKS[0][0]
    c = Ctrl({first: {"X": [_item("A", None, "abc")]}})
    boq_latex.set_controller(c)
    out = boq_latex.boq_to_latex(c)
    assert "0.00" in out and "GRAND TOTAL" in out


def test_empty_returns_blank():
    c = Ctrl({})
    boq_latex.set_controller(c)
    assert boq_latex.boq_to_latex(c) == ""


def test_all_trashed_returns_blank():
    first = STRUCTURE_CHUNKS[0][0]
    c = Ctrl({first: {"X": [_item("A", 1, 1, trash=True)]}})
    boq_latex.set_controller(c)
    assert boq_latex.boq_to_latex(c) == ""


def test_multiple_categories_numbered():
    ch = {STRUCTURE_CHUNKS[0][0]: {"A": [_item("m", 1, 1)]},
          STRUCTURE_CHUNKS[1][0]: {"B": [_item("n", 1, 1)]}}
    c = Ctrl(ch)
    boq_latex.set_controller(c)
    out = boq_latex.boq_to_latex(c)
    assert "1.1.1" in out and "2.1.1" in out
    assert out.count("GRAND TOTAL") == 1


def test_document_wraps_table():
    c = _ctrl()
    boq_latex.set_controller(c)
    doc = boq_latex.boq_document(c)
    assert r"\begin{document}" in doc and r"\end{document}" in doc
    assert r"\section{Detailed bill of quantities}" in doc
    assert r"Bridge \& Co\_1" in doc
    assert r"\begin{longtable}" in doc


def test_layout_has_six_columns():
    assert boq_latex._COL_SPEC.count(r"p{") == 6


def _fake_run(tmp_calls, rc=0, make_pdf=True):
    def run(cmd, cwd=None, capture_output=None, text=None):
        tmp_calls.append(cmd[1:])
        if make_pdf:
            (Path(cwd) / "boq.pdf").write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, rc, "", "")
    return run


def test_build_pdf_two_passes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(rb.subprocess, "run", _fake_run(calls))
    out = tmp_path / "o.pdf"
    boq_latex.build_boq_pdf(_ctrl(), str(out))
    assert out.read_bytes() == b"%PDF"
    assert calls == [["-interaction=nonstopmode", "-draftmode", "boq.tex"],
                     ["-interaction=nonstopmode", "boq.tex"]]


def test_build_pdf_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(rb.subprocess, "run", _fake_run([], rc=1, make_pdf=False))
    with pytest.raises(RuntimeError, match="pdflatex failed"):
        boq_latex.build_boq_pdf(_ctrl(), str(tmp_path / "o.pdf"))
    assert not (tmp_path / "o.pdf").exists()


def test_build_pdf_missing_output(tmp_path, monkeypatch):
    monkeypatch.setattr(rb.subprocess, "run", _fake_run([], make_pdf=False))
    with pytest.raises(FileNotFoundError):
        boq_latex.build_boq_pdf(_ctrl(), str(tmp_path / "o.pdf"))


def test_run_pdflatex_error_message_matches_report(tmp_path, monkeypatch):
    monkeypatch.setattr(rb.subprocess, "run", _fake_run([], rc=1, make_pdf=False))
    tex = tmp_path / "r.tex"
    tex.write_text("x")
    with pytest.raises(RuntimeError) as e:
        rb.run_pdflatex(tex, tmp_path, context=" on attempt 2/2", tex_msg="\n\nsaved")
    s = str(e.value)
    assert s.startswith("pdflatex failed (exit 1) on attempt 2/2.")
    assert "LaTeX errors:" in s and "saved" in s


def test_run_pdflatex_reads_log(tmp_path, monkeypatch):
    monkeypatch.setattr(rb.subprocess, "run", _fake_run([], rc=1, make_pdf=False))
    tex = tmp_path / "r.tex"
    tex.write_text("x")
    tex.with_suffix(".log").write_text("ok\n! Undefined control sequence.\nfine")
    with pytest.raises(RuntimeError, match="Undefined control sequence"):
        rb.run_pdflatex(tex, tmp_path)


def test_format_available_pdf(monkeypatch):
    from three_ps_lcca_gui.gui.components.structure import excel_exporter as ex
    fmt = next(f for f in ex.BOQ_FORMATS if f["ext"] == ".pdf")
    monkeypatch.setattr(rb, "_PDFLATEX", "definitely-not-a-binary-xyz")
    ok, hint = ex.format_available(fmt)
    assert not ok and "TeX" in hint
    monkeypatch.setattr(rb, "_PDFLATEX", sys.executable)
    assert ex.format_available(fmt) == (True, "")
    # non-binary formats unaffected
    assert ex.format_available(ex.BOQ_FORMATS[0])[0]


def test_document_includes_bridge_data_before_boq():
    c = _ctrl()
    c.chunks["bridge_data"] = {"bridge_name": "Test Bridge", "span": 30}
    boq_latex.set_controller(c)
    doc = boq_latex.boq_document(c)
    assert "tab:bridge_data" in doc
    assert doc.index("tab:bridge_data") < doc.index("tab:boq_str_foundation")


def test_one_table_per_category_plus_summary():
    ch = {STRUCTURE_CHUNKS[0][0]: {"A": [_item("m", 1, 1)]},
          STRUCTURE_CHUNKS[1][0]: {"B": [_item("n", 2, 3)]}}
    c = Ctrl(ch)
    boq_latex.set_controller(c)
    out = boq_latex.boq_to_latex(c)
    assert out.count(r"\begin{longtable}") == 3
    assert f"tab:boq_{STRUCTURE_CHUNKS[0][0]}" in out and "tab:boq_summary" in out
    # grand total lives only in the summary table, after the category tables
    assert out.index("tab:boq_summary") < out.index("GRAND TOTAL")
    assert "7.00" in out  # 1 + 6


def test_document_placement():
    c = _ctrl()
    c.chunks["bridge_data"] = {"bridge_name": "T", "span": 30}
    boq_latex.set_controller(c)
    doc = boq_latex.boq_document(c)
    order = [doc.index(k) for k in (
        r"Bill\hspace{0.25em}of", r"\section{Bridge geometry and description}", "tab:bridge_data",
        r"\section{Detailed bill of quantities}", "tab:boq_str_foundation",
        "Summary of costs", "GRAND TOTAL")]
    assert order == sorted(order)
    assert r"\begin{titlepage}" in doc and "Bridge Life Cycle Cost Analysis Report" not in doc
    assert "All amounts in" not in doc
    # the report's title page opens the document; the date sits in Project information
    assert doc.index("Project information") < doc.index(r"\lab{Date}") < doc.index("Evaluated by")
    # index (table of contents) sits between the title page and the bridge data
    assert doc.index("Signature") < doc.index(r"\tableofcontents") < doc.index("tab:bridge_data")


def test_document_without_bridge_data_skips_input_section():
    c = _ctrl()
    boq_latex.set_controller(c)
    doc = boq_latex.boq_document(c)
    assert r"\section{Detailed bill of quantities}" in doc


def test_general_info_and_signature_blocks_follow_title():
    c = _ctrl()
    c.info.update({"project_code": "P-7", "contact_person": "A. Rao", "reviewed_by": "B. Sen"})
    boq_latex.set_controller(c)
    doc = boq_latex.boq_document(c)
    assert doc.index(r"Bill\hspace{0.25em}of") < doc.index("Project information")
    assert "logo-3psLCCA.png" in doc
    assert "P{-}7" in doc and "A. Rao" in doc and "B. Sen" in doc
    assert "Evaluated by" in doc and "Reviewed by" in doc and "Signature" in doc


def test_official_date_format():
    from datetime import date
    assert boq_latex._official_date(date(2026, 11, 11)) == "11 November 2026"
    assert boq_latex._official_date(date(2026, 3, 5)) == "5 March 2026"
