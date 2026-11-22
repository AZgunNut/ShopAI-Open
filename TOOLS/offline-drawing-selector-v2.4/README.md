# ShopAI Offline Drawing ROI Selector — v2.4

A standalone, **offline** Ubuntu GTK3 desktop utility for selecting the region of an engineering drawing that should be processed for geometry.

## Getting started

On Ubuntu 24.04 with existing GTK3 Python bindings, download this folder and run:

```bash
bash shopai_roi_native_offline_v2_4_no_cairo_fix.sh
```

To install the desktop menu/desktop icon afterward:

```bash
bash ShopAI_ROI_Desktop_Icon_Install_FIXED.sh
```

The desktop-icon installer embeds a local 192×192 PNG icon. No internet, remote server, `sudo`, or package installation is used. If system Python lacks GTK3 bindings, installation may not be sufficient to launch the GUI; install dependencies separately using your operating system's package management.

## Operation

- Drop/copy/paste drawings into `~/ShopAI-ROI-Tool/01_INBOX/`.
- Double-click an image in the left-hand list to fit it into the right-hand display.
- Click and drag a rectangle around the part; inspect before saving.
- Save to `02_READY/` for a cropped geometry PNG, full-size keep mask, original image for OCR, selection overlay, JSON coordinates and `READY_INDEX.json`.
- The original source bytes are preserved. The selection applies to geometry inputs; OCR can inspect the complete drawing.

The app does **not** run OpenCV v5, VTracer, or interpret dimensions, and its rectangular crop does not strip annotation lines inside the selected region.

## What is included

- `roi_native_v2_4.py`: application source.
- `START_NATIVE_V2_4.sh`: runtime launcher.
- `shopai_roi_native_offline_v2_4_no_cairo_fix.sh`: complete v2.4 app installer.
- `ShopAI_ROI_Desktop_Icon_Install_FIXED.sh`: corrected offline PNG icon and desktop shortcut installer.
- `install_desktop_launcher.sh` + `assets/shopai-roi-selector.svg`: alternative scalable icon launcher.
- No user drawings, test results, private machine inventories, model weights, or logs.

## Verification and limitations

The application was tested on the owner's VirusLoaderMax desktop: the user confirmed v2.4 showed the image and drag-selection box. A saved 2500×1500 mounting-plate selection was independently inspected for pixel-exact cropping, consistent mask, intact original and exclusion of the outer border. This is **not** a claim of dimensional or complete front-end recognition accuracy.

The corrected icon installer fixes `desktop-file-validate` rejecting a temporary filename without a `.desktop` extension, and removes the redundant main category. It was tested with a dummy install in a temporary HOME; actual Ubuntu desktop-menu validation and launching must still be checked on the user's machine.

## Licensing

**ShopAI Community & Commercial Reciprocity License v1.0** (see repository root `LICENSE`). Personal use is free; commercial use is permitted subject to attribution and the reciprocity terms. This is a custom **source-available** license, not an OSI-approved open-source license. Third-party components remain under their own licenses. No rights are asserted over independent GTK/Python implementations.
