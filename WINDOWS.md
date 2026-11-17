# Windows guide — no terminal needed

## Download and open

1. Open the project's [Releases page](https://github.com/mobeenafzal570/lossless-image-compressor/releases/latest).
2. Download **Lossless-Image-Compressor-1.0.0-windows-x64.zip** for Windows 10 (1809+) or Windows 11 on a 64-bit Intel/AMD computer.
3. In File Explorer, right-click the ZIP and choose **Extract All**.
4. Open the extracted **Lossless Image Compressor** folder and double-click **Lossless Image Compressor.exe**.

Keep the whole folder together, including `_internal`, which contains bundled libraries. You do not need Python, pip, PowerShell or a separate JPEG tool. These builds are unsigned, so Windows may ask for first-launch approval.

## Compress images

1. Drag images or folders from File Explorer into the drop area. Alternatively use **Add images…** or **Add folder…**.
2. Review the **Images** tab. Use **Remove selected** or **Clear** if needed.
3. Beside **Save to**, click **Choose folder…** and select a separate destination outside the input folders.
4. Leave **Include subfolders** checked if you want nested images too.
5. Click **Compress images** and review the **Results** tab.
6. Click **Open output folder** when finished.

Original images are never overwritten. Folder selections keep their hierarchy under the destination. Duplicate filenames receive a numbered name, overlapping selections are processed once, and existing outputs are skipped.

## Read the results

- **Compressed:** a smaller, verified lossless result was saved.
- **Already optimized · copied:** an exact copy was saved because no smaller encoding was found.
- **Animation preserved · copied:** an animated PNG was copied unchanged.
- **Format preserved · copied:** GIF, WebP, BMP, TIFF, AVIF or HEIC was copied; this version does not optimize that format.
- **Already exists · skipped:** choose a fresh output folder to process it again.
- **Could not process:** hover over the row for its reason. Originals remain untouched.

Static PNGs and JPEGs are optimized without resizing or reducing quality. Already compressed images may not shrink further.

## Cancel, reports and troubleshooting

**Cancel** stops safely after the current image finishes. Completed outputs stay in the destination.

**Save report…** exports a local JSON summary. Choose a new filename. Reports can include image paths; the app does not upload them.

If output overlaps an input, choose another folder. For a permissions error, select a writable folder under your user account. If an organization's app policy blocks unsigned software, ask its administrator to review the build.

## Developers and automation

The original script remains available. See [BUILDING.md](BUILDING.md) and the README's [command-line section](README.md#optional-command-line-usage) for source setup, builds and automation.
