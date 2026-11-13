import threading
import time
from collections import OrderedDict
from pathlib import Path
import re

import cv2

from core.config.constants import ROOT_DIR
from core.services.performance import gpu_memory_bytes, process_memory_bytes


class _RealtimeUpscaler:
    def __init__(self, model_path):
        match = re.match(r"(?P<algorithm>.+)_x(?P<scale>[248])$", model_path.stem, re.IGNORECASE)
        if not match:
            raise ValueError(f"Unsupported real-time model name: {model_path.name}")
        if not hasattr(cv2, "dnn_superres"):
            raise RuntimeError("OpenCV was built without dnn_superres support.")
        self._upscaler = cv2.dnn_superres.DnnSuperResImpl_create()
        self._upscaler.readModel(str(model_path))
        algorithm = match.group("algorithm").split("-", 1)[0].lower()
        self._upscaler.setModel(algorithm, int(match.group("scale")))

    def enhance(self, frame):
        return self._upscaler.upsample(frame)


class _RealtimeFrameCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._frames = OrderedDict()
        self._bytes = 0
        self._max_frames = 0

    def configure(self, max_frames):
        with self._lock:
            self._max_frames = max(1, max_frames)
            self._trim()

    def get(self, frame_index):
        with self._lock:
            frame = self._frames.pop(frame_index, None)
            if frame is not None:
                self._frames[frame_index] = frame
            return frame

    def put(self, frame_index, encoded):
        with self._lock:
            previous = self._frames.pop(frame_index, None)
            if previous is not None:
                self._bytes -= len(previous)
            self._frames[frame_index] = encoded
            self._bytes += len(encoded)
            self._trim()

    def _trim(self):
        while (
            len(self._frames) > self._max_frames
            or self._bytes > 256 * 1024 * 1024
        ):
            _, oldest = self._frames.popitem(last=False)
            self._bytes -= len(oldest)

    @property
    def frame_count(self):
        with self._lock:
            return len(self._frames)


_CACHE_REGISTRY = {}
_CACHE_REGISTRY_LOCK = threading.Lock()


def _shared_cache(path, model, scale, output_size):
    key = (str(path.resolve()), model, int(scale), tuple(output_size or ()))
    with _CACHE_REGISTRY_LOCK:
        return _CACHE_REGISTRY.setdefault(key, _RealtimeFrameCache())


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
        self._pause_event = threading.Event()
        self._thread = None
        self._error = None
        self._cache = _shared_cache(self.path, model, scale, output_size)
        self._seek_position = None
        self._cache_hits = 0
        self._cache_misses = 0
        self._processing_fps = 0.0
        self._processed_frames = 0
        self._processing_started = 0.0
        self._loading = False
        self._position = 0.0

    @property
    def running(self):
        return self._running

    @property
    def error(self):
        return self._error

    @property
    def paused(self):
        return self._pause_event.is_set()

    @property
    def loading(self):
        return self._loading

    @property
    def position(self):
        return self._position

    @property
    def latest_frame(self):
        with self._condition:
            return self._latest_jpeg

    def set_paused(self, paused):
        if paused:
            self._pause_event.set()
            with self._condition:
                if self._latest_jpeg is not None:
                    self._loading = False
        else:
            self._pause_event.clear()
        with self._condition:
            self._condition.notify_all()

    def seek(self, position):
        with self._condition:
            self._seek_position = max(0.0, float(position))
            self._loading = True
            self._condition.notify_all()

    @property
    def diagnostics(self):
        return {
            "fps": self._processing_fps,
            "device": "CPU (OpenCV dnn_superres)",
            "ram_bytes": process_memory_bytes(),
            "gpu_memory_bytes": gpu_memory_bytes(),
            "cache_frames": self._cache.frame_count,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "loading": self._loading,
        }

    def start(self, position=0.0):
        if self._running:
            return False
        self._stop_event.clear()
        self._pause_event.clear()
        self._error = None
        self._processing_fps = 0.0
        self._processed_frames = 0
        self._processing_started = time.monotonic()
        self._cache_hits = 0
        self._cache_misses = 0
        self._loading = True
        self._position = max(0.0, float(position))
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
            fps = max(capture.get(cv2.CAP_PROP_FPS), 1.0)
            frame_index = max(0, round(position * fps))
            if frame_index:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            self._cache.configure(round(fps * 300))

            realtime_weights = Path(ROOT_DIR, "weights", "realtime")
            model_paths = sorted(
                (
                    path for path in realtime_weights.iterdir()
                    if path.stem == self.model
                    and path.suffix.lower() in (".pb", ".onnx")
                )
            ) if realtime_weights.is_dir() else []
            if not model_paths:
                raise FileNotFoundError(
                    f"Real-time model not found in weights/realtime: {self.model}"
                )
            upscaler = _RealtimeUpscaler(model_paths[0])
            frame_interval = 1.0 / fps
            next_frame_time = time.monotonic()

            while not self._stop_event.is_set():
                with self._condition:
                    seek_position = self._seek_position
                    self._seek_position = None
                if seek_position is not None:
                    frame_index = max(0, round(seek_position * fps))
                    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                if (
                    self._pause_event.wait(0.05)
                    and seek_position is None
                    and not self._loading
                ):
                    continue
                success, frame = capture.read()
                if not success:
                    break
                cached = self._get_cached_frame(frame_index)
                if cached is not None:
                    encoded = cached
                    self._cache_hits += 1
                else:
                    self._cache_misses += 1
                    output = self._process_frame(frame, upscaler, self.output_size)
                    success, encoded_image = cv2.imencode(
                        ".jpg",
                        output,
                        [cv2.IMWRITE_JPEG_QUALITY, 85],
                    )
                    if not success:
                        frame_index += 1
                        continue
                    encoded = encoded_image.tobytes()
                    self._cache_frame(frame_index, encoded)
                with self._condition:
                    self._latest_jpeg = encoded
                    self._loading = False
                    self._position = frame_index / fps
                    self._sequence += 1
                    self._processed_frames += 1
                    elapsed = time.monotonic() - self._processing_started
                    if elapsed > 0:
                        self._processing_fps = self._processed_frames / elapsed
                    self._condition.notify_all()
                frame_index += 1
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

    def _get_cached_frame(self, frame_index):
        return self._cache.get(frame_index)

    def _cache_frame(self, frame_index, encoded):
        self._cache.put(frame_index, encoded)

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
