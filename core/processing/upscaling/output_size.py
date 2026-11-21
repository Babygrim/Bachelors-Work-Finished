"""Output sizing - compatibility layer re-exporting from sizing module."""

from core.processing.upscaling.sizing import (
    is_target,
    output_plan,
    resolution_label,
    target_label,
    MODEL_FACTORS,
    TARGET_HEIGHTS,
)

__all__ = [
    'is_target',
    'output_plan',
    'resolution_label',
    'target_label',
    'MODEL_FACTORS',
    'TARGET_HEIGHTS',
]
