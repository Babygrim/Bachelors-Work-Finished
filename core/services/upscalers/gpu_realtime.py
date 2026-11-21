"""Real-ESRGAN compact models (DirectML) offered in the real-time list.

These run on the GPU through OnnxRealESRGANer and are far sharper than AMD VideoSR, but they only
keep up with real time on low-resolution sources. A model is offered only for the output option
whose scale it was trained for (4x models for 4x, 2x models for 2x, ...).
"""

import re

from core.models.weights import is_compact_model, max_rrdb_output_pixels, model_files
from core.processing.output_size import output_plan

GPU_REALTIME_SUFFIX = " (Real-ESRGAN GPU)"
# Up to 720p a frame is processed as one tile of fixed shape (2x compact: ~11 fps at 720p, 40+ fps
# at 360p); larger frames fall back to overlapping tiles and are much slower than real time.
MAX_GPU_FULL_FRAME_PIXELS = 1280 * 720


def is_gpu_realtime_model(label):
    return label.endswith(GPU_REALTIME_SUFFIX)


def gpu_realtime_model_name(label):
    """Weight-file stem for a real-time GPU model label."""
    return label[:-len(GPU_REALTIME_SUFFIX)]


def gpu_realtime_model_scale(label):
    """Upscale factor of a real-time GPU model, read from its '4x-...' file name prefix."""
    return int(re.match(r"(\d+)x-", gpu_realtime_model_name(label)).group(1))


def uses_full_frame(frame_size, scale, model_stem):
    """Whether a frame can be upscaled as a single tile (otherwise overlapping tiles are used)."""
    pixels = frame_size[0] * frame_size[1]
    if pixels > MAX_GPU_FULL_FRAME_PIXELS:
        return False
    return is_compact_model(model_stem) or pixels * scale * scale <= max_rrdb_output_pixels(model_stem)


def gpu_realtime_models(factor, source_size):
    """Compact model labels whose scale matches the output option (multiplier or 1080/2160 target)."""
    scale = output_plan(source_size, factor)[0]
    return [
        path.stem + GPU_REALTIME_SUFFIX
        for path in model_files(scale)
        if path.stem.endswith("_fp16") and is_compact_model(path.stem)
    ]
