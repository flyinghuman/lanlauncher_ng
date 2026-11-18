"""Sync provider interfaces and shared data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SyncMetrics:
    download_bps: int
    upload_bps: int


@dataclass(frozen=True)
class SyncStatus:
    provider: str
    running: bool
    state: str
    pid: int | None = None
    last_error: str = ""


class SyncProvider(Protocol):
    def start(self) -> SyncStatus:
        """Start sync backend and return current status."""

    def stop(self) -> SyncStatus:
        """Stop sync backend and return current status."""

    def status(self) -> SyncStatus:
        """Return provider status."""

    def metrics(self) -> SyncMetrics:
        """Return current throughput metrics."""

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        """Ensure a game folder is present in sync configuration."""

    def remove_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        """Remove a folder from sync configuration while leaving local files untouched."""

    def remove_folder_sync_by_secret(self, secret: str) -> tuple[bool, str]:
        """Remove a folder from sync configuration using share secret/game_key."""

    def folder_sync_status(self, folder_path: str) -> dict[str, int | bool]:
        """Return current active flag and progress percent for folder sync."""

    def list_managed_folders(self) -> dict:
        """Return the provider-managed folder inventory when supported."""

    def set_folder_shared(self, folder_path: str, shared: bool) -> tuple[bool, str]:
        """Share or unshare a managed folder when supported."""

    def debug_logs(self, limit: int = 200) -> list[dict]:
        """Return recent provider debug log entries when supported."""

    def set_peer_device_ids(self, device_ids: list[str]) -> None:
        """Update configured peer device ids for providers that support it."""

    def web_ui_url(self) -> str:
        """Return the browser URL for the provider web interface."""


class NoopSyncProvider:
    """Fallback sync provider used when no runtime backend is configured."""

    def start(self) -> SyncStatus:
        return SyncStatus(provider="noop", running=False, state="disabled")

    def stop(self) -> SyncStatus:
        return SyncStatus(provider="noop", running=False, state="disabled")

    def status(self) -> SyncStatus:
        return SyncStatus(provider="noop", running=False, state="disabled")

    def metrics(self) -> SyncMetrics:
        return SyncMetrics(download_bps=0, upload_bps=0)

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        _ = folder_path
        _ = secret
        return False, "sync_provider_disabled"

    def remove_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        _ = folder_path
        return False, "sync_provider_disabled"

    def remove_folder_sync_by_secret(self, secret: str) -> tuple[bool, str]:
        _ = secret
        return False, "sync_provider_disabled"

    def folder_sync_status(self, folder_path: str) -> dict[str, int | bool]:
        _ = folder_path
        return {"active": False, "progress_percent": 0}

    def list_managed_folders(self) -> dict:
        return {"root_path": "", "folders": []}

    def set_folder_shared(self, folder_path: str, shared: bool) -> tuple[bool, str]:
        _ = folder_path
        _ = shared
        return False, "sync_provider_disabled"

    def debug_logs(self, limit: int = 200) -> list[dict]:
        _ = limit
        return []

    def set_peer_device_ids(self, device_ids: list[str]) -> None:
        _ = device_ids

    def web_ui_url(self) -> str:
        return ""
