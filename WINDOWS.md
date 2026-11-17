# Windows guide

## 1. Install Python and download the script

Install a current Python 3 release from [python.org](https://www.python.org/downloads/windows/). Open PowerShell and check:

```powershell
py -3 --version
```

If your installation provides `python` instead of `py`, use `python` for the commands below. If neither works, complete Python's installer setup and reopen PowerShell.

On this repository's GitHub page, choose **Code → Download ZIP**. Extract the ZIP. Open its extracted folder in File Explorer, click the address bar, type `powershell`, and press Enter. Check that the script is there:

```powershell
Get-ChildItem compress_images.py
py -3 compress_images.py --help
```

PNG compression needs no pip packages or additional software.

## 2. Compress an image or folder

One PNG:

```powershell
py -3 compress_images.py "C:\Users\YourName\Pictures\photo.png" --output "C:\Users\YourName\Pictures\compressed"
```

All recognized images in a folder and its subfolders:

```powershell
py -3 compress_images.py "C:\Users\YourName\Pictures\input" --output "C:\Users\YourName\Pictures\compressed" --recursive
```

Replace `YourName` and the example directories with your own paths. Keep the output outside the input directory. Originals stay in `input`, and outputs keep their relative filenames and subfolders. Existing outputs are skipped.

## 3. Preview or save a report

```powershell
py -3 compress_images.py "C:\Pictures\input" -o "C:\Pictures\compressed" -r --dry-run
py -3 compress_images.py "C:\Pictures\input" -o "C:\Pictures\compressed" -r --report "report.json"
```

Dry run creates no files. Use a new report filename for each run. If an output already exists, choose a fresh output directory to process it again.

## 4. Optional JPEG compression

Obtain the Windows binary package for your computer from the [official libjpeg-turbo downloads](https://github.com/libjpeg-turbo/libjpeg-turbo/releases). Follow its installer and locate `jpegtran.exe` in its `bin` directory.

The libjpeg-turbo Project documents a typical Visual C++ x64 installation under `C:\libjpeg-turbo64`; your selected directory may differ. [Official installation directories](https://libjpeg-turbo.org/Documentation/OfficialBinaries).

Check the executable, then point the script at it:

```powershell
& "C:\libjpeg-turbo64\bin\jpegtran.exe" -version
py -3 compress_images.py "C:\Pictures\input" -o "C:\Pictures\compressed" -r --jpegtran "C:\libjpeg-turbo64\bin\jpegtran.exe"
```

Without `--jpegtran`, JPEGs are copied unchanged and labeled `kept_jpegtran_not_configured`. With it, only smaller results that pass the invariant checks are used. The script never adjusts JPEG quality, dimensions or colors.

## 5. Read the result

- `optimized_png` / `optimized_jpeg`: a smaller result was written.
- `kept_not_smaller`: an exact copy was written because the candidate was not smaller.
- `kept_animated_png` / `kept_unsupported_format`: an exact copy was written; this format is not optimized.
- `skipped_existing`: a destination already existed and was left alone.
- `error`: that file failed; inspect its message or the report. An error does not modify the original.

For “input does not exist,” check the quoted path. For “output directory outside the input,” choose a sibling directory. For permissions errors, choose a writable folder such as your Pictures folder. For a JPEG backend error, check its executable path with the `-version` command above.

## Optional development tests

Using Python 3.11 or later:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest -v
```

No PowerShell activation or execution-policy change is required. To enable real JPEG tests in that session:

```powershell
$env:JPEGTRAN_BIN = "C:\libjpeg-turbo64\bin\jpegtran.exe"
.\.venv\Scripts\python.exe -m unittest -v
```
