# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bachelor's thesis project: a desktop image editing and AI-powered enhancement application. Combines traditional image effects (PIL, OpenCV) with deep learning super-resolution (RealESRGAN, GFPGAN) in a pywebview interface.

## Running the Application

```bash
python main.py
```

No build step required. Requires the model weights in `weights/` directory (not tracked by git due to size ~908 MB).

## Installing Dependencies

```bash
pip install -r requirements.txt
```

**Note:** Upscaling runs through ONNX Runtime with the DirectML execution provider (`onnxruntime-directml`) — works on AMD/NVIDIA/Intel GPUs on Windows. PyTorch is used for the one-time `.pth` -> `.onnx` export and for the GFPGAN face-restoration path.

## Architecture

### Entry Point & UI

- **main.py** creates the pywebview window and exposes the Python `WebApp` API.
- **ui/web/** contains the HTML, CSS, and JavaScript interface.
- **core/application.py** owns image/history state, applies effects, handles native file dialogs, and runs long operations.
- **core/processing/** contains reusable effects, resizing, tiling, and resolution operations.
- **core/models/** contains the project's ONNX and GFPGAN model wrappers and architectures.
- **core/constants.py** holds the shared project path and image tiling configuration.

### Module System

The UI has two switchable modules managed by `WebApp.set_module()` and implemented in `ui/web/scripts/modules/`:
- **Image_Effects**: brightness/saturation/contrast/sharpness/blur/inversion/denoise
- **Resolution_Enhancement**: RealESRGAN upscaling (2x/4x/8x) + optional GFPGAN face restoration
- **Video_Enhancement**: automatically selected for video history entries; provides frame playback, seek, crop, and save-frame actions.

Image settings are saved independently per history entry. Video entries retain their source path, FPS, and current frame; cropping or saving a frame creates a still-image history entry.

### Image Processing Pipeline

- Effect settings are sent through `window.pywebview.api` and applied to the source PIL image in `WebApp`.
- Upscaling and denoising run in a child process so the webview event loop stays responsive.
- Progress events use dictionaries (`stage`, `current`, `total`, `unit`, `percent`) on a multiprocessing queue.
- Image previews are rendered asynchronously; full-resolution source images remain in Python for editing and export.

### History System

Each imported, cropped, or processed image creates a Python history entry containing the source PIL image, effect/enhancement settings, scale, and a cached thumbnail. Selecting a history entry restores its settings and schedules a preview render; outdated preview results are discarded.

### Tiling Strategy (`core/processing/tiling.py`, `core/models/onnx_realesrganer.py`)

Large images are split into tiles, processed independently (manages VRAM), then stitched. The ONNX path uses fixed-size IOBinding buffers for interior tiles and a CPU prefetch thread to overlap data prep with GPU inference. Tile size and overlap defaults live in `core/constants.py`.

### Canvas Interaction

- **Shift+MouseWheel**: Zoom (10–500%).
- **Shift+Click+Drag**: Pan image.
- **Ctrl+Click+Drag**: Rectangle crop selection.

### AI Models

- `core/models/onnx_realesrganer.py` — **primary** upscaling path. ONNX Runtime + DirectML, tiled inference, FP16 preferred. On first use it exports the `.pth` weight to both FP32 and FP16 ONNX next to the original file.
- `core/models/gfpganer.py` — GFPGAN wrapper for the optional face-restoration toggle.
- `core/models/rrdbnet_arch.py` — RRDBNet definition used by ONNX export.
- `core/models/arch_util.py` — shared PyTorch layer utilities.
- Weights loaded from `weights/` at inference time.

### Settings and Previews

- Settings are stored as plain Python values per history entry and serialized through the pywebview API.
- `_apply_effects()` applies effects to the original PIL image for export and processing.
- Preview renders run asynchronously; a cached thumbnail is used for history selection and stale renders are discarded.

## Model Weights Location

```
weights/
  2x_NMKD-Superscale-SP_178000_G.pth
  RealESRGAN_x4plus.pth
  RealESRGAN_x4plus_anime_6B.pth
  RealESRGAN_x8.pth
  ... (see weights/ directory for full list)
  GFPGANv1.4.pth
  Fatality-DeBlur_latest_G.pth
  ReFocus-V3.pth
```

## Known Architecture Notes

- Keep web presentation in `ui/web/` and Python application state/operations in `core/application.py`.
- Keep reusable image processing code independent of the webview bridge.
- Model inference remains in a separate process; this avoids blocking the webview event loop and allows progress reporting.

## Progress Events

Use `core.progress.report_progress()` for tiled work. It sends a structured dictionary containing the stage, current item, total, unit, and percentage. The controller continues to accept numeric progress values for compatibility.
