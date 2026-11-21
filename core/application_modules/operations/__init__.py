"""Operations module - facade combining settings, job control, and history operations."""

from core.application_modules.operations.settings import SettingsOperations
from core.application_modules.operations.job import JobOperations
from core.application_modules.media.history import MediaHistoryManager
from core.application_modules.media.crop import ImageCropManager
from core.application_modules.operations.settings_manager import SettingsManager
from core.application_modules.operations.job_manager import JobManager


class OperationsModule(SettingsOperations, JobOperations, MediaHistoryManager, ImageCropManager):
    """Settings, editing operations, and API telemetry capability."""

    def __init__(self):
        """Initialize operation managers."""
        self._settings_manager = SettingsManager(self)
        self._job_manager = JobManager(self)
