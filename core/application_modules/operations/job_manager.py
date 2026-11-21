"""Job management for image operations (denoise, upscale)."""

import multiprocessing
import threading
import time
from queue import Empty

from core.processing import effects as img_effects
from core.processing import resolution as img_resolution
from core.services.app_logging import log_event
from core.services.time_estimator import UpscalingTimeEstimator, format_time_estimate


def _run_image_operation(function, image, arguments, result_queue, progress_queue):
    """Worker function to run image operation in separate process.
    
    Args:
        function: Image processing function to run
        image: Input image
        arguments: Function arguments
        result_queue: Queue for result (success, result)
        progress_queue: Queue for progress updates
    """
    try:
        result_queue.put((True, function(image, progress_queue, *arguments)))
    except Exception as error:
        result_queue.put((False, str(error)))


class JobManager:
    """Manages job operations within OperationsModule context."""
    
    def __init__(self, operations_module):
        """Initialize with reference to parent OperationsModule."""
        self.module = operations_module
    
    def start_operation(self, operation):
        """Start a denoise or upscale operation.
        
        Args:
            operation: 'denoise' or 'upscale'
            
        Returns:
            True if operation started successfully, False otherwise
        """
        with self.module._lock:
            entry = self.module._current()
            if not entry or entry["image_loading"] or self.module._job["running"]:
                return False
            if entry["kind"] == "video":
                return False
            
            image = self.module._apply_effects(entry["image"], entry["settings"])
            
            if operation == "denoise":
                function = img_effects.denoise_image
                arguments = []
            elif operation == "upscale":
                options = entry["settings"]["enhancement"]
                if not options["model"]:
                    self.module._message = {
                        "type": "error",
                        "text": "No ONNX model is available for this scale."
                    }
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
            
            self.module._job = {
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
            self.module._cancel_event = threading.Event()
            self.module._touch()
            
            self.module._job_thread = threading.Thread(
                target=self._process_operation,
                args=(function, image, arguments, self.module._cancel_event),
                daemon=True,
            )
            self.module._job_thread.start()
        return True
    
    def _process_operation(self, function, image, arguments, cancel_event):
        """Process image operation with progress tracking and time estimation.
        
        Args:
            function: Image processing function
            image: Input image
            arguments: Function arguments
            cancel_event: Event to signal cancellation
        """
        result_queue = multiprocessing.Queue()
        progress_queue = multiprocessing.Queue()
        process = multiprocessing.Process(
            target=_run_image_operation,
            args=(function, image, arguments, result_queue, progress_queue),
            daemon=True,
        )
        
        time_estimator = UpscalingTimeEstimator()
        start_time = time.time()
        
        with self.module._lock:
            self.module._process = process
            self.module._job["status"] = "Processing"
        
        try:
            process.start()
            while True:
                if cancel_event.is_set():
                    process.terminate()
                    process.join()
                    return
                
                try:
                    progress = progress_queue.get(timeout=0.05)
                    elapsed = time.time() - start_time
                    with self.module._lock:
                        if isinstance(progress, dict):
                            percent = int(progress.get("percent", 0))
                            estimated_total = time_estimator.estimate_total_time(percent, elapsed)
                            remaining = max(0, estimated_total - elapsed)
                            self.module._job.update(
                                stage=str(progress.get("stage", "")),
                                current=int(progress.get("current", 0)),
                                total=int(progress.get("total", 0)),
                                unit=str(progress.get("unit", "tile")),
                                progress=max(0, min(100, percent)),
                                elapsed_time=round(elapsed, 1),
                                estimated_total_time=round(estimated_total, 1),
                                estimated_remaining_time=round(remaining, 1),
                                time_estimate_formatted=format_time_estimate(estimated_total),
                                time_remaining_formatted=format_time_estimate(remaining),
                            )
                        elif isinstance(progress, (int, float)):
                            percent = max(0, min(100, int(progress)))
                            estimated_total = time_estimator.estimate_total_time(percent, elapsed)
                            remaining = max(0, estimated_total - elapsed)
                            self.module._job.update(
                                progress=percent,
                                elapsed_time=round(elapsed, 1),
                                estimated_total_time=round(estimated_total, 1),
                                estimated_remaining_time=round(remaining, 1),
                                time_estimate_formatted=format_time_estimate(estimated_total),
                                time_remaining_formatted=format_time_estimate(remaining),
                            )
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
                
                with self.module._lock:
                    current = self.module._current()
                    name = current["name"] if current else "image"
                    extension = current["extension"] if current else "png"
                    kind = self.module._job.get("kind", "processing")
                    self.module._new_entry(result, name, extension)
                    self.module._job = {
                        "running": False,
                        "progress": 100,
                        "status": "Complete",
                        "kind": kind,
                        "error": None,
                    }
                return
        
        except Exception as error:
            with self.module._lock:
                kind = self.module._job.get("kind", "processing")
                self.module._job = {
                    "running": False,
                    "progress": 0,
                    "status": "Failed",
                    "kind": kind,
                    "error": str(error),
                }
                self.module._message = {"type": "error", "text": str(error)}
                self.module._touch()
        
        finally:
            if process.pid is not None:
                if process.is_alive():
                    process.join(timeout=0.2)
                else:
                    process.join()
            
            with self.module._lock:
                self.module._process = None
                if cancel_event.is_set():
                    self.module._job = {
                        "running": False,
                        "progress": 0,
                        "status": "Cancelled",
                        "error": None
                    }
                    self.module._touch()
            
            result_queue.close()
            progress_queue.close()
    
    def cancel_operation(self):
        """Cancel the currently running operation.
        
        Returns:
            True if operation was cancelled, False if no operation running
        """
        with self.module._lock:
            if not self.module._job["running"] or not self.module._cancel_event:
                return False
            self.module._cancel_event.set()
            self.module._job["status"] = "Cancelled"
            self.module._job["stage"] = "cancel"
            self.module._job["running"] = False
            if self.module._process and self.module._process.is_alive():
                self.module._process.terminate()
            self.module._touch()
        log_event("operation_cancelled")
        return True
    
    def dismiss_job(self):
        """Dismiss job status.
        
        Returns:
            True
        """
        with self.module._lock:
            if not self.module._job["running"]:
                self.module._job = {
                    "running": False,
                    "progress": 0,
                    "status": "",
                    "error": None
                }
                self.module._touch()
        return True
