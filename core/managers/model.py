"""Model selection and management for image and video upscaling."""

import re
from pathlib import Path

from core.config.constants import ROOT_DIR
from core.processing.output_size import (
    TARGET_HEIGHTS,
    is_target,
    output_plan,
    resolution_label,
    target_label,
)
from core.models.weights import models_for_factor
from core.services.upscalers.constants import AMD_VIDEO_SR_MODEL
from core.services.upscalers.gpu_realtime import gpu_realtime_models


class ModelManager:
    """Handle model selection, factor detection, and option generation."""

    @staticmethod
    def models_for_factor(factor):
        """Get available upscaling models for a given factor."""
        return models_for_factor(factor)

    @staticmethod
    def realtime_model_factors():
        """Get available upscaling factors for realtime models."""
        realtime_weights = Path(ROOT_DIR, "weights", "realtime")
        factors = set()
        if realtime_weights.is_dir():
            for path in realtime_weights.iterdir():
                match = re.search(r"_x(2|4|8)\.(?:pb|onnx)$", path.name, re.IGNORECASE)
                if match:
                    factors.add(int(match.group(1)))
        from core.application_modules.media import MediaModule
        if MediaModule._ffmpeg_path():
            factors.update((2, 4))
        return factors

    @staticmethod
    def realtime_models():
        """Get all available realtime model names."""
        realtime_weights = Path(ROOT_DIR, "weights", "realtime")
        models = set()
        if realtime_weights.is_dir():
            models.update(
                path.stem
                for path in realtime_weights.iterdir()
                if path.suffix.lower() in (".pb", ".onnx")
            )
        from core.application_modules.media import MediaModule
        if MediaModule._ffmpeg_path():
            models.add(AMD_VIDEO_SR_MODEL)
        return sorted(models)

    @classmethod
    def realtime_models_for_factor(cls, factor, source_size=None):
        """Get realtime models available for a specific factor.

        Real-ESRGAN GPU models depend on the source size (they only keep up with low-resolution
        video), so they are included only when `source_size` is given. They are listed last so
        the faster AMD VideoSR stays the default choice.
        """
        factor = int(factor)
        models = []
        for model in cls.realtime_models():
            if model == AMD_VIDEO_SR_MODEL:
                if factor in (2, 4, 1080):
                    models.append(model)
                continue
            match = re.search(r"_x(2|4|8)$", model, re.IGNORECASE)
            if match and int(match.group(1)) == factor:
                models.append(model)
        if source_size is not None:
            models.extend(gpu_realtime_models(factor, source_size))
        return models

    @staticmethod
    def _finalize_options(options):
        """Drop 'N×' options duplicating a 1080p/2160p option, name standard heights, sort by size.

        Real-time models that only existed for a dropped option are moved to the target option.
        """
        targets = {
            (option["width"], option["height"]): option
            for option in options if is_target(option["factor"])
        }
        merged = []
        for option in options:
            target = targets.get((option["width"], option["height"]))
            if target is None or is_target(option["factor"]):
                merged.append(option)
                continue
            for model in option.get("models", []):
                if model not in target["models"]:
                    target["models"].append(model)
        for option in merged:
            option["label"] = resolution_label(option["width"], option["height"])
        return sorted(merged, key=lambda option: (option["height"], option["width"]))

    @classmethod
    def realtime_output_options(cls, entry):
        """Generate output size options for realtime video processing."""
        source_size = entry["original_size"]
        options = []
        for factor in (2, 4, 8, 1080):
            if is_target(factor) and source_size[1] >= factor:
                continue
            models = cls.realtime_models_for_factor(factor, source_size)
            if not models:
                continue
            width, height = output_plan(source_size, factor)[1]
            options.append({
                "factor": factor,
                "width": width,
                "height": height,
                "label": (
                    target_label(factor, (width, height))
                    if is_target(factor) else f"{width} × {height}"
                ),
                "models": models,
            })
        return cls._finalize_options(options)

    @classmethod
    def video_models_for_factor(cls, factor, entry=None):
        """Get available video upscaling models for a factor."""
        if entry is not None:
            factor = output_plan(entry["original_size"], factor)[0]
        models = cls.models_for_factor(factor)
        if models:
            return models
        if int(factor) in cls.realtime_model_factors():
            return ["CPU resize and sharpen"]
        return []

    @classmethod
    def video_output_options(cls, entry):
        """Generate output size options for video export."""
        source_size = entry["original_size"]
        source_width, source_height = source_size
        factors = [
            factor for factor in (2, 4, 8)
            if cls.models_for_factor(factor) or factor in cls.realtime_model_factors()
        ]
        if not factors:
            factors = [1]
        options = [
            {
                "factor": factor,
                "width": source_width * factor,
                "height": source_height * factor,
                "label": f"{source_width * factor} × {source_height * factor}",
            }
            for factor in factors
        ]
        for target in TARGET_HEIGHTS:
            if source_height >= target:
                continue
            model_factor, size = output_plan(source_size, target)
            if model_factor in factors:
                options.append({
                    "factor": target,
                    "width": size[0],
                    "height": size[1],
                    "label": target_label(target, size),
                })
        return cls._finalize_options(options)
