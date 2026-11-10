import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


class VideoStreamServer:
    def __init__(self):
        self._lock = threading.Lock()
        self._videos = {}
        self._realtime = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_HEAD(self):
                owner._serve(self, send_body=False)

            def do_GET(self):
                owner._serve(self, send_body=True)

            def do_OPTIONS(self):
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Range")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format, *args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def address(self):
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def register(self, path):
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._videos[token] = Path(path).resolve()
        return f"{self.address}/video/{token}"

    def _serve(self, handler, send_body):
        request_path = urlparse(handler.path).path
        if request_path.startswith("/realtime/"):
            self._serve_realtime(handler, send_body)
            return
        token = unquote(request_path.removeprefix("/video/")).strip("/")
        with self._lock:
            path = self._videos.get(token)
        if not path or not path.is_file():
            handler.send_error(404)
            return

        size = path.stat().st_size
        start = 0
        end = size - 1
        status = 200
        range_header = handler.headers.get("Range")
        if range_header:
            if not range_header.startswith("bytes=") or "," in range_header:
                self._send_range_error(handler, size)
                return
            value = range_header[6:].strip()
            first, separator, last = value.partition("-")
            if not separator:
                self._send_range_error(handler, size)
                return
            try:
                if not first:
                    suffix_length = int(last)
                    if suffix_length <= 0:
                        raise ValueError
                    start = max(0, size - suffix_length)
                else:
                    start = int(first)
                    end = int(last) if last else size - 1
                if start < 0 or start >= size or end < start:
                    raise ValueError
                end = min(end, size - 1)
            except ValueError:
                self._send_range_error(handler, size)
                return
            status = 206

        length = end - start + 1
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Cache-Control", "private, max-age=3600")
        handler.send_header("Content-Length", str(length))
        if status == 206:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.end_headers()
        if not send_body:
            return

        try:
            with path.open("rb") as video_file:
                video_file.seek(start)
                remaining = length
                while remaining:
                    chunk = video_file.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def register_realtime(self, processor):
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._realtime[token] = processor
        return f"{self.address}/realtime/{token}"

    def unregister_realtime(self, url):
        token = unquote(urlparse(url).path.removeprefix("/realtime/")).strip("/")
        with self._lock:
            processor = self._realtime.pop(token, None)
        if processor:
            processor.stop()

    def _serve_realtime(self, handler, send_body):
        token = unquote(urlparse(handler.path).path.removeprefix("/realtime/")).strip("/")
        with self._lock:
            processor = self._realtime.get(token)
        if not processor:
            handler.send_error(404)
            return
        if not send_body:
            handler.send_response(200)
            handler.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.send_header("Connection", "close")
            handler.end_headers()
            return

        handler.send_response(200)
        handler.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Cache-Control", "no-cache, no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        sequence = 0
        try:
            while processor.running or processor.error:
                sequence, jpeg = processor.wait_for_frame(sequence)
                if jpeg is None:
                    if processor.error:
                        break
                    continue
                handler.wfile.write(
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
                    + jpeg
                    + b"\r\n"
                )
                handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    @staticmethod
    def _send_range_error(handler, size):
        handler.send_response(416)
        handler.send_header("Content-Range", f"bytes */{size}")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    def close(self):
        with self._lock:
            processors = list(self._realtime.values())
            self._realtime.clear()
        for processor in processors:
            processor.stop()
        self._server.shutdown()
        self._server.server_close()
