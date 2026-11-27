"""Status bar text and a wait cursor while a slow build blocks the UI."""

from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


@contextmanager
def busy_status(widget):
    """Yields step(text): shows text in the window's status bar right away.
    When the block ends the cursor comes back and the bar is cleared, so
    the save label shows again (putting back an earlier timed message,
    like "Saved.", would make it stay for good).
    Does nothing to the bar while widget is not yet inside a window that
    has one (pages built during project open report through on_step)."""
    bar = getattr(widget.window(), "status_bar", None)

    def step(text):
        if bar:
            bar.showMessage(text)
            bar.repaint()  # now - the main thread is about to block

    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        yield step
    finally:
        QApplication.restoreOverrideCursor()
        if bar:
            bar.clearMessage()
