"""Regression: themed table headings must actually render text.

Qt <= 6.9 (the installer was pinned to pyside6<6.10) leaves an empty clip region on the
painter after QStyleSheetStyle draws CE_Header, which blanked every heading
painted manually after drawControl. Dev venvs on newer Qt never showed it, so
this test compares a header rendered with labels against one with empty labels:
if the text is clipped away the two images are identical.
"""
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from three_ps_lcca_gui.gui import themes
    themes.reapply(a)  # the bug only appears with the app stylesheet active
    return a


def _grab_header(header_cls, labels, **kw):
    t = QtWidgets.QTableWidget(1, len(labels))
    t.setHorizontalHeader(header_cls(**kw, parent=t))
    t.setHorizontalHeaderLabels(labels)
    t.resize(600, 120)
    t.show()
    QtWidgets.QApplication.processEvents()
    img = t.horizontalHeader().grab().toImage()
    t.close()
    return img


def test_word_wrap_header_draws_text(app):
    from three_ps_lcca_gui.gui.components.utils.table_widgets import WordWrapHeaderView
    with_text = _grab_header(WordWrapHeaderView, ["Material", "Category", "Trips"])
    blank = _grab_header(WordWrapHeaderView, ["", "", ""])
    assert with_text != blank, "WordWrapHeaderView headings rendered blank"


def test_grouped_header_draws_text(app):
    from three_ps_lcca_gui.gui.components.utils.table_widgets import GroupedHeaderView
    groups = [(1, 2, "Group")]
    with_text = _grab_header(GroupedHeaderView, ["Mat", "a", "b"], groups=groups)
    blank = _grab_header(GroupedHeaderView, ["", "", ""], groups=groups)
    assert with_text != blank, "GroupedHeaderView headings rendered blank"
