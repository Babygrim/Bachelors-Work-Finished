import numpy as np
from PIL import Image

def tile_image_with_overlap(image: Image.Image, tile_size: int, overlap: int):
    width, height = image.size
    stride = tile_size - overlap

    tiles = []
    positions = []
    valid_sizes = []  # Track real image size before padding

    for y in range(0, height, stride):
        for x in range(0, width, stride):
            x_end = min(x + tile_size, width)
            y_end = min(y + tile_size, height)
            real_w = x_end - x
            real_h = y_end - y

            tile = image.crop((x, y, x_end, y_end))
            padded_tile = Image.new("RGB", (tile_size, tile_size))
            padded_tile.paste(tile, (0, 0))

            tiles.append(padded_tile)
            positions.append((x, y))
            valid_sizes.append((real_w, real_h))

    return tiles, positions, valid_sizes, (width, height)

def stitch_tiles_with_blending(tiles, positions, valid_sizes, original_size, tile_size, overlap, scale=1):
    out_w, out_h = original_size[0] * scale, original_size[1] * scale

    final_image = np.zeros((out_h, out_w, 3), dtype=np.float32)
    weight_map = np.zeros((out_h, out_w, 3), dtype=np.float32)

    for tile, (x, y), (valid_w, valid_h) in zip(tiles, positions, valid_sizes):
        scaled_w = valid_w * scale
        scaled_h = valid_h * scale

        # Resize and crop to match actual content size
        tile = tile.resize((tile_size * scale, tile_size * scale), Image.BICUBIC)
        tile_np = np.array(tile, dtype=np.float32)[:scaled_h, :scaled_w]

        alpha = np.ones_like(tile_np, dtype=np.float32)

        # Smooth blend on overlapping edges
        fade = overlap * scale
        for i in range(fade):
            weight = (i + 1) / (fade + 1)
            if i < scaled_h:
                alpha[i, :, :] *= weight  # top
                alpha[-(i + 1), :, :] *= weight  # bottom
            if i < scaled_w:
                alpha[:, i, :] *= weight  # left
                alpha[:, -(i + 1), :] *= weight  # right

        x_scaled = x * scale
        y_scaled = y * scale

        final_image[y_scaled:y_scaled + scaled_h, x_scaled:x_scaled + scaled_w] += tile_np * alpha
        weight_map[y_scaled:y_scaled + scaled_h, x_scaled:x_scaled + scaled_w] += alpha

    final_image /= np.maximum(weight_map, 1e-5)
    final_image = np.clip(final_image, 0, 255).astype(np.uint8)

    return Image.fromarray(final_image)
