"""Windowed drag-and-drop application. End users launch the packaged app."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading

from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from compress_images import IMAGE_SUFFIXES, write_new
from desktop_jobs import run_batch, source_key

APP_NAME = "Lossless Image Compressor"
VERSION = "1.0.0"
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

STYLES = """
QMainWindow { background: #f4f7fc; }
QWidget { color: #1c2b46; font-size: 13px; }
QLabel#Title { font-size: 28px; font-weight: 700; }
QLabel#Subtitle { color: #61718b; font-size: 13px; }
QLabel#Badge { color: #107569; background: #e2f5ee; border-radius: 11px; padding: 6px 12px; font-weight: 600; }
QFrame#DropZone { background: white; border: 2px dashed #96afd7; border-radius: 15px; }
QFrame#DropZone[hover="true"] { background: #eaf2ff; border-color: #2b65d9; }
QLabel#DropTitle { font-size: 19px; font-weight: 600; color: #284c87; border: none; }
QLabel#DropHint { color: #61718b; border: none; }
QPushButton { background: white; border: 1px solid #cfdaea; padding: 9px 14px; border-radius: 7px; font-weight: 500; }
QPushButton:hover { background: #eaf0fa; border-color: #9db7df; }
QPushButton:disabled { color: #9ca9ba; background: #edf1f7; border-color: #dde4ee; }
QPushButton#Primary { background: #2863d8; color: white; border: none; padding: 13px 24px; font-size: 15px; font-weight: 600; }
QPushButton#Primary:hover { background: #1d52ba; }
QPushButton#Primary:disabled { background: #b7c9eb; color: white; }
QLineEdit { background: white; border: 1px solid #cfdaea; border-radius: 7px; padding: 9px; }
QTabWidget::pane { background: white; border: 1px solid #dce4f0; border-radius: 8px; }
QTabBar::tab { padding: 9px 16px; color: #61718b; background: #eaf0f9; }
QTabBar::tab:selected { color: #215dce; background: #f4f7fc; font-weight: 600; border-bottom: 2px solid #2863d8; }
QListWidget, QTableWidget { border: none; background: white; alternate-background-color: #f7f9fd; selection-background-color: #e4edff; selection-color: #1c2b46; }
QHeaderView::section { background: #f3f6fb; border: none; padding: 8px; color: #60718d; font-weight: 600; }
QProgressBar { border: none; background: #e0e8f4; border-radius: 5px; min-height: 10px; max-height: 10px; }
QProgressBar::chunk { background: #2b68df; border-radius: 5px; }
QCheckBox { color: #52647f; spacing: 7px; }
"""


def friendly_size(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024 or unit == "GB":
            return "{:.1f} {}".format(value, unit) if unit != "B" else "{} B".format(int(value))
        value /= 1024


def bundled_backend():
    name = "jpegtran.exe" if sys.platform == "win32" else "jpegtran"
    path = ROOT / "bin" / name
    return str(path) if path.is_file() else None


def result_label(status):
    return {"optimized_png": "Compressed", "optimized_jpeg": "Compressed",
            "kept_not_smaller": "Already optimized · copied",
            "kept_animated_png": "Animation preserved · copied",
            "kept_unsupported_format": "Format preserved · copied",
            "kept_jpegtran_not_configured": "JPEG helper unavailable · copied",
            "kept_jpeg_invariants_changed": "Preservation check · original copied",
            "skipped_existing": "Already exists · skipped", "skipped_symlink": "Link · skipped",
            "error": "Could not process"}.get(status, status)


class DropZone(QtWidgets.QFrame):
    paths_dropped = QtCore.Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(132)
        self.setAccessibleName("Drop images and folders here")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title = QtWidgets.QLabel("Drop images or folders here")
        title.setObjectName("DropTitle")
        hint = QtWidgets.QLabel("From Finder or File Explorer — or use the buttons below")
        hint.setObjectName("DropHint")
        layout.addWidget(title, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

    def dragEnterEvent(self, event):
        if self.isEnabled() and any(url.isLocalFile() for url in event.mimeData().urls()):
            self.setProperty("hover", True)
            self.style().unpolish(self); self.style().polish(self)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("hover", False)
        self.style().unpolish(self); self.style().polish(self)
        event.accept()

    def dropEvent(self, event):
        self.setProperty("hover", False)
        self.style().unpolish(self); self.style().polish(self)
        if not self.isEnabled():
            event.ignore(); return
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class BatchThread(QtCore.QThread):
    planned = QtCore.Signal(int, list)
    progress = QtCore.Signal(int, int, dict)
    outcome = QtCore.Signal(dict)

    def __init__(self, paths, output, recursive, backend):
        super().__init__()
        self.paths, self.output = list(paths), output
        self.recursive, self.backend = recursive, backend
        self.cancel = threading.Event()

    def run(self):
        try:
            result = run_batch(self.paths, self.output, self.recursive, self.backend, self.cancel,
                               lambda count, warnings: self.planned.emit(count, warnings),
                               lambda done, total, item: self.progress.emit(done, total, item))
        except Exception as error:
            result = {"files": [], "total_saved_bytes": 0, "cancelled": False,
                      "warnings": [], "fatal_error": str(error)}
        self.outcome.emit(result)


class MainWindow(QtWidgets.QMainWindow):
    batch_done = QtCore.Signal(dict)

    def __init__(self, show_dialogs=True):
        super().__init__()
        self.show_dialogs = show_dialogs
        self.paths, self.summary = [], None
        self.jobs_thread = None
        self.pending_summary = None
        self.close_when_done = False
        self.backend = bundled_backend()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 830)
        self.setMinimumSize(740, 700)
        self.setWindowIcon(QtGui.QIcon(str(ROOT / "app-icon.svg")))
        palette = self.palette()
        for role, color in [(QtGui.QPalette.ColorRole.Window, "#f4f7fc"),
                            (QtGui.QPalette.ColorRole.WindowText, "#1c2b46"),
                            (QtGui.QPalette.ColorRole.Base, "#ffffff"),
                            (QtGui.QPalette.ColorRole.AlternateBase, "#f7f9fd"),
                            (QtGui.QPalette.ColorRole.Text, "#1c2b46"),
                            (QtGui.QPalette.ColorRole.Button, "#ffffff"),
                            (QtGui.QPalette.ColorRole.ButtonText, "#1c2b46"),
                            (QtGui.QPalette.ColorRole.Highlight, "#2863d8"),
                            (QtGui.QPalette.ColorRole.HighlightedText, "#ffffff")]:
            palette.setColor(role, QtGui.QColor(color))
        self.setPalette(palette)
        self.setStyleSheet(STYLES)
        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(13)

        heading = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Smaller files. Same image."); title.setObjectName("Title")
        heading.addWidget(title); heading.addStretch()
        badge = QtWidgets.QLabel("LOSSLESS"); badge.setObjectName("Badge"); heading.addWidget(badge)
        layout.addLayout(heading)
        subtitle = QtWidgets.QLabel("Compress locally. Keep every pixel. Your originals stay untouched.")
        subtitle.setObjectName("Subtitle"); layout.addWidget(subtitle)
        self.drop_zone = DropZone(); self.drop_zone.paths_dropped.connect(self.add_paths)
        layout.addWidget(self.drop_zone)

        tools = QtWidgets.QHBoxLayout()
        self.add_files_button = QtWidgets.QPushButton("Add images…")
        self.add_folder_button = QtWidgets.QPushButton("Add folder…")
        self.remove_button = QtWidgets.QPushButton("Remove selected")
        self.clear_button = QtWidgets.QPushButton("Clear")
        for button in (self.add_files_button, self.add_folder_button, self.remove_button, self.clear_button):
            tools.addWidget(button)
        tools.addStretch(); layout.addLayout(tools)
        self.add_files_button.clicked.connect(self.pick_files)
        self.add_folder_button.clicked.connect(self.pick_folder)
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(self.clear_selection)

        self.tabs = QtWidgets.QTabWidget()
        self.queue_list = QtWidgets.QListWidget()
        self.queue_list.setAccessibleName("Images and folders to compress")
        self.queue_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results = QtWidgets.QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["Image", "Result", "Saved", "Output"])
        self.results.setAlternatingRowColors(True)
        self.results.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.results.horizontalHeader().setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.queue_list, "Images (0)")
        self.tabs.addTab(self.results, "Results")
        layout.addWidget(self.tabs, 1)

        destination = QtWidgets.QHBoxLayout()
        destination.addWidget(QtWidgets.QLabel("Save to"))
        self.output_edit = QtWidgets.QLineEdit(str(Path.home() / "Compressed Images"))
        self.output_edit.setAccessibleName("Output folder")
        self.output_edit.setReadOnly(True)
        self.browse_button = QtWidgets.QPushButton("Choose folder…")
        self.browse_button.clicked.connect(self.pick_output)
        destination.addWidget(self.output_edit, 1); destination.addWidget(self.browse_button)
        layout.addLayout(destination)
        options = QtWidgets.QHBoxLayout()
        self.recursive_box = QtWidgets.QCheckBox("Include subfolders"); self.recursive_box.setChecked(True)
        options.addWidget(self.recursive_box); options.addStretch()
        self.backend_label = QtWidgets.QLabel()
        self.backend_label.setObjectName("Subtitle")
        options.addWidget(self.backend_label)
        self.backend_button = QtWidgets.QPushButton("JPEG helper…")
        self.backend_button.clicked.connect(self.pick_backend)
        options.addWidget(self.backend_button)
        layout.addLayout(options)
        self.refresh_backend()

        self.progress_bar = QtWidgets.QProgressBar(); self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100); self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.status_label = QtWidgets.QLabel("Add images or a folder to get started.")
        self.status_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True); self.status_label.setMinimumHeight(36)
        layout.addWidget(self.status_label)
        bottom = QtWidgets.QHBoxLayout()
        self.open_button = QtWidgets.QPushButton("Open output folder")
        self.open_button.clicked.connect(self.open_output); self.open_button.setEnabled(False)
        self.report_button = QtWidgets.QPushButton("Save report…")
        self.report_button.clicked.connect(self.save_report); self.report_button.setEnabled(False)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_batch); self.cancel_button.setEnabled(False)
        self.compress_button = QtWidgets.QPushButton("Compress images")
        self.compress_button.setObjectName("Primary"); self.compress_button.setEnabled(False)
        self.compress_button.clicked.connect(self.start_batch)
        bottom.addWidget(self.open_button); bottom.addWidget(self.report_button); bottom.addStretch()
        bottom.addWidget(self.cancel_button); bottom.addWidget(self.compress_button)
        layout.addLayout(bottom)
        footer = QtWidgets.QLabel("PNG + JPEG optimization · Other formats are copied unchanged · No uploads")
        footer.setObjectName("Subtitle"); layout.addWidget(footer)
        action = QtGui.QAction("Add images", self)
        action.setShortcut(QtGui.QKeySequence.StandardKey.Open)
        action.triggered.connect(self.pick_files); self.addAction(action)

    def refresh_backend(self):
        self.backend_label.setText("PNG + JPEG ready" if self.backend else "PNG ready · JPEG helper not selected")
        self.backend_button.setVisible(not self.backend)

    def error(self, text):
        self.status_label.setText(text)
        if self.show_dialogs:
            QtWidgets.QMessageBox.warning(self, APP_NAME, text)

    @QtCore.Slot(list)
    def add_paths(self, values):
        if self.jobs_thread is not None:
            return
        existing = {source_key(path) for path in self.paths}
        added, ignored = 0, 0
        for value in values:
            path = Path(value).expanduser().absolute()
            if not path.exists() or path.is_symlink() or not (
                    path.is_dir() or path.suffix.lower() in IMAGE_SUFFIXES):
                ignored += 1; continue
            key = source_key(path)
            if key in existing:
                continue
            existing.add(key); self.paths.append(path); added += 1
        self.refresh_queue()
        self.status_label.setText("{} selection(s) ready.{}".format(len(self.paths),
            " Non-image or linked items were ignored." if ignored else ""))

    def refresh_queue(self):
        self.queue_list.clear()
        for path in self.paths:
            item = QtWidgets.QListWidgetItem(("Folder  ·  " if path.is_dir() else "Image  ·  ") + path.name)
            item.setToolTip(str(path)); self.queue_list.addItem(item)
        self.tabs.setTabText(0, "Images ({})".format(len(self.paths)))
        self.compress_button.setEnabled(bool(self.paths) and self.jobs_thread is None)

    def pick_files(self):
        if self.jobs_thread is not None:
            return
        names, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Choose images", "",
            "Images (*.png *.apng *.jpg *.jpeg *.gif *.webp *.bmp *.tif *.tiff *.avif *.heic);;All files (*)")
        self.add_paths(names)

    def pick_folder(self):
        if self.jobs_thread is not None:
            return
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose a folder of images")
        if path: self.add_paths([path])

    def pick_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_edit.text())
        if path: self.output_edit.setText(path)

    def pick_backend(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose a trusted jpegtran executable")
        if path:
            self.backend = path; self.refresh_backend()

    def remove_selected(self):
        if self.jobs_thread is not None: return
        rows = {self.queue_list.row(item) for item in self.queue_list.selectedItems()}
        self.paths = [path for index, path in enumerate(self.paths) if index not in rows]
        self.refresh_queue()

    def clear_selection(self):
        if self.jobs_thread is not None: return
        self.paths = []; self.refresh_queue()
        self.status_label.setText("Add images or a folder to get started.")

    def set_busy(self, busy):
        for widget in (self.add_files_button, self.add_folder_button, self.remove_button,
                       self.clear_button, self.browse_button, self.recursive_box,
                       self.backend_button, self.drop_zone):
            widget.setEnabled(not busy)
        self.compress_button.setEnabled(not busy and bool(self.paths))
        self.cancel_button.setEnabled(busy)
        self.report_button.setEnabled(not busy and self.summary is not None)

    @QtCore.Slot()
    def start_batch(self):
        if self.jobs_thread is not None or not self.paths: return
        self.summary = None; self.pending_summary = None
        self.results.setRowCount(0); self.tabs.setCurrentIndex(1)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Finding images…")
        self.open_button.setEnabled(False)
        self.jobs_thread = BatchThread(self.paths, self.output_edit.text(),
                                       self.recursive_box.isChecked(), self.backend)
        self.jobs_thread.planned.connect(self.on_planned)
        self.jobs_thread.progress.connect(self.on_progress)
        self.jobs_thread.outcome.connect(self.on_outcome)
        self.jobs_thread.finished.connect(self.on_finished)
        self.set_busy(True)
        self.jobs_thread.start()

    @QtCore.Slot(int, list)
    def on_planned(self, count, warnings):
        self.progress_bar.setRange(0, max(1, count)); self.progress_bar.setValue(0)
        self.status_label.setText("Compressing {} image(s)…".format(count))

    @QtCore.Slot(int, int, dict)
    def on_progress(self, done, total, item):
        self.progress_bar.setRange(0, max(1, total)); self.progress_bar.setValue(done)
        self.status_label.setText("{} of {} · {}".format(done, total, Path(item["source"]).name))
        row = self.results.rowCount(); self.results.insertRow(row)
        values = [Path(item["source"]).name, result_label(item["status"]),
                  friendly_size(item.get("saved_bytes", 0)),
                  Path(item["destination"]).name if item.get("destination") else "—"]
        for column, value in enumerate(values):
            cell = QtWidgets.QTableWidgetItem(value)
            cell.setToolTip(item.get("message") or item.get("destination") or item["source"])
            if item["status"] == "error": cell.setForeground(QtGui.QColor("#b02b40"))
            self.results.setItem(row, column, cell)

    @QtCore.Slot(dict)
    def on_outcome(self, summary):
        self.pending_summary = summary

    @QtCore.Slot()
    def on_finished(self):
        thread = self.jobs_thread
        self.jobs_thread = None
        if thread is not None: thread.deleteLater()
        self.summary = self.pending_summary or {"files": [], "fatal_error": "The batch did not finish."}
        self.progress_bar.setRange(0, max(1, self.summary.get("planned", 1)))
        self.progress_bar.setValue(len(self.summary["files"]))
        self.set_busy(False)
        self.open_button.setEnabled(Path(self.output_edit.text()).is_dir())
        if self.summary.get("fatal_error"):
            self.error(self.summary["fatal_error"])
        else:
            files = self.summary["files"]
            errors = sum(item["status"] == "error" for item in files)
            optimized = sum(item["status"].startswith("optimized_") for item in files)
            self.status_label.setText("{}{} image(s) · {} compressed · {} saved · {} error(s)".format(
                "Stopped · " if self.summary.get("cancelled") else "Finished · ", len(files), optimized,
                friendly_size(self.summary.get("total_saved_bytes", 0)), errors))
        self.batch_done.emit(self.summary)
        if self.close_when_done: self.close()

    def cancel_batch(self):
        if self.jobs_thread is not None:
            self.jobs_thread.cancel.set(); self.cancel_button.setEnabled(False)
            self.status_label.setText("Stopping safely after the current image…")

    def open_output(self):
        path = Path(self.output_edit.text())
        if path.is_dir(): QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def save_report(self):
        if self.summary is None: return
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save compression report", "compression-report.json",
                                                       "JSON report (*.json)")
        if name:
            try: write_new(Path(name), (json.dumps(self.summary, indent=2) + "\n").encode("utf-8"))
            except OSError as error: self.error("Choose a new report filename. {}".format(error))

    def closeEvent(self, event):
        if self.jobs_thread is None:
            event.accept(); return
        answer = QtWidgets.QMessageBox.question(self, APP_NAME,
            "Compression is running. Stop after the current image and close?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self.close_when_done = True; self.cancel_batch()
        event.ignore()


def smoke_test(app, window, report):
    """Build verification only: the build script supplies two synthetic fixtures."""
    report = Path(report)
    inputs = [report.parent / "smoke-input.png", report.parent / "smoke-input.jpg"]
    if not window.backend or not all(path.is_file() for path in inputs): return 2
    outcome = {}
    def done(summary):
        outcome.update(summary); app.quit()
    window.batch_done.connect(done)
    window.add_paths([str(path) for path in inputs])
    window.output_edit.setText(str(report.parent / "smoke-output"))
    window.start_batch()
    QtCore.QTimer.singleShot(60000, app.quit)
    app.exec()
    if window.jobs_thread is not None:
        window.jobs_thread.cancel.set(); window.jobs_thread.wait(65000)
    report.write_text(json.dumps(outcome, indent=2) + "\n")
    return 0 if len(outcome.get("files", [])) == 2 and all(
        item["status"].startswith("optimized_") for item in outcome["files"]) else 1


def main():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--smoke-test", help=argparse.SUPPRESS)
    parser.add_argument("images", nargs="*")
    args = parser.parse_args()
    app = QtWidgets.QApplication([APP_NAME])
    app.setApplicationName(APP_NAME); app.setApplicationVersion(VERSION)
    app.setOrganizationName("mobeenafzal570")
    app.setStyle("Fusion")
    window = MainWindow(show_dialogs=not bool(args.smoke_test))
    if args.smoke_test: return smoke_test(app, window, args.smoke_test)
    if args.images: window.add_paths(args.images)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
