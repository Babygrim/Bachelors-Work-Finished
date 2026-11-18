import queue
import re
import subprocess
import threading
import time
from collections import OrderedDict, deque
from pathlib import Path

import cv2
import numpy as np

from core.config.constants import ROOT_DIR
from core.services.performance import gpu_memory_bytes, process_memory_bytes


AMD_VIDEO_SR_MODEL = "AMD VideoSR (AMF)"


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


class _AMFRealtimeUpscaler:
    def __init__(self, ffmpeg_path, input_size, output_size, fps):
        input_width, input_height = input_size
        self.output_width, self.output_height = output_size
        if min(input_width, input_height, self.output_width, self.output_height) < 32:
            raise ValueError("AMD VideoSR requires input and output dimensions of at least 32 pixels.")
        if any(value % 2 for value in (input_width, input_height, self.output_width, self.output_height)):
            raise ValueError("AMD VideoSR requires even input and output dimensions.")

        filter_graph = (
            "format=nv12,hwupload,"
            f"sr_amf={self.output_width}:{self.output_height}:algorithm=sr1-0:"
            "format=nv12:keep-ratio=false:fill=false,"
            "hwdownload,format=nv12"
        )
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-init_hw_device",
            "amf=amf",
            "-filter_hw_device",
            "amf",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-video_size",
            f"{input_width}x{input_height}",
            "-framerate",
            str(max(float(fps), 1.0)),
            "-i",
            "pipe:0",
            "-vf",
            filter_graph,
            "-fps_mode",
            "passthrough",
            "-flush_packets",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "nv12",
            "pipe:1",
        ]
        self._frame_bytes = self.output_width * self.output_height * 3 // 2
        self._stderr_lock = threading.Lock()
        self._stderr = bytearray()
        self._stop_event = threading.Event()
        self._frames = queue.Queue(maxsize=4)
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as error:
            raise RuntimeError(f"Could not start AMD VideoSR: {error}") from error
        self._stdout_thread = threading.Thread(target=self._read_output, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_errors, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def send_frame(self, frame):
        if self._process.poll() is not None:
            raise RuntimeError(self._process_error("AMD VideoSR stopped unexpectedly."))
        remaining = memoryview(np.ascontiguousarray(frame)).cast("B")
        try:
            while remaining:
                written = self._process.stdin.write(remaining)
                if not written:
                    raise BrokenPipeError("FFmpeg accepted no input frame data.")
                remaining = remaining[written:]
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise RuntimeError(self._process_error("Could not send a frame to AMD VideoSR.")) from error

    def read_frame(self, timeout=15):
        try:
            result = self._frames.get(timeout=timeout)
        except queue.Empty as error:
            self.terminate()
            raise RuntimeError(
                self._process_error(f"AMD VideoSR timed out after {timeout} seconds.")
            ) from error
        if result is None:
            self._wait_for_exit()
            return None
        if isinstance(result, Exception):
            self.terminate()
            raise RuntimeError(self._process_error(str(result))) from result
        return np.frombuffer(result, dtype=np.uint8).reshape(
            self.output_height * 3 // 2,
            self.output_width,
        )

    def finish(self):
        if self._process.stdin and not self._process.stdin.closed:
            self._process.stdin.close()

    def _read_output(self):
        try:
            while True:
                frame = bytearray()
                while len(frame) < self._frame_bytes:
                    chunk = self._process.stdout.read(self._frame_bytes - len(frame))
                    if not chunk:
                        break
                    frame.extend(chunk)
                if not frame:
                    self._enqueue_frame(None)
                    return
                if len(frame) != self._frame_bytes:
                    self._enqueue_frame(
                        RuntimeError(
                            f"FFmpeg returned a partial frame ({len(frame)} of "
                            f"{self._frame_bytes} bytes)."
                        )
                    )
                    return
                if not self._enqueue_frame(bytes(frame)):
                    return
        except Exception as error:
            self._enqueue_frame(error)

    def _enqueue_frame(self, frame):
        while not self._stop_event.is_set():
            try:
                self._frames.put(frame, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _read_errors(self):
        while True:
            chunk = self._process.stderr.read(4096)
            if not chunk:
                return
            with self._stderr_lock:
                self._stderr.extend(chunk)
                if len(self._stderr) > 8192:
                    del self._stderr[:-8192]

    def _process_error(self, message):
        with self._stderr_lock:
            details = self._stderr.decode("utf-8", errors="replace").strip()
        return f"{message} {details}".strip()

    def _wait_for_exit(self):
        try:
            return_code = self._process.wait(timeout=10)
        except subprocess.TimeoutExpired as error:
            self.terminate()
            raise RuntimeError(self._process_error("AMD VideoSR did not exit after input ended.")) from error
        if return_code:
            raise RuntimeError(
                self._process_error(f"AMD VideoSR exited with code {return_code}.")
            )

    def terminate(self):
        self._stop_event.set()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            if stream and not stream.closed:
                stream.close()
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                break
        self._frames.put_nowait(None)
        self._stdout_thread.join(timeout=1)
        self._stderr_thread.join(timeout=1)


class _AMFH264PreviewEncoder:
    def __init__(self, ffmpeg_path, size, fps, revision):
        width, height = size
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "nv12",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            str(max(float(fps), 1.0)),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "h264_amf",
            "-usage",
            "lowlatency",
            "-quality",
            "speed",
            "-latency",
            "1",
            "-async_depth",
            "1",
            "-bf",
            "0",
            "-level",
            "50",
            "-g",
            "15",
            "-flush_packets",
            "1",
            "-f",
            "mp4",
            "-movflags",
            "+empty_moov+default_base_moof+frag_keyframe+frag_every_frame+skip_trailer",
            "pipe:1",
        ]
        self.revision = revision
        self._stop_event = threading.Event()
        self._chunks = queue.Queue(maxsize=64)
        self._stderr_lock = threading.Lock()
        self._stderr = bytearray()
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as error:
            raise RuntimeError(f"Could not start the H.264 preview encoder: {error}") from error
        self._stdout_thread = threading.Thread(target=self._read_output, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_errors, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    @property
    def finished(self):
        return self._stdout_thread is not None and not self._stdout_thread.is_alive()

    def send_frame(self, frame):
        if self._process.poll() is not None:
            raise RuntimeError(self._process_error("The H.264 preview encoder stopped unexpectedly."))
        remaining = memoryview(np.ascontiguousarray(frame)).cast("B")
        try:
            while remaining:
                written = self._process.stdin.write(remaining)
                if not written:
                    raise BrokenPipeError("FFmpeg accepted no H.264 input frame data.")
                remaining = remaining[written:]
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise RuntimeError(
                self._process_error("Could not send a frame to the H.264 preview encoder.")
            ) from error

    def finish(self):
        if self._process.stdin and not self._process.stdin.closed:
            self._process.stdin.close()

    def read_chunk(self, timeout=0.5):
        try:
            chunk = self._chunks.get(timeout=timeout)
        except queue.Empty:
            return None, False
        if chunk is None:
            return None, True
        if isinstance(chunk, Exception):
            raise RuntimeError(str(chunk)) from chunk
        return chunk, False

    def terminate(self):
        self._stop_event.set()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
        if self._process.stdin and not self._process.stdin.closed:
            self._process.stdin.close()
        self._stdout_thread.join(timeout=1)
        self._stderr_thread.join(timeout=1)
        for stream in (self._process.stdout, self._process.stderr):
            if stream and not stream.closed:
                stream.close()
        while True:
            try:
                self._chunks.get_nowait()
            except queue.Empty:
                break
        self._chunks.put_nowait(None)

    def _enqueue(self, chunk):
        while not self._stop_event.is_set():
            try:
                self._chunks.put(chunk, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _read_output(self):
        try:
            while not self._stop_event.is_set():
                chunk = self._process.stdout.read(64 * 1024)
                if not chunk:
                    break
                if not self._enqueue(chunk):
                    return
            if self._stop_event.is_set():
                return
            try:
                return_code = self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._enqueue(RuntimeError("The H.264 preview encoder did not finish."))
                return
            if return_code:
                self._enqueue(
                    RuntimeError(
                        self._process_error(
                            f"The H.264 preview encoder exited with code {return_code}."
                        )
                    )
                )
            self._enqueue(None)
        except Exception as error:
            if not self._stop_event.is_set():
                self._enqueue(RuntimeError(f"Could not read H.264 preview data: {error}"))

    def _read_errors(self):
        while True:
            chunk = self._process.stderr.read(4096)
            if not chunk:
                return
            with self._stderr_lock:
                self._stderr.extend(chunk)
                if len(self._stderr) > 8192:
                    del self._stderr[:-8192]

    def _process_error(self, message):
        with self._stderr_lock:
            details = self._stderr.decode("utf-8", errors="replace").strip()
        return f"{message} {details}".strip()


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
    def __init__(
        self,
        path,
        model,
        scale,
        mode="fast",
        output_size=None,
        ffmpeg_path=None,
    ):
        self.path = Path(path)
        self.model = model
        self.scale = int(scale)
        self.mode = mode
        self.output_size = output_size
        self.ffmpeg_path = ffmpeg_path
        self._condition = threading.Condition()
        self._amf_pipeline_lock = threading.Lock()
        self._amf_pipeline = None
        self._h264_stream = None
        self._latest_jpeg = None
        self._latest_nv12 = None
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
        self._smoothed_frame_time = 0.0
        self._loading = False
        self._loading_stage = "Idle"
        self._position = 0.0
        self._stream_revision = 0
        self._stream_offset = 0.0

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
    def loading_stage(self):
        with self._condition:
            return self._loading_stage

    @property
    def position(self):
        return self._position

    @property
    def latest_frame(self):
        with self._condition:
            encoded = self._latest_jpeg
            frame = self._latest_nv12
        if encoded is not None or frame is None:
            return encoded
        bgr = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_NV12)
        success, encoded_image = cv2.imencode(
            ".jpg",
            bgr,
            [cv2.IMWRITE_JPEG_QUALITY, 85],
        )
        return encoded_image.tobytes() if success else None

    @property
    def stream_revision(self):
        with self._condition:
            return self._stream_revision

    @property
    def stream_offset(self):
        with self._condition:
            return self._stream_offset

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
            if self.model == AMD_VIDEO_SR_MODEL:
                self._stream_revision += 1
                self._stream_offset = self._seek_position
                stream = self._h264_stream
            else:
                stream = None
            self._loading = True
            self._loading_stage = "Seeking to frame"
            self._condition.notify_all()
        if stream:
            stream.terminate()

    def restart_h264_stream(self):
        with self._condition:
            if not self._running or self.model != AMD_VIDEO_SR_MODEL:
                return
            self._stream_revision += 1
            self._stream_offset = self._position
            self._seek_position = self._position
            self._loading = True
            self._loading_stage = "Restarting H.264 preview"
            stream = self._h264_stream
            self._condition.notify_all()
        if stream:
            stream.terminate()

    def fail_h264_stream(self, error):
        with self._condition:
            self._error = str(error)
            self._condition.notify_all()
        self.stop()

    def wait_for_h264_stream(self, revision, timeout=0.5):
        deadline = time.monotonic() + timeout
        with self._condition:
            while (
                revision == self._stream_revision
                and (
                    self._h264_stream is None
                    or self._h264_stream.revision != revision
                )
                and self._running
                and not self._error
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if revision != self._stream_revision:
                return None
            if self._h264_stream and self._h264_stream.revision == revision:
                return self._h264_stream
            return None

    def _set_h264_stream(self, stream):
        with self._condition:
            if stream and stream.revision != self._stream_revision:
                stale = True
            else:
                stale = False
                self._h264_stream = stream
                self._condition.notify_all()
        if stale:
            stream.terminate()

    @property
    def diagnostics(self):
        return {
            "fps": self._processing_fps,
            "device": (
                "GPU (AMD AMF VideoSR + H.264 AMF) + CPU frame readback"
                if self.model == AMD_VIDEO_SR_MODEL
                else "CPU (OpenCV dnn_superres)"
            ),
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
        self._smoothed_frame_time = 0.0
        self._cache_hits = 0
        self._cache_misses = 0
        self._loading = True
        self._loading_stage = "Opening video"
        self._position = max(0.0, float(position))
        self._stream_revision = 0
        self._stream_offset = self._position
        self._h264_stream = None
        self._latest_jpeg = None
        self._latest_nv12 = None
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
            stream = self._h264_stream
            self._condition.notify_all()
        with self._amf_pipeline_lock:
            pipeline = self._amf_pipeline
        if pipeline:
            pipeline.terminate()
        if stream:
            stream.terminate()
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
            if self.model == AMD_VIDEO_SR_MODEL:
                self._run_amf(capture, fps, frame_index)
                return

            self._set_loading_stage("Loading real-time model")
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
            self._set_loading_stage("Upscaling first frame")
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
                frame_started = time.monotonic()
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
                    self._latest_nv12 = None
                    if self._loading:
                        self._loading_stage = "Preparing first preview frame"
                    self._loading = False
                    self._position = frame_index / fps
                    self._sequence += 1
                    self._update_processing_fps(frame_started)
                    self._condition.notify_all()
                frame_index += 1
                next_frame_time += frame_interval
                delay = next_frame_time - time.monotonic()
                if delay > 0:
                    self._stop_event.wait(delay)
                else:
                    next_frame_time = time.monotonic()
        except Exception as error:
            if not self._stop_event.is_set():
                with self._condition:
                    self._error = str(error)
                    self._condition.notify_all()
        finally:
            capture.release()
            with self._amf_pipeline_lock:
                pipeline = self._amf_pipeline
                self._amf_pipeline = None
            if pipeline:
                pipeline.terminate()
            with self._condition:
                self._running = False
                self._condition.notify_all()

    def _run_amf(self, capture, fps, frame_index):
        if not self.ffmpeg_path:
            raise RuntimeError("FFmpeg is required for AMD VideoSR.")
        self._set_loading_stage("Initializing AMD AMF VideoSR")
        pending_frames = deque()
        pipeline = None
        h264_stream = None
        frame_interval = 1.0 / fps
        next_frame_time = time.monotonic()
        completed = False
        try:
            while not self._stop_event.is_set():
                with self._condition:
                    seek_position = self._seek_position
                    self._seek_position = None
                    stream_revision = self._stream_revision
                if seek_position is not None:
                    frame_index = max(0, round(seek_position * fps))
                    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                    if pipeline:
                        pipeline.terminate()
                        pipeline = None
                        with self._amf_pipeline_lock:
                            self._amf_pipeline = None
                    if h264_stream:
                        h264_stream.terminate()
                        h264_stream = None
                        self._set_h264_stream(None)
                    pending_frames.clear()
                    next_frame_time = time.monotonic()
                if (
                    self._pause_event.is_set()
                    and seek_position is None
                    and not self._loading
                ):
                    self._pause_event.wait(0.05)
                    continue
                frame_started = time.monotonic()
                success, frame = capture.read()
                if not success:
                    break

                if pipeline is None:
                    self._set_loading_stage("Upscaling first frame")
                    height, width = frame.shape[:2]
                    output_size = self.output_size or (
                        width * self.scale,
                        height * self.scale,
                    )
                    pipeline = _AMFRealtimeUpscaler(
                        self.ffmpeg_path,
                        (width, height),
                        output_size,
                        fps,
                    )
                    with self._amf_pipeline_lock:
                        self._amf_pipeline = pipeline
                pipeline.send_frame(frame)
                pending_frames.append((frame_index, frame_started))
                frame_index += 1
                if len(pending_frames) < 2:
                    continue
                output = pipeline.read_frame()
                if output is None:
                    raise RuntimeError("AMD VideoSR ended before returning a frame.")
                output_index, output_started = pending_frames.popleft()
                if h264_stream is None:
                    self._set_loading_stage("Preparing H.264 preview")
                    h264_stream = _AMFH264PreviewEncoder(
                        self.ffmpeg_path,
                        output_size,
                        fps,
                        stream_revision,
                    )
                    self._set_h264_stream(h264_stream)
                try:
                    self._publish_amf_frame(
                        output, output_index, fps, h264_stream, output_started
                    )
                except RuntimeError:
                    with self._condition:
                        stream_reset = self._stream_revision != stream_revision
                    if stream_reset and not self._stop_event.is_set():
                        continue
                    raise
                next_frame_time += frame_interval
                delay = next_frame_time - time.monotonic()
                if delay > 0:
                    self._stop_event.wait(delay)
                else:
                    next_frame_time = time.monotonic()

            if not self._stop_event.is_set():
                if pipeline:
                    pipeline.finish()
                while pipeline and pending_frames:
                    output = pipeline.read_frame()
                    if output is None:
                        raise RuntimeError("AMD VideoSR ended before flushing the last frame.")
                    output_index, output_started = pending_frames.popleft()
                    if h264_stream is None:
                        h264_stream = _AMFH264PreviewEncoder(
                            self.ffmpeg_path,
                            output_size,
                            fps,
                            stream_revision,
                        )
                        self._set_h264_stream(h264_stream)
                    self._publish_amf_frame(
                        output, output_index, fps, h264_stream, output_started
                    )
                if pipeline:
                    pipeline._wait_for_exit()
                if h264_stream:
                    h264_stream.finish()
                completed = True
        finally:
            if pipeline:
                pipeline.terminate()
            if h264_stream and not completed:
                h264_stream.terminate()
                self._set_h264_stream(None)
            with self._amf_pipeline_lock:
                self._amf_pipeline = None

    def _publish_amf_frame(self, frame, frame_index, fps, h264_stream, frame_started):
        h264_stream.send_frame(frame)
        with self._condition:
            self._latest_jpeg = None
            self._latest_nv12 = frame
            if self._loading:
                self._loading_stage = "Waiting for decoded preview frame"
            self._loading = False
            self._position = frame_index / fps
            self._sequence += 1
            self._cache_misses += 1
            self._update_processing_fps(frame_started)
            self._condition.notify_all()

    def _set_loading_stage(self, stage):
        with self._condition:
            self._loading_stage = stage
            self._condition.notify_all()

    def _update_processing_fps(self, frame_started):
        now = time.monotonic()
        elapsed = now - frame_started
        if elapsed > 0:
            if self._smoothed_frame_time > 0:
                self._smoothed_frame_time = (
                    self._smoothed_frame_time * 0.9 + elapsed * 0.1
                )
            else:
                self._smoothed_frame_time = elapsed
            self._processing_fps = 1.0 / self._smoothed_frame_time

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
