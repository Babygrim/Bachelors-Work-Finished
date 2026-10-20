from math import ceil

from PIL import Image


def resize_image(photo_image, new_height, new_width):
    resized = photo_image.resize(
        (ceil(new_width), ceil(new_height)),
        Image.Resampling.BICUBIC,
    )
    return resized, 1.0
