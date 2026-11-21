"""Human-readable facts about the upscaling models shown in the UI.

Parameter counts are read from the weight files themselves; the architecture / use / training
notes come from the catalog below. Models that are not in the catalog get an architecture
guess from their parameter count and an explicit "not documented" note.
"""

import re
from functools import lru_cache

import onnx

from core.models.weights import (
    BACKEND_NCNN,
    resolve_model,
    split_model_label,
)
from core.services.upscalers.gpu_realtime import GPU_REALTIME_SUFFIX as REALTIME_GPU_SUFFIX

_PRECISION_SUFFIX = re.compile(r"_(fp16|fp32)$", re.IGNORECASE)
_SCALE_PREFIX = re.compile(r"^\d+x[-_]", re.IGNORECASE)

# Sustained fp16 throughput measured for realesr-general-v3 on an RX 6700 XT (input Mpx/s).
_BASELINE_PARAMS = 1_200_000
_BASELINE_MPX_PER_SECOND = 5.3

_BSD = "BSD-3-Clause"

# key: lowercase file name without scale prefix and precision suffix.
_CATALOG = {
    "realesr-general-v3": {
        "architecture": "SRVGGNetCompact (32 conv layers, 64 channels)",
        "used_for": "General real-world photos and video; fast, also removes noise and compression artefacts.",
        "trained_on": "Real-ESRGAN pipeline: high-resolution photo datasets degraded synthetically "
                      "(blur, noise, resize, JPEG/video compression).",
        "license": _BSD,
    },
    "realesr-animevideov3": {
        "architecture": "SRVGGNetCompact (16 conv layers, 64 channels)",
        "used_for": "Anime and cartoon video; very fast, built for per-frame video upscaling.",
        "trained_on": "Anime video frames degraded with the Real-ESRGAN synthetic pipeline.",
        "license": _BSD,
    },
    "realesrganv2-animevideo-xsx2": {
        "architecture": "SRVGGNetCompact (16 conv layers, 64 channels, 'xs' variant)",
        "used_for": "Anime and cartoon video at 2x; the lightest official Real-ESRGAN model.",
        "trained_on": "Anime video frames degraded with the Real-ESRGAN synthetic pipeline.",
        "license": _BSD,
    },
    "realesrgan_anime_6b": {
        "architecture": "RRDBNet (6 residual-in-residual dense blocks)",
        "used_for": "Anime illustrations and still frames; heavier but sharper than the video models.",
        "trained_on": "Anime images degraded with the Real-ESRGAN synthetic pipeline.",
        "license": _BSD,
    },
    "nomosuni-compact-otf-medium": {
        "architecture": "SRVGGNetCompact (16 conv layers, 64 channels)",
        "used_for": "Fast universal photo/video upscaling that also handles medium noise, blur and JPEG damage.",
        "trained_on": "Phhofm's Nomos-Uni dataset with Real-ESRGAN on-the-fly degradations (medium strength).",
        "license": "CC-BY-4.0",
    },
    "nomosuni-compact-multijpg": {
        "architecture": "SRVGGNetCompact (16 conv layers, 64 channels)",
        "used_for": "Fast universal upscaling of compressed (JPEG-like) sources; keeps more detail, less denoising.",
        "trained_on": "Phhofm's Nomos-Uni dataset with JPEG degradation (quality down to 40) and mixed "
                      "downscaling (bicubic, bilinear, box, nearest, lanczos).",
        "license": "CC-BY-4.0",
    },
    "denoise_realplksr_otf": {
        "architecture": "RealPLKSR (large-kernel super-resolution network), 1x",
        "used_for": "Denoising / compression clean-up without changing the resolution.",
        "trained_on": "Not documented in this project; the name indicates on-the-fly (Real-ESRGAN style) degradations.",
        "license": None,
        "flops_factor": 1.0,
    },
    "real-general": {
        "architecture": "RRDBNet (ESRGAN-style, 23 blocks), inferred from the weights",
        "used_for": "General-purpose photo upscaling (per the file name); highest quality, slow.",
        "trained_on": "Not documented in this project.",
        "license": None,
    },
    "official-general": {
        "architecture": "RRDBNet (ESRGAN-style, 23 blocks), inferred from the weights",
        "used_for": "General-purpose photo upscaling (per the file name); highest quality, slow.",
        "trained_on": "Not documented in this project.",
        "license": None,
    },
    "real-smooth": {
        "architecture": "RRDBNet (ESRGAN-style, 23 blocks), inferred from the weights",
        "used_for": "Smoother, less aggressive upscaling (per the file name); highest quality, slow.",
        "trained_on": "Not documented in this project.",
        "license": None,
    },
    "real-fine-tuned-faces": {
        "architecture": "RRDBNet (ESRGAN-style, 23 blocks), inferred from the weights",
        "used_for": "Photos with faces / portraits (per the file name); highest quality, slow.",
        "trained_on": "Not documented in this project; the name indicates fine-tuning on face images.",
        "license": None,
    },
}

_REALTIME_NOTES = {
    "AMD VideoSR (AMF)": {
        "display": "AMD VideoSR (AMF) (GPU, fixed-function)",
        "architecture": "AMD Video Super Resolution 1.0 (driver-side AMF filter, no weight file)",
        "used_for": "Real-time upscaling of any video to Full HD; the only option that keeps 60 fps at 1080p.",
        "trained_on": "Proprietary; sharpens luma only (this app restores the colour plane from the source).",
        "complexity": "Very light: runs on the GPU's video pipeline at 58+ fps for 1080p output.",
    },
}


