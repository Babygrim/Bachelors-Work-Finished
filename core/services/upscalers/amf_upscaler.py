"""AMD AMF-based real-time upscaler."""

import queue
import subprocess
import threading

import numpy as np


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
                # readinto a preallocated buffer: chunked read()+extend was ~3x slower on Windows pipes.
                frame = bytearray(self._frame_bytes)
                view = memoryview(frame)
                filled = 0
                while filled < self._frame_bytes:
                    received = self._process.stdout.readinto(view[filled:])
                    if not received:
                        break
                    filled += received
                if not filled:
                    self._enqueue_frame(None)
                    return
                if filled != self._frame_bytes:
                    self._enqueue_frame(
                        RuntimeError(
                            f"FFmpeg returned a partial frame ({filled} of "
                            f"{self._frame_bytes} bytes)."
                        )
                    )
                    return
                if not self._enqueue_frame(frame):
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
