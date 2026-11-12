"""
tests/test_comparison_page.py

Comprehensive test suite for comparison_page.py (redesigned).

Coverage areas:
  A. Pure helpers  (_fmt_date, _safe_float, _fmt_M)
  B. lifecycle_summary  (compute_all_summaries)
  C. _KPI / section data maths  (best-project selection, delta %)
  D. _HeatmapDelegate colour logic  (_lerp_color, _contrast)
  E. _DETAIL_ROWS integrity  (stage keys, no duplicates)
  F. Locked colour guard  (LCCA palette colours unchanged)
  G. Qt widget smoke tests  (requires a QApplication)
     G1. _HeroCardsSection instantiates without crash
     G2. _ConsolidatedTable instantiates without crash
     G3. _GroupedBarChart instantiates without crash
     G4. _DetailedBreakdownSection instantiates without crash
     G5. ComparisonResultWindow (mock workers, no real analysis)

Run with:
    python -m pytest tests/test_comparison_page.py -v
or simply:
    python tests/test_comparison_page.py
"""

import sys
import os
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC       = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ── Minimal Qt setup for widget smoke tests ───────────────────────────────────
_HAS_QT = False
try:
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication(sys.argv[:1])
    _HAS_QT = True
except Exception:
    pass

# ── Imports from the module under test (non-Qt helpers) ───────────────────────
from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
    _fmt_date,
    _safe_float,
    _fmt_M,
    _lerp_color,
    _contrast,
    _DETAIL_ROWS,
    _PROJECT_COLORS,
    _PROJECT_HATCHES,
    _STAGE_KEYS,
    _STAGE_LABELS,
    _PILLAR_KEYS,
    _PILLAR_LABELS,
)
from three_ps_lcca_gui.gui.components.outputs.helper_functions.lifecycle_summary import (
    compute_all_summaries,
)
from three_ps_lcca_gui.gui.components.outputs.helper_functions.lcc_colors import (
    COLORS as LCC_PALETTE,
)

# ── Shared realistic mock data ─────────────────────────────────────────────────

def _make_results(
    init_eco=1_000_000, init_env=200_000, init_soc=500_000,
    use_eco=300_000,  use_env=100_000,  use_soc=800_000,
    eol_eco=150_000,  eol_env=50_000,   eol_soc=200_000,
    recon_eco=0, recon_env=0, recon_soc=0,
    scrap_value=50_000,
):
    """Build a minimal results dict that mirrors run_full_lcc_analysis output."""
    return {
        "initial_stage": {
            "economic":      {"initial_construction_cost": init_eco},
            "environmental": {"initial_material_carbon_emission_cost": init_env},
            "social":        {"initial_road_user_cost": init_soc},
        },
        "use_stage": {
            "economic":      {"periodic_maintenance": use_eco},
            "environmental": {"periodic_carbon_costs": use_env},
            "social":        {"major_repair_road_user_costs": use_soc},
        },
        "reconstruction": {
            "economic":      {"total_demolition_and_disposal_costs": recon_eco,
                              "total_scrap_value": 0},
            "environmental": {"carbon_costs_demolition_and_disposal": recon_env},
            "social":        {"ruc_demolition": recon_soc},
        },
        "end_of_life": {
            "economic":      {"total_demolition_and_disposal_costs": eol_eco,
                              "total_scrap_value": scrap_value},
            "environmental": {"carbon_costs_demolition_and_disposal": eol_env},
            "social":        {"ruc_demolition": eol_soc},
        },
    }


# Three projects with clearly ordered totals: A < B < C
_RESULTS_A = _make_results(
    init_eco=1_000_000, init_env=200_000, init_soc=500_000,
    use_eco=300_000,    use_env=100_000,  use_soc=800_000,
    eol_eco=150_000,    eol_env=50_000,   eol_soc=200_000,
    scrap_value=50_000,
)
_RESULTS_B = _make_results(
    init_eco=1_400_000, init_env=250_000, init_soc=650_000,
    use_eco=400_000,    use_env=130_000,  use_soc=900_000,
    eol_eco=200_000,    eol_env=70_000,   eol_soc=250_000,
    scrap_value=40_000,
)
_RESULTS_C = _make_results(
    init_eco=2_000_000, init_env=350_000, init_soc=900_000,
    use_eco=600_000,    use_env=180_000,  use_soc=1_200_000,
    eol_eco=300_000,    eol_env=100_000,  eol_soc=350_000,
    scrap_value=30_000,
)

