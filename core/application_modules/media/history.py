"""Media history management - selecting, browsing, and removing media from history."""


class MediaHistoryManager:
    """Handle media selection, navigation, and removal from history."""

    def select_history(self, image_id):
        """Select a media item from history."""
        with self._lock:
            selected = next((item for item in self._entries if item["id"] == image_id), None)
            if self._job["running"] or not selected or selected["image_loading"]:
                return False
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
            from core.services.app_logging import log_event
            log_event(
                "history_selected",
                item_id=image_id,
                kind=selected["kind"],
            )
        return True

    def remove_image(self):
        """Remove current media from history."""
        from pathlib import Path
        
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
