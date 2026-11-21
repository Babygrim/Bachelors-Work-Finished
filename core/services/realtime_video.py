import math
import threading
import time
from collections import deque
from pathlib import Path

import cv2

from core.config.constants import ROOT_DIR
from core.services.performance import gpu_memory_bytes, process_memory_bytes
from core.services.upscalers.constants import AMD_VIDEO_SR_MODEL, AMF_PREVIEW_BUFFER_SECONDS, AMF_PIPELINE_DEPTH
from core.services.upscalers.opencv_upscaler import _RealtimeUpscaler
from core.services.upscalers.amf_upscaler import _AMFRealtimeUpscaler
from core.services.upscalers.frame_cache import _shared_cache, _RealtimeFrameCache
from core.services.encoders.h264_encoder import _AMFH264PreviewEncoder


__all__ = ["RealTimeVideoProcessor"]


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
        self._publish_times = deque()
        self._loading = False
        self._loading_stage = "Idle"
        self._startup_buffer_frames_required = 1
        self._startup_buffer_frames_sent = 0
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
                self._startup_buffer_frames_sent = 0
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
        self._publish_times.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        self._loading = True
        self._loading_stage = "Opening video"
        self._startup_buffer_frames_sent = 0
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
                    self._update_processing_fps()
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
        with self._condition:
            self._startup_buffer_frames_required = max(
                1, math.ceil(fps * AMF_PREVIEW_BUFFER_SECONDS) + 1
            )
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
                    with self._condition:
                        self._startup_buffer_frames_sent = 0
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
                if len(pending_frames) < AMF_PIPELINE_DEPTH:
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
                with self._condition:
                    self._loading = False
                    self._condition.notify_all()
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
                self._startup_buffer_frames_sent += 1
                if (
                    h264_stream.has_encoded_frame
                    and self._startup_buffer_frames_sent
                    >= self._startup_buffer_frames_required
                ):
                    self._loading = False
                elif h264_stream.has_encoded_frame:
                    self._loading_stage = "Buffering preview"
                else:
                    self._loading_stage = "Waiting for H.264 encoder output"
            self._position = frame_index / fps
            self._sequence += 1
            self._cache_misses += 1
            self._update_processing_fps()
            self._condition.notify_all()

    def _set_loading_stage(self, stage):
        with self._condition:
            self._loading_stage = stage
            self._condition.notify_all()

    def _update_processing_fps(self):
        # Rate of frames actually delivered over the last second. Per-frame latency (read -> publish)
        # is wrong here: the AMF pipeline keeps several frames in flight, so latency is a multiple
        # of the frame time. Per-frame intervals are too jittery because of the pacing sleeps.
        now = time.monotonic()
        times = self._publish_times
        if times and now - times[-1] > 2.0:
            times.clear()  # pause or seek: not processing speed
        times.append(now)
        while now - times[0] > 1.0:
            times.popleft()
        if len(times) >= 2 and times[-1] > times[0]:
            self._processing_fps = (len(times) - 1) / (times[-1] - times[0])

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
