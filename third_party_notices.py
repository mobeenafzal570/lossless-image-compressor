"""Collect versioned upstream license texts and attribution records for bundles."""

import hashlib
import json
import os
from pathlib import Path
import posixpath
import urllib.parse
import urllib.request

QT_SOURCES = [("pyside/pyside-setup", "6.12.0"), ("qt/qtbase", "v6.12.0"),
              ("qt/qtsvg", "v6.12.0")]


def fetch(url):
    headers = {"User-Agent": "lossless-image-compressor-build"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and urllib.parse.urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as stream:
        return stream.read()


def collect_qt_notices(destination):
    destination = Path(destination)
    manifest_path = destination / "qt-source-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if all((destination / item["file"]).is_file() and hashlib.sha256(
                (destination / item["file"]).read_bytes()).hexdigest() == item["sha256"]
               for item in manifest["files"]):
            return
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for repository, revision in QT_SOURCES:
        tree = json.loads(fetch("https://api.github.com/repos/{}/git/trees/{}?recursive=1".format(
            repository, revision)))
        if tree.get("truncated"):
            raise RuntimeError("Upstream license inventory was truncated")
        paths = {item["path"] for item in tree["tree"] if item["type"] == "blob"}
        selected = {path for path in paths if path.startswith("LICENSES/")}
        attributions = sorted(path for path in paths if path.endswith("qt_attribution.json")
                              and not {"tests", "testdata", "examples", "doc"}.intersection(Path(path).parts))
        cached = {}
        def raw(path):
            if path not in cached:
                cached[path] = fetch("https://raw.githubusercontent.com/{}/{}/{}".format(
                    repository, revision, urllib.parse.quote(path)))
            return cached[path]
        for path in attributions:
            selected.add(path)
            try:
                entries = json.loads(raw(path), strict=False)
            except ValueError as error:
                raise RuntimeError("Cannot read upstream attribution: " + repository + "/" + path) from error
            for entry in entries if isinstance(entries, list) else [entries]:
                names = entry.get("LicenseFile", entry.get("LicenseFiles", []))
                if isinstance(names, str): names = [names]
                for name in names:
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), name))
                    if resolved in paths: selected.add(resolved)
        prefix = repository.replace("/", "-")
        for path in sorted(selected):
            relative = Path(prefix) / path
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = raw(path); target.write_bytes(payload)
            records.append({"file": relative.as_posix(), "repository": repository,
                            "revision": revision, "source": "https://github.com/{}/blob/{}/{}".format(
                                repository, revision, path),
                            "sha256": hashlib.sha256(payload).hexdigest()})
    manifest_path.write_text(json.dumps({"files": records}, indent=2) + "\n")
