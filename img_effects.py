from PIL import Image, ImageOps
import numpy as np
from PIL import Image
import numpy as np
import cv2
from scipy.signal import convolve2d

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

def deblur_image_wiener(input_img, values):
    # Convert PIL image to grayscale NumPy array
    img = input_img.convert('L')
    value = int(values[0])
    img_np = np.array(img)

    # Create horizontal motion blur kernel
    kernel = np.zeros((value, value))
    kernel[value // 2, :] = np.ones(value)
    kernel /= value

    # Apply Wiener filter
    deblurred_np = wiener_filter(img_np, kernel, 0.1)

    # Convert back to PIL image
    deblurred_pil = Image.fromarray(deblurred_np)
    return deblurred_pil

    
