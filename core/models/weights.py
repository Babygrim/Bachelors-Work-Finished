from importlib.util import find_spec
from pathlib import Path

from core.config.constants import ROOT_DIR

BACKEND_DIRECTML = "DirectML"
BACKEND_NCNN = "ncnn Vulkan"
_BACKEND_SUFFIX = " ({})"


def weights_directory():
    return Path(ROOT_DIR, "weights")


def ncnn_directory():
    return weights_directory() / "ncnn"


def model_files(factor):
    weights = weights_directory()
    if not weights.is_dir():
        return []
    prefix = f"{int(factor)}x-"
    return sorted(
        path for path in weights.rglob("*.onnx")
        if path.name.startswith(prefix)
    )


def ncnn_model_files(factor=None):
    """ncnn models (`.param` + `.bin` pairs in weights/ncnn); empty when ncnn isn't installed."""
    folder = ncnn_directory()
    if not folder.is_dir() or find_spec("ncnn") is None:
        return []
    prefix = f"{int(factor)}x-" if factor is not None else ""
    return sorted(
        path for path in folder.glob("*.param")
        if path.name.startswith(prefix) and path.with_suffix(".bin").is_file()
    )


def model_name(path):
    return path.stem


def model_label(name, backend):
    return name + _BACKEND_SUFFIX.format(backend)


def split_model_label(label):
    """Split 'name (Backend)' into (name, backend); backend is None for a bare name."""
    for backend in (BACKEND_DIRECTML, BACKEND_NCNN):
        suffix = _BACKEND_SUFFIX.format(backend)
        if label.endswith(suffix):
            return label[:-len(suffix)], backend
    return label, None


def models_for_factor(factor):
    onnx_labels = sorted({
        model_label(model_name(path), BACKEND_DIRECTML)
        for path in model_files(factor)
    })
    ncnn_labels = sorted({
        model_label(model_name(path), BACKEND_NCNN)
        for path in ncnn_model_files(factor)
    })
    return onnx_labels + ncnn_labels


def resolve_model(label, factor=None):
    """Map a UI model label to (backend, weight path); None when no weights match."""
    name, backend = split_model_label(label)
    if backend == BACKEND_NCNN:
        for path in ncnn_model_files(factor):
            if model_name(path) == name:
                return BACKEND_NCNN, path
        return None
    path = find_model(name, factor)
    return (BACKEND_DIRECTML, path) if path is not None else None


def find_model(model, factor=None):
    weights = weights_directory()
    candidates = []
    if factor is not None:
        candidates.extend(
            path for path in model_files(factor)
            if model_name(path) == model
        )
    if not candidates:
        candidates = [
            path for path in weights.rglob("*.onnx")
            if model_name(path) == model
        ] if weights.is_dir() else []
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda path: (not path.stem.endswith("_fp16"), str(path)),
    )[0]
