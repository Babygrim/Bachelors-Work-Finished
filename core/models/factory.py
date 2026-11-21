from core.models.weights import BACKEND_NCNN, resolve_model


def create_upscaler(model, factor, tile, tile_pad, num_threads=2):
    """Build the upscaler (ONNX/DirectML or ncnn/Vulkan) selected by a UI model label."""
    resolved = resolve_model(model, factor)
    if resolved is None:
        raise FileNotFoundError(f"Weight file not found for model: {model}")
    backend, path = resolved

    if backend == BACKEND_NCNN:
        from core.models.ncnn_realesrganer import NcnnRealESRGANer

        return NcnnRealESRGANer(
            scale=int(factor),
            param_path=str(path),
            tile=tile,
            tile_pad=tile_pad,
            num_threads=num_threads,
        )

    from core.models.onnx_realesrganer import OnnxRealESRGANer

    return OnnxRealESRGANer(
        scale=int(factor),
        pth_path=str(path),
        tile=tile,
        tile_pad=tile_pad,
        num_threads=num_threads,
    )


def device_label(upscaler):
    device = upscaler.device
    if "DmlExecutionProvider" in device:
        return "GPU (DirectML)"
    if "NcnnVulkan" in device:
        return "GPU (ncnn Vulkan)"
    return "CPU"
