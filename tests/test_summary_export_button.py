"""Structure Summary's Export Priced BOQ button.

Covers the hover / pressed colours (solid theme shades, not the see-through
global hover) and the busy state while an export runs: the button is
disabled and reads "Exporting…", then comes back.
"""
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QObject, QPoint, Signal  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from three_ps_lcca_gui.gui import themes  # noqa: E402
from three_ps_lcca_gui.gui.themes import get_token  # noqa: E402
from three_ps_lcca_gui.gui.components.structure import main as structure_main  # noqa: E402
from three_ps_lcca_gui.gui.components.structure.widgets.summary import (  # noqa: E402
    StructureSummaryWidget,
)


def _item(name, qty, rate):
    return {"id": name, "values": {"material_name": name, "quantity": qty, "rate": rate,
                                   "unit": "m3", "rate_source": "SOR 2023"},
            "meta": {}, "state": {"in_trash": False}}


def _controller():
    chunks = {
        "general_info": {"project_currency": "INR", "project_name": "Test"},
        "str_foundation": {"Excavation": [_item("Backfilling", 100, 1000)]},
    }

    class Engine:
        def fetch_chunk(self, c):
            return chunks.get(c)

        def stage_update(self, chunk_name=None, data=None):
            chunks[chunk_name] = data

    class Controller(QObject):
        chunk_updated = Signal(str)
        material_trashed = Signal(str)
        engine = Engine()

        def get_chunk(self, c):
            return chunks.get(c) or {}

    return Controller()


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    themes.reapply(app)  # main.qss, so the #exportBtn rules apply
    return app


@pytest.fixture
def summary(qapp):
    w = StructureSummaryWidget(_controller())
    w.resize(900, 400)
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def _centre_colour(btn):
    """Colour of the button's fill, sampled away from its label."""
    img = btn.grab().toImage()
    return QColor(img.pixel(QPoint(2, img.height() // 2))).name()


# ── hover / pressed colours ──────────────────────────────────────────────


def test_hover_tokens_are_solid_and_differ(qapp):
    base = get_token("warning")
    for name in ("warning-hover", "warning-pressed"):
        shade = get_token(name)
        assert len(shade) == 7, f"{name} must be solid #rrggbb, got {shade!r}"
        assert shade.lower() != base.lower()
    assert get_token("warning-hover") != get_token("warning-pressed")


@pytest.mark.parametrize("btn_name", ["export_btn", "fmt_btn"])
def test_hover_changes_the_fill(summary, qapp, btn_name):
    btn = getattr(summary, btn_name)
    assert btn.isEnabled()
    assert _centre_colour(btn) == get_token("warning").lower()

    QTest.mouseMove(btn, QPoint(4, btn.height() // 2))  # pointer enters
    qapp.processEvents()
    assert btn.underMouse()
    assert _centre_colour(btn) == get_token("warning-hover").lower()

    QTest.mouseMove(summary, QPoint(5, summary.height() - 5))  # and leaves
    qapp.processEvents()
    assert _centre_colour(btn) == get_token("warning").lower()


def test_button_is_standard_height(summary):
    from three_ps_lcca_gui.gui.theme import BTN_MD
    assert summary.export_btn.height() == BTN_MD
    assert summary.fmt_btn.height() == BTN_MD


# ── busy state ──────────────────────────────────────────────────────────


def test_set_exporting_disables_and_relabels(summary):
    summary.set_exporting(True)
    assert not summary.export_btn.isEnabled()
    assert not summary.fmt_btn.isEnabled()
    assert summary._export_label.text() == "Exporting…"

    summary.set_exporting(False)
    assert summary.export_btn.isEnabled()
    assert summary.fmt_btn.isEnabled()
    assert summary._export_label.text() == "Export Priced BOQ"


def test_refresh_during_export_keeps_it_disabled(summary):
    # a data refresh mid-export must not re-enable the button
    summary.set_exporting(True)
    summary.on_refresh(force=True)
    assert not summary.export_btn.isEnabled()
    summary.set_exporting(False)
    assert summary.export_btn.isEnabled()


def test_no_items_stays_disabled_after_export(qapp):
    w = StructureSummaryWidget(_controller())
    w.controller.engine.stage_update("str_foundation", {})
    w.on_refresh(force=True)
    w.set_exporting(True)
    w.set_exporting(False)
    assert not w.export_btn.isEnabled()


# ── the real export flow (StructureTabView._download_excel) ─────────────


@pytest.fixture
def tab_view(qapp, monkeypatch, tmp_path):
    view = structure_main.StructureTabView(controller=_controller())
    view.show()
    view.summary_tab.on_refresh(force=True)  # as when the Summary tab is opened
    qapp.processEvents()
    assert view.summary_tab.export_btn.isEnabled()
    out = str(tmp_path / "boq.xlsx")
    monkeypatch.setattr(structure_main.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (out, "Excel Workbook (*.xlsx)")))
    monkeypatch.setattr(structure_main.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(structure_main.QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(structure_main.QDesktopServices, "openUrl", staticmethod(lambda *a, **k: True))
    yield view
    view.close()


def _record_state(view, seen, result=None, error=None):
    def fake_export(*_a, **_k):
        s = view.summary_tab
        seen.append((s.export_btn.isEnabled(), s.fmt_btn.isEnabled(), s._export_label.text()))
        if error:
            raise error
        return result
    return fake_export


def test_export_flow_busy_then_restored(tab_view, monkeypatch):
    seen = []
    monkeypatch.setattr(structure_main, "export_boq", _record_state(tab_view, seen, result=1))
    tab_view.summary_tab.export_requested.emit(".xlsx")

    assert seen == [(False, False, "Exporting…")], "busy while exporting"
    s = tab_view.summary_tab
    assert s.export_btn.isEnabled() and s._export_label.text() == "Export Priced BOQ"


def test_export_flow_restored_after_error(tab_view, monkeypatch):
    seen = []
    monkeypatch.setattr(structure_main, "export_boq",
                        _record_state(tab_view, seen, error=RuntimeError("disk full")))
    tab_view.summary_tab.export_requested.emit(".xlsx")

    assert seen == [(False, False, "Exporting…")]
    s = tab_view.summary_tab
    assert s.export_btn.isEnabled() and s._export_label.text() == "Export Priced BOQ"


def test_cancelled_dialog_never_goes_busy(tab_view, monkeypatch):
    seen = []
    monkeypatch.setattr(structure_main.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(structure_main, "export_boq", _record_state(tab_view, seen, result=1))
    tab_view.summary_tab.export_requested.emit(".xlsx")

    assert seen == []
    assert tab_view.summary_tab.export_btn.isEnabled()
