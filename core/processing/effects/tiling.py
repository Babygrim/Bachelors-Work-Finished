"""Image tiling - compatibility layer re-exporting from upscaling.tiling module."""

from core.processing.upscaling.tiling import (
    tile_image_with_overlap,
    stitch_tiles_with_blending,
)

__all__ = [
    'tile_image_with_overlap',
    'stitch_tiles_with_blending',
]
