"""Settings management operations."""


class SettingsOperations:
    """Handle settings and configuration operations."""

    def set_module(self, module):
        """Set the current processing module."""
        return self._settings_manager.set_module(module)

    def set_setting(self, key, value):
        """Set a configuration setting with validation."""
        return self._settings_manager.set_setting(key, value)

    def reset_module(self, scope=None):
        """Reset settings to defaults (optionally only the 'adjust' or 'upscale' tab)."""
        return self._settings_manager.reset_module(scope)

    def set_scale(self, scale):
        """Set the scale factor for processing."""
        with self._lock:
            entry = self._current()
            if not entry:
                return False
            entry["scale"] = max(0.1, min(5.0, float(scale)))
            self._touch()
        return True
