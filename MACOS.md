# macOS guide — no terminal needed

## Pick the right download

Open **Apple menu → About This Mac**:

- An Apple chip: choose **Lossless-Image-Compressor-1.0.0-macos-arm64.zip**.
- An Intel processor: choose **Lossless-Image-Compressor-1.0.0-macos-x64.zip**.

These builds require macOS 14.4 or later. Download from the project's [Releases page](https://github.com/mobeenafzal570/lossless-image-compressor/releases/latest), rather than GitHub's automatic source-code archive.

## Open the app

1. Double-click the ZIP in Finder to extract it.
2. Move **Lossless Image Compressor.app** into Applications if you want to keep it installed.
3. Double-click the app.

Python and the lossless JPEG helper are included. You do not need Terminal, Homebrew, pip or a separate JPEG installation.

The builds do not have an Apple Developer ID signature or notarization. macOS may require your explicit first-launch approval through its normal app-approval controls in **System Settings → Privacy & Security**. Review the source and release checksums before deciding whether to trust an unsigned build.

## Compress images

1. Drag images or folders from Finder into the drop area. You can also use **Add images…** or **Add folder…**.
2. Review the **Images** tab and remove selections you do not need.
3. Click **Choose folder…** beside **Save to** and select a separate destination outside the input folders.
4. Keep **Include subfolders** enabled to include nested images.
5. Click **Compress images** and review **Results**.
6. Click **Open output folder** when finished.

The app preserves originals, metadata, dimensions and pixel quality. It keeps folder hierarchy, disambiguates duplicate filenames, processes overlapping selections once and skips existing outputs.

## Understand the results

- **Compressed:** a smaller, verified lossless result was saved.
- **Already optimized · copied:** an exact copy was saved because no smaller encoding was found.
- **Animation preserved · copied:** an animated PNG was copied unchanged.
- **Format preserved · copied:** GIF, WebP, BMP, TIFF, AVIF or HEIC was copied without optimization.
- **Already exists · skipped:** choose a fresh output folder to process it again.
- **Could not process:** hover over the row for its error. Originals stay untouched.

PNG and JPEG size reduction varies. Already efficiently compressed images may not get smaller.

## Cancel and reports

**Cancel** stops after the current image, leaving completed outputs in place.

**Save report…** exports a local JSON summary to a new filename. It may contain image paths and is never uploaded automatically.

If output overlaps an input, choose another destination. If macOS requests normal folder access, grant only the access appropriate for your own images. If device policies block unsigned software, ask the administrator to review the build.

## Developers and automation

The original script still supports terminal automation. See [BUILDING.md](BUILDING.md) and the README's [command-line section](README.md#optional-command-line-usage) for source setup, builds and tests.
