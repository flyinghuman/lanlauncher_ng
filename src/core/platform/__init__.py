"""Platform package exports."""

from src.core.platform.base import ActionResult, PlatformAdapter, StorageValidation
from src.core.platform.factory import create_platform_adapter
from src.core.platform.linux.adapter import LinuxPlatformAdapter
from src.core.platform.windows.adapter import WindowsPlatformAdapter

__all__ = [
    "ActionResult",
    "PlatformAdapter",
    "StorageValidation",
    "create_platform_adapter",
    "LinuxPlatformAdapter",
    "WindowsPlatformAdapter",
]