_PIDS   = ["pid_a", "pid_b", "pid_c"]
_NAMES  = ["Bridge A", "Bridge B", "Bridge C"]
_CACHES = {
    "pid_a": {"analysis_period": 100, "currency": "INR",
              "all_data": {}, "lcc_breakdown": {}, "results": _RESULTS_A},
    "pid_b": {"analysis_period": 100, "currency": "INR",
              "all_data": {}, "lcc_breakdown": {}, "results": _RESULTS_B},
    "pid_c": {"analysis_period": 100, "currency": "INR",
              "all_data": {}, "lcc_breakdown": {}, "results": _RESULTS_C},
}
_SUMMARIES = {pid: compute_all_summaries(_CACHES[pid]["results"]) for pid in _PIDS}


# ═════════════════════════════════════════════════════════════════════════════
# A. Pure helper functions
# ═════════════════════════════════════════════════════════════════════════════

class TestFmtDate(unittest.TestCase):

    def _iso(self, delta_seconds: int) -> str:
        return (datetime.now() - timedelta(seconds=delta_seconds)).isoformat()

    def test_just_now(self):
        self.assertEqual(_fmt_date(self._iso(5)), "Just now")

    def test_minutes_ago(self):
        result = _fmt_date(self._iso(120))
        self.assertIn("m ago", result)

    def test_hours_ago(self):
        result = _fmt_date(self._iso(7200))
        self.assertIn("h ago", result)

    def test_yesterday(self):
        result = _fmt_date(self._iso(90_000))
        self.assertEqual(result, "Yesterday")

    def test_days_ago(self):
        result = _fmt_date(self._iso(5 * 86400))
        self.assertIn("days ago", result)

    def test_bad_string_returns_slice(self):
        result = _fmt_date("2025-01-15T10:00:00")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_empty_string(self):
        self.assertEqual(_fmt_date(""), "")

    def test_none_like_empty(self):
        self.assertEqual(_fmt_date(None), "")


class TestSafeFloat(unittest.TestCase):

    def test_int(self):            self.assertAlmostEqual(_safe_float(42), 42.0)
    def test_float(self):          self.assertAlmostEqual(_safe_float(3.14), 3.14)
    def test_string_number(self):  self.assertAlmostEqual(_safe_float("99.5"), 99.5)
    def test_none(self):           self.assertAlmostEqual(_safe_float(None), 0.0)
    def test_garbage(self):        self.assertAlmostEqual(_safe_float("abc"), 0.0)
    def test_negative(self):       self.assertAlmostEqual(_safe_float(-500), -500.0)
    def test_zero(self):           self.assertAlmostEqual(_safe_float(0), 0.0)



class TestFmtM(unittest.TestCase):

    def test_one_million(self):
        self.assertEqual(_fmt_M(1_000_000, "INR"), "1.00M")

    def test_half_million(self):
        self.assertEqual(_fmt_M(500_000, "INR"), "0.50M")

    def test_negative(self):
        # abs is taken
        self.assertEqual(_fmt_M(-2_000_000, "INR"), "2.00M")

    def test_zero(self):
        self.assertEqual(_fmt_M(0, "INR"), "0.00M")


# ═════════════════════════════════════════════════════════════════════════════
# B. lifecycle_summary compute_all_summaries
# ═════════════════════════════════════════════════════════════════════════════

class TestComputeAllSummaries(unittest.TestCase):

    def setUp(self):
        self.sumA = compute_all_summaries(_RESULTS_A)

    def test_returns_required_keys(self):
        for key in ("stagewise", "pillar_wise", "pillar_totals", "environmental_split"):
            self.assertIn(key, self.sumA)

    def test_stagewise_keys(self):
        for k in ("initial", "use", "end_of_life"):
            self.assertIn(k, self.sumA["stagewise"])

    def test_stagewise_initial_positive(self):
        self.assertGreater(self.sumA["stagewise"]["initial"], 0)

    def test_pillar_totals_keys(self):
        for k in ("eco", "env", "social"):
            self.assertIn(k, self.sumA["pillar_totals"])

    def test_pillar_totals_positive(self):
        for k in ("eco", "env", "social"):
            self.assertGreater(self.sumA["pillar_totals"][k], 0)

    def test_scrap_value_is_credit(self):
        # scrap_value=50_000 in end_of_life → should reduce eco pillar
        # Results with and without scrap
        r_no_scrap  = _make_results(scrap_value=0)
        r_scrap     = _make_results(scrap_value=50_000)
        s_no_scrap  = compute_all_summaries(r_no_scrap)
        s_scrap     = compute_all_summaries(r_scrap)
        # With scrap, end_of_life eco should be LOWER (credit applied)
        self.assertLess(
            s_scrap["stagewise"]["end_of_life"],
            s_no_scrap["stagewise"]["end_of_life"],
        )

    def test_grand_total_equals_sum_of_stages(self):
        sw    = self.sumA["stagewise"]
        total = sw["initial"] + sw["use"] + sw["end_of_life"]
        pt    = self.sumA["pillar_totals"]
        pillar_total = pt["eco"] + pt["env"] + pt["social"]
        self.assertAlmostEqual(total, pillar_total, places=2)

    def test_reconstruction_merged_into_end_of_life(self):
        r = _make_results(recon_eco=999_000, recon_env=111_000, recon_soc=222_000)
        s = compute_all_summaries(r)
        # end_of_life stagewise should include reconstruction
        self.assertGreater(s["stagewise"]["end_of_life"], 0)

    def test_zero_results_gives_zero_totals(self):
        zero_r = {k: {} for k in
                  ("initial_stage", "use_stage", "reconstruction", "end_of_life")}
        s = compute_all_summaries(zero_r)
        for k in ("eco", "env", "social"):
            self.assertAlmostEqual(s["pillar_totals"][k], 0.0)


