"""Fast image-effect preview (brightness, colour, contrast, sharpness, blur, inversion).

The full-quality result (export, upscale input) is still produced by PIL's ImageEnhance in
EffectsManager.apply_effects; this module renders the interactive preview from a downscaled
proxy with the same maths. The pointwise effects and the 3x3 sharpness filter run in a small
ONNX graph on the GPU (DirectML); blur (variable radius) and a CPU fallback use OpenCV/numpy.
"""

import threading

import cv2
import numpy as np
import onnx
import onnxruntime as ort
from onnx import TensorProto, helper, numpy_helper

from core.services.app_logging import log_event

_PARAMS = ("brightness", "color", "contrast", "sharpness", "invert")
_GRAY_WEIGHTS = np.array([0.299, 0.587, 0.114], dtype=np.float32)


def _build_effects_model():
    nodes, initializers = [], []

    def const(name, array):
        initializers.append(numpy_helper.from_array(np.asarray(array), name))

    def node(op, inputs, outputs, **attrs):
        nodes.append(helper.make_node(op, inputs, outputs, **attrs))

    const("w_gray", _GRAY_WEIGHTS.reshape(1, 3, 1, 1))
    const("k_smooth", np.repeat((np.array([[1, 1, 1], [1, 5, 1], [1, 1, 1]], np.float32) / 13).reshape(1, 1, 3, 3), 3, axis=0))
    for name, value in (("zero", 0.0), ("one", 1.0), ("two", 2.0), ("k255", 255.0)):
        const(name, np.float32(value))
    const("pads", np.array([0, 0, 1, 1, 0, 0, 1, 1], dtype=np.int64))

    node("Cast", ["frame"], ["f32"], to=TensorProto.FLOAT)
    node("Transpose", ["f32"], ["nchw"], perm=[0, 3, 1, 2])
    node("Div", ["nchw", "k255"], ["x"])
    # Brightness
    node("Mul", ["x", "brightness"], ["bright_raw"])
    node("Clip", ["bright_raw", "zero", "one"], ["bright"])
    # Color: blend with the grayscale image
    node("Conv", ["bright", "w_gray"], ["gray"])
    node("Sub", ["bright", "gray"], ["color_delta"])
    node("Mul", ["color_delta", "color"], ["color_scaled"])
    node("Add", ["gray", "color_scaled"], ["color_raw"])
    node("Clip", ["color_raw", "zero", "one"], ["colored"])
    # Contrast: blend with the mean gray level
    node("Conv", ["colored", "w_gray"], ["gray2"])
    node("ReduceMean", ["gray2"], ["mean"], keepdims=1)
    node("Sub", ["colored", "mean"], ["contrast_delta"])
    node("Mul", ["contrast_delta", "contrast"], ["contrast_scaled"])
    node("Add", ["mean", "contrast_scaled"], ["contrast_raw"])
    node("Clip", ["contrast_raw", "zero", "one"], ["contrasted"])
    # Sharpness: blend with PIL's SMOOTH filter (edge pixels replicated)
    node("Pad", ["contrasted", "pads"], ["padded"], mode="edge")
    node("Conv", ["padded", "k_smooth"], ["smooth"], group=3)
    node("Sub", ["contrasted", "smooth"], ["sharp_delta"])
    node("Mul", ["sharp_delta", "sharpness"], ["sharp_scaled"])
    node("Add", ["smooth", "sharp_scaled"], ["sharp_raw"])
    node("Clip", ["sharp_raw", "zero", "one"], ["sharpened"])
    # Inversion: invert in {0, 1} -> x * (1 - 2 * invert) + invert
    node("Mul", ["invert", "two"], ["invert2"])
    node("Sub", ["one", "invert2"], ["invert_sign"])
    node("Mul", ["sharpened", "invert_sign"], ["inverted_raw"])
    node("Add", ["inverted_raw", "invert"], ["inverted"])
    node("Mul", ["inverted", "k255"], ["scaled"])
    node("Round", ["scaled"], ["rounded"])
    node("Cast", ["rounded"], ["u8"], to=TensorProto.UINT8)
    node("Transpose", ["u8"], ["out"], perm=[0, 2, 3, 1])

    inputs = [helper.make_tensor_value_info("frame", TensorProto.UINT8, [1, "height", "width", 3])]
    inputs += [helper.make_tensor_value_info(name, TensorProto.FLOAT, [1]) for name in _PARAMS]
    outputs = [helper.make_tensor_value_info("out", TensorProto.UINT8, [1, "height", "width", 3])]
    graph = helper.make_graph(nodes, "preview_effects", inputs, outputs, initializers)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model.SerializeToString()


def _scalar(value):
    return np.array([value], dtype=np.float32)


class PreviewEffects:
    """Renders the effect preview on the GPU when possible, otherwise on the CPU."""

    def __init__(self, use_gpu=True):
        self._lock = threading.Lock()
        self._session = None
        self._gpu_failed = not use_gpu
        self.device = "CPU"

    def _gpu_session(self):
        if self._gpu_failed:
            return None
        if self._session is None:
            try:
                session = ort.InferenceSession(
                    _build_effects_model(),
                    providers=["DmlExecutionProvider", "CPUExecutionProvider"],
                )
                if session.get_providers()[0] != "DmlExecutionProvider":
                    raise RuntimeError("DirectML is not available")
                self._session = session
                self.device = "GPU (DirectML)"
            except Exception as error:
                self._gpu_failed = True
                log_event("preview_effects_gpu_unavailable", error=str(error))
                return None
        return self._session

    def apply(self, rgb, effects, blur_scale=1.0):
        """Apply the effect settings to an HxWx3 uint8 RGB array and return the new array.

        `blur_scale` converts the blur radius (set for the full-size image) to this array's size.
        """
        params = {
            "brightness": _scalar(float(effects["Brightness"]) / 100),
            "color": _scalar(float(effects["Color"]) / 100),
            "contrast": _scalar(float(effects["Contrast"]) / 100),
            "sharpness": _scalar(float(effects["Sharpness"]) / 100),
            "invert": _scalar(1.0 if effects["Inversion"] else 0.0),
        }
        result = None
        with self._lock:
            session = self._gpu_session()
            if session is not None:
                try:
                    result = session.run(None, {"frame": rgb[None], **params})[0][0]
                except Exception as error:
                    self._gpu_failed = True
                    self._session = None
                    self.device = "CPU"
                    log_event("preview_effects_gpu_failed", error=str(error))
        if result is None:
            result = self._apply_cpu(rgb, params)
        blur = float(effects["Blur"]) / 100 * blur_scale
        if blur > 0:
            result = cv2.GaussianBlur(result, (0, 0), blur)
        return result

    @staticmethod
    def _apply_cpu(rgb, params):
        x = rgb.astype(np.float32) / 255
        x = np.clip(x * params["brightness"][0], 0, 1)
        gray = (x @ _GRAY_WEIGHTS)[..., None]
        x = np.clip(gray + (x - gray) * params["color"][0], 0, 1)
        mean = (x @ _GRAY_WEIGHTS).mean()
        x = np.clip(mean + (x - mean) * params["contrast"][0], 0, 1)
        smooth = cv2.filter2D(
            x, -1, np.array([[1, 1, 1], [1, 5, 1], [1, 1, 1]], np.float32) / 13,
            borderType=cv2.BORDER_REPLICATE,
        )
        x = np.clip(smooth + (x - smooth) * params["sharpness"][0], 0, 1)
        if params["invert"][0]:
            x = 1 - x
        return np.rint(x * 255).astype(np.uint8)
