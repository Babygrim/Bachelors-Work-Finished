# Model weights

The application does not download large model files automatically. Download
weights from the official project release pages, then place them in the
repository `weights/` directory.

## RealESRGAN upscaling

Official source:

- <https://github.com/xinntao/Real-ESRGAN/releases>

Place RRDBNet checkpoints under `weights/` with an upscale-factor prefix:

```text
weights/
  2x-<model>.pth
  4x-<model>.pth
  8x-<model>.pth
```

The UI lists only ONNX files matching `weights/{factor}x-*.onnx`. Convert
available `.pth` checkpoints with:

```powershell
python scripts\export_onnx.py
```

The exporter creates FP32 and FP16 ONNX files next to each compatible
checkpoint. GFPGAN, deblur, and refocus checkpoints are skipped because they
use different architectures.

## GFPGAN face restoration

Official source:

- <https://github.com/TencentARC/GFPGAN/releases>

Keep the GFPGAN `.pth` checkpoint at the path expected by
`core/models/gfpganer.py`. GFPGAN is not an ONNX upscaling model and must not
be converted with `scripts\export_onnx.py`.

## Real-time video models

Real-time models belong in:

```text
weights\realtime\
```

Supported files use `.pb` or `.onnx` extensions. The filename must contain a
supported factor suffix such as `_x2.pb`, `_x4.onnx`, or `_x8.onnx`.

The application discovers these files automatically when the video real-time
preview is opened.

## Current repository layout

```text
weights\
  2x\
  4x\
  realtime\
```

Do not commit large checkpoints to Git. The `weights/` directory is intended
for local model files.
