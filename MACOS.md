# macOS guide

## 1. Install Python and download the script

Check Python in Terminal:

```sh
python3 --version
```

Use a current Python 3 release from [python.org](https://www.python.org/downloads/macos/) if you need to install or update it. PNG compression uses only the standard library and does not need pip packages.

On the repository's GitHub page, choose **Code → Download ZIP** and extract it. In Terminal, change to the extracted folder. Adjust the path if you extracted it elsewhere:

```sh
cd "$HOME/Downloads/lossless-image-compressor-main"
python3 compress_images.py --help
```

## 2. Compress an image or folder

One PNG:

```sh
python3 compress_images.py "$HOME/Pictures/photo.png" --output "$HOME/Pictures/compressed"
```

A folder including subfolders:

```sh
python3 compress_images.py "$HOME/Pictures/input" --output "$HOME/Pictures/compressed" --recursive
```

Keep the output outside the input directory. `input` and `compressed` are sibling directories in these examples. Originals stay untouched, and output paths retain their relative filenames and subfolders. Quote paths with spaces.

## 3. Preview or save a report

```sh
python3 compress_images.py "$HOME/Pictures/input" -o "$HOME/Pictures/compressed" -r --dry-run
python3 compress_images.py "$HOME/Pictures/input" -o "$HOME/Pictures/compressed" -r --report "report.json"
```

Dry run creates no files. Reports and existing image outputs are not overwritten; use a fresh report name or output directory for another run.

## 4. Optional JPEG compression

If you use [Homebrew](https://brew.sh/), its [jpeg-turbo formula](https://formulae.brew.sh/formula/jpeg-turbo) provides `jpegtran`:

```sh
brew install jpeg-turbo
"$(brew --prefix jpeg-turbo)/bin/jpegtran" -version
python3 compress_images.py "$HOME/Pictures/input" -o "$HOME/Pictures/compressed" -r --jpegtran "$(brew --prefix jpeg-turbo)/bin/jpegtran"
```

These commands discover Homebrew's prefix, so they do not assume an Intel or Apple Silicon installation path.

Alternatively, obtain the correct macOS package from the [official libjpeg-turbo downloads](https://github.com/libjpeg-turbo/libjpeg-turbo/releases), following its platform compatibility notes. The official package commonly installs programs under `/opt/libjpeg-turbo/bin`; check the directory used by your package. [Official installation directories](https://libjpeg-turbo.org/Documentation/OfficialBinaries).

```sh
/opt/libjpeg-turbo/bin/jpegtran -version
python3 compress_images.py "$HOME/Pictures/input" -o "$HOME/Pictures/compressed" -r --jpegtran "/opt/libjpeg-turbo/bin/jpegtran"
```

Without this option, JPEGs are copied unchanged. With it, the script uses a smaller JPEG result only if the frame, quantization, and metadata checks pass. It does not reduce JPEG quality or resize the image.

## 5. Read the result

- `optimized_png` / `optimized_jpeg`: a smaller result was written.
- `kept_not_smaller`: the unchanged original was copied because no smaller verified result was found.
- `kept_animated_png` / `kept_unsupported_format`: the image was copied unchanged.
- `skipped_existing`: a destination already existed and was left alone.
- `error`: inspect the file's message or JSON report. Originals are not modified.

If a path is not found, check capitalization and quotation marks. If output is rejected, choose a directory outside the input. If Terminal cannot access a folder, use a folder you can access or grant the normal macOS folder access requested for your own work. No administrator privileges are needed to run the script against your images.

## Optional development tests

Using Python 3.11 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest -v
```

With the Homebrew JPEG backend installed, enable the real JPEG integration checks in this terminal session:

```sh
JPEGTRAN_BIN="$(brew --prefix jpeg-turbo)/bin/jpegtran" .venv/bin/python -m unittest -v
```
