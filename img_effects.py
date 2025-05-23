from PIL import Image, ImageOps
import numpy as np
from PIL import Image
import cv2
from numpy.fft import fft2, ifft2, fftshift


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

def psnr(target, ref):
    target_data = target.astype(np.float32)
    ref_data = ref.astype(np.float32)
    mse = np.mean((ref_data - target_data) ** 2)
    if mse == 0:
        return float('inf')
    return 20 * np.log10(255.0 / np.sqrt(mse))

def evaluate_methods(original, dict):
    scores = {}
    for method, output in dict.items():
        score = psnr(original, output)
        scores[method] = score
    return scores


############ IMAGE DENOISING cv2
def denoise_methods(noisy_img):
    methods = {}
    methods['GaussianBlur'] = cv2.GaussianBlur(noisy_img, (5, 5), 0)
    methods['MedianBlur'] = cv2.medianBlur(noisy_img, 5)
    methods['BilateralFilter'] = cv2.bilateralFilter(noisy_img, 9, 75, 75)
    methods['FastNlMeans'] = cv2.fastNlMeansDenoisingColored(noisy_img, None, 10, 10, 6, 18)
    return methods

def denoise_image(input_img, progress_bar_queue):
    input_img = np.array(input_img.convert("RGB")).astype(np.uint8)
    denoised_results = denoise_methods(input_img)
    psnr_scores = evaluate_methods(input_img, denoised_results)
    best_method = max(psnr_scores, key=psnr_scores.get)
    best_image = denoised_results[best_method]
    return Image.fromarray(best_image)

############ IMAGE DEBLURRING cv2
# def motion_blur_kernel(size=15):
#     kernel = np.zeros((size, size))
#     kernel[size // 2, :] = np.ones(size)
#     return kernel / size

# def wiener_deconvolution(img, kernel, K=0.01):
#     img = img.astype(np.float32)
#     kernel /= np.sum(kernel)

#     # Pad kernel to image size
#     kernel_padded = np.zeros_like(img[:, :, 0])
#     kh, kw = kernel.shape
#     kernel_padded[:kh, :kw] = kernel
#     kernel_fft = fft2(kernel_padded)

#     deblurred = np.zeros_like(img)
#     for c in range(3):
#         img_fft = fft2(img[:, :, c])
#         deconvolved = np.real(ifft2(
#             img_fft * np.conj(kernel_fft) / (np.abs(kernel_fft)**2 + K)
#         ))
#         deblurred[:, :, c] = np.clip(deconvolved, 0, 255)

#     return deblurred.astype(np.uint8)

# def deblur_image(input_img, progress_bar_queue, kernel):
#     kernel = motion_blur_kernel(size=int(kernel))
#     input_img = np.array(input_img.convert("RGB")).astype(np.uint8)
#     deblurred_img = wiener_deconvolution(input_img, kernel)
    
#     return Image.fromarray(deblurred_img)

import numpy as np
import cv2
from skimage.restoration import richardson_lucy
from skimage import img_as_float, img_as_ubyte
from PIL import Image
from scipy.signal import convolve2d

def estimate_psf_from_edges(image_gray, kernel_size=15):
    """Estimate a very basic blur kernel by computing edge structure."""
    edges = cv2.Canny(image_gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, 100)
    if lines is not None:
        angle = np.mean([line[0][1] for line in lines])
        angle_deg = np.rad2deg(angle)
        print(f"Estimated motion blur angle: {angle_deg:.2f}")
    else:
        angle_deg = 0  # fallback

    return motion_blur_psf(kernel_size, angle_deg)

def motion_blur_psf(length=15, angle=0):
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

def deblur_image(img_pil, progress_bar_queue, kernel_size=15):
    iterations=1
    img_rgb = np.array(img_pil.convert("RGB"))
    gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)

    # Estimate PSF
    psf = estimate_psf_from_edges(gray, kernel_size=int(kernel_size))

    # Deblur using Richardson-Lucy
    img = img_as_float(img_rgb)
    deconvolved = np.zeros_like(img)
    for c in range(3):
        deconvolved[:, :, c] = richardson_lucy(img[:, :, c], psf, num_iter=iterations, clip=False)
    result = np.clip(deconvolved, 0, 1)
    return Image.fromarray(img_as_ubyte(result))

    
    
