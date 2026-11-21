"""FFmpeg utilities and availability checks."""

import os
import shutil
import threading
import time
from pathlib import Path

# Cache FFmpeg path to avoid repeated PATH scans during frequent UI polling
_ffmpeg_path_cache = (0.0, None)
_ffmpeg_path_lock = threading.Lock()


def find_ffmpeg_path():
    """
    Find FFmpeg executable in system PATH or Windows package manager.
    
    Returns:
        str or None: Path to ffmpeg executable if found, None otherwise.
        Result is cached for 5 seconds to minimize PATH scanning overhead.
    """
    global _ffmpeg_path_cache
    now = time.monotonic()
    
    # Check cache first
    with _ffmpeg_path_lock:
        cached_at, cached_path = _ffmpeg_path_cache
        if now - cached_at < 5.0:
            return cached_path
    
    # Try standard PATH lookup
    ffmpeg = shutil.which("ffmpeg")
    
    # Try Windows package manager installation if not in PATH
    if not ffmpeg:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            package_root = Path(local_app_data, "Microsoft", "WinGet", "Packages")
            if package_root.is_dir():
                matches = sorted(
                    package_root.glob("Gyan.FFmpeg.Shared_*/ffmpeg-*/bin/ffmpeg.exe")
                )
                ffmpeg = str(matches[-1]) if matches else None
    
    # Update cache
    with _ffmpeg_path_lock:
        _ffmpeg_path_cache = (now, ffmpeg)
    
    return ffmpeg


def is_ffmpeg_available():
    """Check if FFmpeg is available on the system."""
    return find_ffmpeg_path() is not None
