# Third-party components in desktop distributions

The desktop application bundles Python, Qt for Python (PySide6/Shiboken), Qt shared libraries, the PyInstaller bootloader, and a native `jpegtran` built from libjpeg-turbo. The command-line script remains a standard-library-only tool unless a JPEG helper is explicitly supplied.

Desktop bundles include a `third_party_notices` directory with upstream license texts, attribution records, component versions, and the exact source URLs used to collect those records. On macOS it is inside the `.app` resources; on Windows it is under the portable application's `_internal` directory.

## Qt for Python and Qt

Qt for Python and the Qt modules used here are distributed under their applicable open-source terms, including LGPL v3. Qt shared libraries remain separate from the application's code and may be replaced by compatible builds. This application places no restriction on debugging modifications to those libraries.

Corresponding upstream sources and license records:

- https://github.com/pyside/pyside-setup/tree/6.12.0
- https://github.com/qt/qtbase/tree/v6.12.0
- https://github.com/qt/qtsvg/tree/v6.12.0
- https://doc.qt.io/qtforpython-6/licenses.html

The notices inventory includes upstream third-party attribution files and their referenced license files, including records for components that may not be enabled in every platform build.

## libjpeg-turbo

The JPEG helper is built without changing upstream source, at commit `7b4993786d856cbccabfc0ed2f923ba000e326cc` (3.2.1). Its `LICENSE.md` and `README.ijg` are included with the binary.

Source: https://github.com/libjpeg-turbo/libjpeg-turbo/tree/7b4993786d856cbccabfc0ed2f923ba000e326cc

## Python and PyInstaller

The Python license and the PyInstaller license/bootloader exception are included in the notices directory. The build manifest identifies the interpreter and packaging versions used.

- https://github.com/python/cpython
- https://github.com/pyinstaller/pyinstaller

No commercial Qt license, Apple Developer ID signature, Microsoft code-signing certificate, or notarization is asserted by these builds.
