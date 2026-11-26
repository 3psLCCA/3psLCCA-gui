"""SOR numbers in the structure work and BOQ reports.

Rule: each database (SOR or custom database) in a report gets a number, in
the order it first appears (category, component, item; trashed items
skipped). The number follows the change mark (abc$^{1}$, edf$^{\\S\\,2}$).
Numbers are used only with two or more databases; with one, the legend names
it. Excel and manual rows never get a number.
"""
import re

import pytest

from three_ps_lcca_gui.code_to_latex import boq_latex, structure_work_data_latex as swd
from three_ps_lcca_gui.gui.components.structure.material_flags import (
    db_label, material_db_key, report_databases,
)
from three_ps_lcca_gui.gui.components.utils.common_requested_data import set_controller
from three_ps_lcca_gui.gui.components.utils.definitions import STRUCTURE_CHUNKS

BIHAR = "INDIA/Bihar/RCD SOR 2025"
MAHA = "INDIA/Maharashtra/PWD SSR 2022-23"
KARN = "INDIA/Karnataka/KPWD SOR 2023-24"
CUSTOM = "custom::My Rates"


def db_item(name, key, modified=False, trash=False):
    original = {"action": "custom_db" if key.startswith("custom::") else "internal_db",
                "db_key": key, "src_id": "A1", "name": name, "unit": "cum",
                "rate": 100.0, "rate_src": "SOR"}
    rate = 101.0 if modified else 100.0
    return {"values": {"material_name": name, "src_id": "A1", "unit": "cum",
                       "quantity": 2.0, "rate": rate, "rate_source": "SOR"},
            "meta": {"db_original": original}, "state": {"in_trash": trash}}


def excel_item(name):
    original = {"action": "excel", "name": name, "unit": "cum", "rate": 5.0, "quantity": 1.0}
    return {"values": {"material_name": name, "unit": "cum", "quantity": 1.0, "rate": 5.0},
            "meta": {"db_original": original}, "state": {}}


def manual_item(name):
    return {"values": {"material_name": name, "unit": "cum", "quantity": 1.0, "rate": 5.0},
            "meta": {}, "state": {}}


class Ctrl:
    def __init__(self, chunks):
        self.chunks = chunks
        self.info = {"project_name": "P", "project_currency": "INR"}

    def get_fresh_chunk(self, name):
        return self.info if name == "general_info" else self.chunks.get(name, {})

    get_chunk = get_fresh_chunk


def reports(chunks):
    ctrl = Ctrl(chunks)
    set_controller(ctrl)
    return swd.structure_work_data_to_latex(ctrl), boq_latex.boq_to_latex(ctrl)


C1, C2, C3, C4 = (c for c, _ in STRUCTURE_CHUNKS)


# ── material_db_key / report_databases / db_label ────────────────────────

@pytest.mark.parametrize("item,key", [
    (db_item("a", BIHAR), BIHAR),
    (db_item("a", CUSTOM), CUSTOM),
    (excel_item("a"), ""),
    (manual_item("a"), ""),
    ({}, ""), (None, ""), ({"meta": None}, ""), ({"meta": {"db_original": "x"}}, ""),
    ({"meta": {"db_original": {"action": "internal_db"}}}, ""),
    ({"meta": {"db_original": {"action": "internal_db", "db_key": 5}}}, ""),
    ({"meta": {"db_original": {"action": "internal_db", "db_key": f"  {BIHAR} "}}}, BIHAR),
    ({"meta": {"source": "db", "source_db_key": BIHAR}}, ""),   # no snapshot: no database
])
def test_material_db_key(item, key):
    assert material_db_key(item) == key


def test_report_databases_first_seen_order_no_repeats():
    items = [db_item("a", MAHA), excel_item("x"), db_item("b", BIHAR),
             db_item("c", MAHA, True), manual_item("m"), db_item("d", CUSTOM),
             db_item("e", KARN)]
    assert report_databases(items) == [MAHA, BIHAR, CUSTOM, KARN]


def test_report_databases_skips_trash():
    items = [db_item("a", KARN, trash=True), db_item("b", BIHAR), db_item("c", KARN)]
    assert report_databases(items) == [BIHAR, KARN]


def test_report_databases_none():
    assert report_databases([excel_item("x"), manual_item("m")]) == []
    assert report_databases([]) == []


