"""Media state queries and reporting."""

from core.services.upscalers.constants import AMD_VIDEO_SR_MODEL
from core.application_modules.media.media_state import create_media_entry
from pathlib import Path


class MediaStateManager:
    """Query and report current media state."""

    @staticmethod
    def _ffmpeg_path():
        """Get path to FFmpeg executable."""
        from core.services.ffmpeg_utils import find_ffmpeg_path
        return find_ffmpeg_path()

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
        """Create a new media entry."""
        return create_media_entry(
            self,
            image,
            name=name,
            extension=extension,
            original_size=original_size,
            full_resolution=full_resolution,
            kind=kind,
            video_path=video_path,
            video_url=video_url,
            video_fps=video_fps,
            video_frame_count=video_frame_count,
            video_frame_index=video_frame_index,
            video_position=video_position,
            source_path=source_path,
            temporary_path=temporary_path,
        )

    def get_state(self, previous_revision=None, previous_history_revision=None):
        """Get complete media state for rendering."""
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
                            option for option in self._realtime_output_options(entry)
                            if option["factor"] == entry["realtime_factor"]
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
                    "realtime_factor": entry["realtime_factor"],
                    "realtime_model": entry["realtime_model"],
                    "realtime_options": self._realtime_output_options(entry),
                    "realtime_transport": (
                        "mse"
                        if entry["realtime_model"] == AMD_VIDEO_SR_MODEL
                        else "mjpeg"
                    ),
                    "realtime_stream_revision": (
                        entry["realtime_processor"].stream_revision
                        if entry["realtime_processor"] else 0
                    ),
                    "realtime_stream_offset": (
                        entry["realtime_processor"].stream_offset
                        if entry["realtime_processor"] else entry["video_position"]
                    ),
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
                    "realtime_stage": (
                        entry["realtime_processor"].loading_stage
                        if entry["realtime_processor"] else "Idle"
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
                "models": self._video_models_for_factor(entry["settings"]["enhancement"]["factor"], entry)
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
        """Get debug diagnostics from current operation or realtime processor."""
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
        """Get current job/operation state."""
        with self._lock:
            return dict(self._job)
