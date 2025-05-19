from PIL import Image, ImageOps
import numpy as np
from PIL import Image


#color inversion
def invert_image_colors(input_img, values): 
    img = input_img
    try:
        r, g, b, a = img.split()

        # Merge the RGB channels back and invert them
        rgb_image = Image.merge("RGB", (r, g, b))
        inverted_rgb = ImageOps.invert(rgb_image)

        # Combine the inverted RGB channels with the original alpha channel
        modified_image = Image.merge("RGBA", (*inverted_rgb.split(), a))
    except ValueError:
        modified_image = ImageOps.invert(img)
    
    return modified_image

# Wiener Deblurring
def wiener_filter(input_img, kernel, K):
    kernel = np.flipud(np.fliplr(kernel))  # Flip kernel
    dummy = np.fft.fft2(input_img)
    kernel = np.fft.fft2(kernel, s=input_img.shape)
    kernel = np.conj(kernel) / (np.abs(kernel) ** 2 + K)
    dummy = dummy * kernel
    dummy = np.abs(np.fft.ifft2(dummy))
    return np.uint8(np.clip(dummy, 0, 255))

def gaussian_kernel(size, sigma):
    """Generate a Gaussian kernel (PSF)."""
    ax = np.linspace(-(size // 2), size // 2, size)
    xx, yy = np.meshgrid(ax, ax)
    kernel = np.exp(-(xx**2 + yy**2) / (2. * sigma**2))
    return kernel / np.sum(kernel)

def deblur_image_wiener(input_img, progress_queue, value):
    img = input_img.convert('L')
    img_np = np.array(img)

    # Use a Gaussian kernel matching the blur radius
    kernel_size = 2 * int(value) + 1
    sigma = value
    kernel = gaussian_kernel(kernel_size, sigma)

    # Apply Wiener filter
    deblurred_np = wiener_filter(img_np, kernel, K=0.5)

    # Convert back to PIL image
    deblurred_pil = Image.fromarray(deblurred_np).convert('RGBA')
    return deblurred_pil
    