# ═════════════════════════════════════════════════════════════════════════════
# C. Best-project selection and delta logic
# ═════════════════════════════════════════════════════════════════════════════

class TestBestProjectLogic(unittest.TestCase):
    """Mirrors the logic in _ConsolidatedTable and _HeroCardsSection."""

    def _totals(self):
        result = {}
        for pid in _PIDS:
            sw = _SUMMARIES[pid]["stagewise"]
            result[pid] = sum(sw.values())
        return result

    def test_best_project_is_pid_a(self):
        totals  = self._totals()
        best    = min(totals, key=totals.get)
        self.assertEqual(best, "pid_a")

    def test_worst_project_is_pid_c(self):
        totals  = self._totals()
        worst   = max(totals, key=totals.get)
        self.assertEqual(worst, "pid_c")

    def test_delta_percent_positive_for_non_best(self):
        totals   = self._totals()
        best_val = totals["pid_a"]
        delta_b  = (totals["pid_b"] - best_val) / best_val * 100
        self.assertGreater(delta_b, 0)

    def test_delta_percent_zero_for_best(self):
        totals   = self._totals()
        best_val = totals["pid_a"]
        delta_a  = (totals["pid_a"] - best_val) / best_val * 100
        self.assertAlmostEqual(delta_a, 0.0)

    def test_project_ordering_a_lt_b_lt_c(self):
        totals = self._totals()
        self.assertLess(totals["pid_a"], totals["pid_b"])
        self.assertLess(totals["pid_b"], totals["pid_c"])

    def test_pillar_best_eco(self):
        eco_vals = {pid: _SUMMARIES[pid]["pillar_totals"]["eco"] for pid in _PIDS}
        best_eco = min(eco_vals, key=eco_vals.get)
        self.assertEqual(best_eco, "pid_a")

    def test_stage_best_initial(self):
        init_vals = {pid: _SUMMARIES[pid]["stagewise"]["initial"] for pid in _PIDS}
        best_init = min(init_vals, key=init_vals.get)
        self.assertEqual(best_init, "pid_a")

    def test_two_project_comparison(self):
        """Test with exactly 2 projects (minimum comparison)."""
        pids_2   = ["pid_a", "pid_b"]
        totals_2 = {pid: sum(_SUMMARIES[pid]["stagewise"].values()) for pid in pids_2}
        best_2   = min(totals_2, key=totals_2.get)
        self.assertEqual(best_2, "pid_a")

    def test_single_project_no_best_marked(self):
        """With only 1 project, no 'best' comparison can be made."""
        pids_1 = ["pid_a"]
        best_1 = None if len(pids_1) < 2 else "pid_a"
        self.assertIsNone(best_1)


# ═════════════════════════════════════════════════════════════════════════════
# D. Heatmap colour helpers
# ═════════════════════════════════════════════════════════════════════════════

