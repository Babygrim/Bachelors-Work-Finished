"""Job/operation control and telemetry."""

from core.services.app_logging import log_event, log_toast


class JobOperations:
    """Handle job/operation control, progress, and logging."""

    def start_operation(self, operation):
        """Start a denoise or upscale operation."""
        return self._job_manager.start_operation(operation)

    def _process_operation(self, function, image, arguments, cancel_event):
        """Process image operation with progress tracking."""
        return self._job_manager._process_operation(function, image, arguments, cancel_event)

    def cancel_operation(self):
        """Cancel the currently running operation."""
        return self._job_manager.cancel_operation()

    def dismiss_job(self):
        """Dismiss job status."""
        return self._job_manager.dismiss_job()

    def _set_message(self, kind, text):
        """Set an internal message."""
        with self._lock:
            self._message = {"type": kind, "text": text}
            self._touch()

    def log_toast(self, kind, text):
        """Log a toast notification."""
        log_toast(kind, text)

    def log_event(self, event, details=None):
        """Log an event."""
        log_event(event, **(details if isinstance(details, dict) else {}))
        return True
