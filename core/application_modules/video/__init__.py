import cv2
import io
import time
from pathlib import Path

from PIL import Image

from core.services.app_logging import log_event
from core.services.upscalers.constants import AMD_VIDEO_SR_MODEL
from core.services.realtime_video import RealTimeVideoProcessor


class VideoModule:
    """Video playback and real-time preview capability."""

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

    def seek_video_realtime(self, seconds):
        with self._lock:
            entry = self._current()
            processor = entry["realtime_processor"] if entry and entry["kind"] == "video" else None
            if not processor or not processor.running:
                return False
            duration = (
                entry["video_frame_count"] / entry["video_fps"]
                if entry["video_fps"] > 0 else 0
            )
            entry["video_position"] = max(0.0, min(float(seconds), duration))
            entry["video_frame_index"] = int(entry["video_position"] * entry["video_fps"])
            processor.seek(seconds)
            self._revision += 1
            log_event("realtime_seek_requested", position=entry["video_position"])
        return True

    def set_video_trim(self, start, end):
        """Mark an in/out range (seconds) so only that fragment gets upscaled."""
        with self._lock:
            entry = self._current()
            if not entry or entry["kind"] != "video" or self._job["running"]:
                return False
            duration = (
                entry["video_frame_count"] / entry["video_fps"]
                if entry["video_fps"] > 0 else 0
            )
            if duration <= 0:
                return False
            try:
                start = float(start)
                end = float(end)
            except (TypeError, ValueError):
                return False
            start = max(0.0, min(start, duration))
            end = max(0.0, min(end, duration))
            min_span = 1.0 / entry["video_fps"] if entry["video_fps"] > 0 else 0.1
            if end - start < min_span:
                return False
            entry["video_trim_start"] = start
            entry["video_trim_end"] = end
            self._touch()
        log_event("video_trim_set", start=round(start, 3), end=round(end, 3))
        return True

    def clear_video_trim(self):
        """Drop the in/out range so upscaling runs on the full video again."""
        with self._lock:
            entry = self._current()
            if not entry or entry["kind"] != "video":
                return False
            if entry["video_trim_start"] is None and entry["video_trim_end"] is None:
                return False
            entry["video_trim_start"] = None
            entry["video_trim_end"] = None
            self._touch()
        log_event("video_trim_cleared")
        return True

    def set_video_realtime_options(self, factor, mode):
        with self._lock:
            entry = self._current()
            if (
                not entry
                or entry["kind"] != "video"
                or self._job["running"]
                or (
                    entry["realtime_processor"]
                    and entry["realtime_processor"].running
                )
            ):
                return False
            try:
                factor = int(factor)
            except (TypeError, ValueError):
                return False
            option = next(
                (
                    option for option in self._realtime_output_options(entry)
                    if option["factor"] == factor
                ),
                None,
            )
            if not option or mode not in option["models"]:
                self._set_message(
                    "error",
                    "Select a real-time model supported by the output resolution.",
                )
                return False
            entry["realtime_factor"] = factor
            entry["realtime_model"] = mode
            self._touch()
        log_event("realtime_options_changed", model=mode, factor=factor)
        return True

    def start_video_realtime(self, position=None, mode="", factor=None):
        with self._lock:
            entry = self._current()
            if (
                not entry
                or entry["kind"] != "video"
                or self._job["running"]
            ):
                return False
            try:
                factor = int(
                    entry["realtime_factor"] if factor is None else factor
                )
            except (TypeError, ValueError):
                factor = None
            output_option = next(
                (
                    option for option in self._realtime_output_options(entry)
                    if option["factor"] == factor
                ),
                None,
            )
            if not output_option or mode not in output_option["models"]:
                self._set_message(
                    "error",
                    "Select a real-time model supported by the output resolution.",
                )
                return False
            if entry["realtime_processor"] and entry["realtime_processor"].running:
                return True
            processor = RealTimeVideoProcessor(
                entry["video_path"],
                mode,
                factor,
                output_size=(output_option["width"], output_option["height"]),
                ffmpeg_path=(
                    self._ffmpeg_path() if mode == AMD_VIDEO_SR_MODEL else None
                ),
            )
            entry["realtime_processor"] = processor
            entry["realtime_url"] = self._video_stream.register_realtime(processor)
            entry["realtime_factor"] = factor
            entry["realtime_model"] = mode
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
        log_event(
            "realtime_started",
            model=mode,
            factor=factor,
            position=start_position,
        )
        return True

    def stop_video_realtime(self):
        with self._lock:
            entry = self._current()
            if not entry or entry["kind"] != "video":
                return False
            processor = entry["realtime_processor"]
            url = entry["realtime_url"]
            position = entry["video_position"]
            if processor:
                position = processor.position
                entry["video_position"] = position
                entry["video_frame_index"] = int(
                    entry["video_position"] * entry["video_fps"]
                )
            entry["realtime_url"] = None
            entry["realtime_processor"] = None
            self._touch()
        if url:
            self._video_stream.unregister_realtime(url)
        log_event("realtime_stopped")
        return position

    def set_video_realtime_paused(self, paused):
        requested_at = time.monotonic()
        with self._lock:
            lock_acquired_at = time.monotonic()
            entry = self._current()
            processor = entry["realtime_processor"] if entry and entry["kind"] == "video" else None
            if not processor or not processor.running:
                return False
            processor.set_paused(bool(paused))
            self._touch()
        completed_at = time.monotonic()
        log_event(
            "realtime_pause_changed",
            paused=bool(paused),
            lock_wait_ms=round((lock_acquired_at - requested_at) * 1000, 1),
            handler_ms=round((completed_at - lock_acquired_at) * 1000, 1),
        )
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

    @staticmethod
    def _realtime_frame_image(processor):
        if not processor:
            return None
        encoded = processor.latest_frame
        if not encoded:
            return None
        try:
            with Image.open(io.BytesIO(encoded)) as image:
                return image.convert("RGBA")
        except (OSError, ValueError):
            return None

    def save_video_frame(self, position=None):
        with self._lock:
            entry = self._current()
            if not entry or entry["kind"] != "video" or self._job["running"]:
                return False
            position = entry["video_position"] if position is None else float(position)
            video_path = entry["video_path"]
            processor = entry["realtime_processor"]
            name = f"{entry['name']}_frame_{int(position * max(entry['video_fps'], 1)) + 1:06d}"
            entry_id = entry["id"]
        image = self._realtime_frame_image(processor)
        if image is None:
            image = self._capture_video_frame(video_path, position)
        if image is None:
            return False
        with self._lock:
            current = self._current()
            if not current or current["id"] != entry_id:
                return False
            self._new_entry(image, name, "png")
        return True

