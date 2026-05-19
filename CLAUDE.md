# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bachelor's thesis project: a desktop GUI image editing and AI-powered enhancement application. Combines traditional image effects (PIL, OpenCV) with deep learning super-resolution (RealESRGAN, GFPGAN) in a CustomTkinter interface.

## Running the Application

```bash
python main.py
```

No build step required. Requires the model weights in `weights/` directory (not tracked by git due to size ~908 MB).

## Installing Dependencies

```bash
pip install -r requirements.txt
```

**Note:** `torch-directml` is for AMD GPU support on Windows. On NVIDIA, regular `torch` with CUDA suffices. Device selection is automatic via `constants.DEVICE`.

## Architecture

### Entry Point & UI

- **main.py** → creates ttkbootstrap root window ("superhero" theme, fullscreen) → instantiates `App`
- **app.py** (`App` class) is the central state container: holds `self.current_image`, `self.history`, all module settings, and orchestrates all UI construction and image operations
- **styles.py** defines custom-colored variants of CTk widgets used throughout the UI
- **constants.py** holds slider configs, device detection logic, and tiling parameters — edit here to change defaults

### Module System

The UI has two switchable modules managed by `App.load_module()`:
- **Image_Effects**: brightness/saturation/contrast/sharpness/blur/inversion/denoise/deblur
- **Resolution_Enhancement**: RealESRGAN upscaling (2x/4x/8x) + optional GFPGAN face restoration

Each module's settings are saved independently per history entry so switching history items restores the correct controls.

### Image Processing Pipeline

```
User action
  → app.modify_image()           # lightweight effects (PIL sliders, blur)
  → img_manipulation.py          # applies effects, calls @display_image decorator
  → helpers.display_on_canvas()  # renders PIL image to Tkinter canvas

Heavy operations (upscaling, deblur):
  → process_handlers.start_processing()   # disables UI, shows progress dialog
  → spawns multiprocessing.Process        # avoids blocking Tkinter event loop
  → image_processing_wrapper()            # handles tiling for large images
  → result/progress returned via Queue   # main thread polls with after()
```

### History System

Every image operation that produces a new image calls `App.build_history()`. Each history entry stores:
- The processed image (or a placeholder reference for lazy loading)
- Scale/viewport state
- Per-module settings snapshots (so undo restores effect sliders too)
- Parent ID for branching history

`App.load_history(id)` restores both the image and all module control states.

### Tiling Strategy (`image_tiling.py`, `realesrganer_my.py`)

Large images are split into 128×128 tiles with 60px overlap, processed independently (manages VRAM), then stitched with fade-weight blending on overlapping edges. The upscale factor is applied correctly during stitching. Tile size and overlap are in `constants.py`.

### Canvas Interaction

- **Shift+MouseWheel**: Zoom (10–500% range, implemented in `img_scaling.py`)
- **Shift+Click+Drag**: Pan image
- **Ctrl+Click+Drag**: Rectangle crop selection (`img_crop.py`)

### AI Models

- `realesrganer_my.py` — custom RealESRGAN with tiling; wraps `rrdbnet_arch.RRDBNet`
- `gfpganer_my.py` — GFPGAN wrapper supporting 3 architecture variants (clean, bilinear, original)
- `arch_util.py` — shared PyTorch layer utilities (weight init, DCN, optical flow ops)
- Weights loaded from `weights/` at inference time; device placement handled by `constants.DEVICE`

### Key Helper Patterns

- `helpers.generate_function_arguments()` — converts slider/switch widget values into `kwargs` for effect functions; adding a new effect requires registering it here
- `helpers.reset_module_tools()` — resets all controls to defaults; called on module switch
- `@display_image` decorator in `img_manipulation.py` — wraps modification functions to automatically update the canvas after the image changes

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

- `test.py` contains mostly commented-out experimental SRCNN code; it is not part of the active application
- `app.py` is large (~629 lines) and serves as both controller and view — new UI features go here
- `process_handlers.py` uses `multiprocessing` (not threading) because PyTorch releases the GIL inconsistently; the subprocess approach is intentional
