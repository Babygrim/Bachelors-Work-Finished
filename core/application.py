import base64
import io
import multiprocessing
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from queue import Empty

import cv2
import numpy as np
import webview
from PIL import Image, ImageEnhance, ImageFilter

from core.config.constants import IMAGE_TILE_OVERLAP, IMAGE_TILE_SIZE, ROOT_DIR
from core.processing import effects as img_effects
from core.processing import resolution as img_resolution
from core.services.app_logging import log_toast
from core.services.realtime_video import RealTimeVideoProcessor
from core.services.video_stream import VideoStreamServer

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
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


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

    def _new_entry(
        self,
        image,
        name="image",
        extension="png",
        original_size=None,
        full_resolution=True,
        kind="image",
        video_path=None,
        video_url=None,
        video_fps=0.0,
        video_frame_count=0,
        video_frame_index=0,
        video_position=0.0,
        source_path=None,
    ):
        entry = {
            "id": uuid.uuid4().hex[:12],
            "image": image.convert("RGBA"),
            "original_size": original_size or image.size,
            "image_loading": not full_resolution,
            "kind": kind,
            "video_path": str(video_path) if video_path else None,
            "video_url": video_url,
            "video_fps": float(video_fps),
            "video_frame_count": int(video_frame_count),
            "video_frame_index": int(video_frame_index),
            "video_position": float(video_position),
            "source_path": str(source_path) if source_path else None,
            "realtime_url": None,
            "realtime_processor": None,
            "realtime_mode": "fast",
            "name": name,
            "extension": extension or "png",
            "settings": self._default_settings(),
            "scale": 1.0,
        }
        if kind == "video":
            output_options = self._video_output_options(entry)
            entry["settings"]["enhancement"]["factor"] = output_options[0]["factor"]
            models = self._models_for_factor(output_options[0]["factor"])
            entry["settings"]["enhancement"]["model"] = (
                models[0] if models else "Fast CPU resize + sharpen"
            )
        thumbnail = entry["image"].copy()
        thumbnail.thumbnail((150, 100), Image.Resampling.LANCZOS)
        entry["thumbnail_image"] = thumbnail
        entry["thumbnail"] = self._image_url(thumbnail)
        self._entries.append(entry)
        self._current_id = entry["id"]
        self._history_revision += 1
        if kind == "video":
            self._module = "Video_Enhancement"
        else:
            self._module = "Image_Effects"
        self._touch(preview=True, immediate=True)

    def get_state(self, previous_revision=None, previous_history_revision=None):
        with self._lock:
            entry = self._current()
            media_info = None
            if entry:
                native_width, native_height = entry["original_size"]
                current_width, current_height = native_width, native_height
                duration = None
                if entry["kind"] == "video":
                    duration = (
                        entry["video_frame_count"] / entry["video_fps"]
                        if entry["video_fps"] > 0 else 0
                    )
                    selected_option = next(
                        (
                            option for option in self._video_output_options(entry)
                            if option["factor"] == entry["settings"]["enhancement"]["factor"]
                        ),
                        None,
                    )
                    if entry["realtime_processor"] and selected_option:
                        current_width = selected_option["width"]
                        current_height = selected_option["height"]
                file_size = None
                if entry["source_path"]:
                    try:
                        file_size = Path(entry["source_path"]).stat().st_size
                    except OSError:
                        file_size = None
                media_info = {
                    "name": entry["name"],
                    "type": entry["kind"],
                    "extension": entry["extension"],
                    "path": entry["source_path"],
                    "native_size": [native_width, native_height],
                    "current_size": [current_width, current_height],
                    "duration": duration,
                    "fps": entry["video_fps"] if entry["kind"] == "video" else None,
                    "frame_count": entry["video_frame_count"] if entry["kind"] == "video" else None,
                    "file_size": file_size,
                }
            state = {
                "module": self._module,
                "revision": self._revision,
                "image_revision": self._preview_delivery_revision,
                "history_revision": self._history_revision,
                "current_id": self._current_id,
                "kind": entry["kind"] if entry else "image",
                "has_image": entry is not None,
                "image_loading": bool(entry and entry["image_loading"]),
                "preview_loading": self._preview_worker_running,
                "video": {
                    "url": entry["video_url"],
                    "frame": entry["video_frame_index"],
                    "frame_count": entry["video_frame_count"],
                    "fps": entry["video_fps"],
                    "position": entry["video_position"],
                    "duration": entry["video_frame_count"] / entry["video_fps"]
                    if entry["video_fps"] > 0 else 0,
                    "realtime_url": entry["realtime_url"],
                    "realtime_mode": entry["realtime_mode"],
                    "realtime_running": bool(
                        entry["realtime_processor"]
                        and entry["realtime_processor"].running
                    ),
                    "realtime_error": (
                        entry["realtime_processor"].error
                        if entry["realtime_processor"] else None
                    ),
                    "output_options": self._video_output_options(entry),
                } if entry and entry["kind"] == "video" else None,
                "image": None,
                "image_size": None,
                "image_name": None,
                "media_info": media_info,
                "settings": entry["settings"] if entry else self._default_settings(),
                "scale": entry["scale"] if entry else 1.0,
                "models": self._video_models_for_factor(entry["settings"]["enhancement"]["factor"])
                if entry and entry["kind"] == "video"
                else self._models_for_factor(entry["settings"]["enhancement"]["factor"])
                if entry else self._models_for_factor(2),
                "history": [
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "size": item["original_size"],
                        "thumbnail": item["thumbnail"],
                        "kind": item["kind"],
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

    def get_job_state(self):
        with self._lock:
            return dict(self._job)

    def open_image(self):
        current = self._current()
        if not _native_window or self._job["running"] or (current and current["image_loading"]):
            return False
        selected = _native_window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=(
                "Media files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff;*.mp4;*.mov;*.avi;*.mkv;*.webm;*.m4v)",
            ),
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
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            return self._load_video(path)
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
                    source_path=path,
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

    def _load_video(self, path):
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            self._set_message("error", f"Could not open video: {path.name}")
            return False
        success, frame = capture.read()
        if not success:
            capture.release()
            self._set_message("error", f"Could not read the first video frame: {path.name}")
            return False

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        video_url = self._video_stream.register(path)
        capture.release()
        with self._lock:
            self._new_entry(
                frame_image,
                path.stem,
                "png",
                kind="video",
                video_path=path,
                video_url=video_url,
                video_fps=fps,
                video_frame_count=frame_count,
                video_frame_index=0,
                video_position=0,
                source_path=path,
            )
        return True

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
            webview.FileDialog.SAVE,
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

    def save_video(self):
        with self._lock:
            entry = self._current()
            if (
                not entry
                or entry["kind"] != "video"
                or self._job["running"]
                or (self._job_thread and self._job_thread.is_alive())
                or not _native_window
            ):
                return False
            options = dict(entry["settings"]["enhancement"])
            if not options["model"]:
                self._set_message("error", "No ONNX model is available for this scale.")
                return False
            default_name = f"{entry['name']}_{options['factor']}x.mp4"
        selected = _native_window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=default_name,
            file_types=("Video files (*.mp4)",),
        )
        if not selected:
            return False
        with self._lock:
            self._job = {
                "running": True,
                "progress": 0,
                "status": "Upscaling video",
                "stage": "frames",
                "current": 0,
                "total": entry["video_frame_count"],
                "unit": "frame",
                "kind": "video_export",
                "fps": entry["video_fps"],
                "duration": (
                    entry["video_frame_count"] / entry["video_fps"]
                    if entry["video_fps"] > 0 else 0
                ),
                "error": None,
            }
            self._cancel_event = threading.Event()
            self._touch()
        self._job_thread = threading.Thread(
            target=self._upscale_video_worker,
            args=(entry["video_path"], selected[0], options, self._cancel_event),
            daemon=True,
        )
        self._job_thread.start()
        return True

    def _upscale_video_worker(self, source_path, output_path, options, cancel_event):
        capture = cv2.VideoCapture(str(source_path))
        writer = None
        silent_output = f"{output_path}.silent.mp4"
        try:
            if not capture.isOpened():
                raise RuntimeError(f"Could not open video: {Path(source_path).name}")
            fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
            total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            with self._lock:
                self._job.update(
                    fps=float(fps),
                    duration=total / fps if fps else 0,
                    total=total,
                )
                self._touch()
            scale = int(options["factor"])
            model_name = str(options["model"]).lower()
            is_cpu_model = "cpu" in model_name or "resize" in model_name or "sharpen" in model_name
            upscaler = None
            if not is_cpu_model:
                model_path = Path(ROOT_DIR, "weights", f"{options['model']}.onnx")
                if not model_path.is_file():
                    raise FileNotFoundError(f"Weight file not found: {model_path}")

                from core.models.onnx_realesrganer import OnnxRealESRGANer

                upscaler = OnnxRealESRGANer(
                    scale=scale,
                    pth_path=str(model_path),
                    tile=IMAGE_TILE_SIZE,
                    tile_pad=IMAGE_TILE_OVERLAP,
                )
            frame_index = 0
            while not cancel_event.is_set():
                success, frame = capture.read()
                if not success:
                    break
                current_frame = frame_index + 1
                with self._lock:
                    self._job.update(
                        status="Processing video",
                        current=current_frame,
                        total=total,
                        progress=round(current_frame * 100 / total) if total else 0,
                    )
                    self._touch()
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGB")
                image = self._apply_effects(image, {"effects": SLIDER_DEFAULTS | {"Inversion": False}})
                source_frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
                output_size = (frame.shape[1] * scale, frame.shape[0] * scale)
                output = (
                    upscaler.enhance(source_frame)
                    if upscaler is not None
                    else RealTimeVideoProcessor._process_frame(
                        source_frame,
                        None,
                        output_size,
                    )
                )
                if options["keep_size"]:
                    output = cv2.resize(
                        output,
                        (frame.shape[1], frame.shape[0]),
                        interpolation=cv2.INTER_AREA,
                    )
                if writer is None:
                    height, width = output.shape[:2]
                    writer = cv2.VideoWriter(
                        silent_output,
                        cv2.VideoWriter_fourcc(*"mp4v"),
                        fps,
                        (width, height),
                    )
                    if not writer.isOpened():
                        raise RuntimeError(f"Could not create video: {output_path}")
                writer.write(output)
                frame_index += 1
                with self._lock:
                    self._job.update(
                        current=frame_index,
                        total=total,
                        progress=round(frame_index * 100 / total) if total else 0,
                    )
                    self._touch()
            if cancel_event.is_set():
                return
            if writer is None:
                raise RuntimeError("The video contains no readable frames.")
            writer.release()
            writer = None
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        silent_output,
                        "-i",
                        str(source_path),
                        "-map",
                        "0:v:0",
                        "-map",
                        "1:a?",
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-shortest",
                        str(output_path),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            else:
                Path(silent_output).replace(output_path)
        except Exception as error:
            with self._lock:
                self._job = {
                    "running": False,
                    "progress": 0,
                    "status": "Failed",
                    "kind": "video_export",
                    "error": str(error),
                }
                self._message = {"type": "error", "text": str(error)}
                self._touch()
        else:
            with self._lock:
                self._job = {
                    "running": False,
                    "progress": 100,
                    "status": "Complete",
                    "kind": "video_export",
                    "error": None,
                }
                self._message = {"type": "success", "text": "Video exported successfully."}
                self._touch()
        finally:
            capture.release()
            if writer is not None:
                writer.release()
            if cancel_event.is_set():
                try:
                    Path(output_path).unlink(missing_ok=True)
                    Path(silent_output).unlink(missing_ok=True)
                except OSError:
                    pass
                with self._lock:
                    if self._job.get("status") != "Cancelled":
                        self._job = {
                            "running": False,
                            "progress": 0,
                            "status": "Cancelled",
                            "current": self._job.get("current", 0),
                            "total": self._job.get("total", 0),
                            "unit": "frame",
                            "kind": "video_export",
                            "fps": self._job.get("fps", 0),
                            "duration": self._job.get("duration", 0),
                            "error": None,
                        }
                        self._touch()
            else:
                Path(silent_output).unlink(missing_ok=True)
            with self._lock:
                self._cancel_event = None

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

    def set_video_position(self, seconds):
        with self._lock:
            entry = self._current()
            if not entry or entry["kind"] != "video":
                return False
            duration = entry["video_frame_count"] / entry["video_fps"] if entry["video_fps"] > 0 else 0
            entry["video_position"] = max(0.0, min(float(seconds), duration))
            entry["video_frame_index"] = int(entry["video_position"] * entry["video_fps"])
            self._revision += 1
        return True

    def start_video_realtime(self, position=None, mode="fast"):
        with self._lock:
            entry = self._current()
            if (
                not entry
                or entry["kind"] != "video"
                or self._job["running"]
                or mode not in ("fast", "ai")
            ):
                return False
            if mode == "ai" and entry["settings"]["enhancement"]["model"] == "Fast CPU resize + sharpen":
                self._set_message("error", "AI preview requires an ONNX model for the selected resolution.")
                return False
            if entry["realtime_processor"] and entry["realtime_processor"].running:
                return True
            output_option = next(
                option for option in self._video_output_options(entry)
                if option["factor"] == entry["settings"]["enhancement"]["factor"]
            )
            processor = RealTimeVideoProcessor(
                entry["video_path"],
                entry["settings"]["enhancement"]["model"],
                entry["settings"]["enhancement"]["factor"],
                mode=mode,
                output_size=(output_option["width"], output_option["height"]),
            )
            entry["realtime_processor"] = processor
            entry["realtime_url"] = self._video_stream.register_realtime(processor)
            entry["realtime_mode"] = mode
            start_position = (
                entry["video_position"] if position is None else float(position)
            )
        try:
            processor.start(start_position)
        except Exception:
            self._video_stream.unregister_realtime(entry["realtime_url"])
            with self._lock:
                entry["realtime_processor"] = None
                entry["realtime_url"] = None
            raise
        with self._lock:
            self._touch()
        return True

    def stop_video_realtime(self):
        with self._lock:
            entry = self._current()
            if not entry or entry["kind"] != "video":
                return False
            url = entry["realtime_url"]
            entry["realtime_url"] = None
            entry["realtime_processor"] = None
            self._touch()
        if url:
            self._video_stream.unregister_realtime(url)
        return True

    @staticmethod
    def _capture_video_frame(video_path, position):
        capture = cv2.VideoCapture(video_path)
        try:
            if not capture.isOpened():
                return None
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(position)) * 1000)
            success, frame = capture.read()
            if not success:
                return None
            return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        finally:
            capture.release()

    def save_video_frame(self, position=None):
        with self._lock:
            entry = self._current()
            if not entry or entry["kind"] != "video" or self._job["running"]:
                return False
            position = entry["video_position"] if position is None else float(position)
            video_path = entry["video_path"]
            name = f"{entry['name']}_frame_{int(position * max(entry['video_fps'], 1)) + 1:06d}"
            entry_id = entry["id"]
        image = self._capture_video_frame(video_path, position)
        if image is None:
            return False
        with self._lock:
            current = self._current()
            if not current or current["id"] != entry_id:
                return False
            self._new_entry(image, name, "png")
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
            if selected["kind"] == "video":
                self._module = "Video_Enhancement"
            else:
                self._module = "Image_Effects"
            self._current_id = image_id
            self._touch(preview=True, immediate=True)
        return True

    def remove_image(self):
        with self._lock:
            entry = self._current()
            if self._job["running"] or not entry or entry["image_loading"]:
                return False
            realtime_url = entry["realtime_url"]
            self._entries = [item for item in self._entries if item["id"] != self._current_id]
            self._current_id = self._entries[-1]["id"] if self._entries else None
            current = self._current()
            self._module = "Image_Effects" if not current or current["kind"] == "image" else "Video_Enhancement"
            self._history_revision += 1
            self._touch(preview=True, immediate=True)
        if realtime_url:
            self._video_stream.unregister_realtime(realtime_url)
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
                video_position = entry["video_position"] if video_position is None else float(video_position)
                name = f"{entry['name']}_frame_{int(video_position * max(entry['video_fps'], 1)):06d}_crop"
            else:
                image = self._apply_effects(entry["image"], entry["settings"])
                name = entry["name"]
                extension = entry["extension"]

        if video_frame:
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