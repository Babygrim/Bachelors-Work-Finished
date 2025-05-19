from PIL import Image
from realesrganer_my import RealESRGANer
from gfpganer_my import GFPGANer
from basicsr.archs.rrdbnet_arch import RRDBNet
import torch_directml
import torch
import os
import numpy as np
import cv2
from constants import IMAGE_TILE_OVERLAP, IMAGE_TILE_SIZE
from skimage import restoration
from skimage import img_as_float
from image_tiling import *
from img_manipulation import resize_image
from constants import ROOT_DIR


def multisampling(input_img, progress_bar_queue, sample_rate):
    """
    Apply multisampling (supersampling) to a single image for edge smoothing.
    
    Args:
        input_image (Image.Image): The input image as a PIL Image.
        sample_rate (int): The sampling rate (e.g., 2, 4, 8). Higher values mean better quality but slower processing.

    Returns:
        Image.Image: The antialiased output image.
    """
    input_image = input_img
    sample_rate = int(sample_rate)

    # Step 1: Upscale the image
    width, height = input_image.size
    upscale_width, upscale_height = width * sample_rate, height * sample_rate
    upscaled_image = input_image.resize((upscale_width, upscale_height), Image.NEAREST)

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

    if torch_directml.is_available():
        device = torch_directml.device()
    else:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    upscale_factor = int(upscale_factor)
    outscale_factor = 1 / upscale_factor if keep_size else 1
    
    # Create the ESRGAN model
    model = RRDBNet(
        num_in_ch=3,
        num_out_ch=3,
        num_feat=64,
        num_block=23,
        num_grow_ch=32,
        scale=upscale_factor
    )
    
    # Initialize RealESRGAN with AMD-compatible device
    upscaler_ESRGAN = RealESRGANer(
        scale=upscale_factor,
        model_path=weights_path,
        model=model,
        device=device
    )
    
    if face_restoration:
        upscaler_GFPGAN = GFPGANer(
            upscale=upscale_factor,
            bg_upsampler=upscaler_ESRGAN
        )
        
        final_image = upscaler_GFPGAN.enhance(np.array(input_image), progress_queue=progress_bar_queue)
        final_image = Image.fromarray(final_image)
    else:
        tiles, positions, valid_sizes, original_size = tile_image_with_overlap(input_image, IMAGE_TILE_SIZE, IMAGE_TILE_OVERLAP)
    
        upscaled_tiles = []
        for i, tile in enumerate(tiles):
            upscaled_tile = upscaler_ESRGAN.enhance(np.array(tile))
            upscaled_tiles.append(Image.fromarray(upscaled_tile))
            if progress_bar_queue:
                progress_bar_queue.put(((i + 1) / len(tiles)) * 100)

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
    
    for _ in range(samples):
        image = cv2.pyrUp(image)
    image = Image.fromarray(image)
    
    return image
    

############ IMAGE DENOISING PILLOW

def denoise_image_pil(input, progress_bar_queue):
    """
    Applies denoising to the input PIL image using non-local means denoising.
    
    Args:
        input_image (Image.Image): The input image as a PIL Image.
    
    Returns:
        Image.Image: The denoised output image as a PIL Image.
    """
    # Step 1: Convert the PIL image to a NumPy array
    image_np = input

    # Step 2: Convert the image to float (required by skimage)
    image_float = img_as_float(image_np)

    # Step 3: Apply denoising (non-local means)
    denoised_image = restoration.denoise_nl_means(image_float, 
                                                  patch_size=2, 
                                                  patch_distance=3)

    # Step 4: Convert the denoised image back to uint8 for saving
    denoised_image_uint8 = np.uint8(denoised_image * 255)

    # Step 5: Convert the result back to a PIL Image and return it
    image = Image.fromarray(denoised_image_uint8)
    return image