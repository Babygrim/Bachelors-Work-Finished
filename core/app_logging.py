import logging
from pathlib import Path

from core.constants import ROOT_DIR

LOG_DIRECTORY = Path(ROOT_DIR, "app_logs")
LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("picture_editor")
if not logger.handlers:
    handler = logging.FileHandler(LOG_DIRECTORY / "logs.txt", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def log_toast(level, message):
    level_name = str(level).upper()
    log_method = getattr(logger, level_name.lower(), logger.info)
    log_method("toast[%s] %s", level_name, str(message))