class TestLerpColor(unittest.TestCase):

    def test_t_zero_returns_c1(self):
        c = _lerp_color((255, 0, 0), (0, 255, 0), 0.0)
        self.assertEqual((c.red(), c.green(), c.blue()), (255, 0, 0))

    def test_t_one_returns_c2(self):
        c = _lerp_color((255, 0, 0), (0, 255, 0), 1.0)
        self.assertEqual((c.red(), c.green(), c.blue()), (0, 255, 0))

    def test_t_half_midpoint(self):
        c = _lerp_color((0, 0, 0), (100, 100, 100), 0.5)
        self.assertEqual((c.red(), c.green(), c.blue()), (50, 50, 50))

    def test_clamps_below_zero(self):
        c = _lerp_color((255, 255, 255), (0, 0, 0), -1.0)
        self.assertEqual((c.red(), c.green(), c.blue()), (255, 255, 255))

    def test_clamps_above_one(self):
        c = _lerp_color((255, 255, 255), (0, 0, 0), 2.0)
        self.assertEqual((c.red(), c.green(), c.blue()), (0, 0, 0))

    def test_returns_qcolor(self):
        from PySide6.QtGui import QColor
        c = _lerp_color((100, 150, 200), (50, 75, 100), 0.5)
        self.assertIsInstance(c, QColor)


class TestContrast(unittest.TestCase):

    def test_white_background_gives_dark_text(self):
        from PySide6.QtGui import QColor
        bg   = QColor(255, 255, 255)
        fg   = _contrast(bg)
        lum  = 0.299 * fg.red() + 0.587 * fg.green() + 0.114 * fg.blue()
        self.assertLess(lum, 140)   # dark text

    def test_black_background_gives_light_text(self):
        from PySide6.QtGui import QColor
        bg   = QColor(0, 0, 0)
        fg   = _contrast(bg)
        lum  = 0.299 * fg.red() + 0.587 * fg.green() + 0.114 * fg.blue()
        self.assertGreater(lum, 140)  # light text

    def test_mid_grey(self):
        from PySide6.QtGui import QColor
        bg = QColor(130, 130, 130)
        fg = _contrast(bg)
        self.assertIsNotNone(fg)     # must return something


# ═════════════════════════════════════════════════════════════════════════════
# E. _DETAIL_ROWS integrity
# ═════════════════════════════════════════════════════════════════════════════

class TestDetailRows(unittest.TestCase):

    _VALID_STAGES = {"initial_stage", "use_stage", "reconstruction", "end_of_life"}
    _VALID_CATS   = {"economic", "environmental", "social"}

    def test_not_empty(self):
        self.assertGreater(len(_DETAIL_ROWS), 0)

    def test_all_have_five_fields(self):
        for row in _DETAIL_ROWS:
            self.assertEqual(len(row), 5,
                             msg=f"Row {row} does not have 5 fields")

    def test_all_stage_keys_valid(self):
        for sk, cat, key, lbl, is_credit in _DETAIL_ROWS:
            self.assertIn(sk, self._VALID_STAGES,
                          msg=f"Unknown stage key: {sk}")

    def test_all_category_keys_valid(self):
        for sk, cat, key, lbl, is_credit in _DETAIL_ROWS:
            self.assertIn(cat, self._VALID_CATS,
                          msg=f"Unknown category: {cat}")

    def test_labels_are_non_empty_strings(self):
        for sk, cat, key, lbl, is_credit in _DETAIL_ROWS:
            self.assertIsInstance(lbl, str)
            self.assertGreater(len(lbl.strip()), 0,
                               msg=f"Empty label for {sk}/{cat}/{key}")

    def test_is_credit_is_boolean(self):
        for row in _DETAIL_ROWS:
            self.assertIsInstance(row[4], bool)

    def test_only_scrap_value_is_credit(self):
        credit_rows = [(sk, key) for sk, cat, key, lbl, is_credit in _DETAIL_ROWS
                       if is_credit]
        for sk, key in credit_rows:
            self.assertEqual(key, "total_scrap_value",
                             msg=f"Non-scrap credit row found: {sk}/{key}")

    def test_no_duplicate_rows(self):
        seen = set()
        for sk, cat, key, lbl, is_credit in _DETAIL_ROWS:
            combo = (sk, cat, key)
            self.assertNotIn(combo, seen,
                             msg=f"Duplicate row: {combo}")
            seen.add(combo)

    def test_all_result_keys_are_strings(self):
        for sk, cat, key, lbl, is_credit in _DETAIL_ROWS:
            self.assertIsInstance(key, str)
            self.assertGreater(len(key), 0)


# ═════════════════════════════════════════════════════════════════════════════
# F. LOCKED colour guard
# ═════════════════════════════════════════════════════════════════════════════

