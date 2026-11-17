"""Lossless PNG optimization and optional jpegtran JPEG optimization.

Uses only the Python standard library. Writes to a separate directory and never
overwrites a source or existing destination. Other image formats are copied.
"""

import argparse
import binascii
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IMAGE_SUFFIXES = {".png", ".apng", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                  ".tif", ".tiff", ".avif", ".heic"}
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_DECODED_BYTES = 512 * 1024 * 1024


def png_chunks(data):
    """Parse and CRC-check a PNG container, retaining original chunk bytes."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Not a PNG stream")
    chunks = []
    position = len(PNG_SIGNATURE)
    seen_data = False
    ended_data = False
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError("Truncated PNG chunk")
        length = struct.unpack_from(">I", data, position)[0]
        end = position + length + 12
        if end > len(data):
            raise ValueError("PNG chunk extends beyond the file")
        kind = data[position + 4:position + 8]
        payload = data[position + 8:end - 4]
        if any(not (65 <= c <= 90 or 97 <= c <= 122) for c in kind):
            raise ValueError("Invalid PNG chunk type")
        crc = struct.unpack_from(">I", data, end - 4)[0]
        if binascii.crc32(kind + payload) & 0xffffffff != crc:
            raise ValueError("PNG CRC mismatch")
        if not chunks and (kind != b"IHDR" or length != 13):
            raise ValueError("PNG must start with a 13-byte IHDR")
        if chunks and kind == b"IHDR":
            raise ValueError("Duplicate PNG header")
        if kind[0] < 97 and kind not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"}:
            raise ValueError("Unknown critical PNG chunk")
        if kind == b"IDAT":
            if ended_data:
                raise ValueError("PNG IDAT chunks must be consecutive")
            seen_data = True
        elif seen_data:
            ended_data = True
        chunks.append((kind, payload, data[position:end]))
        position = end
        if kind == b"IEND":
            if length or position != len(data) or not seen_data:
                raise ValueError("Invalid PNG end or trailing bytes")
            return chunks
    raise ValueError("PNG has no IEND")


def inflate_checked(payload, limit):
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(payload, limit + 1)
    except zlib.error as error:
        raise ValueError("Invalid PNG compression stream") from error
    if len(raw) > limit or decoder.unconsumed_tail:
        raise ValueError("PNG decoded-data limit exceeded")
    if not decoder.eof or decoder.unused_data:
        raise ValueError("Incomplete or trailing PNG compression stream")
    return raw


def make_chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload +
            struct.pack(">I", binascii.crc32(kind + payload) & 0xffffffff))


def verify_png_rows(chunks, raw, limit):
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1])
    depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
              4: {8, 16}, 6: {8, 16}}
    if (not width or not height or depth not in depths.get(color, set()) or
            compression != 0 or filtering != 0 or interlace not in (0, 1)):
        raise ValueError("Unsupported or invalid PNG header")
    if color == 3:
        palettes = [p for kind, p, _ in chunks if kind == b"PLTE"]
        if len(palettes) != 1 or not palettes[0] or len(palettes[0]) % 3 or len(palettes[0]) > 3 * 2 ** depth:
            raise ValueError("Invalid indexed PNG palette")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = ((0, 0, 1, 1),) if not interlace else (
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
    position = 0
    for start_x, start_y, step_x, step_y in passes:
        columns = max(0, (width - start_x + step_x - 1) // step_x)
        rows = max(0, (height - start_y + step_y - 1) // step_y)
        if not columns or not rows:
            continue
        stride = (columns * depth * channels + 7) // 8 + 1
        end = position + stride * rows
        if end > limit or end > len(raw):
            raise ValueError("PNG scanline size is invalid or exceeds the decoded-data limit")
        if any(raw[index] > 4 for index in range(position, end, stride)):
            raise ValueError("Invalid PNG row filter")
        position = end
    if position != len(raw):
        raise ValueError("PNG scanline size does not match its header")


def optimize_png(data, max_decoded=MAX_DECODED_BYTES):
    chunks = png_chunks(data)
    if any(kind == b"acTL" for kind, _, _ in chunks):
        return data, "kept_animated_png"
    compressed = b"".join(payload for kind, payload, _ in chunks if kind == b"IDAT")
    raw = inflate_checked(compressed, max_decoded)
    verify_png_rows(chunks, raw, max_decoded)
    candidates = []
    for strategy in (zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED, zlib.Z_RLE):
        encoder = zlib.compressobj(9, zlib.DEFLATED, 15, 9, strategy)
        candidate = encoder.compress(raw) + encoder.flush()
        if inflate_checked(candidate, max_decoded) != raw:
            raise ValueError("PNG image-data verification failed")
        candidates.append(candidate)
    best = min(candidates, key=len)
    result = [PNG_SIGNATURE]
    written_data = False
    for kind, _, original in chunks:
        if kind == b"IDAT":
            if not written_data:
                result.append(make_chunk(b"IDAT", best))
                written_data = True
        else:
            result.append(original)
    optimized = b"".join(result)
    verified = png_chunks(optimized)
    if [c[2] for c in verified if c[0] != b"IDAT"] != [
            c[2] for c in chunks if c[0] != b"IDAT"]:
        raise ValueError("PNG metadata verification failed")
    return ((optimized, "optimized_png") if len(optimized) < len(data)
            else (data, "kept_not_smaller"))


def jpeg_invariants(data):
    """Read frame, quantization and APP/COM metadata, including between scans.

    This is a container check, not a JPEG coefficient or pixel decoder. jpegtran
    supplies the lossless coefficient transform; integration tests decode pixels.
    """
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Not a JPEG stream")
    metadata, frames, tables = [], [], {}
    position = 2
    scan_seen = False
    sof = {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
           0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}
    while position < len(data):
        if data[position] != 0xff:
            raise ValueError("Expected JPEG marker")
        while position < len(data) and data[position] == 0xff:
            position += 1
        if position >= len(data):
            raise ValueError("Truncated JPEG marker")
        marker = data[position]
        position += 1
        if marker == 0xd9:
            if position != len(data) or not frames or not scan_seen:
                raise ValueError("Invalid JPEG end or trailing bytes")
            return metadata, frames, tables
        if marker == 0x01 or 0xd0 <= marker <= 0xd7:
            continue
        if marker in (0, 0xd8) or position + 2 > len(data):
            raise ValueError("Invalid JPEG segment")
        length = struct.unpack_from(">H", data, position)[0]
        end = position + length
        if length < 2 or end > len(data):
            raise ValueError("Truncated JPEG segment")
        payload = data[position + 2:end]
        if marker == 0xfe or 0xe0 <= marker <= 0xef:
            metadata.append((marker, payload))
        if marker in sof:
            frames.append(payload)
        if marker == 0xdb:
            offset = 0
            while offset < len(payload):
                descriptor = payload[offset]
                precision, table_id = descriptor >> 4, descriptor & 15
                if precision not in (0, 1):
                    raise ValueError("Invalid JPEG quantization precision")
                size = 64 * (precision + 1)
                if offset + 1 + size > len(payload):
                    raise ValueError("Truncated JPEG quantization table")
                value = payload[offset:offset + 1 + size]
                if table_id in tables and tables[table_id] != value:
                    raise ValueError("Changing JPEG tables are not supported")
                tables[table_id] = value
                offset += 1 + size
        position = end
        if marker == 0xda:
            scan_seen = True
            # Skip entropy bytes, stuffed 0xff bytes, fill bytes and restart markers.
            while position < len(data):
                marker_start = data.find(b"\xff", position)
                if marker_start < 0:
                    raise ValueError("JPEG scan has no terminating marker")
                next_byte = marker_start + 1
                while next_byte < len(data) and data[next_byte] == 0xff:
                    next_byte += 1
                if next_byte >= len(data):
                    raise ValueError("Truncated JPEG scan")
                if data[next_byte] == 0 or 0xd0 <= data[next_byte] <= 0xd7:
                    position = next_byte + 1
                    continue
                position = marker_start
                break
    raise ValueError("JPEG has no end marker")


def optimize_jpeg(data, executable=None):
    original = jpeg_invariants(data)
    if executable is None:
        return data, "kept_jpegtran_not_configured"
    try:
        process = subprocess.run([str(executable), "-copy", "all", "-optimize"],
                                 input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=60, check=False,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("jpegtran could not run: {}".format(error)) from error
    if process.returncode:
        raise ValueError("jpegtran failed with exit code {}".format(process.returncode))
    candidate = process.stdout
    try:
        if jpeg_invariants(candidate) != original:
            return data, "kept_jpeg_invariants_changed"
    except ValueError:
        return data, "kept_jpeg_invariants_changed"
    return ((candidate, "optimized_jpeg") if len(candidate) < len(data)
            else (data, "kept_not_smaller"))


def optimize(data, jpegtran=None, max_decoded=MAX_DECODED_BYTES):
    if data.startswith(PNG_SIGNATURE):
        return optimize_png(data, max_decoded)
    if data.startswith(b"\xff\xd8"):
        return optimize_jpeg(data, jpegtran)
    return data, "kept_unsupported_format"


def inside(path, directory):
    return path == directory or directory in path.parents


def write_new(path, payload):
    """Exclusive creation. On write failure, remove only the output created here."""
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


def process_file(source, target, jpegtran=None, dry_run=False,
                 max_file=MAX_FILE_BYTES, max_decoded=MAX_DECODED_BYTES):
    result = {"source": str(source), "destination": str(target)}
    if source.is_symlink():
        return dict(result, status="skipped_symlink")
    if target.exists() or target.is_symlink():
        return dict(result, status="skipped_existing")
    try:
        if source.stat().st_size > max_file:
            raise ValueError("Input-file size limit exceeded")
        with source.open("rb") as stream:
            data = stream.read(max_file + 1)
        if len(data) > max_file:
            raise ValueError("Input-file size limit exceeded")
        if source.suffix.lower() in {".png", ".apng"} and not data.startswith(PNG_SIGNATURE):
            raise ValueError("PNG extension does not match the file signature")
        if source.suffix.lower() in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8"):
            raise ValueError("JPEG extension does not match the file signature")
        payload, status = optimize(data, jpegtran, max_decoded)
        if len(payload) > len(data):
            raise ValueError("Internal check: output must not be larger")
        if not dry_run:
            write_new(target, payload)
        return dict(result, status=status, dry_run=dry_run,
                    input_bytes=len(data), output_bytes=len(payload),
                    saved_bytes=len(data) - len(payload),
                    input_sha256=hashlib.sha256(data).hexdigest(),
                    output_sha256=hashlib.sha256(payload).hexdigest())
    except (OSError, ValueError, zlib.error) as error:
        return dict(result, status="error", message=str(error))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Image file or directory")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Separate output directory")
    parser.add_argument("-r", "--recursive", action="store_true", help="Include input subdirectories")
    parser.add_argument("--jpegtran", help="Trusted jpegtran executable path; JPEGs otherwise stay unchanged")
    parser.add_argument("--report", type=Path, help="Write a new JSON report; existing reports are not overwritten")
    parser.add_argument("--dry-run", action="store_true", help="Calculate results without writing any files")
    parser.add_argument("--max-file-mib", type=int, default=256)
    parser.add_argument("--max-decoded-mib", type=int, default=512)
    args = parser.parse_args(argv)
    if args.max_file_mib < 1 or args.max_decoded_mib < 1:
        parser.error("size limits must be positive")
    source = args.input.absolute()
    output = args.output.resolve()
    if not source.exists():
        parser.error("input does not exist")
    if source.is_dir():
        root = source.resolve()
        if inside(output, root):
            parser.error("choose an output directory outside the input directory")
        paths = source.rglob("*") if args.recursive else source.iterdir()
        files = sorted(p for p in paths if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
        pairs = [(p, p.relative_to(source)) for p in files]
    elif source.is_file():
        if source.resolve() == (output / source.name).resolve():
            parser.error("output would overwrite the source")
        pairs = [(source, Path(source.name))]
    else:
        parser.error("input must be a regular file or directory")
    if not pairs:
        parser.error("no image files found")
    report = args.report.resolve() if args.report else None
    destinations = [(output / relative).resolve() for _, relative in pairs]
    if report and (report.exists() or report.is_symlink() or report in destinations):
        parser.error("report already exists or conflicts with an image output")
    results = []
    for (path, _), target in zip(pairs, destinations):
        if not inside(target, output):
            results.append({"source": str(path), "status": "error",
                            "message": "destination symlink escapes the output directory"})
            continue
        result = process_file(path, target, args.jpegtran, args.dry_run,
                              args.max_file_mib * 1024 * 1024,
                              args.max_decoded_mib * 1024 * 1024)
        results.append(result)
        print("{}: {} ({} bytes saved)".format(path.name, result["status"],
                                                result.get("saved_bytes", 0)))
    summary = {"dry_run": args.dry_run, "files": results,
               "total_saved_bytes": sum(r.get("saved_bytes", 0) for r in results)}
    if report and not args.dry_run:
        try:
            write_new(report, (json.dumps(summary, indent=2) + "\n").encode("utf-8"))
        except OSError as error:
            print("Could not create report: {}".format(error), file=sys.stderr)
            return 1
    print("Total saved: {} bytes{}".format(summary["total_saved_bytes"],
                                          " (dry run)" if args.dry_run else ""))
    return 1 if any(r["status"] == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
