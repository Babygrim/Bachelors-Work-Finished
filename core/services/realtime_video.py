import threading
import time
from pathlib import Path

import cv2

from core.config.constants import (
    IMAGE_TILE_OVERLAP,
    IMAGE_TILE_SIZE,
    ROOT_DIR,
)


class RealTimeVideoProcessor:
    def __init__(self, path, model, scale, mode="fast", output_size=None):
        self.path = Path(path)
        self.model = model
        self.scale = int(scale)
        self.mode = mode
        self.output_size = output_size
        self._condition = threading.Condition()
        self._latest_jpeg = None
        self._sequence = 0
        self._running = False
        self._stop_event = threading.Event()
        self._thread = None
        self._error = None

    @property
    def running(self):
        return self._running

    @property
    def error(self):
        return self._error

    def start(self, position=0.0):
        if self._running:
            return False
        self._stop_event.clear()
        self._error = None
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(max(0.0, float(position)),),
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
        self._thread = None
        self._running = False

    def wait_for_frame(self, sequence, timeout=1.0):
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._sequence <= sequence and self._running and not self._error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._sequence, self._latest_jpeg

    def _run(self, position):
        capture = cv2.VideoCapture(str(self.path))
        try:
            if not capture.isOpened():
                raise RuntimeError(f"Could not open video: {self.path.name}")
            if position:
                capture.set(cv2.CAP_PROP_POS_MSEC, position * 1000)

            upscaler = None
            if self.mode == "ai":
                model_path = Path(ROOT_DIR, "weights", f"{self.model}.onnx")
                if not model_path.is_file():
                    raise FileNotFoundError(f"Weight file not found: {model_path}")
                from core.models.onnx_realesrganer import OnnxRealESRGANer

                upscaler = OnnxRealESRGANer(
                    scale=self.scale,
                    pth_path=str(model_path),
                    tile=IMAGE_TILE_SIZE,
                    tile_pad=IMAGE_TILE_OVERLAP,
                )
            frame_interval = 1.0 / max(capture.get(cv2.CAP_PROP_FPS), 1.0)
            next_frame_time = time.monotonic()

            while not self._stop_event.is_set():
                success, frame = capture.read()
                if not success:
                    break
                output = self._process_frame(frame, upscaler, self.output_size)
                success, encoded = cv2.imencode(
                    ".jpg",
                    output,
                    [cv2.IMWRITE_JPEG_QUALITY, 85],
                )
                if not success:
                    continue
                with self._condition:
                    self._latest_jpeg = encoded.tobytes()
                    self._sequence += 1
                    self._condition.notify_all()
                next_frame_time += frame_interval
                delay = next_frame_time - time.monotonic()
                if delay > 0:
                    self._stop_event.wait(delay)
                else:
                    next_frame_time = time.monotonic()
        except Exception as error:
            with self._condition:
                self._error = str(error)
                self._condition.notify_all()
        finally:
            capture.release()
            with self._condition:
                self._running = False
                self._condition.notify_all()

    @staticmethod
    def _process_frame(frame, upscaler, output_size=None):
        if upscaler is not None:
            output = upscaler.enhance(frame)
            if output_size and output.shape[1::-1] != output_size:
                output = cv2.resize(output, output_size, interpolation=cv2.INTER_AREA)
            return output
        output_width, output_height = output_size or (frame.shape[1], frame.shape[0])
        source_height, source_width = frame.shape[:2]
        scale = min(
            output_width / source_width,
            output_height / source_height,
        )
        resized = cv2.resize(
            frame,
            (round(source_width * scale), round(source_height * scale)),
            interpolation=cv2.INTER_LINEAR,
        )
        output = cv2.copyMakeBorder(
            resized,
            (output_height - resized.shape[0]) // 2,
            output_height - resized.shape[0]
            - (output_height - resized.shape[0]) // 2,
            (output_width - resized.shape[1]) // 2,
            output_width - resized.shape[1]
            - (output_width - resized.shape[1]) // 2,
            cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        )
        blurred = cv2.GaussianBlur(output, (0, 0), 1.0)
        return cv2.addWeighted(output, 1.15, blurred, -0.15, 0)
