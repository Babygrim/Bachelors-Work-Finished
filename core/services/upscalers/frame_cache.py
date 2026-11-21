"""Real-time frame caching for video processing."""

import threading
from collections import OrderedDict


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
