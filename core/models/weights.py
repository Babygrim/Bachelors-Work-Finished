from pathlib import Path

from core.config.constants import ROOT_DIR


def weights_directory():
    return Path(ROOT_DIR, "weights")


def model_files(factor):
    weights = weights_directory()
    if not weights.is_dir():
        return []
    prefix = f"{int(factor)}x-"
    return sorted(
        path for path in weights.rglob("*.onnx")
        if path.name.startswith(prefix)
    )


def model_name(path):
    return path.stem


def models_for_factor(factor):
    return sorted({model_name(path) for path in model_files(factor)})


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
