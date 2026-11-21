"""Image cropping operations."""

class ImageCropManager:
    """Handle image cropping operations."""

    @staticmethod
    def _crop_bounds(image, bounds):
        """Crop image to specified bounds."""
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
        """Crop current image or video frame."""
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
