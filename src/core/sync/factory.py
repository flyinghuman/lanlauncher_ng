"""Sync provider construction based on runtime configuration."""

from __future__ import annotations

from src.core.config.loader import AppConfig
from src.core.sync.provider import NoopSyncProvider, SyncProvider
from src.core.sync.ouisync_provider import OuisyncSyncProvider
from src.core.sync.resilio_provider import ResilioSyncProvider


def create_sync_provider(config: AppConfig) -> SyncProvider:
    provider = config.sync_provider.lower()
    if provider == "syncthing":
        provider = "ouisync"
    if provider == "resilio":
        return ResilioSyncProvider(
            binary_path=config.sync_binary_path,
            config_path=config.sync_config_path,
            pid_path=config.sync_pid_path,
            log_path=config.sync_log_path,
            license_key_path=config.sync_license_key_path,
            api_url=config.sync_api_url,
            api_key=config.sync_api_key,
            request_timeout_seconds=config.sync_request_timeout_seconds,
            retry_count=config.sync_retry_count,
            startup_retry_seconds=config.sync_startup_retry_seconds,
        )
    if provider == "ouisync":
        return OuisyncSyncProvider(
            binary_path=config.ouisync_binary_path,
            config_dir=config.ouisync_config_dir,
            log_path=config.ouisync_log_path,
            repo_root=config.repo_root,
            startup_timeout_seconds=config.ouisync_startup_timeout_seconds,
            request_timeout_seconds=config.sync_request_timeout_seconds,
        )
    return NoopSyncProvider()
