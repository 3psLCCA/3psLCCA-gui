"""Structure tab cards (StructureManagerWidget + StructureTableWidget).

Builds a Foundation tab from in-memory chunks, so a broken table or card
file fails here instead of only at app start.
"""
import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QObject, QRect, Signal  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QStyleOptionViewItem  # noqa: E402

from three_ps_lcca_gui.gui.components.structure.widgets.manager import StructureManagerWidget  # noqa: E402


def _item(name, qty, rate):
    return {"id": name, "values": {"material_name": name, "quantity": qty, "rate": rate,
                                   "unit": "m3", "rate_source": "SOR 2023"},
            "meta": {}, "state": {"in_trash": False}}


@pytest.fixture
def widget(qapp):
    chunks = {
        "general_info": {"project_currency": "INR"},
        "str_foundation": {
            "Excavation": [_item("Backfilling", 100, 1000)],
            "Pile Cap": [_item("Reinforcement in pile cap", 2, 100),
                         _item("Crash barrier\n[M40]", 3, 100)],        },
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

    w = StructureManagerWidget(Controller(), "str_foundation")
    w.resize(1100, 700)
    w.show()
    w.on_refresh()
    w.set_section_name("Foundation")
    qapp.processEvents()
    yield w
    w.close()


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_cards_built(widget):
    assert widget.sections["Excavation"].rowCount() == 1
    assert widget.sections["Pile Cap"].rowCount() == 2


def test_header_counts_only_components_with_materials(widget):
    filled = sum(1 for t in widget.sections.values() if t.rowCount())
    assert filled == 2
    assert widget.count_lbl.text() == "2 components"


class _RecordingPainter(QPainter):
    """Paints into an image and keeps every string passed to drawText."""

    def __init__(self, image):
        super().__init__(image)
        self.texts = []

    def drawText(self, *args):
        self.texts += [a for a in args if isinstance(a, str)]
        return super().drawText(*args)


def test_name_with_line_break_is_one_line(widget):
    # a name saved with a line break is drawn as one line
    table = widget.sections["Pile Cap"]
    index = table.model().index(1, 0)
    assert "\n" in index.data()
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 400, 40)
    option.widget = table
    image = QImage(400, 40, QImage.Format_ARGB32)
    painter = _RecordingPainter(image)
    table.itemDelegateForIndex(index).paint(painter, option, index)
    painter.end()
    assert "Crash barrier [M40]" in painter.texts
