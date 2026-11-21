"""AMD AMF H.264 preview encoder."""

import queue
import subprocess
import threading

import numpy as np


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
        self._first_frame_event = threading.Event()
        self._output_scan_tail = b""
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

    @property
    def has_encoded_frame(self):
        return self._first_frame_event.is_set()

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
                if b"moof" in self._output_scan_tail + chunk:
                    self._first_frame_event.set()
                self._output_scan_tail = (self._output_scan_tail + chunk)[-3:]
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