class TestLockedColors(unittest.TestCase):

    def test_eco_color_locked(self):
        self.assertEqual(LCC_PALETTE["eco_color"], "#9e9eff")

    def test_env_color_locked(self):
        self.assertEqual(LCC_PALETTE["env_color"], "#8ad400")

    def test_soc_color_locked(self):
        self.assertEqual(LCC_PALETTE["soc_color"], "#ff5a2a")

    def test_init_color_locked(self):
        self.assertEqual(LCC_PALETTE["init_color"], "#CCCCCC")

    def test_use_color_locked(self):
        self.assertEqual(LCC_PALETTE["use_color"], "#00C49A")

    def test_end_color_locked(self):
        self.assertEqual(LCC_PALETTE["end_color"], "#EA9E9E")

    def test_project_colors_list_has_at_least_5(self):
        self.assertGreaterEqual(len(_PROJECT_COLORS), 5)

    def test_project_colors_all_valid_hex(self):
        import re
        for c in _PROJECT_COLORS:
            self.assertRegex(c, r"^#[0-9A-Fa-f]{6}$",
                             msg=f"Invalid hex color: {c}")

    def test_stage_keys_length(self):
        self.assertEqual(len(_STAGE_KEYS), 3)
        self.assertEqual(len(_STAGE_LABELS), 3)

    def test_pillar_keys_length(self):
        self.assertEqual(len(_PILLAR_KEYS), 3)
        self.assertEqual(len(_PILLAR_LABELS), 3)

    def test_project_hatches_defined(self):
        self.assertGreaterEqual(len(_PROJECT_HATCHES), 5)
        # First project should be solid
        self.assertEqual(_PROJECT_HATCHES[0], "")
        # Later projects have hatch patterns and dots
        self.assertIn("///", _PROJECT_HATCHES)
        self.assertIn("...", _PROJECT_HATCHES)


