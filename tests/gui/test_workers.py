'''
pickmix: tests for GUI background workers
'''

# Import external dependencies
from pytestqt.qtbot import QtBot
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

# Import internal pickmix objects
from pickmix.gui.workers import run_in_background

# TestWorkers: background workers
class TestWorkers:
    # test_done: the result arrives on the GUI thread
    def test_done(self, qtbot: QtBot) -> None:
        got: list[tuple[int, bool]] = []
        run_in_background(lambda: 6 * 7, lambda r: got.append((r, QThread.currentThread() == QApplication.instance().thread())), lambda m: None)
        qtbot.waitUntil(lambda: bool(got))
        assert got == [(42, True)]

    # test_failed: an exception arrives as a message
    def test_failed(self, qtbot: QtBot) -> None:
        got: list[str] = []
        # boom: always fails
        def boom() -> None:
            raise ValueError('nope')
        run_in_background(boom, lambda r: None, got.append)
        qtbot.waitUntil(lambda: bool(got))
        assert got == ['ValueError: nope']
