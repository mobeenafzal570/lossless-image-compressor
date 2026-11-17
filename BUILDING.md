# Development and desktop builds

End users should use the prebuilt Windows or macOS downloads described in [WINDOWS.md](WINDOWS.md) and [MACOS.md](MACOS.md). This page is for developers.

## Run the GUI from source

Use Python 3.10+ for the GUI. Build/test dependencies require Python 3.11+; CI uses Python 3.12.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-gui.txt
.venv/bin/python desktop_app.py
```

Windows equivalents:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-gui.txt
.\.venv\Scripts\python.exe desktop_app.py
```

Source runs can select a trusted `jpegtran` with **JPEG helper…**. Packaged builds discover their bundled helper automatically. The CLI remains independent of Qt and accepts an explicit helper path with `--jpegtran`.

## Native packaging

Build on the operating system and CPU architecture you intend to distribute. Install Git and a C compiler (Xcode command-line tools on macOS; Visual Studio C++ build tools on Windows), then:

```sh
python3 -m pip install -r requirements-build.txt
python3 build_desktop.py --output dist/desktop
```

On Windows substitute `py -3` for `python3`. The script:

1. Fetches the pinned libjpeg-turbo source revision and compiles a native static JPEG helper.
2. Runs format, independent decoding, desktop planner, worker and Qt drop-event checks.
3. Collects versioned upstream licenses and attribution records.
4. Builds a windowed PyInstaller application, including Python, Qt and the helper.
5. Launches the actual packaged app headlessly to compress synthetic PNG/JPEG fixtures, then independently verifies decoded pixels.
6. Produces a portable ZIP, SHA-256 checksum and build manifest under `dist/desktop`.

Use `--backend-only` to compile just the helper during development. `--label` asserts the expected architecture. Existing release archives are preserved; use a new output directory for another build.

The build uses internet access for declared packages, pinned source and upstream notices. The installed app works locally and does not upload images.

## GitHub Actions

**Lossless compression checks** validates the source on Windows, macOS and Linux. The separate **Build desktop apps** workflow is manually dispatched from the Actions tab and builds Windows x64, Apple silicon macOS arm64 and Intel macOS x64.

Artifacts contain ZIPs and checksum/build-manifest files. Maintainers can attach those ZIPs to a GitHub Release after review. The workflow has read-only repository permissions; it does not publish releases or change repository contents automatically.

## Tests

```sh
python3 -m pip install -r requirements-dev.txt -r requirements-gui.txt
QT_QPA_PLATFORM=offscreen REQUIRE_GUI_TESTS=1 REQUIRE_DECODER_TESTS=1 python3 -m unittest -v
```

On Windows set those environment variables in PowerShell before `py -3 -m unittest -v`. Set `JPEGTRAN_BIN` to a trusted helper to enable the real JPEG integration checks. The desktop build sets these variables itself.

Planning tests cover input/output separation, overlapping selections, duplicate filenames, recursion and cancellation. Qt tests send actual local-file drop events with Unicode/spaced paths, reject remote URLs, and verify responsive background processing.

## Signing and licenses

This build process does not use paid code-signing certificates, Apple Developer ID signing or notarization. macOS bundles are locally ad-hoc signed by PyInstaller. A distributor can add its own platform signing/notarization after packaging.

Qt libraries remain dynamically linked. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the packaged notices directory for component sources and terms.
