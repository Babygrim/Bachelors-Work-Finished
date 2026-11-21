"""Image effects and filters - denoising, deblurring, inversion."""

import numpy as np
import cv2
from PIL import Image, ImageOps
from skimage.restoration import richardson_lucy
from skimage.util import img_as_float, img_as_ubyte


def invert_colors(image):
    """Invert image colors."""
    try:
        r, g, b, a = image.split()
        rgb_image = Image.merge("RGB", (r, g, b))
        inverted_rgb = ImageOps.invert(rgb_image)
        return Image.merge("RGBA", (*inverted_rgb.split(), a))
    except ValueError:
        return ImageOps.invert(image)


def psnr(target, ref):
    """Calculate PSNR (Peak Signal-to-Noise Ratio)."""
    target_data = target.astype(np.float32)
    ref_data = ref.astype(np.float32)
    mse = np.mean((ref_data - target_data) ** 2)
    if mse == 0:
        return float('inf')
    return 20 * np.log10(255.0 / np.sqrt(mse))


def evaluate_methods(original, methods_dict):
    """Evaluate denoising methods by PSNR score."""
    scores = {}
    for method, output in methods_dict.items():
        score = psnr(original, output)
        scores[method] = score
    return scores


def denoise_methods(image):
    """Apply multiple denoising methods."""
    methods = {}
    methods['GaussianBlur'] = cv2.GaussianBlur(image, (5, 5), 0)
    methods['MedianBlur'] = cv2.medianBlur(image, 5)
    methods['BilateralFilter'] = cv2.bilateralFilter(image, 9, 75, 75)
    methods['FastNlMeans'] = cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 6, 18)
    return methods


def denoise_image(input_image, progress_bar_queue):
    """Denoise image using best-performing method."""
    input_array = np.array(input_image.convert("RGB")).astype(np.uint8)
    methods = denoise_methods(input_array)
    scores = evaluate_methods(input_array, methods)
    best_method = max(scores, key=scores.get)
    best_image = methods[best_method]
    return Image.fromarray(best_image)


def motion_blur_psf(length=15, angle=0):
    """Generate motion blur point-spread function."""
    psf = np.zeros((length, length))
    center = length // 2
    x = np.linspace(-center, center, length)
    y = np.tan(np.deg2rad(angle)) * x
    for i in range(length):
        xi = int(round(center + x[i]))
        yi = int(round(center + y[i]))
        if 0 <= xi < length and 0 <= yi < length:
            psf[yi, xi] = 1
    psf /= psf.sum()
    return psf


def estimate_psf_from_edges(image_gray, kernel_size=15):
    """Estimate blur kernel from image edges."""
    edges = cv2.Canny(image_gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 100)
    if lines is not None:
        angle = np.mean([line[0][1] for line in lines])
        angle_deg = np.rad2deg(angle)
    else:
        angle_deg = 0
    return motion_blur_psf(kernel_size, angle_deg)


def deblur_image(image_pil, progress_bar_queue, kernel_size=15):
    """Deblur image using Richardson-Lucy deconvolution."""
    iterations = 1
    img_rgb = np.array(image_pil.convert("RGB"))
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    psf = estimate_psf_from_edges(gray, kernel_size=int(kernel_size))

    img = img_as_float(img_rgb)
    deconvolved = np.zeros_like(img)
    for c in range(3):
        deconvolved[:, :, c] = richardson_lucy(img[:, :, c], psf, num_iter=iterations, clip=False)
    result = np.clip(deconvolved, 0, 1)
    return Image.fromarray(img_as_ubyte(result))
