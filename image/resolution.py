from PIL import Image
from models.realesrganer import RealESRGANer
from models.gfpganer import GFPGANer
from models.rrdbnet_arch import RRDBNet
from core.constants import DEVICE
import os
import numpy as np
import cv2
from core.constants import IMAGE_TILE_OVERLAP, IMAGE_TILE_SIZE, TILE_BATCH_SIZE
from image.tiling import tile_image_with_overlap, stitch_tiles_with_blending
from image.manipulation import resize_image
from core.constants import ROOT_DIR


def multisampling(input_img, progress_bar_queue, sample_rate):
    """
    Apply multisampling (supersampling) to a single image for edge smoothing.
    """
    input_image = input_img
    sample_rate = int(sample_rate)

    # Step 1: Upscale the image
    width, height = input_image.size
    upscale_width, upscale_height = width * sample_rate, height * sample_rate
    upscaled_image = input_image.resize((upscale_width, upscale_height), Image.Resampling.NEAREST)

    # Step 2: Apply a smoothing filter (optional, to mimic multisampling operations)
    # upscaled_image = upscaled_image.filter(ImageFilter.SMOOTH)

    # Step 3: Downscale back to the original size with antialiasing
    output_image = upscaled_image.resize((width, height), Image.Resampling.LANCZOS)

    return output_image

######### REAL ESRGAN UPSCALING
def upscale_image(input_image, progress_bar_queue, keep_size, model, face_restoration, upscale_factor):
    model = model
    weights_path = ROOT_DIR + f'/weights/{model}.pth'
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"Weight file not found: {weights_path}")

    upscale_factor = int(upscale_factor)
    outscale_factor = 1 / upscale_factor if keep_size else 1
    
    # create ESRGAN model
    model = RRDBNet(
        num_in_ch=3,
        num_out_ch=3,
        num_feat=64,
        num_block=23,
        num_grow_ch=32,
        scale=upscale_factor
    )
    
    # init RealESRGAN
    upscaler_ESRGAN = RealESRGANer(
        scale=upscale_factor,
        model_path=weights_path,
        model=model,
        device=DEVICE
    )
    
    if face_restoration:
        upscaler_GFPGAN = GFPGANer(
            upscale=upscale_factor,
            bg_upsampler=upscaler_ESRGAN,
            arch='clean', # clean, bilinear, original, RestoreFormer
            # device=DEVICE, #unable to use AMD GPU, because face comes out distorted.
        )
        
        final_image = upscaler_GFPGAN.enhance(np.array(input_image), progress_queue=progress_bar_queue)
        final_image = Image.fromarray(final_image)
    else:
        tiles, positions, valid_sizes, original_size = tile_image_with_overlap(input_image, IMAGE_TILE_SIZE, IMAGE_TILE_OVERLAP)

        tile_arrays = [np.array(t) for t in tiles]
        upscaled_arrays = upscaler_ESRGAN.enhance_batch(
            tile_arrays,
            batch_size=TILE_BATCH_SIZE,
            progress_queue=progress_bar_queue
        )
        upscaled_tiles = [Image.fromarray(a) for a in upscaled_arrays]

        final_image = stitch_tiles_with_blending(upscaled_tiles, 
                                                positions, 
                                                valid_sizes, 
                                                original_size, 
                                                IMAGE_TILE_SIZE,
                                                IMAGE_TILE_OVERLAP, 
                                                upscale_factor)
    if outscale_factor < 1:
        final_image, _ = resize_image(None, photo_image=final_image, new_height=final_image.height * outscale_factor, new_width=final_image.width * outscale_factor)
        
    return final_image

########## OPENCV UPSCALING

def upscale_cv2(input, progress_bar_queue, sample_rate):
    image =  np.array(input)
    samples = int(sample_rate)
    
    for _ in range(2, samples):
        image = cv2.pyrUp(image)
    image = Image.fromarray(image)
    
    return image