"""Chroma handling for the AMD VideoSR (AMF) real-time pipeline.

AMF's SR1.0 upscales luma well but returns a weak chroma plane (~1.7 dB PSNR below
what the source chroma allows). The NV12 chroma plane is half the output size, so
for a 2x upscale it is the source's own full-resolution chroma. This module builds
that plane from the source frame so it can replace AMF's UV plane.
"""

import cv2
import numpy as np

# BT.601 full-range -> limited-range chroma (16..240), matching ffmpeg's bgr24 -> nv12.
_CHROMA_LUT = np.clip(
    np.round(128 + (np.arange(256) - 128) * 224 / 255), 0, 255
).astype(np.uint8)


def source_chroma_plane(frame_bgr, output_size):
    """Return the NV12 UV plane (output_h // 2 rows, output_w bytes) built from the source frame."""
    output_width, output_height = output_size
    ycrcb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2YCrCb)
    cr = cv2.LUT(ycrcb[:, :, 1], _CHROMA_LUT)
    cb = cv2.LUT(ycrcb[:, :, 2], _CHROMA_LUT)
    uv = cv2.merge((cb, cr))
    chroma_size = (output_width // 2, output_height // 2)
    if (uv.shape[1], uv.shape[0]) != chroma_size:
        uv = cv2.resize(uv, chroma_size, interpolation=cv2.INTER_CUBIC)
    return uv.reshape(chroma_size[1], chroma_size[0] * 2)
