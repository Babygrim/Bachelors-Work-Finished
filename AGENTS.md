# Agent Instructions

## Project

This repository is a Windows desktop image and video editor built with pywebview. The Python application exposes a JavaScript API to the UI and combines PIL/OpenCV effects with RealESRGAN upscaling and optional GFPGAN face restoration.

Read [CLAUDE.md](CLAUDE.md) for the fuller architecture and workflow notes.

## Repository Boundaries

- `main.py` creates the pywebview window and binds `WebApp`.
- `core/application.py` owns history, settings, previews, native dialogs, jobs, and the Python-to-JavaScript API.
- `core/config/` contains shared paths and processing configuration.
- `core/processing/` contains reusable image operations; keep it independent of the webview bridge.
- `core/models/` contains the project-owned ONNX/GFPGAN wrappers and RRDBNet architecture.
- `core/services/` contains cross-cutting services such as logging and local video streaming.
- `ui/web/` contains the HTML, CSS, and browser JavaScript. Keep presentation logic there and Python state/operations in `core/`.
- `basicsr/BasicSR/` is a separate third-party repository when present; do not treat it as application code or rewrite it during app changes.

## Environment and Commands

Run commands from this directory using the checked-in Python 3.12 virtual environment when available:

```powershell
.venv/Scripts/python main.py
.venv/Scripts/python -m pip install -r requirements.txt
ruff check .
ty check
```

There is no application test suite. Run `ruff check .` and `ty check` after Python changes; manually exercise the affected UI workflow when practical.

## Model and Runtime Constraints

- Large checkpoints are intentionally untracked in `weights/`.
- The UI discovers only exported ONNX files matching `weights/{factor}x-*.onnx`; `.pth` files alone are not selectable.
- RealESRGAN uses ONNX Runtime with `DmlExecutionProvider`, tiled inference, and progress dictionaries from `core.progress.report_progress()`.
- Missing ONNX files may be exported from `.pth` checkpoints on first model use. Avoid changing this startup/runtime behavior without checking GPU memory and cancellation behavior.
- GFPGAN still uses PyTorch and BasicSR/facexlib dependencies; preserve that boundary when changing the primary ONNX path.

## Change Conventions

- Preserve the Python/JavaScript API shape unless a coordinated UI and backend change requires otherwise.
- Keep long-running inference out of the webview event loop and continue reporting structured progress.
- Preserve history-entry settings and stale-preview revision checks when changing image operations or previews.
- Keep changes focused; do not modify generated/exported model files or third-party BasicSR code for an application fix.