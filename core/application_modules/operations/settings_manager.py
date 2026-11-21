"""Settings management for media operations."""

from core.application_modules.shared import SLIDER_DEFAULTS, SLIDER_RANGES
from core.processing.output_size import is_target
from core.services.app_logging import log_event


def _get_available_modules(entry):
    """Determine available modules for entry kind.
    
    Args:
        entry: Media entry dict
        
    Returns:
        Tuple of available module names
    """
    if entry and entry["kind"] == "video":
        return ("Video_Enhancement",)
    return ("Image_Effects", "Resolution_Enhancement")


def _validate_setting_value(key, value, entry):
    """Validate setting value before applying.
    
    Args:
        key: Setting key
        value: Setting value
        entry: Media entry dict
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if key in SLIDER_RANGES:
        try:
            int(value)
            return True, None
        except (ValueError, TypeError):
            return False, f"Invalid value for {key}"
    
    if key == "Inversion":
        return True, None
    
    if key == "factor":
        try:
            factor = int(value)
            if factor not in (2, 4, 8) and not (
                entry["kind"] == "video" and is_target(factor)
            ):
                return False, f"Invalid scale factor: {factor}"
            return True, None
        except (ValueError, TypeError):
            return False, "Factor must be an integer"
    
    if key == "model":
        return True, None
    
    if key in ("keep_size", "face_restoration"):
        return True, None
    
    return False, f"Unknown setting: {key}"


class SettingsManager:
    """Manages settings operations within OperationsModule context."""
    
    def __init__(self, operations_module):
        """Initialize with reference to parent OperationsModule."""
        self.module = operations_module
    
    def set_module(self, module):
        """Set the current processing module.
        
        Args:
            module: Module name to set
            
        Returns:
            True if successful, False otherwise
        """
        with self.module._lock:
            entry = self.module._current()
            available = _get_available_modules(entry)
            if module not in available:
                return False
            self.module._module = module
            self.module._touch()
        return True
    
    def set_setting(self, key, value):
        """Set a configuration setting with validation.
        
        Args:
            key: Setting key
            value: Setting value
            
        Returns:
            True if successful, False otherwise
        """
        with self.module._lock:
            entry = self.module._current()
            if not entry or entry["image_loading"] or self.module._job["running"]:
                return False
            
            is_valid, error_msg = _validate_setting_value(key, value, entry)
            if not is_valid:
                return False
            
            if key in SLIDER_RANGES:
                minimum, maximum = SLIDER_RANGES[key]
                entry["settings"]["effects"][key] = max(minimum, min(maximum, int(value)))
            elif key == "Inversion":
                entry["settings"]["effects"][key] = bool(value)
            elif key == "factor":
                factor = int(value)
                if factor not in (2, 4, 8) and not (
                    entry["kind"] == "video" and is_target(factor)
                ):
                    return False
                if entry["kind"] == "video" and not any(
                    option["factor"] == factor
                    for option in self.module._video_output_options(entry)
                ):
                    return False
                enhancement = entry["settings"]["enhancement"]
                enhancement["factor"] = factor
                models = (
                    self.module._video_models_for_factor(factor, entry)
                    if entry["kind"] == "video"
                    else self.module._models_for_factor(factor)
                )
                enhancement["model"] = models[0] if models else ""
            elif key == "model":
                choices = (
                    self.module._video_models_for_factor(entry["settings"]["enhancement"]["factor"], entry)
                    if entry["kind"] == "video"
                    else self.module._models_for_factor(entry["settings"]["enhancement"]["factor"])
                )
                if value not in choices:
                    return False
                entry["settings"]["enhancement"][key] = value
            elif key in ("keep_size", "face_restoration"):
                entry["settings"]["enhancement"][key] = bool(value)
            else:
                return False
            
            self.module._touch(preview=key in SLIDER_RANGES or key == "Inversion")
            log_event("setting_changed", key=key, value=value)
        return True
    
    def reset_module(self, scope=None):
        """Reset settings to defaults.

        Args:
            scope: 'adjust' (image effects), 'upscale' (upscale settings) or None for everything
                that applies to the current media.

        Returns:
            True if successful, False otherwise
        """
        with self.module._lock:
            entry = self.module._current()
            if not entry or entry["image_loading"] or self.module._job["running"]:
                return False
            if entry["kind"] == "image":
                if scope in (None, "adjust"):
                    entry["settings"]["effects"] = {**SLIDER_DEFAULTS, "Inversion": False}
                if scope in (None, "upscale"):
                    entry["settings"]["enhancement"] = self.module._default_settings()["enhancement"]
                self.module._touch(preview=scope in (None, "adjust"))
            elif scope in (None, "upscale"):
                enhancement = self.module._default_settings()["enhancement"]
                # The default 2x option may be merged into a 1080p option for this video.
                first_option = self.module._video_output_options(entry)[0]["factor"]
                models = self.module._video_models_for_factor(first_option, entry)
                enhancement.update(factor=first_option, model=models[0] if models else "")
                entry["settings"]["enhancement"] = enhancement
                self.module._touch()
        return True
