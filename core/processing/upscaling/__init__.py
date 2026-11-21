"""Image upscaling and resizing operations."""

import numpy as np
import cv2
from time import time
from PIL import Image

from core.models.gfpganer import GFPGANer
from core.models.factory import create_upscaler
from core.config.constants import IMAGE_TILE_OVERLAP, IMAGE_TILE_SIZE
import multiprocessing


def upscale_image(input_image, progress_bar_queue, keep_size, model, face_restoration, upscale_factor):
    """Upscale an image using the specified model."""
    upscale_factor = int(upscale_factor)
    outscale_factor = 1 / upscale_factor if keep_size else 1

    num_threads = max(2, min(multiprocessing.cpu_count() // 2, 4))

    start_time = time()
    upscaler = create_upscaler(
        model, upscale_factor, IMAGE_TILE_SIZE, IMAGE_TILE_OVERLAP, num_threads,
    )
    if face_restoration:
        upscaler_GFPGAN = GFPGANer(
            upscale=upscale_factor,
            bg_upsampler=upscaler,
            arch='clean',
        )
        # GFPGAN / facexlib work on BGR arrays (the face model gets wrong colours from RGB input).
        bgr = cv2.cvtColor(np.array(input_image.convert("RGB")), cv2.COLOR_RGB2BGR)
        restored_bgr = upscaler_GFPGAN.enhance(bgr, progress_queue=progress_bar_queue)
        final_image = Image.fromarray(cv2.cvtColor(restored_bgr, cv2.COLOR_BGR2RGB))
    else:
        img_bgr = cv2.cvtColor(np.array(input_image), cv2.COLOR_RGB2BGR)
        output_bgr = upscaler.enhance(img_bgr, progress_queue=progress_bar_queue)
        final_image = Image.fromarray(cv2.cvtColor(output_bgr, cv2.COLOR_BGR2RGB))
    if outscale_factor < 1:
        final_image = resize_image(final_image, outscale_factor)
    
    print(f"Upscaling completed in {time() - start_time:.2f} seconds.")
    return final_image


def resize_image(image, scale_factor):
    """Resize an image by a scale factor."""
    from math import ceil
    new_height = ceil(image.height * scale_factor)
    new_width = ceil(image.width * scale_factor)
    resized = image.resize(
        (new_width, new_height),
        Image.Resampling.BICUBIC,
    )
    return resized
