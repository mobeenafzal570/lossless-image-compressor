"""Build a native, windowed bundle with a pinned lossless JPEG helper."""

import argparse
import hashlib
from importlib.metadata import distribution
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request

from third_party_notices import collect_qt_notices

ROOT = Path(__file__).resolve().parent
NAME = "Lossless Image Compressor"
VERSION = "1.0.0"
JPEG_COMMIT = "7b4993786d856cbccabfc0ed2f923ba000e326cc"
JPEG_REPOSITORY = "https://github.com/libjpeg-turbo/libjpeg-turbo.git"


def run(command, **kwargs):
    print("+", " ".join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def tool(name):
    local = Path(sys.executable).parent / (name + ".exe" if os.name == "nt" else name)
    found = str(local) if local.exists() else shutil.which(name)
    if not found: raise RuntimeError("Build tool is missing: " + name)
    return found


def build_backend(work):
    source = work / "jpeg-source"
    compiled = work / "jpeg-build"
    if not (source / ".git").exists():
        source.mkdir(parents=True, exist_ok=True)
        run(["git", "init", source])
        run(["git", "-C", source, "remote", "add", "origin", JPEG_REPOSITORY])
        run(["git", "-C", source, "fetch", "--depth", "1", "origin", JPEG_COMMIT])
        run(["git", "-C", source, "checkout", "--detach", "FETCH_HEAD"])
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != JPEG_COMMIT: raise RuntimeError("JPEG source revision does not match the pin")
    command = [tool("cmake"), "-S", source, "-B", compiled,
               "-DENABLE_SHARED=OFF", "-DENABLE_STATIC=ON", "-DWITH_SIMD=OFF",
               "-DWITH_TURBOJPEG=OFF", "-DWITH_TOOLS=ON", "-DWITH_TESTS=OFF",
               "-DCMAKE_BUILD_TYPE=Release"]
    if os.name == "nt": command.extend(["-A", "x64", "-DWITH_CRT_DLL=OFF"])
    else: command.extend(["-G", "Ninja", "-DCMAKE_MAKE_PROGRAM=" + tool("ninja")])
    run(command)
    run([tool("cmake"), "--build", compiled, "--config", "Release", "--target", "jpegtran-static", "--parallel", "2"])
    executable_name = "jpegtran-static.exe" if os.name == "nt" else "jpegtran-static"
    candidates = list(compiled.rglob(executable_name))
    if len(candidates) != 1: raise RuntimeError("Cannot identify the built JPEG helper")
    run([candidates[0], "-version"])
    return candidates[0], source


def collect_notices(work, jpeg_source):
    notices = work / "notices"
    collect_qt_notices(notices)
    vendor = notices / "libjpeg-turbo"; vendor.mkdir(parents=True, exist_ok=True)
    for name in ["LICENSE.md", "README.ijg"]:
        shutil.copy2(jpeg_source / name, vendor / name)
    for name in ["PyInstaller", "shiboken6", "PySide6_Essentials"]:
        metadata = distribution(name)
        for relative in metadata.files or []:
            if any(word in str(relative).upper() for word in ["LICENSE", "COPYING", "NOTICE"]):
                source = Path(metadata.locate_file(relative))
                if source.is_file():
                    target = notices / name / str(relative).replace("../", "")
                    target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
    python_license = notices / "Python-LICENSE.txt"
    if not python_license.exists():
        version = platform.python_version()
        url = "https://raw.githubusercontent.com/python/cpython/v{}/LICENSE".format(version)
        with urllib.request.urlopen(url, timeout=30) as response:
            python_license.write_bytes(response.read())
    (notices / "components.json").write_text(json.dumps({
        "Python": platform.python_version(), "Qt for Python": "6.12.0",
        "libjpeg-turbo": {"repository": JPEG_REPOSITORY, "commit": JPEG_COMMIT},
        "PyInstaller": distribution("PyInstaller").version,
    }, indent=2) + "\n")
    return notices


def make_icon(work):
    from PySide6 import QtCore, QtGui, QtSvg
    from PIL import Image
    icon = work / "app-icon.png"
    image = QtGui.QImage(1024, 1024, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    renderer = QtSvg.QSvgRenderer(str(ROOT / "app-icon.svg")); renderer.render(painter); painter.end()
    if not image.save(str(icon)): raise RuntimeError("Could not render application icon")
    extension = ".icns" if sys.platform == "darwin" else ".ico"
    target = work / ("app-icon" + extension)
    with Image.open(icon) as source: source.save(target)
    return target


def verify_bundle(executable, work, env):
    from PIL import Image
    fixture_dir = work / "smoke"; fixture_dir.mkdir(parents=True, exist_ok=True)
    output = fixture_dir / "smoke-output"
    if output.exists(): shutil.rmtree(output)
    for extension, options in [("png", {"compress_level": 0}), ("jpg", {"quality": 92, "optimize": False})]:
        Image.new("RGB", (128, 128), (30, 90, 160)).save(fixture_dir / ("smoke-input." + extension), **options)
    report = fixture_dir / "smoke-result.json"
    run([executable, "--smoke-test", report], env=env, timeout=120)
    result = json.loads(report.read_text())
    if len(result.get("files", [])) != 2: raise RuntimeError("Packaged application did not process both fixtures")
    for item in result["files"]:
        with Image.open(item["source"]) as source, Image.open(item["destination"]) as target:
            if source.mode != target.mode or source.size != target.size or source.tobytes() != target.tobytes():
                raise RuntimeError("Packaged application changed decoded pixels")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "desktop")
    parser.add_argument("--label", help="Expected platform label (windows-x64, macos-arm64, macos-x64)")
    args = parser.parse_args()
    machine = platform.machine().lower()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    system = "macos" if sys.platform == "darwin" else "windows" if os.name == "nt" else "linux"
    label = system + "-" + architecture
    if args.label and args.label != label: raise RuntimeError("Build architecture is " + label + ", not " + args.label)
    work = ROOT / "build" / ("desktop-" + label); work.mkdir(parents=True, exist_ok=True)
    backend, jpeg_source = build_backend(work)
    (work / "backend.json").write_text(json.dumps({"executable": str(backend)}, indent=2) + "\n")
    if args.backend_only: return 0
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", JPEGTRAN_BIN=str(backend),
               REQUIRE_GUI_TESTS="1", REQUIRE_DECODER_TESTS="1")
    run([sys.executable, "-m", "unittest", "-v"], cwd=ROOT, env=env)
    notices = collect_notices(work, jpeg_source)
    helper_dir = work / "helper"; helper_dir.mkdir(exist_ok=True)
    helper = helper_dir / ("jpegtran.exe" if os.name == "nt" else "jpegtran")
    shutil.copy2(backend, helper)
    icon = make_icon(work)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
               "--name", NAME, "--distpath", work / "dist", "--workpath", work / "pyinstaller",
               "--specpath", work / "spec", "--icon", icon,
               "--add-binary", str(helper) + ":bin", "--add-data", str(ROOT / "app-icon.svg") + ":.",
               "--add-data", str(notices) + ":third_party_notices",
               "--add-data", str(ROOT / "THIRD_PARTY_NOTICES.md") + ":.",
               "--hidden-import", "PySide6.QtSvg"]
    if sys.platform == "darwin": command.extend(["--osx-bundle-identifier", "com.mobeenafzal.losslesscompressor"])
    command.append(ROOT / "desktop_app.py")
    run(command, cwd=ROOT)
    if sys.platform == "darwin":
        bundle = work / "dist" / (NAME + ".app")
        executable = bundle / "Contents" / "MacOS" / NAME
    else:
        bundle = work / "dist" / NAME
        executable = bundle / (NAME + ".exe" if os.name == "nt" else NAME)
    verification = verify_bundle(executable, work, env)
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / ("Lossless-Image-Compressor-{}-{}".format(VERSION, label) + ".zip")
    if archive.exists(): raise RuntimeError("Preserving existing release archive: " + str(archive))
    if sys.platform == "darwin":
        run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", bundle, archive])
    else:
        shutil.make_archive(str(archive)[:-4], "zip", root_dir=bundle.parent, base_dir=bundle.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n")
    archive.with_suffix(".build.json").write_text(json.dumps({"version": VERSION, "platform": label,
        "archive": archive.name, "sha256": digest, "packagedSmokeTest": "passed",
        "decodedPixelChecks": len(verification["files"]), "signing": "unsigned / local ad-hoc on macOS"}, indent=2) + "\n")
    print(json.dumps({"archive": str(archive), "sha256": digest, "platform": label}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
