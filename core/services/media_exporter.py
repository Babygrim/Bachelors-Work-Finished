"""Media export and processing utilities for saving images and videos."""

import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from core.config.constants import IMAGE_TILE_OVERLAP, IMAGE_TILE_SIZE
from core.processing.output_size import is_target, output_plan
from core.services.app_logging import log_event
from core.services.performance import gpu_memory_bytes, process_memory_bytes
from core.services.realtime_video import RealTimeVideoProcessor
from core.services.time_estimator import UpscalingTimeEstimator, format_time_estimate
from core.application_modules.shared import SLIDER_DEFAULTS
from core.services.ffmpeg_utils import find_ffmpeg_path


def save_image_dialog(media_module):
    """
    Open save dialog for exporting an image.
    
    Args:
        media_module: MediaModule instance
        
    Returns:
        bool: True if save dialog completed and job started, False otherwise
    """
    entry = media_module._current()
    window = media_module._get_native_window()
    
    if not entry or entry["image_loading"] or media_module._job["running"] or not window:
        return False
    
    import webview
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
    
    with media_module._lock:
        media_module._job = {
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
        media_module._touch()
    
    media_module._job_thread = threading.Thread(
        target=export_image_worker,
        args=(media_module, image, settings, output_path),
        daemon=True,
    )
    log_event("export_image_requested", path=output_path.name, extension=extension)
    media_module._job_thread.start()
    
    return True


def save_video_dialog(media_module):
    """
    Open save dialog for exporting a video.
    
    Args:
        media_module: MediaModule instance
        
    Returns:
        bool: True if save dialog completed and job started, False otherwise
    """
    with media_module._lock:
        entry = media_module._current()
        if (
            not entry
            or entry["kind"] != "video"
            or media_module._job["running"]
            or (media_module._job_thread and media_module._job_thread.is_alive())
            or not media_module._get_native_window()
        ):
            return False
        
        source_path = Path(entry["video_path"])
        if not source_path.is_file():
            media_module._set_message("error", f"Video source not found: {source_path}")
            return False
        
        default_name = f"{entry['name']}.mp4"
    
    import webview
    selected = media_module._get_native_window().create_file_dialog(
        webview.FileDialog.SAVE,
        save_filename=default_name,
        file_types=("Video files (*.mp4)",),
    )
    
    if not selected:
        return False
    
    output_path = Path(selected[0])
    
    if output_path.resolve() == source_path.resolve():
        media_module._set_message("error", "Choose a different export path.")
        return False
    
    with media_module._lock:
        media_module._job = {
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
        media_module._cancel_event = threading.Event()
        media_module._touch()
    
    media_module._job_thread = threading.Thread(
        target=export_video_worker,
        args=(media_module, source_path, output_path, media_module._cancel_event),
        daemon=True,
    )
    log_event("export_video_requested", path=output_path.name)
    media_module._job_thread.start()
    
    return True


def start_video_upscale_process(media_module):
    """
    Start video upscaling process.
    
    Args:
        media_module: MediaModule instance
        
    Returns:
        bool: True if upscaling started, False otherwise
    """
    with media_module._lock:
        entry = media_module._current()
        if (
            not entry
            or entry["kind"] != "video"
            or media_module._job["running"]
            or (media_module._job_thread and media_module._job_thread.is_alive())
        ):
            return False
        
        options = dict(entry["settings"]["enhancement"])
        models = media_module._video_models_for_factor(options["factor"], entry)
        
        if not models or options["model"] not in models:
            media_module._set_message(
                "error",
                "No upscaling model is available for the selected resolution.",
            )
            return False
        
        output_path = Path(tempfile.gettempdir()) / (
            f"picture-editor-{uuid.uuid4().hex}.mp4"
        )
        source_path = Path(entry["video_path"])
        
        if not source_path.is_file():
            media_module._set_message("error", f"Video source not found: {source_path}")
            return False
        
        ffmpeg = find_ffmpeg_path()
        if ffmpeg is None:
            message = (
                "FFmpeg is required for video upscaling. "
                "Install FFmpeg and add it to PATH."
            )
            media_module._set_message("error", message)
            log_event("video_upscale_rejected", reason="ffmpeg_not_found")
            return False
        
        # Estimate processing time
        estimator = UpscalingTimeEstimator()
        time_estimate = estimator.estimate_time(
            total_frames=entry["video_frame_count"],
            fps=entry["video_fps"],
            input_resolution=(entry.get("video_width", 1920), entry.get("video_height", 1080)),
            scale=options["factor"],
            model_name=options["model"],
            is_gpu=True,  # Assume GPU by default
        )
        
        media_module._job = {
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
            "time_estimate": time_estimate,
            "time_estimate_formatted": time_estimate["formatted"],
        }
        media_module._cancel_event = threading.Event()
        media_module._touch()
    
    media_module._job_thread = threading.Thread(
        target=upscale_video_worker,
        args=(media_module, source_path, output_path, options, media_module._cancel_event),
        daemon=True,
    )
    log_event(
        "video_upscale_requested",
        model=options["model"],
        factor=options["factor"],
        output=output_path.name,
    )
    media_module._job_thread.start()
    
    return True


def export_video_worker(media_module, source_path, output_path, cancel_event):
    """
    Worker thread for exporting/copying video files.
    
    Args:
        media_module: MediaModule instance
        source_path: Source video path
        output_path: Output video path
        cancel_event: Event to signal cancellation
    """
    try:
        if cancel_event.is_set():
            return
        
        shutil.copy2(source_path, output_path)
    except Exception as error:
        log_event("export_video_failed", error=str(error))
        with media_module._lock:
            media_module._job = {
                "running": False,
                "progress": 0,
                "status": "Failed",
                "kind": "export",
                "error": str(error),
            }
            media_module._message = {
                "type": "error",
                "text": f"Could not export video: {error}"
            }
            media_module._touch()
    else:
        log_event("export_video_completed", output=output_path.name)
        with media_module._lock:
            media_module._job = {
                "running": False,
                "progress": 100,
                "status": "Complete",
                "kind": "export",
                "error": None,
            }
            media_module._message = {
                "type": "success",
                "text": "Video exported successfully."
            }
            media_module._touch()
    finally:
        with media_module._lock:
            media_module._cancel_event = None


def upscale_video_worker(media_module, source_path, output_path, options, cancel_event):
    """
    Worker thread for video upscaling.
    
    Args:
        media_module: MediaModule instance
        source_path: Source video path
        output_path: Output video path
        options: Upscaling options (factor, model, keep_size)
        cancel_event: Event to signal cancellation
    """
    capture = cv2.VideoCapture(str(source_path))
    writer = None
    silent_output = f"{output_path}.silent.mp4"
    
    try:
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video: {Path(source_path).name}")
        
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        
        with media_module._lock:
            media_module._job.update(
                fps=float(fps),
                duration=total / fps if fps else 0,
                total=total,
            )
            media_module._touch()
        
        source_size = (
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        
        scale, target_size = output_plan(source_size, options["factor"])
        model_name = str(options["model"]).lower()
        is_cpu_model = "cpu" in model_name or "resize" in model_name or "sharpen" in model_name
        
        upscaler = None
        processing_device = "CPU"
        
        if not is_cpu_model:
            from core.models.factory import create_upscaler, device_label
            
            upscaler = create_upscaler(
                options["model"], scale, IMAGE_TILE_SIZE, IMAGE_TILE_OVERLAP,
            )
            processing_device = device_label(upscaler)
        
        processing_started = time.monotonic()
        frame_index = 0
        
        # Get initial time estimate from job
        time_estimate = media_module._job.get("time_estimate", {})
        
        while not cancel_event.is_set():
            success, frame = capture.read()
            if not success:
                break
            
            current_frame = frame_index + 1
            elapsed_seconds = time.monotonic() - processing_started
            
            # Calculate remaining time estimate
            time_remaining_seconds = 0
            if current_frame > 0 and time_estimate:
                fps_actual = current_frame / elapsed_seconds if elapsed_seconds > 0 else 0
                frames_remaining = total - current_frame
                time_remaining_seconds = frames_remaining / fps_actual if fps_actual > 0 else 0
            
            # Format remaining time
            remaining_hours = int(time_remaining_seconds // 3600)
            remaining_minutes = int((time_remaining_seconds % 3600) // 60)
            remaining_seconds = int(time_remaining_seconds % 60)
            
            if remaining_hours > 0:
                time_remaining_formatted = f"{remaining_hours}h {remaining_minutes}m {remaining_seconds}s"
            elif remaining_minutes > 0:
                time_remaining_formatted = f"{remaining_minutes}m {remaining_seconds}s"
            else:
                time_remaining_formatted = f"{remaining_seconds}s"
            
            with media_module._lock:
                media_module._job.update(
                    status="Processing video",
                    current=current_frame,
                    total=total,
                    progress=round(current_frame * 100 / total) if total else 0,
                    time_remaining=time_remaining_seconds,
                    time_remaining_formatted=time_remaining_formatted,
                    time_estimate_formatted=time_estimate.get("formatted", "") if time_estimate else '',
                )
                media_module._touch()
            
            # Apply effects to frame
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGB")
            image = media_module._apply_effects(image, {"effects": SLIDER_DEFAULTS | {"Inversion": False}})
            source_frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
            
            # Upscale frame
            output = (
                upscaler.enhance(source_frame)
                if upscaler is not None
                else RealTimeVideoProcessor._process_frame(source_frame, None, target_size)
            )
            
            if output.shape[1::-1] != target_size:
                output = cv2.resize(output, target_size, interpolation=cv2.INTER_AREA)
            
            if options["keep_size"] and not is_target(options["factor"]):
                output = cv2.resize(
                    output,
                    (frame.shape[1], frame.shape[0]),
                    interpolation=cv2.INTER_AREA,
                )
            
            # Initialize video writer
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
            
            with media_module._lock:
                media_module._job.update(
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
                    time_estimate_formatted=time_estimate.get("formatted", "") if time_estimate else '',
                )
                media_module._touch()
        
        if cancel_event.is_set():
            return
        
        if writer is None:
            raise RuntimeError("The video contains no readable frames.")
        
        writer.release()
        writer = None
        
        # Remux video with audio using FFmpeg
        ffmpeg = find_ffmpeg_path()
        if ffmpeg is None:
            raise RuntimeError(
                "FFmpeg became unavailable while finalizing the upscaled video."
            )
        
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
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-shortest",
                str(output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as error:
        log_event("video_upscale_failed", error=str(error))
        try:
            Path(output_path).unlink(missing_ok=True)
        except OSError:
            pass
        
        with media_module._lock:
            media_module._job = {
                "running": False,
                "progress": 0,
                "status": "Failed",
                "kind": "video_upscale",
                "error": str(error),
            }
            media_module._message = {"type": "error", "text": str(error)}
            media_module._touch()
    else:
        # Record actual processing time for calibration
        actual_time = time.monotonic() - processing_started
        log_event(
            "video_upscale_completed",
            actual_time_seconds=round(actual_time, 2),
            frames_processed=frame_index,
            fps_actual=round(frame_index / actual_time, 2) if actual_time > 0 else 0,
        )
        
        try:
            from core.services.media_loader import create_video_entry_from_path
            
            with media_module._lock:
                create_video_entry_from_path(
                    media_module,
                    output_path,
                    temporary_path=output_path,
                    name=f"{Path(source_path).stem}_{options['factor']}{'p' if is_target(options['factor']) else 'x'}",
                )
                media_module._job = {
                    "running": False,
                    "progress": 100,
                    "status": "Complete",
                    "kind": "video_upscale",
                    "error": None,
                    "actual_time_seconds": actual_time,
                }
                media_module._message = {
                    "type": "success",
                    "text": "Upscaled video added to history.",
                }
                media_module._touch()
        except Exception as error:
            with media_module._lock:
                media_module._job = {
                    "running": False,
                    "progress": 0,
                    "status": "Failed",
                    "kind": "video_upscale",
                    "error": str(error),
                }
                media_module._message = {"type": "error", "text": str(error)}
                media_module._touch()
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
            
            with media_module._lock:
                if media_module._job.get("status") != "Cancelled":
                    media_module._job = {
                        "running": False,
                        "progress": 0,
                        "status": "Cancelled",
                        "stage": "cancel",
                        "current": media_module._job.get("current", 0),
                        "total": media_module._job.get("total", 0),
                        "unit": "frame",
                        "kind": "video_upscale",
                        "fps": media_module._job.get("fps", 0),
                        "duration": media_module._job.get("duration", 0),
                        "error": None,
                    }
                    media_module._touch()
        else:
            Path(silent_output).unlink(missing_ok=True)
            if media_module._job.get("status") == "Failed":
                Path(output_path).unlink(missing_ok=True)
        
        with media_module._lock:
            media_module._cancel_event = None


def export_image_worker(media_module, image, settings, path):
    """
    Worker thread for exporting image files.
    
    Args:
        media_module: MediaModule instance
        image: PIL Image object to export
        settings: Image settings (effects, enhancement)
        path: Output path
    """
    try:
        image = media_module._apply_effects(image, settings)
        
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
    
    with media_module._lock:
        media_module._job = {
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
        media_module._message = message
        media_module._touch()