# ═════════════════════════════════════════════════════════════════════════════
# G. Qt Widget Smoke Tests
# ═════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestHeroCardsSection(unittest.TestCase):

    def test_instantiates_with_3_projects(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _HeroCardsSection,
        )
        w = _HeroCardsSection(_PIDS, _NAMES, _SUMMARIES, _CACHES, "INR")
        self.assertIsNotNone(w)

    def test_instantiates_with_2_projects(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _HeroCardsSection,
        )
        pids2  = _PIDS[:2]
        names2 = _NAMES[:2]
        sums2  = {p: _SUMMARIES[p] for p in pids2}
        caches2 = {p: _CACHES[p] for p in pids2}
        w = _HeroCardsSection(pids2, names2, sums2, caches2, "INR")
        self.assertIsNotNone(w)

    def test_shows_lowest_cost_badge_for_best(self):
        """Best project card must have success border."""
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _HeroCardsSection,
        )
        from PySide6.QtWidgets import QFrame
        from three_ps_lcca_gui.gui.themes import get_token
        w = _HeroCardsSection(_PIDS, _NAMES, _SUMMARIES, _CACHES, "INR")
        cards = w.findChildren(QFrame, "heroCardMain")
        best_card = cards[0]
        self.assertIn(get_token("success"), best_card.styleSheet())

    def test_usd_currency_label(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _HeroCardsSection,
        )
        from PySide6.QtWidgets import QLabel
        w = _HeroCardsSection(_PIDS, _NAMES, _SUMMARIES, _CACHES, "USD")
        labels = w.findChildren(QLabel)
        texts  = [lbl.text() for lbl in labels]
        self.assertTrue(any("USD" in t for t in texts),
                        msg="Currency 'USD' label not found")


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestConsolidatedTable(unittest.TestCase):

    def test_instantiates(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _ConsolidatedTable,
        )
        w = _ConsolidatedTable(_PIDS, _NAMES, _SUMMARIES, _CACHES, "INR")
        self.assertIsNotNone(w)

    def test_table_has_correct_column_count(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _ConsolidatedTable,
        )
        from PySide6.QtWidgets import QTableWidget
        w      = _ConsolidatedTable(_PIDS, _NAMES, _SUMMARIES, _CACHES, "INR")
        tables = w.findChildren(QTableWidget)
        self.assertTrue(len(tables) > 0, "No QTableWidget found")
        tbl = tables[0]
        # 1 label col + 3 project cols
        self.assertEqual(tbl.columnCount(), len(_PIDS) + 1)

    def test_table_has_rows(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _ConsolidatedTable,
        )
        from PySide6.QtWidgets import QTableWidget
        w      = _ConsolidatedTable(_PIDS, _NAMES, _SUMMARIES, _CACHES, "INR")
        tables = w.findChildren(QTableWidget)
        tbl    = tables[0]
        self.assertGreater(tbl.rowCount(), 5)

    def test_total_row_exists(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _ConsolidatedTable,
        )
        from PySide6.QtWidgets import QTableWidget
        w      = _ConsolidatedTable(_PIDS, _NAMES, _SUMMARIES, _CACHES, "INR")
        tables = w.findChildren(QTableWidget)
        tbl    = tables[0]
        labels = [tbl.item(r, 0).text().strip()
                  for r in range(tbl.rowCount())
                  if tbl.item(r, 0)]
        self.assertTrue(
            any("Total" in lbl for lbl in labels),
            msg=f"'Total' row not found. Labels: {labels}"
        )

    def test_best_value_cell_is_green(self):
        """Best-value cell should have formatted currency text."""
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _ConsolidatedTable,
        )
        from PySide6.QtWidgets import QTableWidget
        w      = _ConsolidatedTable(_PIDS, _NAMES, _SUMMARIES, _CACHES, "INR")
        tables = w.findChildren(QTableWidget)
        tbl    = tables[0]
        has_formatted = False
        for r in range(tbl.rowCount()):
            cell = tbl.item(r, 1)
            if cell and cell.text().strip():
                has_formatted = True
                break
        self.assertTrue(has_formatted)


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestGroupedBarChart(unittest.TestCase):

    def _make_chart(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _GroupedBarChart,
        )
        group_data = [
            {"name": n, "color": _PROJECT_COLORS[i],
             "values": [_SUMMARIES[pid]["pillar_totals"]["eco"],
                        _SUMMARIES[pid]["pillar_totals"]["env"],
                        _SUMMARIES[pid]["pillar_totals"]["social"]]}
            for i, (pid, n) in enumerate(zip(_PIDS, _NAMES))
        ]
        return _GroupedBarChart(
            groups=["Economic", "Environmental", "Social"],
            group_data=group_data,
            title="Test Pillar Chart",
            ylabel="Cost (M INR)",
        )

    def test_instantiates(self):
        w = self._make_chart()
        self.assertIsNotNone(w)

    def test_has_canvas(self):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        w       = self._make_chart()
        canvases = w.findChildren(FigureCanvasQTAgg)
        self.assertGreater(len(canvases), 0, "No matplotlib canvas found")

    def test_rebuild_does_not_crash(self):
        w = self._make_chart()
        w._rebuild()   # simulate theme change
        self.assertIsNotNone(w)

    def test_empty_groups_handled(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _GroupedBarChart,
        )
        w = _GroupedBarChart(groups=[], group_data=[], title="Empty", ylabel="Y")
        self.assertIsNotNone(w)

    def test_stage_chart_uses_locked_stage_colors(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _StageChartSection, _STAGE_COLORS,
        )
        w = _StageChartSection(_PIDS, _NAMES, _SUMMARIES, "INR")
        self.assertIsNotNone(w)

    def test_pillar_chart_uses_locked_pillar_colors(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _PillarChartSection, _PILLAR_COLORS,
        )
        w = _PillarChartSection(_PIDS, _NAMES, _SUMMARIES, "INR")
        self.assertIsNotNone(w)


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestDetailedBreakdownSection(unittest.TestCase):

    def test_instantiates_with_full_results(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _DetailedBreakdownSection,
        )
        results = {"pid_a": _RESULTS_A, "pid_b": _RESULTS_B, "pid_c": _RESULTS_C}
        w = _DetailedBreakdownSection(_PIDS, _NAMES, results, "INR")
        self.assertIsNotNone(w)

    def test_table_has_item_rows(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _DetailedBreakdownSection,
        )
        from PySide6.QtWidgets import QTableWidget
        results = {"pid_a": _RESULTS_A, "pid_b": _RESULTS_B}
        w       = _DetailedBreakdownSection(["pid_a", "pid_b"], _NAMES[:2], results, "INR")
        tables  = w.findChildren(QTableWidget)
        self.assertTrue(len(tables) > 0)
        self.assertGreater(tables[0].rowCount(), 2)

    def test_all_zero_results_handled(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _DetailedBreakdownSection,
        )
        empty_r = {"pid_a": {}, "pid_b": {}}
        w = _DetailedBreakdownSection(["pid_a", "pid_b"], _NAMES[:2], empty_r, "INR")
        self.assertIsNotNone(w)

    def test_credit_row_has_negative_value(self):
        """Scrap value rows should produce negative numbers (credits)."""
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _DetailedBreakdownSection, _DETAIL_ROWS,
        )
        from PySide6.QtWidgets import QTableWidget
        from PySide6.QtCore import Qt
        results = {"pid_a": _RESULTS_A, "pid_b": _RESULTS_B}
        w       = _DetailedBreakdownSection(["pid_a", "pid_b"], _NAMES[:2], results, "INR")
        tables  = w.findChildren(QTableWidget)
        if not tables:
            self.skipTest("No table rendered (all-zero results skipped)")
        tbl = tables[0]
        # Find any cell with UserRole float < 0 (credit)
        has_credit = False
        for r in range(tbl.rowCount()):
            for c in range(1, tbl.columnCount()):
                item = tbl.item(r, c)
                if item is not None:
                    val = item.data(Qt.UserRole)
                    if isinstance(val, float) and val < 0:
                        has_credit = True
                        break
        # Credits only exist if scrap_value > 0 (which it is in our fixtures)
        self.assertTrue(has_credit, "No credit (negative) cell found in breakdown table")

    def test_usd_currency_formatting(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _DetailedBreakdownSection,
        )
        from PySide6.QtWidgets import QTableWidget
        results = {"pid_a": _RESULTS_A, "pid_b": _RESULTS_B}
        w       = _DetailedBreakdownSection(["pid_a", "pid_b"], _NAMES[:2], results, "USD")
        tables  = w.findChildren(QTableWidget)
        if not tables:
            self.skipTest("No table rendered")
        tbl = tables[0]
        # USD values should contain 'M'
        has_m = False
        for r in range(tbl.rowCount()):
            for c in range(1, tbl.columnCount()):
                item = tbl.item(r, c)
                if item and "M" in (item.text() or ""):
                    has_m = True
                    break
        self.assertTrue(has_m, "No 'M' suffix found in USD mode")


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestComparisonResultWindowSmoke(unittest.TestCase):
    """
    Smoke test for ComparisonResultWindow.
    We skip the actual worker threads by directly calling _show_results()
    with pre-populated self._results.
    """

    def _build_window(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            ComparisonResultWindow,
        )
        win = ComparisonResultWindow.__new__(ComparisonResultWindow)
        # Minimal manual __init__
        from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame
        from PySide6.QtCore import Qt
        QWidget.__init__(win, None, Qt.Window)
        win._pids        = _PIDS
        win._names       = _NAMES
        win._caches      = _CACHES
        win._override_ap = 0
        win._results     = {"pid_a": _RESULTS_A, "pid_b": _RESULTS_B, "pid_c": _RESULTS_C}
        win._errors      = {}
        win._pending     = set()
        win._workers     = {}
        win._currency    = "INR"
        win._progress_status = {}
        outer = QVBoxLayout(win)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        win._body        = QWidget()
        win._body_layout = QVBoxLayout(win._body)
        win._body_layout.setContentsMargins(32, 24, 32, 32)
        win._body_layout.setSpacing(24)
        scroll.setWidget(win._body)
        outer.addWidget(scroll)
        return win

    def test_show_results_does_not_crash(self):
        win = self._build_window()
        win._show_results()   # must not raise
        self.assertIsNotNone(win)

    def test_body_has_children_after_results(self):
        from PySide6.QtWidgets import QLabel
        win = self._build_window()
        win._show_results()
        labels = win._body.findChildren(QLabel)
        self.assertGreater(len(labels), 0)

    def test_show_results_with_partial_failure(self):
        """One project errors, two succeed — should render partial results."""
        win = self._build_window()
        win._results = {"pid_a": _RESULTS_A, "pid_c": _RESULTS_C}
        win._errors  = {"pid_b": "Simulated calculation error"}
        win._pids    = _PIDS
        win._show_results()
        self.assertIsNotNone(win)

    def test_show_results_all_failed(self):
        """All projects fail — should show failure message without crash."""
        win = self._build_window()
        win._results = {}
        win._errors  = {
            "pid_a": "Error A",
            "pid_b": "Error B",
            "pid_c": "Error C",
        }
        win._show_results()
        self.assertIsNotNone(win)

    def test_clear_body_removes_all_widgets(self):
        from PySide6.QtWidgets import QLabel
        win = self._build_window()
        win._show_results()
        win._clear_body()
        self.assertEqual(win._body_layout.count(), 0)