def _humanize(count):
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    return f"{count / 1000:.0f}K"


def _weight_class(count):
    if count < 3_000_000:
        return "Light"
    if count < 10_000_000:
        return "Medium"
    return "Heavy"


@lru_cache(maxsize=None)
def _count_parameters(path, modified):
    """Number of weights stored in an ONNX file (initializer elements)."""
    model = onnx.load(path, load_external_data=False)
    total = 0
    for initializer in model.graph.initializer:
        size = 1
        for dim in initializer.dims:
            size *= dim
        total += size
    return total


def _parameter_count(path):
    """Return (parameters, is_estimate, weight_file) for a model file."""
    suffix = path.suffix.lower()
    if suffix == ".onnx":
        return _count_parameters(str(path), path.stat().st_mtime_ns), False, path
    # ncnn stores fp16 weights (2 bytes each) in the .bin; OpenCV .pb files hold fp32 weights.
    if suffix == ".param":
        weights = path.with_suffix(".bin")
        return weights.stat().st_size // 2, True, weights
    return path.stat().st_size // 4, True, path


def _complexity_text(params, scale, flops_factor):
    # Convolution FLOPs per input pixel ~ 2 x parameters x flops_factor (the share of the weights
    # applied at input resolution: 1.0 for compact / plain conv nets; RRDBNet runs its trunk at 1/4
    # resolution for 2x (pixel-unshuffle) and adds output-resolution convs at 4x/8x).
    mflops = 2 * params * flops_factor / 1e6
    relative = params * flops_factor / _BASELINE_PARAMS
    mpx_per_second = _BASELINE_MPX_PER_SECOND / max(relative, 0.01)
    if relative < 0.9:
        tier = "very low"
    elif relative < 2.5:
        tier = "low"
    elif relative < 12:
        tier = "moderate"
    else:
        tier = "high"
    if mpx_per_second >= 8:
        fps = "real-time capable for about 360p sources at 30 fps"
    elif mpx_per_second >= 2:
        fps = "real-time only for very small frames (about 240p), otherwise slower than real time"
    else:
        fps = "offline use only"
    return (
        f"Compute cost {tier}: about {mflops:.1f} MFLOPs per input pixel "
        f"(~{relative:.1f}x realesr-general-v3), roughly {mpx_per_second:.1f} input Mpx/s "
        f"on an RX 6700 XT-class GPU; {fps}."
    )


def _scale_of(stem):
    match = re.match(r"^(\d+)x[-_]", stem, re.IGNORECASE)
    return int(match.group(1)) if match else 1


@lru_cache(maxsize=None)
def describe_model(label):
    """Facts for a model label as used in the UI lists (None for unknown labels)."""
    if label in _REALTIME_NOTES:
        notes = _REALTIME_NOTES[label]
        return {
            "name": label,
            "display": notes["display"],
            "weight_class": "Fixed-function",
            "parameters": None,
            "precision": None,
            "size_bytes": None,
            **{key: notes[key] for key in ("architecture", "used_for", "trained_on", "complexity")},
            "license": None,
        }

    realtime = label.endswith(REALTIME_GPU_SUFFIX)
    if realtime:
        label = label[:-len(REALTIME_GPU_SUFFIX)] + " (DirectML)"
    name, backend = split_model_label(label)
    resolved = resolve_model(label)
    path = resolved[1] if resolved else None
    if path is None:
        return None

    params, estimated, weight_file = _parameter_count(path)
    stem = _PRECISION_SUFFIX.sub("", name)
    precision_match = _PRECISION_SUFFIX.search(name)
    precision = precision_match.group(1).lower() if precision_match else None
    scale = _scale_of(stem)
    key = _SCALE_PREFIX.sub("", stem).lower()
    notes = _CATALOG.get(key)
    compact = params < 3_000_000
    if notes is None:
        notes = {
            "architecture": ("SRVGGNetCompact-style" if compact else "RRDBNet-style")
                            + " network, inferred from the parameter count",
            "used_for": "Not documented in this project.",
            "trained_on": "Not documented in this project.",
            "license": None,
        }
    flops_factor = notes.get("flops_factor")
    if flops_factor is None:
        flops_factor = 1.0 if compact else {1: 0.06, 2: 0.3, 4: 1.1, 8: 1.35}.get(scale, 1.0)
    size = weight_file.stat().st_size
    weight_class = _weight_class(params)
    detail = [weight_class, ("~" if estimated else "") + _humanize(params) + " params"]
    if realtime:
        detail.append("GPU")
    elif backend == BACKEND_NCNN:
        detail.append("ncnn")
    return {
        "name": name,
        "display": f"{name} ({', '.join(detail)})",
        "weight_class": weight_class,
        "parameters": params,
        "parameters_estimated": estimated,
        "precision": precision,
        "size_bytes": size,
        "architecture": notes["architecture"],
        "used_for": notes["used_for"],
        "trained_on": notes["trained_on"],
        "license": notes["license"],
        "complexity": _complexity_text(params, scale, flops_factor),
    }


def warm_model_info():
    """Fill the description cache in the background so the first state request isn't slowed down."""
    from core.models.weights import models_for_factor

    for factor in (1, 2, 4, 8):
        for label in models_for_factor(factor):
            try:
                describe_model(label)
            except Exception:
                pass
