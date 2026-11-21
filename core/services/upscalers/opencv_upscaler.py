"""OpenCV-based real-time upscaler."""

import re
import cv2


class _RealtimeUpscaler:
    def __init__(self, model_path):
        match = re.match(r"(?P<algorithm>.+)_x(?P<scale>[248])$", model_path.stem, re.IGNORECASE)
        if not match:
            raise ValueError(f"Unsupported real-time model name: {model_path.name}")
        if not hasattr(cv2, "dnn_superres"):
            raise RuntimeError("OpenCV was built without dnn_superres support.")
        self._upscaler = cv2.dnn_superres.DnnSuperResImpl_create()
        self._upscaler.readModel(str(model_path))
        algorithm = match.group("algorithm").split("-", 1)[0].lower()
        self._upscaler.setModel(algorithm, int(match.group("scale")))

    def enhance(self, frame):
        return self._upscaler.upsample(frame)
