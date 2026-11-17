"""Desktop planning, worker, and real Qt drag-and-drop regression checks."""

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from desktop_jobs import build_plan, run_batch
from test_compress_images import png

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    import desktop_app
except ImportError:
    QtWidgets = None
    if os.environ.get("REQUIRE_GUI_TESTS") == "1":
        raise RuntimeError("Desktop CI requires requirements-gui.txt")


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.folder = self.root / "source"; self.folder.mkdir()
        self.image = self.folder / "image with spaces.png"; self.image.write_bytes(png())
        self.output = self.root / "output"

    def tearDown(self):
        self.temporary.cleanup()

    def test_overlapping_file_and_folder_selections_do_not_duplicate_sources(self):
        jobs, _ = build_plan([self.image, self.folder, self.image], self.output)
        self.assertEqual(len(jobs), 1)

    def test_same_named_files_get_distinct_destinations(self):
        other = self.root / "other"; other.mkdir()
        second = other / self.image.name; second.write_bytes(png())
        jobs, _ = build_plan([self.image, second], self.output)
        self.assertEqual(len({job.destination for job in jobs}), 2)
        self.assertTrue(any("(2)" in job.destination.name for job in jobs))

    def test_duplicate_folder_names_keep_both_hierarchies(self):
        parent = self.root / "other"; parent.mkdir()
        folder = parent / self.folder.name; folder.mkdir()
        (folder / "second.png").write_bytes(png())
        jobs, _ = build_plan([self.folder, folder], self.output)
        self.assertEqual({job.destination.parent.name for job in jobs}, {"source", "source (2)"})

    def test_folder_named_like_an_image_does_not_collide_with_file(self):
        folder = self.root / self.image.name; folder.mkdir()
        (folder / "second.png").write_bytes(png())
        jobs, _ = build_plan([folder, self.image], self.output)
        self.assertEqual(len(jobs), 2)
        self.assertNotEqual(jobs[0].destination, jobs[1].destination.parent)

    def test_recursive_toggle(self):
        nested = self.folder / "nested"; nested.mkdir()
        (nested / "second.png").write_bytes(png())
        self.assertEqual(len(build_plan([self.folder], self.output, False)[0]), 1)
        self.assertEqual(len(build_plan([self.folder], self.output, True)[0]), 2)

    def test_output_inside_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            build_plan([self.folder], self.folder / "output")

    def test_output_overlapping_source_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "original"):
            build_plan([self.image], self.folder)

    def test_missing_and_nonimage_inputs_are_handled(self):
        with self.assertRaisesRegex(ValueError, "no longer exists"):
            build_plan([self.root / "missing.png"], self.output)
        text = self.root / "notes.txt"; text.write_text("not an image")
        jobs, warnings = build_plan([text], self.output)
        self.assertFalse(jobs); self.assertTrue(warnings)

    def test_real_batch_preserves_sources_and_reports_progress(self):
        original = self.image.read_bytes(); progress = []
        summary = run_batch([self.image], self.output, on_progress=lambda *args: progress.append(args))
        self.assertEqual(summary["files"][0]["status"], "optimized_png")
        self.assertEqual(self.image.read_bytes(), original)
        self.assertEqual(progress[0][:2], (1, 1))
        self.assertGreater(summary["total_saved_bytes"], 0)

    def test_cancellation_before_start_writes_nothing(self):
        cancel = threading.Event(); cancel.set()
        summary = run_batch([self.image], self.output, cancel=cancel)
        self.assertTrue(summary["cancelled"]); self.assertFalse(self.output.exists())

    def test_cancellation_between_files_stops_after_completed_image(self):
        second = self.folder / "second.png"; second.write_bytes(png())
        cancel = threading.Event()
        summary = run_batch([self.image, second], self.output, cancel=cancel,
                            on_progress=lambda *args: cancel.set())
        self.assertEqual(len(summary["files"]), 1); self.assertTrue(summary["cancelled"])


