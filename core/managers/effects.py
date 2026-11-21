"""Image effects application - brightness, contrast, filters, etc."""

import base64
import io

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

from core.processing import effects as img_effects
from core.processing.preview_effects import PreviewEffects

PREVIEW_MAX_SIZE = (1800, 1400)


class EffectsManager:
    """Apply image effects and filters."""

    _preview_effects = None

    @classmethod
    def preview_effects(cls):
        if cls._preview_effects is None:
            cls._preview_effects = PreviewEffects()
        return cls._preview_effects

    @staticmethod
    def build_preview_proxy(image):
        """Downscale an image to preview size once; effects are then rendered from this proxy."""
        proxy = image.copy()
        proxy.thumbnail(PREVIEW_MAX_SIZE, Image.Resampling.LANCZOS)
        rgba = np.array(proxy.convert("RGBA"))
        alpha = rgba[..., 3]
        return {
            "source": image,
            "rgb": np.ascontiguousarray(rgba[..., :3]),
            "alpha": None if alpha.min() == 255 else np.ascontiguousarray(alpha),
            "scale": proxy.width / image.width,
        }

    @classmethod
    def render_effect_preview(cls, proxy, effects):
        """Apply the effect settings to a preview proxy and return it as a data URL."""
        rgb = cls.preview_effects().apply(proxy["rgb"], effects, proxy["scale"])
        if proxy["alpha"] is None:
            ok, encoded = cv2.imencode(
                ".jpg",
                np.ascontiguousarray(rgb[..., ::-1]),
                [
                    cv2.IMWRITE_JPEG_QUALITY, 92,
                    cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444,
                ],
            )
            if not ok:
                raise RuntimeError("Could not encode the preview image.")
            mime, data = "image/jpeg", encoded.tobytes()
        else:
            buffer = io.BytesIO()
            Image.fromarray(np.dstack((rgb, proxy["alpha"])), "RGBA").save(
                buffer, format="WEBP", quality=92, method=0
            )
            mime, data = "image/webp", buffer.getvalue()
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"

    def apply_effects(self, image, settings):
        """Apply all configured effects to an image."""
        settings = settings["effects"]
        result = image.copy()
        for name, function in (
            ("Brightness", ImageEnhance.Brightness),
            ("Color", ImageEnhance.Color),
            ("Contrast", ImageEnhance.Contrast),
            ("Sharpness", ImageEnhance.Sharpness),
        ):
            result = function(result).enhance(float(settings[name]) / 100)
        blur = float(settings["Blur"]) / 100
        if blur:
            result = result.filter(ImageFilter.GaussianBlur(blur))
        if settings["Inversion"]:
            result = img_effects.invert_image_colors(result)
        return result

    @staticmethod
    def image_to_url(image):
        """Convert PIL image to data URL."""
        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=92, method=4)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/webp;base64,{encoded}"

    @staticmethod
    def video_preview_url(image):
        """Convert PIL image to thumbnail data URL for video preview."""
        preview = image.copy()
        preview.thumbnail((960, 720), Image.Resampling.BILINEAR)
        buffer = io.BytesIO()
        preview.save(buffer, format="WEBP", quality=72, method=0)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/webp;base64,{encoded}"
