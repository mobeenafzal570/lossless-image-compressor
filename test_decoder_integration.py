"""Independent decoded-pixel checks; Pillow is a development-only dependency."""

import io
import os
import struct
import unittest
import zlib

import compress_images as tool

try:
    from PIL import Image, ImageCms, PngImagePlugin
except ImportError:
    Image = None
    if os.environ.get("REQUIRE_DECODER_TESTS") == "1":
        raise RuntimeError("CI requires the decoder checks; install requirements-dev.txt")


def encode(image, format="PNG", **options):
    stream = io.BytesIO()
    image.save(stream, format=format, **options)
    return stream.getvalue()


def decode(data):
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.mode, image.size, image.tobytes(), image.info.copy(), image.getexif().tobytes()


@unittest.skipUnless(Image is not None, "Install requirements-dev.txt for independent pixel checks")
class DecoderTests(unittest.TestCase):
    def test_png_rgb_rgba_palette_and_grayscale_pixels(self):
        for mode in ("RGB", "RGBA", "P", "L"):
            with self.subTest(mode=mode):
                image = Image.new(mode, (67, 43))
                if mode == "P":
                    image.putpalette([v for i in range(256) for v in (i, 255 - i, i // 2)])
                    image.info["transparency"] = 0
                if mode == "RGBA":
                    # Nonzero invisible RGB values must survive as well as visible pixels.
                    image.putpixel((1, 1), (97, 53, 17, 0))
                source = encode(image, compress_level=0)
                result, status = tool.optimize_png(source)
                self.assertEqual(status, "optimized_png")
                self.assertEqual(decode(source)[:3], decode(result)[:3])
                with Image.open(io.BytesIO(source)) as a, Image.open(io.BytesIO(result)) as b:
                    self.assertEqual(a.convert("RGBA").tobytes(), b.convert("RGBA").tobytes())

    def test_sixteen_bit_grayscale_is_not_reduced_to_eight_bits(self):
        raw = b"".join(struct.pack("<H", (i * 239) % 65536) for i in range(37 * 29))
        image = Image.frombytes("I;16", (37, 29), raw)
        source = encode(image, compress_level=0)
        result, _ = tool.optimize_png(source)
        self.assertEqual(decode(source)[:3], decode(result)[:3])
        self.assertEqual(tool.png_chunks(source)[0][1], tool.png_chunks(result)[0][1])

    def test_adam7_interlaced_png(self):
        width, height = 17, 13
        pixels = bytes((x * 13 + y * 17) % 256 for y in range(height) for x in range(width))
        scanlines = bytearray()
        for sx, sy, dx, dy in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8),
                               (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)):
            for y in range(sy, height, dy):
                row = bytes(pixels[y * width + x] for x in range(sx, width, dx))
                if row:
                    scanlines.extend(b"\x00" + row)
        header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 1)
        source = (tool.PNG_SIGNATURE + tool.make_chunk(b"IHDR", header) +
                  tool.make_chunk(b"IDAT", zlib.compress(bytes(scanlines), 0)) +
                  tool.make_chunk(b"IEND", b""))
        result, _ = tool.optimize_png(source)
        self.assertEqual(decode(source)[2], pixels)
        self.assertEqual(decode(source)[:3], decode(result)[:3])

    def test_png_color_profile_exif_text_and_resolution(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        text = PngImagePlugin.PngInfo(); text.add_text("Author", "Synthetic fixture")
        exif = Image.Exif(); exif[274] = 6; exif[315] = "Synthetic fixture"
        source = encode(Image.new("RGB", (63, 45), (19, 82, 173)), compress_level=0,
                        icc_profile=profile, exif=exif, pnginfo=text, dpi=(144, 144))
        result, _ = tool.optimize_png(source)
        before, after = decode(source), decode(result)
        self.assertEqual(before[:3], after[:3])
        self.assertEqual(before[4], after[4])
        for key in ("icc_profile", "Author", "dpi"):
            self.assertEqual(before[3][key], after[3][key])

    def test_real_animated_png_is_copied_without_frame_changes(self):
        frames = [Image.new("RGBA", (31, 19), color) for color in ("red", "blue")]
        source = encode(frames[0], save_all=True, append_images=frames[1:], duration=50, loop=0)
        result, status = tool.optimize_png(source)
        self.assertEqual(status, "kept_animated_png")
        self.assertEqual(source, result)
        with Image.open(io.BytesIO(result)) as decoded:
            self.assertEqual(decoded.n_frames, 2)


@unittest.skipUnless(Image is not None and os.environ.get("JPEGTRAN_BIN"),
                     "Real JPEG tests require Pillow and JPEGTRAN_BIN")
class JpegtranIntegrationTests(unittest.TestCase):
    def test_real_jpeg_optimization_reduces_size_with_identical_decoded_pixels(self):
        source = encode(Image.new("RGB", (128, 128), (30, 90, 160)), "JPEG", quality=92,
                        optimize=False)
        result, status = tool.optimize_jpeg(source, os.environ["JPEGTRAN_BIN"])
        self.assertEqual(status, "optimized_jpeg")
        self.assertLess(len(result), len(source))
        self.assertEqual(decode(source)[:3], decode(result)[:3])

    def test_jpeg_modes_progressive_exif_and_profile(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        exif = Image.Exif(); exif[274] = 6; exif[315] = "Synthetic fixture"
        for mode in ("RGB", "L", "CMYK"):
            for progressive in (False, True):
                with self.subTest(mode=mode, progressive=progressive):
                    image = Image.new(mode, (97, 73))
                    source = encode(image, "JPEG", quality=92, progressive=progressive,
                                    optimize=False, exif=exif, icc_profile=profile)
                    result, _ = tool.optimize_jpeg(source, os.environ["JPEGTRAN_BIN"])
                    self.assertLessEqual(len(result), len(source))
                    self.assertEqual(decode(source)[:3], decode(result)[:3])
                    self.assertEqual(decode(source)[4], decode(result)[4])
                    self.assertEqual(decode(source)[3]["icc_profile"], decode(result)[3]["icc_profile"])


if __name__ == "__main__":
    unittest.main()
