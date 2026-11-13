"""Independently loadable WebApp capabilities."""

from .media import MediaModule
from .operations import OperationsModule
from .video import VideoModule

__all__ = ["MediaModule", "OperationsModule", "VideoModule"]
