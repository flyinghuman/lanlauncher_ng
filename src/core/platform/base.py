"""Platform adapter interfaces and shared result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    message: str
    detail: str = ""


@dataclass(frozen=True)
class StorageValidation:
    path: str
    exists: bool
    writable: bool
    is_directory: bool
    ok: bool
    message: str


class PlatformAdapter(Protocol):
    def platform_name(self) -> str:
        """Return canonical platform id."""

    def normalize_path(self, raw_path: str) -> str:
        """Normalize user provided path for current OS semantics."""

    def validate_storage_path(self, raw_path: str) -> StorageValidation:
        """Validate that storage path is a writable directory."""

    def open_folder(self, raw_path: str) -> ActionResult:
        """Open folder in OS file manager."""

    def launch_executable(
        self, executable_path: str, args: list[str] | None = None
    ) -> ActionResult:
        """Start executable with optional args."""

    def list_storage_locations(self) -> list[dict[str, str]]:
        """List user-selectable storage locations for first-run setup."""

    def configure_sync_network_mode(
        self,
        script_path: str,
        sync_binary_path: str,
        mode: str,
    ) -> ActionResult:
        """Apply LAN/internet network restrictions for the sync service."""

    def set_local_network_private(self, script_path: str) -> ActionResult:
        """Set active local network profiles from public to private where supported."""

    def install_common_wine_dependencies(
        self,
        packages: list[str],
        *,
        winetricks_path: str = "",
        cache_path: str = "",
    ) -> ActionResult:
        """Install common Winetricks dependencies for default user Wine prefix."""

    def install_common_wine_dependencies_for_prefix(
        self,
        prefix_path: str,
        packages: list[str],
        *,
        winetricks_path: str = "",
        cache_path: str = "",
    ) -> ActionResult:
        """Install common Winetricks dependencies for a specific Wine/Proton prefix."""

    def open_wine_prefix_uninstaller(self, prefix_path: str) -> ActionResult:
        """Open the Wine uninstaller UI for a specific prefix."""
