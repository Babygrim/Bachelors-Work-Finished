import base64
import io
import multiprocessing
import threading
import uuid
from pathlib import Path
from queue import Empty

import webview
from PIL import Image, ImageEnhance, ImageFilter

from core.app_logging import log_toast
from core.constants import ROOT_DIR
from core.processing import effects as img_effects
from core.processing import resolution as img_resolution

_native_window = None


SLIDER_DEFAULTS = {
    "Brightness": 100,
    "Color": 100,
    "Contrast": 100,
    "Sharpness": 100,
    "Blur": 0,
}
SLIDER_RANGES = {
    "Brightness": (0, 500),
    "Color": (0, 500),
    "Contrast": (0, 500),
    "Sharpness": (-500, 500),
    "Blur": (0, 1000),
}


def _run_image_operation(function, image, arguments, result_queue, progress_queue):
    try:
        result_queue.put((True, function(image, progress_queue, *arguments)))
    except Exception as error:
        result_queue.put((False, str(error)))


class WebApp:
    def __init__(self):
        self._lock = threading.RLock()
        self._entries = []
        self._current_id = None
        self._pending_image_path = None
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
        }
        self._job_thread = None
        self._cancel_event = None
        self._process = None

    def _bind_window(self, window):
        global _native_window
        _native_window = window

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
        weights = Path(ROOT_DIR, "weights")
        if not weights.is_dir():
            return []
        return sorted({path.stem for path in weights.glob(f"{int(factor)}x-*.onnx")})

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

    def _new_entry(
        self,
        image,
        name="image",
        extension="png",
        original_size=None,
        full_resolution=True,
    ):
        entry = {
            "id": uuid.uuid4().hex[:12],
            "image": image.convert("RGBA"),
            "original_size": original_size or image.size,
            "image_loading": not full_resolution,
            "name": name,
            "extension": extension or "png",
            "settings": self._default_settings(),
            "scale": 1.0,
        }
        thumbnail = entry["image"].copy()
        thumbnail.thumbnail((150, 100), Image.Resampling.LANCZOS)
        entry["thumbnail_image"] = thumbnail
        entry["thumbnail"] = self._image_url(thumbnail)
        self._entries.append(entry)
        self._current_id = entry["id"]
        self._history_revision += 1
        self._touch(preview=True, immediate=True)

    def get_state(self, previous_revision=None, previous_history_revision=None):
        with self._lock:
            entry = self._current()
            state = {
                "module": self._module,
                "revision": self._revision,
                "image_revision": self._preview_delivery_revision,
                "history_revision": self._history_revision,
                "current_id": self._current_id,
                "has_image": entry is not None,
                "image_loading": bool(entry and entry["image_loading"]),
                "preview_loading": self._preview_worker_running,
                "image": None,
                "image_size": None,
                "image_name": None,
                "settings": entry["settings"] if entry else self._default_settings(),
                "scale": entry["scale"] if entry else 1.0,
                "models": self._models_for_factor(entry["settings"]["enhancement"]["factor"])
                if entry else self._models_for_factor(2),
                "history": [
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "size": item["original_size"],
                        "thumbnail": item["thumbnail"],
                    }
                    for item in self._entries
                ] if previous_history_revision != self._history_revision else None,
                "job": dict(self._job),
                "message": self._message,
            }
            if entry:
                state["image_size"] = entry["original_size"]
                state["image_name"] = entry["name"]
                if previous_revision != self._preview_delivery_revision:
                    state["image"] = self._preview_url
            self._message = None
            return state

    def open_image(self):
        current = self._current()
        if not _native_window or self._job["running"] or (current and current["image_loading"]):
            return False
        selected = _native_window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Image files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff)",),
        )
        if not selected:
            return False
        self._pending_image_path = selected[0]
        return True

    def load_selected_image(self):
        path = self._pending_image_path
        self._pending_image_path = None
        if not path or self._job["running"]:
            return False
        path = Path(path)
        try:
            with Image.open(path) as source:
                original_size = source.size
                source.thumbnail((1800, 1400), Image.Resampling.LANCZOS)
                preview = source.convert("RGBA")
            with self._lock:
                self._new_entry(
                    preview,
                    path.stem,
                    path.suffix.lstrip("."),
                    original_size=original_size,
                    full_resolution=False,
                )
                self._module = "Image_Effects"
                entry_id = self._current_id
            threading.Thread(
                target=self._load_full_resolution_image,
                args=(entry_id, path),
                daemon=True,
            ).start()
            return True
        except Exception as error:
            self._set_message("error", f"Could not open image: {error}")
            return False

    def _load_full_resolution_image(self, entry_id, path):
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
        except Exception as error:
            with self._lock:
                self._entries = [entry for entry in self._entries if entry["id"] != entry_id]
                self._current_id = self._entries[-1]["id"] if self._entries else None
                self._history_revision += 1
                self._message = {"type": "error", "text": f"Could not load full image: {error}"}
                self._touch(preview=True, immediate=True)
            return

        with self._lock:
            entry = next((item for item in self._entries if item["id"] == entry_id), None)
            if entry is None:
                return
            entry["image"] = image
            entry["image_loading"] = False
            self._touch(preview=True)

    def save_image(self):
        entry = self._current()
        if not entry or entry["image_loading"] or self._job["running"] or not _native_window:
            return False
        extension = entry["extension"] or "png"
        selected = _native_window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=f"{entry['name']}_{entry['id']}.{extension}",
            file_types=("Image files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff)",),
        )
        if not selected:
            return False
        image = entry["image"].copy()
        settings = {
            "effects": dict(entry["settings"]["effects"]),
            "enhancement": dict(entry["settings"]["enhancement"]),
        }
        with self._lock:
            self._job = {
                "running": True,
                "progress": 0,
                "status": "Exporting image",
                "stage": "export",
                "current": 0,
                "total": 0,
                "unit": "",
                "kind": "export",
                "error": None,
            }
            self._touch()
        self._job_thread = threading.Thread(
            target=self._export_image_worker,
            args=(image, settings, selected),
            daemon=True,
        )
        self._job_thread.start()
        return True

    def _export_image_worker(self, image, settings, path):
        try:
            image = self._apply_effects(image, settings)
            if image.mode == "RGBA" and Path(path).suffix.lower() in (".jpg", ".jpeg"):
                image = image.convert("RGB")
            image.save(path)
            message = {"type": "success", "text": "Image exported successfully."}
            status = "Complete"
        except Exception as error:
            message = {"type": "error", "text": f"Could not save image: {error}"}
            status = "Failed"
        with self._lock:
            self._job = {
                "running": False,
                "progress": 100 if status == "Complete" else 0,
                "status": status,
                "stage": "export",
                "current": 0,
                "total": 0,
                "unit": "",
                "kind": "export",
                "error": None if status == "Complete" else message["text"],
            }
            self._message = message
            self._touch()

    def set_module(self, module):
        if module not in ("Image_Effects", "Resolution_Enhancement"):
            return False
        with self._lock:
            self._module = module
            self._touch()
        return True

    def set_setting(self, key, value):
        with self._lock:
            entry = self._current()
            if not entry or entry["image_loading"] or self._job["running"]:
                return False
            if key in SLIDER_RANGES:
                minimum, maximum = SLIDER_RANGES[key]
                entry["settings"]["effects"][key] = max(minimum, min(maximum, int(value)))
            elif key == "Inversion":
                entry["settings"]["effects"][key] = bool(value)
            elif key == "factor":
                factor = int(value)
                if factor not in (2, 4, 8):
                    return False
                enhancement = entry["settings"]["enhancement"]
                enhancement["factor"] = factor
                models = self._models_for_factor(factor)
                enhancement["model"] = models[0] if models else ""
            elif key == "model":
                choices = self._models_for_factor(entry["settings"]["enhancement"]["factor"])
                if value not in choices:
                    return False
                entry["settings"]["enhancement"][key] = value
            elif key in ("keep_size", "face_restoration"):
                entry["settings"]["enhancement"][key] = bool(value)
            else:
                return False
            self._touch(preview=key in SLIDER_RANGES or key == "Inversion")
        return True

    def reset_module(self):
        with self._lock:
            entry = self._current()
            if not entry or entry["image_loading"] or self._job["running"]:
                return False
            if self._module == "Image_Effects":
                entry["settings"]["effects"] = {**SLIDER_DEFAULTS, "Inversion": False}
                self._touch(preview=True)
            else:
                entry["settings"]["enhancement"] = self._default_settings()["enhancement"]
                self._touch()
        return True

    def select_history(self, image_id):
        with self._lock:
            selected = next((item for item in self._entries if item["id"] == image_id), None)
            if self._job["running"] or not selected or selected["image_loading"]:
                return False
            self._current_id = image_id
            self._touch(preview=True, immediate=True)
        return True

    def remove_image(self):
        with self._lock:
            entry = self._current()
            if self._job["running"] or not entry or entry["image_loading"]:
                return False
            self._entries = [item for item in self._entries if item["id"] != self._current_id]
            self._current_id = self._entries[-1]["id"] if self._entries else None
            self._history_revision += 1
            self._touch(preview=True, immediate=True)
        return True

    def set_scale(self, scale):
        with self._lock:
            entry = self._current()
            if not entry:
                return False
            entry["scale"] = max(0.1, min(5.0, float(scale)))
            self._touch()
        return True

    def crop_image(self, bounds):
        with self._lock:
            entry = self._current()
            if not entry or entry["image_loading"] or self._job["running"]:
                return False
            image = self._apply_effects(entry["image"], entry["settings"])
            left, top, right, bottom = (float(value) for value in bounds)
            width, height = image.size
            box = (
                max(0, min(width, int(left * width))),
                max(0, min(height, int(top * height))),
                max(0, min(width, int(right * width))),
                max(0, min(height, int(bottom * height))),
            )
            if box[0] >= box[2] or box[1] >= box[3]:
                return False
            cropped = image.crop(box)
            self._new_entry(cropped, entry["name"], entry["extension"])
            return True

    def start_operation(self, operation):
        with self._lock:
            entry = self._current()
            if not entry or entry["image_loading"] or self._job["running"]:
                return False
            image = self._apply_effects(entry["image"], entry["settings"])
            if operation == "denoise":
                function = img_effects.denoise_image
                arguments = []
            elif operation == "upscale":
                options = entry["settings"]["enhancement"]
                if not options["model"]:
                    self._message = {"type": "error", "text": "No ONNX model is available for this scale."}
                    return False
                function = img_resolution.upscale_image
                arguments = [
                    options["keep_size"],
                    options["model"],
                    options["face_restoration"],
                    options["factor"],
                ]
            else:
                return False
            self._job = {
                "running": True,
                "progress": 0,
                "status": "Starting",
                "stage": "",
                "current": 0,
                "total": 0,
                "unit": "tile",
                "kind": operation,
                "error": None,
            }
            self._cancel_event = threading.Event()
            self._touch()
            self._job_thread = threading.Thread(
                target=self._process_operation,
                args=(function, image, arguments, self._cancel_event),
                daemon=True,
            )
            self._job_thread.start()
        return True

    def _process_operation(self, function, image, arguments, cancel_event):
        result_queue = multiprocessing.Queue()
        progress_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_run_image_operation,
            args=(function, image, arguments, result_queue, progress_queue),
            daemon=True,
        )
        with self._lock:
            self._process = process
            self._job["status"] = "Processing"
        try:
            process.start()
            while True:
                if cancel_event.is_set():
                    process.terminate()
                    process.join()
                    return
                try:
                    progress = progress_queue.get(timeout=0.05)
                    with self._lock:
                        if isinstance(progress, dict):
                            self._job.update(
                                stage=str(progress.get("stage", "")),
                                current=int(progress.get("current", 0)),
                                total=int(progress.get("total", 0)),
                                unit=str(progress.get("unit", "tile")),
                                progress=max(0, min(100, int(progress.get("percent", 0)))),
                            )
                        elif isinstance(progress, (int, float)):
                            self._job["progress"] = max(0, min(100, int(progress)))
                except Empty:
                    pass
                try:
                    succeeded, result = result_queue.get(timeout=0.1)
                except Empty:
                    if process.is_alive():
                        continue
                    process.join()
                    try:
                        succeeded, result = result_queue.get(timeout=1)
                    except Empty as error:
                        raise RuntimeError(
                            f"Image process exited with code {process.exitcode} without a result."
                        ) from error
                if not succeeded:
                    raise RuntimeError(result)
                with self._lock:
                    current = self._current()
                    name = current["name"] if current else "image"
                    extension = current["extension"] if current else "png"
                    kind = self._job.get("kind", "processing")
                    self._new_entry(result, name, extension)
                    self._job = {
                        "running": False,
                        "progress": 100,
                        "status": "Complete",
                        "kind": kind,
                        "error": None,
                    }
                return
        except Exception as error:
            with self._lock:
                kind = self._job.get("kind", "processing")
                self._job = {
                    "running": False,
                    "progress": 0,
                    "status": "Failed",
                    "kind": kind,
                    "error": str(error),
                }
                self._message = {"type": "error", "text": str(error)}
                self._touch()
        finally:
            if process.pid is not None:
                if process.is_alive():
                    process.join(timeout=0.2)
                else:
                    process.join()
            with self._lock:
                self._process = None
                if cancel_event.is_set():
                    self._job = {"running": False, "progress": 0, "status": "Cancelled", "error": None}
                    self._touch()
            result_queue.close()
            progress_queue.close()

    def cancel_operation(self):
        with self._lock:
            if not self._job["running"] or not self._cancel_event:
                return False
            self._cancel_event.set()
            if self._process and self._process.is_alive():
                self._process.terminate()
            return True

    def dismiss_job(self):
        with self._lock:
            if not self._job["running"]:
                self._job = {"running": False, "progress": 0, "status": "", "error": None}
                self._touch()
        return True

    def _set_message(self, kind, text):
        with self._lock:
            self._message = {"type": kind, "text": text}
            self._touch()

    def log_toast(self, kind, text):
        log_toast(kind, text)
        return True