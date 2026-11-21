import threading

import webview
from PIL import Image

from core.services.video_stream import VideoStreamServer
from core.application_modules.media import MediaModule
from core.application_modules.shared import SLIDER_DEFAULTS
from core.application_modules.video import VideoModule
from core.application_modules.operations import OperationsModule
from core.managers import ModelManager, EffectsManager

_native_window = None


class WebApp(MediaModule, VideoModule, OperationsModule, ModelManager, EffectsManager):
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
        OperationsModule.__init__(self)

    def _bind_window(self, window):
        global _native_window
        _native_window = window

    @staticmethod
    def _get_native_window():
        return _native_window

    def _current(self):
        return next((item for item in self._entries if item["id"] == self._current_id), None)

    def _default_settings(self):
        models = self.models_for_factor(2)
        return {
            "effects": {**SLIDER_DEFAULTS, "Inversion": False},
            "enhancement": {
                "factor": 2,
                "keep_size": False,
                "face_restoration": False,
                "model": models[0] if models else "",
            },
        }

    def _models_for_factor(self, factor):
        return self.models_for_factor(factor)

    def _realtime_model_factors(self):
        return self.realtime_model_factors()

    def _realtime_models(self):
        return self.realtime_models()

    def _realtime_models_for_factor(self, factor):
        return self.realtime_models_for_factor(factor)

    def _realtime_output_options(self, entry):
        return self.realtime_output_options(entry)

    def _video_models_for_factor(self, factor, entry=None):
        return self.video_models_for_factor(factor, entry)

    def _video_output_options(self, entry):
        return self.video_output_options(entry)

    def _apply_effects(self, image, settings):
        return self.apply_effects(image, settings)

    def _image_url(self, image):
        return self.image_to_url(image)

    def _video_preview_url(self, image):
        return self.video_preview_url(image)

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
