import multiprocessing
import threading
from pathlib import Path
from queue import Empty

from core.processing import effects as img_effects
from core.processing import resolution as img_resolution
from core.services.app_logging import log_event, log_toast
from core.application_modules.shared import SLIDER_DEFAULTS, SLIDER_RANGES


def _run_image_operation(function, image, arguments, result_queue, progress_queue):
    try:
        result_queue.put((True, function(image, progress_queue, *arguments)))
    except Exception as error:
        result_queue.put((False, str(error)))


class OperationsModule:
    """Settings, editing operations, and API telemetry capability."""

    def set_module(self, module):
        with self._lock:
            entry = self._current()
            available = (
                ("Video_Enhancement",)
                if entry and entry["kind"] == "video"
                else ("Image_Effects", "Resolution_Enhancement")
            )
            if module not in available:
                return False
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
                if entry["kind"] == "video" and not any(
                    option["factor"] == factor
                    for option in self._video_output_options(entry)
                ):
                    return False
                enhancement = entry["settings"]["enhancement"]
                enhancement["factor"] = factor
                models = (
                    self._video_models_for_factor(factor)
                    if entry["kind"] == "video"
                    else self._models_for_factor(factor)
                )
                enhancement["model"] = models[0] if models else ""
            elif key == "model":
                choices = (
                    self._video_models_for_factor(entry["settings"]["enhancement"]["factor"])
                    if entry["kind"] == "video"
                    else self._models_for_factor(entry["settings"]["enhancement"]["factor"])
                )
                if value not in choices:
                    return False
                entry["settings"]["enhancement"][key] = value
            elif key in ("keep_size", "face_restoration"):
                entry["settings"]["enhancement"][key] = bool(value)
            else:
                return False
            self._touch(preview=key in SLIDER_RANGES or key == "Inversion")
            log_event("setting_changed", key=key, value=value)
        return True

    def reset_module(self):
        with self._lock:
            entry = self._current()
            if not entry or entry["image_loading"] or self._job["running"]:
                return False
            if entry["kind"] == "image":
                entry["settings"]["effects"] = {**SLIDER_DEFAULTS, "Inversion": False}
                entry["settings"]["enhancement"] = self._default_settings()["enhancement"]
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
            previous = self._current()
            for item in self._entries:
                processor = item["realtime_processor"]
                if processor:
                    processor.set_paused(True)
            if selected["kind"] == "video":
                self._module = "Video_Enhancement"
            else:
                self._module = "Image_Effects"
            self._current_id = image_id
            self._touch(preview=True, immediate=True)
            log_event(
                "history_selected",
                item_id=image_id,
                kind=selected["kind"],
            )
        return True

    def remove_image(self):
        with self._lock:
            entry = self._current()
            if self._job["running"] or not entry or entry["image_loading"]:
                return False
            realtime_url = entry["realtime_url"]
            temporary_path = entry.get("temporary_path")
            self._entries = [item for item in self._entries if item["id"] != self._current_id]
            self._current_id = self._entries[-1]["id"] if self._entries else None
            current = self._current()
            self._module = "Image_Effects" if not current or current["kind"] == "image" else "Video_Enhancement"
            self._history_revision += 1
            self._touch(preview=True, immediate=True)
        if realtime_url:
            self._video_stream.unregister_realtime(realtime_url)
        if temporary_path:
            try:
                Path(temporary_path).unlink(missing_ok=True)
            except OSError:
                pass
        return True

    def set_scale(self, scale):
        with self._lock:
            entry = self._current()
            if not entry:
                return False
            entry["scale"] = max(0.1, min(5.0, float(scale)))
            self._touch()
        return True

    @staticmethod
    def _crop_bounds(image, bounds):
        left, top, right, bottom = (float(value) for value in bounds)
        width, height = image.size
        box = (
            max(0, min(width, int(left * width))),
            max(0, min(height, int(top * height))),
            max(0, min(width, int(right * width))),
            max(0, min(height, int(bottom * height))),
        )
        if box[0] >= box[2] or box[1] >= box[3]:
            return None
        return image.crop(box)

    def crop_image(self, bounds, video_position=None):
        with self._lock:
            entry = self._current()
            if not entry or entry["image_loading"] or self._job["running"]:
                return False
            entry_id = entry["id"]
            video_frame = entry["kind"] == "video"
            if video_frame:
                video_path = entry["video_path"]
                processor = entry["realtime_processor"]
                video_position = entry["video_position"] if video_position is None else float(video_position)
                name = f"{entry['name']}_frame_{int(video_position * max(entry['video_fps'], 1)):06d}_crop"
            else:
                image = self._apply_effects(entry["image"], entry["settings"])
                name = entry["name"]
                extension = entry["extension"]

        if video_frame:
            image = self._realtime_frame_image(processor)
            if image is None:
                image = self._capture_video_frame(video_path, video_position)
            if image is None:
                return False
        cropped = self._crop_bounds(image, bounds)
        if cropped is None:
            return False

        with self._lock:
            current = self._current()
            if not current or current["id"] != entry_id or self._job["running"]:
                return False
            self._new_entry(cropped, name, "png" if video_frame else extension)
        return True

    def start_operation(self, operation):
        with self._lock:
            entry = self._current()
            if not entry or entry["image_loading"] or self._job["running"]:
                return False
            if entry["kind"] == "video":
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
            self._job["status"] = "Cancelled"
            self._job["stage"] = "cancel"
            self._job["running"] = False
            if self._process and self._process.is_alive():
                self._process.terminate()
            self._touch()
        log_event("operation_cancelled")
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

    def log_event(self, event, details=None):
        log_event(event, **(details if isinstance(details, dict) else {}))
        return True
