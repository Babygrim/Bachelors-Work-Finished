"""Media entry creation and management utilities."""

import uuid
from PIL import Image


def create_media_entry(
    media_module,
    image,
    name="image",
    extension="png",
    original_size=None,
    full_resolution=True,
    kind="image",
    video_path=None,
    video_url=None,
    video_fps=0.0,
    video_frame_count=0,
    video_frame_index=0,
    video_position=0.0,
    source_path=None,
    temporary_path=None,
):
    """
    Create a new media entry and add it to the history.
    
    Args:
        media_module: MediaModule instance with access to internal state
        image: PIL Image object
        name: Entry name
        extension: File extension
        original_size: Original image dimensions
        full_resolution: Whether full resolution is loaded
        kind: "image" or "video"
        video_path: Path to source video file
        video_url: URL for streaming video
        video_fps: Video frames per second
        video_frame_count: Total frames in video
        video_frame_index: Current frame index
        video_position: Current playback position
        source_path: Path to source file
        temporary_path: Path to temporary file (for upscaled videos)
        
    Returns:
        dict: The created entry
    """
    entry = {
        "id": uuid.uuid4().hex[:12],
        "image": image.convert("RGBA"),
        "original_size": original_size or image.size,
        "image_loading": not full_resolution,
        "kind": kind,
        "video_path": str(video_path) if video_path else None,
        "video_url": video_url,
        "video_fps": float(video_fps),
        "video_frame_count": int(video_frame_count),
        "video_frame_index": int(video_frame_index),
        "video_position": float(video_position),
        "source_path": str(source_path) if source_path else None,
        "temporary_path": str(temporary_path) if temporary_path else None,
        "realtime_url": None,
        "realtime_processor": None,
        "realtime_model": "",
        "name": name,
        "extension": extension or "png",
        "settings": media_module._default_settings(),
        "scale": 1.0,
    }
    
    # Setup video-specific fields
    if kind == "video":
        realtime_options = media_module._realtime_output_options(entry)
        output_options = media_module._video_output_options(entry)
        
        entry["settings"]["enhancement"]["factor"] = output_options[0]["factor"]
        models = media_module._models_for_factor(output_options[0]["factor"])
        entry["settings"]["enhancement"]["model"] = (
            models[0] if models else "Fast CPU resize + sharpen"
        )
        entry["realtime_factor"] = (
            realtime_options[0]["factor"] if realtime_options else None
        )
        entry["realtime_model"] = (
            realtime_options[0]["models"][0] if realtime_options else ""
        )
    
    # Create thumbnail
    thumbnail = entry["image"].copy()
    thumbnail.thumbnail((150, 100), Image.Resampling.LANCZOS)
    entry["thumbnail_image"] = thumbnail
    entry["thumbnail"] = media_module._image_url(thumbnail)
    
    # Add to entries and update state
    media_module._entries.append(entry)
    media_module._current_id = entry["id"]
    media_module._history_revision += 1
    
    # Set module based on kind
    if kind == "video":
        media_module._module = "Video_Enhancement"
    else:
        media_module._module = "Image_Effects"
    
    media_module._touch(preview=True, immediate=True)
    
    return entry
