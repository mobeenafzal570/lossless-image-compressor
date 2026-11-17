"""Standard-library checks; fixtures contain only generated synthetic pixels."""

import contextlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

import compress_images as tool


def png(width=64, height=48, depth=8, color=6, extra=(), raw=None, split=False):
    header = struct.pack(">IIBBBBB", width, height, depth, color, 0, 0, 0)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    if raw is None:
        row = b"\x00" + bytes((i % 11 for i in range((width * channels * depth + 7) // 8)))
        raw = row * height
    encoded = zlib.compress(raw, 0)
    chunks = [tool.make_chunk(b"IHDR", header)]
    chunks.extend(tool.make_chunk(kind, payload) for kind, payload in extra)
    parts = [encoded[:len(encoded) // 2], encoded[len(encoded) // 2:]] if split else [encoded]
    chunks.extend(tool.make_chunk(b"IDAT", part) for part in parts)
    chunks.append(tool.make_chunk(b"IEND", b""))
    return tool.PNG_SIGNATURE + b"".join(chunks)


def image_stream(data):
    chunks = tool.png_chunks(data)
    return tool.inflate_checked(b"".join(p for k, p, _ in chunks if k == b"IDAT"), 1024 * 1024)


def segment(marker, payload):
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload


def jpeg(metadata=b"fixture", table=1, entropy=b"test\xff\x00data"):
    # Container-only fixture; decoded-pixel integration tests generate real JPEGs.
    return (b"\xff\xd8" + segment(0xe1, metadata) +
            segment(0xdb, b"\x00" + bytes([table]) * 64) +
            segment(0xc0, b"\x08\x00\x08\x00\x08\x01\x01\x11\x00") +
            segment(0xda, b"\x01\x01\x00\x00\x3f\x00") + entropy + b"\xff\xd9")


class PngTests(unittest.TestCase):
    def test_reduction_preserves_filtered_image_data(self):
        source = png(split=True)
        result, status = tool.optimize_png(source)
        self.assertEqual(status, "optimized_png")
        self.assertLess(len(result), len(source))
        self.assertEqual(image_stream(source), image_stream(result))

    def test_alpha_depth_and_all_metadata_chunks_stay_exact(self):
        source = png(depth=16, extra=[(b"tEXt", b"Author\x00Synthetic fixture"),
                                     (b"gAMA", struct.pack(">I", 45455)),
                                     (b"eXIf", b"metadata-bytes")])
        result, _ = tool.optimize_png(source)
        before = [chunk[2] for chunk in tool.png_chunks(source) if chunk[0] != b"IDAT"]
        after = [chunk[2] for chunk in tool.png_chunks(result) if chunk[0] != b"IDAT"]
        self.assertEqual(before, after)
        self.assertEqual(image_stream(source), image_stream(result))

    def test_palette_and_transparency_stay_exact(self):
        source = png(color=3, extra=[(b"PLTE", b"\x00\x00\x00\xff\xff\xff"),
                                     (b"tRNS", b"\x00\xff")], raw=(b"\x00" + bytes([0, 1]) * 32) * 48)
        result, _ = tool.optimize_png(source)
        self.assertEqual(image_stream(source), image_stream(result))
        self.assertIn((b"tRNS", b"\x00\xff"), [(k, p) for k, p, _ in tool.png_chunks(result)])

    def test_animated_png_is_preserved_byte_for_byte(self):
        source = png(extra=[(b"acTL", struct.pack(">II", 2, 0))])
        self.assertEqual(tool.optimize_png(source), (source, "kept_animated_png"))

    def test_already_optimized_input_never_grows(self):
        first, _ = tool.optimize_png(png())
        second, _ = tool.optimize_png(first)
        self.assertLessEqual(len(second), len(first))
        self.assertEqual(image_stream(first), image_stream(second))

    def test_crc_corruption_is_rejected(self):
        data = bytearray(png()); data[20] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC"):
            tool.optimize_png(bytes(data))

    def test_truncation_and_trailing_data_are_rejected(self):
        for data in [png()[:-1], png() + b"trailing"]:
            with self.subTest(data=data[-8:]), self.assertRaises(ValueError):
                tool.optimize_png(data)

    def test_decoded_size_limit_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "limit"):
            tool.optimize_png(png(), max_decoded=32)

    def test_invalid_filter_and_row_count_are_rejected(self):
        for raw in [b"\xff" + bytes(64 * 4), b"\x00short"]:
            with self.assertRaises(ValueError):
                tool.optimize_png(png(height=1, raw=raw))

    def test_invalid_color_depth_is_rejected(self):
        with self.assertRaises(ValueError):
            tool.optimize_png(png(depth=4, color=6))


class JpegTests(unittest.TestCase):
    def test_missing_backend_preserves_jpeg_bytes(self):
        source = jpeg()
        self.assertEqual(tool.optimize_jpeg(source), (source, "kept_jpegtran_not_configured"))

    def test_entropy_repacking_can_be_accepted_without_touching_invariants(self):
        source = jpeg(entropy=b"a" * 100)
        candidate = jpeg(entropy=b"a")
        completed = subprocess.CompletedProcess([], 0, stdout=candidate, stderr=b"")
        with patch.object(tool.subprocess, "run", return_value=completed) as run:
            result, status = tool.optimize_jpeg(source, "trusted-jpegtran")
        self.assertEqual(result, candidate)
        self.assertEqual(status, "optimized_jpeg")
        self.assertEqual(run.call_args[0][0], ["trusted-jpegtran", "-copy", "all", "-optimize"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_metadata_or_quantization_change_rejects_candidate(self):
        source = jpeg(entropy=b"a" * 100)
        for candidate in [jpeg(metadata=b"changed"), jpeg(table=2), b"not-a-jpeg"]:
            with self.subTest(candidate=candidate[:10]):
                completed = subprocess.CompletedProcess([], 0, stdout=candidate, stderr=b"")
                with patch.object(tool.subprocess, "run", return_value=completed):
                    result, status = tool.optimize_jpeg(source, "trusted-jpegtran")
                self.assertEqual(result, source)
                self.assertEqual(status, "kept_jpeg_invariants_changed")

    def test_larger_candidate_keeps_original(self):
        source = jpeg()
        completed = subprocess.CompletedProcess([], 0, stdout=jpeg(entropy=b"a" * 100), stderr=b"")
        with patch.object(tool.subprocess, "run", return_value=completed):
            self.assertEqual(tool.optimize_jpeg(source, "trusted-jpegtran"), (source, "kept_not_smaller"))

    def test_failed_and_missing_backends_report_errors(self):
        with patch.object(tool.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaises(ValueError):
                tool.optimize_jpeg(jpeg(), "missing")
        with patch.object(tool.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(ValueError):
                tool.optimize_jpeg(jpeg(), "failed")

    def test_jpeg_stuffed_bytes_restart_and_inter_scan_metadata(self):
        data = jpeg(entropy=b"a\xff\x00b\xff\xd0c")
        self.assertEqual(tool.jpeg_invariants(data), tool.jpeg_invariants(jpeg()))
        between = data[:-2] + segment(0xfe, b"after-scan") + b"\xff\xd9"
        self.assertIn((0xfe, b"after-scan"), tool.jpeg_invariants(between)[0])


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"; self.source.mkdir()
        self.image = self.source / "image with spaces.png"; self.image.write_bytes(png())
        self.output = self.root / "output"

    def tearDown(self):
        self.temporary.cleanup()

    def run_tool(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return tool.main(list(map(str, args)))

    def test_single_file_does_not_modify_source(self):
        original = self.image.read_bytes()
        self.assertEqual(self.run_tool(self.image, "-o", self.output), 0)
        self.assertEqual(self.image.read_bytes(), original)
        self.assertEqual(image_stream((self.output / self.image.name).read_bytes()), image_stream(original))

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir(); target = self.output / self.image.name; target.write_bytes(b"existing")
        result = tool.process_file(self.image, target)
        self.assertEqual(result["status"], "skipped_existing")
        self.assertEqual(target.read_bytes(), b"existing")

    def test_recursive_paths_and_json_report(self):
        nested = self.source / "nested"; nested.mkdir()
        (nested / "second.png").write_bytes(png())
        report = self.root / "report.json"
        self.assertEqual(self.run_tool(self.source, "-o", self.output, "-r", "--report", report), 0)
        data = json.loads(report.read_text())
        self.assertEqual(len(data["files"]), 2)
        self.assertGreater(data["total_saved_bytes"], 0)
        self.assertTrue((self.output / "nested/second.png").exists())

    def test_dry_run_creates_no_files(self):
        report = self.root / "report.json"
        self.assertEqual(self.run_tool(self.image, "-o", self.output, "--dry-run", "--report", report), 0)
        self.assertFalse(self.output.exists()); self.assertFalse(report.exists())

    def test_in_place_and_nested_output_are_rejected(self):
        for args in [(self.image, "-o", self.source), (self.source, "-o", self.source / "inside")]:
            with self.assertRaises(SystemExit) as error:
                self.run_tool(*args)
            self.assertEqual(error.exception.code, 2)

    def test_invalid_image_reports_error_without_output(self):
        self.image.write_bytes(b"invalid image")
        self.assertEqual(self.run_tool(self.image, "-o", self.output), 1)
        self.assertFalse(self.output.exists())

    def test_existing_or_conflicting_report_is_rejected_before_writes(self):
        report = self.root / "report.json"; report.write_text("original")
        with self.assertRaises(SystemExit):
            self.run_tool(self.image, "-o", self.output, "--report", report)
        self.assertEqual(report.read_text(), "original"); self.assertFalse(self.output.exists())
        with self.assertRaises(SystemExit):
            self.run_tool(self.image, "-o", self.output, "--report", self.output / self.image.name)

    def test_unsupported_image_is_copied_exactly(self):
        image = self.source / "animation.gif"; image.write_bytes(b"GIF89a fixture")
        self.assertEqual(self.run_tool(image, "-o", self.output), 0)
        self.assertEqual(image.read_bytes(), (self.output / image.name).read_bytes())

    def test_input_size_limit_blocks_processing(self):
        result = tool.process_file(self.image, self.output / "x.png", max_file=1)
        self.assertEqual(result["status"], "error"); self.assertFalse(self.output.exists())

    def test_broken_destination_symlink_is_not_overwritten(self):
        self.output.mkdir(); target = self.output / "link.png"
        try:
            target.symlink_to(self.root / "missing.png")
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable")
        self.assertEqual(tool.process_file(self.image, target)["status"], "skipped_existing")
        self.assertTrue(target.is_symlink())

    def test_symlink_escape_is_rejected(self):
        nested = self.source / "nested"; nested.mkdir(); (nested / "second.png").write_bytes(png())
        self.output.mkdir(); outside = self.root / "outside"; outside.mkdir()
        try:
            (self.output / "nested").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable")
        self.assertEqual(self.run_tool(self.source, "-o", self.output, "-r"), 1)
        self.assertFalse((outside / "second.png").exists())


if __name__ == "__main__":
    unittest.main()