@pytest.mark.parametrize("key,label", [
    (BIHAR, "Bihar – RCD SOR 2025"),
    ("INDIA/Madhya_Pradesh/MPPWD SOR 2025", "Madhya Pradesh – MPPWD SOR 2025"),
    ("INDIA/Maharashtra/Nagpur/NMC/2022", "Maharashtra – Nagpur – NMC – 2022"),
    ("INDIA/MumbaiSOR", "MumbaiSOR"),
    ("INDIA", "INDIA"),
    (CUSTOM, "My Rates (Custom)"),
])
def test_db_label(key, label):
    assert db_label(key) == label


# ── cell and legend ──────────────────────────────────────────────────────

@pytest.mark.parametrize("source,number,cell", [
    ("db", None, "abc"),
    ("db", 1, "abc$^{1}$"),
    ("db_modified", None, r"abc$^{\S}$"),
    ("db_modified", 2, r"abc$^{\S\,2}$"),
    ("custom_db", 3, r"abc$^{\P\,3}$"),
    ("custom_db_modified", 4, r"abc$^{\|\,4}$"),
    ("excel", None, r"abc$^{\dagger}$"),
    ("excel_modified", None, r"abc$^{\ddagger}$"),
    ("manual", None, r"abc$^{\#}$"),
])
def test_mat_cell(source, number, cell):
    assert str(swd._mat_cell("abc", source, number)) == cell


def test_legend_without_databases_is_unchanged():
    text = str(swd._legend("INR"))
    assert "Database:" not in text and "Databases:" not in text


def test_legend_one_database_named_no_numbers():
    text = str(swd._legend("INR", [BIHAR]))
    assert "Database: Bihar – RCD SOR 2025" in text and "$^{1}$" not in text


def test_legend_numbers_databases_in_order():
    text = str(swd._legend("INR", [MAHA, CUSTOM, BIHAR]))
    assert re.search(r"Databases: \$\^\{1\}\$\\,Maharashtra.*\$\^\{2\}\$\\,My Rates \(Custom\)"
                     r".*\$\^\{3\}\$\\,Bihar", text)


# ── the reports ──────────────────────────────────────────────────────────

def test_three_sors_numbered_same_in_both_reports():
    chunks = {
        C1: {"Pile": [db_item("p1", MAHA), db_item("p2", BIHAR, True), manual_item("p3")]},
        C2: {"Pier": [db_item("q1", BIHAR), db_item("q2", MAHA, True), db_item("q3", CUSTOM)],
             "Old": [db_item("old", KARN, trash=True)]},
        C3: {"Deck": [db_item("d1", KARN, True), db_item("d2", CUSTOM, True),
                      excel_item("d3")]},
    }
    for tex in reports(chunks):
        assert "p1$^{1}$" in tex
        assert r"p2$^{\S\,2}$" in tex
        assert r"p3$^{\#}$" in tex
        assert "q1$^{2}$" in tex
        assert r"q2$^{\S\,1}$" in tex
        assert r"q3$^{\P\,3}$" in tex
        assert r"d1$^{\S\,4}$" in tex          # trashed Karnataka item took no number
        assert r"d2$^{\|\,4}$" not in tex and r"d2$^{\|\,3}$" in tex
        assert r"d3$^{\dagger}$" in tex
        assert re.search(r"Databases: \$\^\{1\}\$\\,Maharashtra.*\$\^\{2\}\$\\,Bihar"
                         r".*\$\^\{3\}\$\\,My Rates.*\$\^\{4\}\$\\,Karnataka", tex)


def test_one_sor_no_numbers_legend_names_it():
    chunks = {C1: {"Pile": [db_item("p1", BIHAR), db_item("p2", BIHAR, True),
                            excel_item("p3"), manual_item("p4")]}}
    for tex in reports(chunks):
        assert re.search(r"p1(?!\$)", tex)
        assert r"p2$^{\S}$" in tex
        assert "Database: Bihar – RCD SOR 2025" in tex
        assert "Databases:" not in tex


def test_one_sor_plus_custom_is_two_databases():
    chunks = {C1: {"Pile": [db_item("p1", BIHAR), db_item("p2", CUSTOM)]}}
    for tex in reports(chunks):
        assert "p1$^{1}$" in tex and r"p2$^{\P\,2}$" in tex


def test_second_sor_only_in_trash_means_one_database():
    chunks = {C1: {"Pile": [db_item("p1", BIHAR), db_item("p2", MAHA, trash=True)]}}
    for tex in reports(chunks):
        assert "Database: Bihar" in tex and "$^{1}$" not in tex


def test_no_database_no_database_line():
    chunks = {C1: {"Pile": [excel_item("p1"), manual_item("p2")]}}
    for tex in reports(chunks):
        assert "Database" not in tex.replace("Database value", "")
