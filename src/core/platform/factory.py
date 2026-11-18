"""Platform adapter selection."""

from __future__ import annotations

import platform

from src.core.platform.base import PlatformAdapter
from src.core.platform.linux.adapter import LinuxPlatformAdapter
from src.core.platform.windows.adapter import WindowsPlatformAdapter


def create_platform_adapter(force_platform: str | None = None) -> PlatformAdapter:
    current = (force_platform or platform.system()).lower()
    if current.startswith("win"):
        return WindowsPlatformAdapter()
    return LinuxPlatformAdapter()
