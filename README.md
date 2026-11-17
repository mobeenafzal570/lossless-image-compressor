# Lossless image compressor

[![Lossless compression checks](https://github.com/mobeenafzal570/lossless-image-compressor/actions/workflows/ci.yml/badge.svg)](https://github.com/mobeenafzal570/lossless-image-compressor/actions/workflows/ci.yml)

An offline desktop app and Python script that reduce image file sizes **without resizing, quantizing colors, or applying lossy re-encoding**. Originals are never overwritten. A candidate is used only when it passes its format checks and is smaller; otherwise the original bytes are copied to the output.

**Guides:** [Windows](WINDOWS.md) · [macOS](MACOS.md)

## Desktop app — no terminal or Python installation

Get the app from [Releases](https://github.com/mobeenafzal570/lossless-image-compressor/releases/latest):

| Computer | Download |
| --- | --- |
| Windows 10 (1809+) or Windows 11, 64-bit | `Lossless-Image-Compressor-1.0.0-windows-x64.zip` |
| Apple silicon Mac, macOS 14.4+ | `Lossless-Image-Compressor-1.0.0-macos-arm64.zip` |
| Intel Mac, macOS 14.4+ | `Lossless-Image-Compressor-1.0.0-macos-x64.zip` |

Extract the download, open **Lossless Image Compressor**, and drag images or folders into the window. You can also use **Add images** or **Add folder**. Choose an output folder and click **Compress images**.

The app includes Python and the lossless JPEG helper. It offers progress, readable per-image results, safe cancellation after the current image, **Open output folder**, and optional report export. Duplicate filenames are disambiguated; overlapping selections are processed once. Existing outputs remain untouched.

Desktop builds are unsigned (locally ad-hoc signed on macOS) and are not notarized. Your operating system may ask for approval on first launch. For build details, checksums, dependencies and developer instructions, see [BUILDING.md](BUILDING.md).

## What it does

| Format | Behavior |
| --- | --- |
| Static PNG | Recompresses existing filtered image data with several zlib strategies. Verifies exact scanline-byte equality and preserves every non-IDAT chunk byte for byte. |
| JPEG | The desktop app bundles `jpegtran`; the CLI accepts it optionally. `jpegtran -copy all -optimize` repacks the existing representation. Frame headers, quantization tables, and APP/COM metadata must remain equal. |
| JPEG without configured jpegtran | Copies the file unchanged and reports `kept_jpegtran_not_configured`. |
| Animated PNG | Copies the entire file unchanged to preserve animation. |
| GIF, WebP, BMP, TIFF, AVIF, HEIC | Copies unchanged. These formats are not optimized by this version. |

Transparency, dimensions, bit depth, palette data, color-profile chunks, orientation metadata, and comments are retained. There is no “quality percentage” slider because the script does not trade pixel quality for size.

Already optimized images may not shrink. Lossless compression cannot promise a particular reduction or recover detail missing from an already lossy image.

## Optional command-line usage

Download this repository with **Code → Download ZIP**, extract it, and open a terminal in its folder. The script itself uses only Python's standard library. Use a current Python 3 release; its syntax is compatible with Python 3.9+.

Windows:

```powershell
py -3 compress_images.py "C:\Pictures\input" --output "C:\Pictures\compressed" --recursive
```

macOS:

```sh
python3 compress_images.py "$HOME/Pictures/input" --output "$HOME/Pictures/compressed" --recursive
```

Use a separate output directory **outside** the input directory. Folder structure and original filenames are preserved. Existing output files are skipped, not replaced. Omit `--recursive` to process only the input directory's immediate files.

## Single image, preview and report

```sh
python3 compress_images.py "photo.png" --output "compressed"
python3 compress_images.py "images" --output "compressed" --recursive --dry-run
python3 compress_images.py "images" --output "compressed" --recursive --report "report.json"
```

On Windows, substitute `py -3` for `python3`. Quote paths containing spaces.

`--dry-run` performs the checks and calculates candidate sizes without creating image outputs, directories, or a report. JSON reports include per-file status, input/output sizes, SHA-256 hashes, and total bytes saved. Reports are local files and can contain local filenames and paths; the script never uploads them.

## Optional lossless JPEG optimization

Install a trusted copy of [libjpeg-turbo](https://libjpeg-turbo.org/Documentation/OfficialBinaries), then explicitly provide its `jpegtran` executable:

```sh
python3 compress_images.py "photos" --output "compressed" --recursive --jpegtran "/path/to/jpegtran"
```

The platform guides provide the Windows and macOS paths. Do not substitute `cjpeg` or a JPEG quality-setting encoder. `jpegtran` operates on the existing compressed coefficients, avoiding a decode/re-encode quality loss. Metadata is requested with `-copy all`; this script also rejects candidates whose checked metadata or quantization tables differ. [Backend details](https://raw.githubusercontent.com/libjpeg-turbo/libjpeg-turbo/main/doc/usage.txt).

An unavailable or failed configured backend is reported as an error, with no output for that file. A successful backend result that is larger, malformed, or fails the invariants check is replaced by an unchanged copy of the input.

## Verification

```sh
python3 -m unittest -v
```

The core checks use only the standard library. Independent pixel-decoder tests are enabled by installing the development requirements with Python 3.11+:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest -v
```

GitHub Actions runs the core checks and independent PNG decoding checks on Windows, macOS and Linux. Linux additionally installs `jpegtran` and checks real JPEG size reduction and decoded pixel equality, including progressive images and metadata. Set `JPEGTRAN_BIN` locally to enable those JPEG integration tests. Missing optional test dependencies are explicitly marked as skipped.

Desktop checks add real Qt drag/drop events, Unicode/spaced paths, duplicate selections, name collisions, background-worker results, responsive cancellation and output-folder validation. Native packaging builds its own pinned JPEG helper, runs the full suite, and then launches the actual packaged app to compress two synthetic fixtures and verify decoded pixels. Desktop artifacts are built on Windows, Apple silicon macOS and Intel macOS; they are not cross-compiled.

Coverage includes PNG CRCs, RGB/RGBA and invisible transparent pixels, palette transparency, 16-bit grayscale, Adam7 interlacing, ICC/Exif/text/resolution preservation, animated PNG passthrough, JPEG invariants, corrupt inputs, resource limits, overwrite protection, symlinks, recursive folders, reports, and dry runs. All fixtures are synthetic; no personal images are included.

## Practical limits

- The script validates PNG structure, decompression, scanline sizes and filters; it is not a general image repair tool.
- JPEG runtime checks are container-level checks. Lossless coefficient handling comes from the trusted `jpegtran` backend. Independent decoder tests cover generated fixtures, not every possible JPEG.
- No metadata stripping is performed, so files with large embedded profiles or thumbnails may remain large.
- PNG recompression preserves existing row filters; this implementation does not search new filters or reduce palettes. Stronger lossless optimizers may find smaller encodings.
- Input files are limited to 256 MiB and decoded PNG data to 512 MiB by default. Override with `--max-file-mib` and `--max-decoded-mib`; large limits require more memory. Files are processed one at a time, with several in-memory buffers per file.
- Discovered source-file symlinks are skipped; resolved output paths that escape the destination directory are rejected. Existing files and broken destination symlinks are not overwritten.
- Outputs are created exclusively. A write error removes the incomplete file created by that operation; a forced process termination can leave an incomplete output, which should be removed before retrying. Source files remain untouched.
- Exit code `0`: no processing errors, including safe passthrough and existing-file skips. Exit code `1`: a file or report failed. Exit code `2`: invalid command-line usage.

## Design references

- [W3C PNG specification](https://www.w3.org/TR/png-3/): chunks, image data and filtering.
- [Python zlib documentation](https://docs.python.org/3/library/zlib.html): lossless recompression strategies.
- [The libjpeg-turbo Project](https://libjpeg-turbo.org/Documentation/OfficialBinaries): official installations and platform notes.

Developed with AI assistance. The format-specific guarantees and runnable tests are documented for review.