@unittest.skipUnless(QtWidgets is not None, "Install requirements-gui.txt for desktop tests")
class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.image = self.root / "日本語 image with spaces.png"; self.image.write_bytes(png())
        self.window = desktop_app.MainWindow(show_dialogs=False)
        self.window.output_edit.setText(str(self.root / "output"))
        self.window.show(); self.app.processEvents()

    def tearDown(self):
        if self.window.jobs_thread is not None:
            self.window.jobs_thread.cancel.set()
            self.window.jobs_thread.wait(10000)
            self.app.processEvents()
        self.window.close(); self.app.processEvents(); self.temporary.cleanup()

    def pump_until(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.app.processEvents(); time.sleep(0.005)
            if time.monotonic() > deadline:
                self.fail("Desktop event loop timed out")
        self.app.processEvents()

    def test_real_drop_event_accepts_local_paths_with_spaces_and_unicode(self):
        mime = QtCore.QMimeData(); mime.setUrls([QtCore.QUrl.fromLocalFile(str(self.image))])
        enter = QtGui.QDragEnterEvent(QtCore.QPoint(12, 12), QtCore.Qt.DropAction.CopyAction,
                                     mime, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.window.drop_zone, enter)
        self.assertTrue(enter.isAccepted())
        drop = QtGui.QDropEvent(QtCore.QPointF(12, 12), QtCore.Qt.DropAction.CopyAction,
                               mime, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.window.drop_zone, drop)
        self.assertEqual(self.window.paths, [self.image])
        self.assertTrue(self.window.compress_button.isEnabled())

    def test_remote_urls_are_not_downloaded_or_accepted(self):
        mime = QtCore.QMimeData(); mime.setUrls([QtCore.QUrl("https://example.com/photo.png")])
        event = QtGui.QDragEnterEvent(QtCore.QPoint(12, 12), QtCore.Qt.DropAction.CopyAction,
                                     mime, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.window.drop_zone, event)
        self.assertFalse(event.isAccepted()); self.assertFalse(self.window.paths)

    def test_add_remove_and_duplicate_selection(self):
        self.window.add_paths([str(self.image), str(self.image)])
        self.assertEqual(len(self.window.paths), 1)
        self.window.queue_list.item(0).setSelected(True); self.window.remove_selected()
        self.assertFalse(self.window.paths); self.assertFalse(self.window.compress_button.isEnabled())

    def test_background_compression_updates_results_and_reenables_controls(self):
        original = self.image.read_bytes(); self.window.add_paths([str(self.image)])
        self.window.start_batch()
        self.assertFalse(self.window.add_files_button.isEnabled())
        self.pump_until(lambda: self.window.jobs_thread is None)
        self.assertEqual(self.window.results.rowCount(), 1)
        self.assertEqual(self.window.results.item(0, 1).text(), "Compressed")
        self.assertTrue(self.window.report_button.isEnabled())
        self.assertTrue(self.window.open_button.isEnabled())
        self.assertTrue(self.window.add_files_button.isEnabled())
        self.assertEqual(self.image.read_bytes(), original)

    def test_invalid_output_becomes_readable_error(self):
        self.window.add_paths([str(self.image)])
        self.window.output_edit.setText(str(self.root))
        self.window.start_batch(); self.pump_until(lambda: self.window.jobs_thread is None)
        self.assertIn("Choose", self.window.status_label.text())
        self.assertTrue(self.window.compress_button.isEnabled())

    def test_cancel_keeps_event_loop_responsive_and_restores_controls(self):
        self.window.add_paths([str(self.image)])
        started = threading.Event(); responsive = threading.Event()
        def waiting_batch(inputs, output, recursive, backend, cancel, planned, progress):
            started.set()
            while not cancel.wait(0.01): pass
            return {"files": [], "total_saved_bytes": 0, "planned": 1, "cancelled": True}
        with patch.object(desktop_app, "run_batch", side_effect=waiting_batch):
            self.window.start_batch(); self.pump_until(started.is_set)
            QtCore.QTimer.singleShot(0, responsive.set); self.pump_until(responsive.is_set)
            self.window.cancel_batch(); self.pump_until(lambda: self.window.jobs_thread is None)
        self.assertIn("Stopped", self.window.status_label.text())
        self.assertTrue(self.window.compress_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