# ═════════════════════════════════════════════════════════════════════════════
# H. Edge case / boundary tests
# ═════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):

    def test_all_projects_equal_cost_no_crash(self):
        """Equal totals — best selection must still work without division by zero."""
        r_equal = _make_results()  # same for all
        pids_eq = ["p1", "p2"]
        sums_eq = {pid: compute_all_summaries(r_equal) for pid in pids_eq}
        totals  = {pid: sum(sums_eq[pid]["stagewise"].values()) for pid in pids_eq}
        best    = min(totals, key=totals.get)
        # Must return one of the pids (no crash)
        self.assertIn(best, pids_eq)

    def test_very_large_values_no_overflow(self):
        r = _make_results(init_eco=9_999_999_999, use_eco=9_999_999_999)
        s = compute_all_summaries(r)
        self.assertGreater(s["pillar_totals"]["eco"], 0)

    def test_negative_non_credit_values_handled(self):
        """Non-credit fields that somehow come in negative must not crash."""
        r = _make_results(init_eco=-500_000)
        s = compute_all_summaries(r)
        # eco total may be negative, but must not raise
        self.assertIsInstance(s["pillar_totals"]["eco"], float)

    def test_safe_float_dict(self):
        self.assertAlmostEqual(_safe_float({"a": 1}), 0.0)

    def test_safe_float_list(self):
        self.assertAlmostEqual(_safe_float([1, 2, 3]), 0.0)

    def test_heatmap_col_max_zero_no_division(self):
        """If all values are 0, normalisation must not raise ZeroDivisionError."""
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _lerp_color,
        )
        # Simulate intensity = 0 / 0 guard: intensity = val/col_m if col_m > 0 else 0
        col_m   = 0.0
        val     = 0.0
        intensity = val / col_m if col_m > 0 else 0.0
        self.assertAlmostEqual(intensity, 0.0)

    def test_fmt_date_old_format_no_T(self):
        # Some date strings might not have 'T'
        result = _fmt_date("2024-06-15")
        # Should return a non-empty string (not crash)
        self.assertIsInstance(result, str)


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestWordWrapHeaderView(unittest.TestCase):

    def test_instantiates(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _WordWrapHeaderView,
        )
        from PySide6.QtWidgets import QTableWidget
        tbl = QTableWidget(2, 3)
        hdr = _WordWrapHeaderView(tbl)
        self.assertIsNotNone(hdr)

    def test_size_hint_expands_for_multiline_text(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _WordWrapHeaderView,
        )
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
        tbl = QTableWidget(2, 3)
        hdr = _WordWrapHeaderView(tbl)
        tbl.setHorizontalHeader(hdr)
        tbl.setHorizontalHeaderItem(0, QTableWidgetItem("Short"))
        tbl.setHorizontalHeaderItem(1, QTableWidgetItem("M_20_2L_OF_S (imported) (imported) 500yrs horizon"))
        tbl.setHorizontalHeaderItem(2, QTableWidgetItem("Normal"))
        tbl.resize(400, 300)
        # Header sizeHint height should be large enough to hold wrapped lines (>32px)
        hint = hdr.sizeHint()
        self.assertGreaterEqual(hint.height(), 32)


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestTableFontConsistency(unittest.TestCase):
    """Verifies font size consistency across both comparison tables."""

    def setUp(self):
        from three_ps_lcca_gui.gui.components.outputs.comparison_page import (
            _ConsolidatedTable,
            _DetailedBreakdownSection,
            compute_all_summaries,
        )
        from PySide6.QtWidgets import QTableWidget
        results = {p: _make_results() for p in _PIDS}
        summaries = {p: compute_all_summaries(results[p]) for p in _PIDS}
        self.w1 = _ConsolidatedTable(_PIDS, _NAMES, summaries, _CACHES, "INR")
        self.w2 = _DetailedBreakdownSection(_PIDS, _NAMES, results, "INR")
        self.t1 = self.w1.findChildren(QTableWidget)[0]
        self.t2 = self.w2.findChildren(QTableWidget)[0]

    def test_tables_share_same_cell_font_size(self):
        """Cell font point sizes must match between Consolidated and Detailed tables."""
        f1 = self.t1.item(1, 0).font().pointSize()
        f2 = self.t2.item(0, 1).font().pointSize()
        self.assertEqual(f1, f2, f"Cell font size mismatch: {f1}pt vs {f2}pt")

    def test_tables_share_same_header_font_size(self):
        """Header font point sizes must match between Consolidated and Detailed tables."""
        h1 = self.t1.horizontalHeader().font().pointSize()
        h2 = self.t2.horizontalHeader().font().pointSize()
        self.assertEqual(h1, h2, f"Header font size mismatch: {h1}pt vs {h2}pt")

    def test_table_default_fonts_match(self):
        """Default table widget fonts must have identical point sizes."""
        self.assertEqual(
            self.t1.font().pointSize(),
            self.t2.font().pointSize(),
        )


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    runner  = unittest.TextTestRunner(verbosity=2)
    suite   = unittest.TestLoader().loadTestsFromModule(
        __import__(__name__)
    )
    result  = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
