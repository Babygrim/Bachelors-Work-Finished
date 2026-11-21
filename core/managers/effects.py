"""Image effects application - brightness, contrast, filters, etc."""

import base64
import io
from PIL import Image, ImageEnhance, ImageFilter

from core.processing import effects as img_effects


class EffectsManager:
    """Apply image effects and filters."""

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
            result = img_effects.invert_image_colors(result, None)
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
