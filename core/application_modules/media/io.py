"""Media I/O operations - loading and saving files."""

from core.services import media_loader, media_exporter


class MediaIOManager:
    """Handle file open/save dialogs and I/O operations."""

    def open_image(self):
        """Open file dialog to select image or video."""
        return media_loader.open_image_dialog(self)

    def load_selected_image(self):
        """Load selected image or video file."""
        return media_loader.load_selected_image_file(self)

    def _load_video(self, path):
        """Load a video file."""
        return media_loader.load_video_file(self, path)

    def _create_video_entry_from_path(self, path, temporary_path=None, name=None):
        """Create video entry from path."""
        return media_loader.create_video_entry_from_path(
            self, path, temporary_path=temporary_path, name=name
        )

    def _load_full_resolution_image(self, entry_id, path):
        """Load full resolution image in background."""
        return media_loader.load_full_resolution_image(self, entry_id, path)

    def save_image(self):
        """Save image file."""
        return media_exporter.save_image_dialog(self)

    def save_video(self):
        """Save video file."""
        return media_exporter.save_video_dialog(self)

    def start_video_upscale(self):
        """Start video upscaling process."""
        return media_exporter.start_video_upscale_process(self)

    def _export_video_worker(self, source_path, output_path, cancel_event):
        """Export video worker."""
        return media_exporter.export_video_worker(self, source_path, output_path, cancel_event)

    def _upscale_video_worker(self, source_path, output_path, options, cancel_event):
        """Upscale video worker."""
        return media_exporter.upscale_video_worker(self, source_path, output_path, options, cancel_event)

    def _export_image_worker(self, image, settings, path):
        """Export image worker."""
        return media_exporter.export_image_worker(self, image, settings, path)
