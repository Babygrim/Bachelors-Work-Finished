"""Media module - facade combining media history, I/O, state, and cropping."""

from core.application_modules.media.history import MediaHistoryManager
from core.application_modules.media.io import MediaIOManager
from core.application_modules.media.state import MediaStateManager
from core.application_modules.media.crop import ImageCropManager


class MediaModule(MediaHistoryManager, MediaIOManager, MediaStateManager, ImageCropManager):
    """History, media loading, export, and video processing capability."""
    pass
