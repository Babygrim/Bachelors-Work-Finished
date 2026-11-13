import cv2
import io
from pathlib import Path

from PIL import Image

from core.services.app_logging import log_event
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

    def start_video_realtime(self, position=None, mode=""):
        with self._lock:
            entry = self._current()
            if (
                not entry
                or entry["kind"] != "video"
                or self._job["running"]
            ):
                return False
            if mode not in self._realtime_models():
                self._set_message("error", "Select an available real-time model.")
                return False
            if entry["realtime_processor"] and entry["realtime_processor"].running:
                return True
            output_option = next(
                option for option in self._video_output_options(entry)
                if option["factor"] == entry["settings"]["enhancement"]["factor"]
            )
            processor = RealTimeVideoProcessor(
                entry["video_path"],
                mode,
                entry["settings"]["enhancement"]["factor"],
                output_size=(output_option["width"], output_option["height"]),
            )
            entry["realtime_processor"] = processor
            entry["realtime_url"] = self._video_stream.register_realtime(processor)
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
            factor=entry["settings"]["enhancement"]["factor"],
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
        with self._lock:
            entry = self._current()
            processor = entry["realtime_processor"] if entry and entry["kind"] == "video" else None
            if not processor or not processor.running:
                return False
            processor.set_paused(bool(paused))
            self._touch()
        log_event("realtime_pause_changed", paused=bool(paused))
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

