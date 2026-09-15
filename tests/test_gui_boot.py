"""Offscreen GUI boot test: the main window must construct, show and close.

Runs with ``QT_QPA_PLATFORM=offscreen`` so it works headless (CI, containers).
On machines without system Qt libraries, build the stub set first — see the
README's "Headless/CI note"::

    python tools/genstubs.py .stublibs
    LD_LIBRARY_PATH=.stublibs QT_QPA_PLATFORM=offscreen python -m unittest tests.test_gui_boot
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from PySide6.QtWidgets import QApplication

    from jautomatic import APP_TITLE, __version__
    from jautomatic.ui.main_window import MainWindow

    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class GuiBootTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_boot_show_close(self):
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            window = MainWindow(data_dir=tmp)
            try:
                window.show()
                self.app.processEvents()
                self.assertIn(APP_TITLE, window.windowTitle())
                self.assertIn(__version__, window.windowTitle())
                self.assertEqual(len(window.tabs), 5)
                self.assertTrue(window.status_label.text())
            finally:
                window.close()
                self.app.processEvents()
            self.assertTrue(window._closing)

    def test_boot_twice_restores_geometry(self):
        # Second boot in the same data dir must not crash (geometry restore
        # reads QSettings written by the first window's closeEvent).
        with tempfile.TemporaryDirectory(prefix="jautomatic-gui-boot-") as tmp:
            first = MainWindow(data_dir=tmp)
            first.show()
            self.app.processEvents()
            first.close()
            self.app.processEvents()
            second = MainWindow(data_dir=tmp)
            try:
                second.show()
                self.app.processEvents()
            finally:
                second.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
