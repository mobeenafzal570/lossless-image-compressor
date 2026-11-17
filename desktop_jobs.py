"""Desktop batch planning and execution, independent of the GUI framework."""

from dataclasses import dataclass
import os
from pathlib import Path
import threading

from compress_images import IMAGE_SUFFIXES, inside, process_file


@dataclass(frozen=True)
class ImageJob:
    source: Path
    destination: Path


def source_key(path):
    return os.path.normcase(str(path.resolve()))


def build_plan(inputs, output, recursive=True, cancel=None):
    """Keep folders, disambiguate duplicate names and reject unsafe destinations."""
    cancel = cancel or threading.Event()
    output = Path(output).expanduser().resolve()
    selections, warnings, seen_roots = [], [], set()
    for value in inputs:
        path = Path(value).expanduser().absolute()
        if not path.exists():
            raise ValueError("An input no longer exists: {}".format(path))
        if path.is_symlink():
            warnings.append("Skipped symbolic link: {}".format(path))
            continue
        key = source_key(path)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        if path.is_dir() and inside(output, path.resolve()):
            raise ValueError("Choose an output folder outside the input folder: {}".format(path.name))
        if path.is_dir() or (path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES):
            selections.append(path)
        else:
            warnings.append("Not a supported image selection: {}".format(path.name))
    if output.exists() and not output.is_dir():
        raise ValueError("The output location must be a folder.")

    jobs, seen_sources, reserved_roots, used_targets = [], set(), set(), set()

    def add(path, relative):
        if path.is_symlink():
            warnings.append("Skipped symbolic link: {}".format(path))
            return
        key = source_key(path)
        if key in seen_sources:
            return
        seen_sources.add(key)
        original, number = relative, 1
        while relative.as_posix().casefold() in used_targets:
            number += 1
            relative = original.with_name("{} ({}){}".format(original.stem, number, original.suffix))
        used_targets.add(relative.as_posix().casefold())
        target = (output / relative).resolve()
        if not inside(target, output):
            raise ValueError("An output subfolder links outside the selected destination.")
        jobs.append(ImageJob(path, target))

    # Files first: folder prefixes cannot collide with a top-level image filename.
    for path in selections:
        if cancel.is_set():
            return jobs, warnings
        if path.is_file():
            relative = Path(path.name)
            if relative.name.casefold() in reserved_roots:
                number = 2
                while "{} ({}){}".format(path.stem, number, path.suffix).casefold() in reserved_roots:
                    number += 1
                relative = Path("{} ({}){}".format(path.stem, number, path.suffix))
            reserved_roots.add(relative.name.casefold())
            add(path, relative)
    for folder in selections:
        if not folder.is_dir():
            continue
        prefix, number = folder.name or "Images", 1
        original = prefix
        while prefix.casefold() in reserved_roots:
            number += 1
            prefix = "{} ({})".format(original, number)
        reserved_roots.add(prefix.casefold())
        paths = folder.rglob("*") if recursive else folder.iterdir()
        for path in paths:
            if cancel.is_set():
                return jobs, warnings
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                add(path, Path(prefix) / path.relative_to(folder))
    all_sources = {source_key(job.source) for job in jobs}
    if any(source_key(job.destination) in all_sources for job in jobs):
        raise ValueError("The output would overlap an original image. Choose a different folder.")
    return jobs, warnings


def run_batch(inputs, output, recursive=True, jpegtran=None, cancel=None,
              on_planned=None, on_progress=None):
    cancel = cancel or threading.Event()
    jobs, warnings = build_plan(inputs, output, recursive, cancel)
    if not jobs and not cancel.is_set():
        raise ValueError("No image files found. Add images or a folder containing images.")
    if on_planned:
        on_planned(len(jobs), warnings)
    results = []
    for index, job in enumerate(jobs):
        if cancel.is_set():
            break
        result = process_file(job.source, job.destination, jpegtran=jpegtran)
        results.append(result)
        if on_progress:
            on_progress(index + 1, len(jobs), result)
    return {"files": results, "warnings": warnings, "planned": len(jobs),
            "cancelled": cancel.is_set(),
            "total_saved_bytes": sum(item.get("saved_bytes", 0) for item in results)}
