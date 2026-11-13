import base64
import io
import re
import threading
from pathlib import Path

import webview
from PIL import Image, ImageEnhance, ImageFilter

from core.config.constants import ROOT_DIR
from core.processing import effects as img_effects
from core.models.weights import models_for_factor
from core.services.video_stream import VideoStreamServer
from core.application_modules.media import MediaModule
from core.application_modules.shared import SLIDER_DEFAULTS
from core.application_modules.video import VideoModule
from core.application_modules.operations import OperationsModule

_native_window = None


class WebApp(MediaModule, VideoModule, OperationsModule):
    def __init__(self):
        self._lock = threading.RLock()
        self._entries = []
        self._current_id = None
        self._pending_image_path = None
        self._video_stream = VideoStreamServer()
        self._module = "Image_Effects"
        self._revision = 0
        self._preview_revision = 0
        self._preview_delivery_revision = 0
        self._preview_url = None
        self._preview_worker_running = False
        self._history_revision = 0
        self._message = None
        self._job = {
            "running": False,
            "progress": 0,
            "status": "",
            "stage": "",
            "current": 0,
            "total": 0,
            "unit": "tile",
            "error": None,
            "processing_fps": 0.0,
            "processing_device": None,
            "ram_bytes": None,
            "gpu_memory_bytes": None,
        }
        self._job_thread = None
        self._cancel_event = None
        self._process = None

    def _bind_window(self, window):
        global _native_window
        _native_window = window

    @staticmethod
    def _get_native_window():
        return _native_window

    def _current(self):
        return next((item for item in self._entries if item["id"] == self._current_id), None)

    def _default_settings(self):
        models = self._models_for_factor(2)
        return {
            "effects": {**SLIDER_DEFAULTS, "Inversion": False},
            "enhancement": {
                "factor": 2,
                "keep_size": False,
                "face_restoration": False,
                "model": models[0] if models else "",
            },
        }

    @staticmethod
    def _models_for_factor(factor):
        return models_for_factor(factor)

    @staticmethod
    def _realtime_model_factors():
        realtime_weights = Path(ROOT_DIR, "weights", "realtime")
        if not realtime_weights.is_dir():
            return set()
        factors = set()
        for path in realtime_weights.iterdir():
            match = re.search(r"_x(2|4|8)\.(?:pb|onnx)$", path.name, re.IGNORECASE)
            if match:
                factors.add(int(match.group(1)))
        return factors

    @staticmethod
    def _realtime_models():
        realtime_weights = Path(ROOT_DIR, "weights", "realtime")
        if not realtime_weights.is_dir():
            return []
        return sorted({
            path.stem
            for path in realtime_weights.iterdir()
            if path.suffix.lower() in (".pb", ".onnx")
        })

    @classmethod
    def _video_models_for_factor(cls, factor):
        models = cls._models_for_factor(factor)
        if models:
            return models
        if int(factor) in cls._realtime_model_factors():
            return ["CPU resize and sharpen"]
        return []

    @classmethod
    def _video_output_options(cls, entry):
        source_width, source_height = entry["original_size"]
        factors = [
            factor for factor in (2, 4, 8)
            if cls._models_for_factor(factor) or factor in cls._realtime_model_factors()
        ]
        if not factors:
            factors = [1]
        return [
            {
                "factor": factor,
                "width": source_width * factor,
                "height": source_height * factor,
                "label": f"{source_width * factor} × {source_height * factor}",
            }
            for factor in factors
        ]

    def _apply_effects(self, image, settings):
        settings = settings["effects"]
        result = image.copy()
        for name, function in (
            ("Brightness", ImageEnhance.Brightness),
            ("Color", ImageEnhance.Color),
            ("Contrast", ImageEnhance.Contrast),
            ("Sharpness", ImageEnhance.Sharpness),
        ):
            result = function(result).enhance(float(settings[name]) / 100)
        blur = float(settings["Blur"]) / 100
        if blur:
            result = result.filter(ImageFilter.GaussianBlur(blur))
        if settings["Inversion"]:
            result = img_effects.invert_image_colors(result, None)
        return result

    @staticmethod
    def _image_url(image):
        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=92, method=4)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/webp;base64,{encoded}"

    @staticmethod
    def _video_preview_url(image):
        preview = image.copy()
        preview.thumbnail((960, 720), Image.Resampling.BILINEAR)
        buffer = io.BytesIO()
        preview.save(buffer, format="WEBP", quality=72, method=0)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/webp;base64,{encoded}"

    def _touch(self, preview=False, immediate=False):
        self._revision += 1
        if preview:
            self._preview_revision += 1
            self._schedule_preview(immediate=immediate)

    def _schedule_preview(self, immediate=False):
        with self._lock:
            entry = self._current()
            if not entry:
                self._preview_url = None
                self._preview_delivery_revision += 1
                return

            if entry["kind"] == "video":
                self._preview_url = self._video_preview_url(entry["image"])
                self._preview_delivery_revision += 1
                return

            if immediate:
                preview_image = self._apply_effects(
                    entry["thumbnail_image"], entry["settings"]
                )
                self._preview_url = self._image_url(preview_image)
                self._preview_delivery_revision += 1
            if self._preview_worker_running:
                return
            self._preview_worker_running = True

        threading.Thread(target=self._render_preview_worker, daemon=True).start()

    def _render_preview_worker(self):
        while True:
            with self._lock:
                entry = self._current()
                if not entry:
                    self._preview_worker_running = False
                    return
                entry_id = entry["id"]
                revision = self._preview_revision
                image = entry["image"].copy()
                settings = {
                    "effects": dict(entry["settings"]["effects"]),
                    "enhancement": dict(entry["settings"]["enhancement"]),
                }

            try:
                image = self._apply_effects(image, settings)
                image.thumbnail((1800, 1400), Image.Resampling.LANCZOS)
                preview_url = self._image_url(image)
            except Exception as error:
                with self._lock:
                    if revision == self._preview_revision and entry_id == self._current_id:
                        self._message = {"type": "error", "text": f"Preview failed: {error}"}
                        self._revision += 1
                        self._preview_worker_running = False
                        return
                continue

            with self._lock:
                if revision == self._preview_revision and entry_id == self._current_id:
                    self._preview_url = preview_url
                    self._preview_delivery_revision += 1
                    self._preview_worker_running = False
                    return
