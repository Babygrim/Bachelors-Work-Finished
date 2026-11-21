"""Media loading utilities for images and videos."""

from pathlib import Path
import threading
from PIL import Image
import cv2

from core.application_modules.shared import VIDEO_EXTENSIONS


def open_image_dialog(media_module):
    """
    Open file dialog to select an image or video file.
    
    Args:
        media_module: MediaModule instance with access to _get_native_window
        
    Returns:
        bool: True if file was selected and stored in _pending_image_path, False otherwise
    """
    current = media_module._current()
    window = media_module._get_native_window()
    
    if not window or media_module._job["running"] or (current and current["image_loading"]):
        return False
    
    import webview
    selected = window.create_file_dialog(
        webview.FileDialog.OPEN,
        allow_multiple=False,
        file_types=(
            "Media files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tif;*.tiff;*.mp4;*.mov;*.avi;*.mkv;*.webm;*.m4v)",
        ),
    )
    
    if not selected:
        return False
    
    media_module._pending_image_path = selected[0]
    return True


def load_selected_image_file(media_module):
    """
    Load the selected image or video file.
    
    Args:
        media_module: MediaModule instance
        
    Returns:
        bool: True if file was loaded successfully, False otherwise
    """
    path = media_module._pending_image_path
    media_module._pending_image_path = None
    
    if not path or media_module._job["running"]:
        return False
    
    path = Path(path)
    
    # Check if it's a video file
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        return load_video_file(media_module, path)
    
    # Load as image
    try:
        with Image.open(path) as source:
            original_size = source.size
            source.thumbnail((1800, 1400), Image.Resampling.LANCZOS)
            preview = source.convert("RGBA")
        
        with media_module._lock:
            media_module._new_entry(
                preview,
                path.stem,
                path.suffix.lstrip("."),
                original_size=original_size,
                full_resolution=False,
                source_path=path,
            )
            media_module._module = "Image_Effects"
            entry_id = media_module._current_id
        
        # Load full resolution image in background
        threading.Thread(
            target=load_full_resolution_image,
            args=(media_module, entry_id, path),
            daemon=True,
        ).start()
        
        return True
    except Exception as error:
        media_module._set_message("error", f"Could not open image: {error}")
        return False


def load_video_file(media_module, path):
    """
    Load a video file.
    
    Args:
        media_module: MediaModule instance
        path: Path to video file
        
    Returns:
        bool: True if video was loaded successfully, False otherwise
    """
    try:
        create_video_entry_from_path(media_module, path)
    except Exception as error:
        media_module._set_message("error", str(error))
        return False
    return True


def create_video_entry_from_path(media_module, path, temporary_path=None, name=None):
    """
    Create a video entry from a video file path.
    
    Args:
        media_module: MediaModule instance
        path: Path to video file
        temporary_path: Optional path to temporary video file
        name: Optional custom name for the entry
        
    Raises:
        RuntimeError: If video cannot be opened or first frame cannot be read
    """
    capture = cv2.VideoCapture(str(path))
    
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Could not open video: {path.name}")
    
    success, frame = capture.read()
    if not success:
        capture.release()
        raise RuntimeError(f"Could not read the first video frame: {path.name}")
    
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frame_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    video_url = media_module._video_stream.register(path)
    capture.release()
    
    with media_module._lock:
        media_module._new_entry(
            frame_image,
            name or path.stem,
            "png",
            kind="video",
            video_path=path,
            video_url=video_url,
            video_fps=fps,
            video_frame_count=frame_count,
            video_frame_index=0,
            video_position=0,
            source_path=path,
            temporary_path=temporary_path,
        )


def load_full_resolution_image(media_module, entry_id, path):
    """
    Load full resolution image in background.
    
    Args:
        media_module: MediaModule instance
        entry_id: ID of the entry to update
        path: Path to image file
    """
    try:
        with Image.open(path) as source:
            image = source.convert("RGBA")
    except Exception as error:
        with media_module._lock:
            media_module._entries = [
                entry for entry in media_module._entries
                if entry["id"] != entry_id
            ]
            media_module._current_id = (
                media_module._entries[-1]["id"]
                if media_module._entries else None
            )
            media_module._history_revision += 1
            media_module._message = {
                "type": "error",
                "text": f"Could not load full image: {error}"
            }
            media_module._touch(preview=True, immediate=True)
        return
    
    with media_module._lock:
        entry = next(
            (item for item in media_module._entries if item["id"] == entry_id),
            None
        )
        if entry is None:
            return
        
        entry["image"] = image
        entry["image_loading"] = False
        media_module._touch(preview=True)
