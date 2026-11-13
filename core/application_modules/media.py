import cv2
import io
import multiprocessing
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import webview
from PIL import Image

from core.config.constants import IMAGE_TILE_OVERLAP, IMAGE_TILE_SIZE, ROOT_DIR
from core.models.weights import find_model
from core.processing import effects as img_effects
from core.services.app_logging import log_event
from core.services.performance import gpu_memory_bytes, process_memory_bytes
from core.services.realtime_video import RealTimeVideoProcessor
from core.application_modules.shared import SLIDER_DEFAULTS, VIDEO_EXTENSIONS


class MediaModule:
    """History, media loading, export, and video processing capability."""

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
        temporary_path=None,
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
            "temporary_path": str(temporary_path) if temporary_path else None,
            "realtime_url": None,
            "realtime_processor": None,
            "realtime_model": "",
            "name": name,
            "extension": extension or "png",
            "settings": self._default_settings(),
            "scale": 1.0,
        }
        if kind == "video":
            realtime_models = self._realtime_models()
            output_options = self._video_output_options(entry)
            entry["settings"]["enhancement"]["factor"] = output_options[0]["factor"]
            models = self._models_for_factor(output_options[0]["factor"])
            entry["settings"]["enhancement"]["model"] = (
                models[0] if models else "Fast CPU resize + sharpen"
            )
            entry["realtime_model"] = realtime_models[0] if realtime_models else ""
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
                    "realtime_model": entry["realtime_model"],
                    "realtime_models": self._realtime_models(),
                    "realtime_running": bool(
                        entry["realtime_processor"]
                        and entry["realtime_processor"].running
                    ),
                    "realtime_paused": bool(
                        entry["realtime_processor"]
                        and entry["realtime_processor"].paused
                    ),
                    "realtime_loading": bool(
                        entry["realtime_processor"]
                        and entry["realtime_processor"].loading
                    ),
                    "realtime_position": (
                        entry["realtime_processor"].position
                        if entry["realtime_processor"] else entry["video_position"]
                    ),
                    "realtime_error": (
                        entry["realtime_processor"].error
                        if entry["realtime_processor"] else None
                    ),
                    "output_options": self._video_output_options(entry),
                } if entry and entry["kind"] == "video" else None,
                "debug": self._debug_state(entry),
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

    def _debug_state(self, entry):
        if entry and entry["realtime_processor"]:
            return entry["realtime_processor"].diagnostics
        if self._job.get("running") or self._job.get("processing_device"):
            return {
                "fps": self._job.get("processing_fps"),
                "device": self._job.get("processing_device"),
                "ram_bytes": self._job.get("ram_bytes"),
                "gpu_memory_bytes": self._job.get("gpu_memory_bytes"),
            }
        return None

    def get_job_state(self):
        with self._lock:
            return dict(self._job)

    def open_image(self):
        current = self._current()
        window = self._get_native_window()
        if not window or self._job["running"] or (current and current["image_loading"]):
            return False
        selected = window.create_file_dialog(
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
        try:
            self._create_video_entry_from_path(path)
        except Exception as error:
            self._set_message("error", str(error))
            return False
        return True

    def _create_video_entry_from_path(self, path, temporary_path=None, name=None):
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"Could not open video: {path.name}")
        success, frame = capture.read()
        if not success:
            capture.release()
            raise RuntimeError(f"Could not read the first video frame: {path.name}")

        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
        video_url = self._video_stream.register(path)
        capture.release()
        with self._lock:
            self._new_entry(
                frame_image,
                name or path.stem,
                "png",
                kind="video",
                video_path=path,
                video_url=video_url,
                video_fps=fps,
                video_frame_count=frame_count,
                video_frame_index=0,
                video_position=0,
                source_path=path,
                temporary_path=temporary_path,
            )

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
        window = self._get_native_window()
        if not entry or entry["image_loading"] or self._job["running"] or not window:
            return False
        extension = entry["extension"] or "png"
        selected = window.create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=f"{entry['name']}_{entry['id']}.{extension}",
            file_types=("Image files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff)",),
        )
        if not selected:
            return False
        output_path = Path(selected[0])
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
                "processing_fps": 0.0,
                "processing_device": None,
                "ram_bytes": None,
                "gpu_memory_bytes": None,
            }
            self._touch()
        self._job_thread = threading.Thread(
            target=self._export_image_worker,
            args=(image, settings, output_path),
            daemon=True,
        )
        log_event("export_image_requested", path=output_path.name, extension=extension)
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
                or not self._get_native_window()
            ):
                return False
            source_path = Path(entry["video_path"])
            if not source_path.is_file():
                self._set_message("error", f"Video source not found: {source_path}")
                return False
            default_name = f"{entry['name']}.mp4"
        selected = self._get_native_window().create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=default_name,
            file_types=("Video files (*.mp4)",),
        )
        if not selected:
            return False
        output_path = Path(selected[0])
        if output_path.resolve() == source_path.resolve():
            self._set_message("error", "Choose a different export path.")
            return False
        with self._lock:
            self._job = {
                "running": True,
                "progress": 0,
                "status": "Exporting video",
                "stage": "export",
                "current": 0,
                "total": 0,
                "unit": "",
                "kind": "export",
                "error": None,
            }
            self._cancel_event = threading.Event()
            self._touch()
        self._job_thread = threading.Thread(
            target=self._export_video_worker,
            args=(source_path, output_path, self._cancel_event),
            daemon=True,
        )
        log_event("export_video_requested", path=output_path.name)
        self._job_thread.start()
        return True

    def start_video_upscale(self):
        with self._lock:
            entry = self._current()
            if (
                not entry
                or entry["kind"] != "video"
                or self._job["running"]
                or (self._job_thread and self._job_thread.is_alive())
            ):
                return False
            options = dict(entry["settings"]["enhancement"])
            models = self._video_models_for_factor(options["factor"])
            if not models or options["model"] not in models:
                self._set_message(
                    "error",
                    "No upscaling model is available for the selected resolution.",
                )
                return False
            output_path = Path(tempfile.gettempdir()) / (
                f"picture-editor-{uuid.uuid4().hex}.mp4"
            )
            source_path = Path(entry["video_path"])
            if not source_path.is_file():
                self._set_message("error", f"Video source not found: {source_path}")
                return False
            self._job = {
                "running": True,
                "progress": 0,
                "status": "Upscaling video",
                "stage": "frames",
                "current": 0,
                "total": entry["video_frame_count"],
                "unit": "frame",
                "kind": "video_upscale",
                "fps": entry["video_fps"],
                "duration": (
                    entry["video_frame_count"] / entry["video_fps"]
                    if entry["video_fps"] > 0 else 0
                ),
                "error": None,
                "processing_fps": 0.0,
                "processing_device": None,
                "ram_bytes": None,
                "gpu_memory_bytes": None,
            }
            self._cancel_event = threading.Event()
            self._touch()
        self._job_thread = threading.Thread(
            target=self._upscale_video_worker,
            args=(source_path, output_path, options, self._cancel_event),
            daemon=True,
        )
        log_event(
            "video_upscale_requested",
            model=options["model"],
            factor=options["factor"],
            output=output_path.name,
        )
        self._job_thread.start()
        return True

    def _export_video_worker(self, source_path, output_path, cancel_event):
        try:
            if cancel_event.is_set():
                return
            shutil.copy2(source_path, output_path)
        except Exception as error:
            log_event("export_video_failed", error=str(error))
            with self._lock:
                self._job = {
                    "running": False,
                    "progress": 0,
                    "status": "Failed",
                    "kind": "export",
                    "error": str(error),
                }
                self._message = {"type": "error", "text": f"Could not export video: {error}"}
                self._touch()
        else:
            log_event("export_video_completed", output=output_path.name)
            with self._lock:
                self._job = {
                    "running": False,
                    "progress": 100,
                    "status": "Complete",
                    "kind": "export",
                    "error": None,
                }
                self._message = {"type": "success", "text": "Video exported successfully."}
                self._touch()
        finally:
            with self._lock:
                self._cancel_event = None

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
            processing_device = "CPU"
            if not is_cpu_model:
                model_path = find_model(options["model"], scale)
                if model_path is None:
                    raise FileNotFoundError(
                        f"Weight file not found for model: {options['model']}"
                    )

                from core.models.onnx_realesrganer import OnnxRealESRGANer

                upscaler = OnnxRealESRGANer(
                    scale=scale,
                    pth_path=str(model_path),
                    tile=IMAGE_TILE_SIZE,
                    tile_pad=IMAGE_TILE_OVERLAP,
                )
                processing_device = (
                    "GPU (DirectML)"
                    if "DmlExecutionProvider" in upscaler.device
                    else "CPU"
                )
            processing_started = time.monotonic()
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
                        processing_fps=(
                            frame_index / (time.monotonic() - processing_started)
                            if time.monotonic() > processing_started else 0.0
                        ),
                        processing_device=processing_device,
                        ram_bytes=process_memory_bytes(),
                        gpu_memory_bytes=gpu_memory_bytes(),
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
            try:
                Path(output_path).unlink(missing_ok=True)
            except OSError:
                pass
            with self._lock:
                self._job = {
                    "running": False,
                    "progress": 0,
                    "status": "Failed",
                    "kind": "video_upscale",
                    "error": str(error),
                }
                self._message = {"type": "error", "text": str(error)}
                self._touch()
        else:
            try:
                with self._lock:
                    self._create_video_entry_from_path(
                        output_path,
                        temporary_path=output_path,
                        name=f"{Path(source_path).stem}_{options['factor']}x",
                    )
                    self._job = {
                        "running": False,
                        "progress": 100,
                        "status": "Complete",
                        "kind": "video_upscale",
                        "error": None,
                    }
                    self._message = {
                        "type": "success",
                        "text": "Upscaled video added to history.",
                    }
                    self._touch()
            except Exception as error:
                with self._lock:
                    self._job = {
                        "running": False,
                        "progress": 0,
                        "status": "Failed",
                        "kind": "video_upscale",
                        "error": str(error),
                    }
                    self._message = {"type": "error", "text": str(error)}
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
                            "stage": "cancel",
                            "current": self._job.get("current", 0),
                            "total": self._job.get("total", 0),
                            "unit": "frame",
                            "kind": "video_upscale",
                            "fps": self._job.get("fps", 0),
                            "duration": self._job.get("duration", 0),
                            "error": None,
                        }
                        self._touch()
            else:
                Path(silent_output).unlink(missing_ok=True)
                if self._job.get("status") == "Failed":
                    Path(output_path).unlink(missing_ok=True)
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
            log_event("export_image_failed", path=Path(path).name, error=str(error))
        else:
            log_event("export_image_completed", path=Path(path).name)
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

