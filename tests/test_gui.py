"""The PyQt window, run offscreen: builds, and shows events without crashing."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # the GUI is optional; the console agent doesn't need PyQt
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_events_render(self):
        from civ5ai.agent import turn_overview
        from civ5ai.gui import MainWindow
        from civ5ai.state import parse, summarize
        from tests.test_state import SNAPSHOT

        w = MainWindow()
        s = parse(SNAPSHOT)
        text = summarize(s)
        w.on_event("status", "", {"status": "playing"})
        w.on_event("turn", text, {"plan": "Target: science victory.", "lessons": ["Shoot with cities."],
                                  **turn_overview(s, text)})
        w.on_event("model", "I will found a city <here> & research Pottery.", {})
        w.on_event("action", "", {"tool": "found_city", "args": {"unit_id": 8192},
                                  "result": "ok: founded Berlin", "ok": True})
        w.on_event("action", "", {"tool": "move_unit", "args": {"unit_id": 1, "x": 2, "y": 3},
                                  "result": "error: it is a mountain", "ok": False})
        w.on_event("warn", "waiting for the game", {})

        self.assertEqual(w.turn_label.text(), "Turn 12")
        self.assertEqual(w.status.text(), "playing")
        feed = w.feed.toPlainText()
        for expected in ["Turn 12", "found_city", "founded Berlin", "it is a mountain", "<here> & research"]:
            self.assertIn(expected, feed)
        self.assertIn("UNIT_BARBARIAN_WARRIOR", w.lists["threats"].text())
        self.assertIn("Target: science victory.", w.plan.text())
        self.assertIn("Turn 12", w.prompt_view.toPlainText())

        w.on_event("lessons", "", {"lessons": ["[general] Shoot with cities.", "[science] Build libraries.",
                                               "[domination] Build an army."]})
        self.assertIn("libraries", w.lessons_label.text())
        self.assertNotIn("army", w.lessons_label.text())  # in use: general + science
        self.assertIn("science", w.lessons_filter.itemText(0))
        w.lessons_filter.setCurrentIndex(w.lessons_filter.findData("domination"))
        self.assertIn("army", w.lessons_label.text())
        self.assertNotIn("cities", w.lessons_label.text())
        self.assertEqual(w.lessons_filter.currentText(), "Domination: 1")
        w.close()


    def test_start_asks_for_an_opening_message(self):
        from unittest import mock
        from civ5ai import gui

        started = []

        class FakeRunner:
            def __init__(self, **kw):
                started.append(kw)
                self.messages = mock.Mock(qsize=lambda: 0)

            def run(self):
                pass

        w = gui.MainWindow()
        with mock.patch.object(gui, "Runner", FakeRunner),                 mock.patch.object(gui.OpeningDialog, "exec", return_value=0):
            w.start()  # cancelled
        self.assertEqual(started, [])
        with mock.patch.object(gui, "Runner", FakeRunner),                 mock.patch.object(gui.OpeningDialog, "exec", return_value=1),                 mock.patch.object(gui.OpeningDialog, "text", return_value="Go for science."):
            w.start()
        self.assertEqual(started[0]["say"], "Go for science.")
        w.close()


if __name__ == "__main__":
    unittest.main()
