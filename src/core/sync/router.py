"""Route sync work between the Ouisync and optional Resilio providers."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Callable

from src.core.config.loader import AppConfig
from src.core.sync.provider import NoopSyncProvider, SyncMetrics, SyncProvider, SyncStatus
from src.core.sync.ouisync_provider import OuisyncSyncProvider
from src.core.sync.resilio_provider import ResilioSyncProvider


def _normalize_provider_type(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if value == "syncthing":
        return "ouisync"
    if value in {"resilio", "ouisync", "local"}:
        return value
    return "ouisync"


@dataclass(frozen=True)
class _ProviderPair:
    resilio: SyncProvider
    ouisync: SyncProvider | None = None


class DualSyncProviderRouter:
    """Expose one sync API while routing work to two backend providers."""

    def __init__(
        self,
        providers: _ProviderPair,
        *,
        default_provider_type: str,
        resolve_game_provider_type: Callable[[str], str | None],
        resolve_catalog_provider_types: Callable[[], set[str]] | None = None,
        startup_retry_seconds: float = 0.0,
    ):
        self._providers = providers
        self._default_provider_type = _normalize_provider_type(default_provider_type)
        self._resolve_game_provider_type = resolve_game_provider_type
        self._resolve_catalog_provider_types = resolve_catalog_provider_types
        self._startup_retry_seconds = max(0.0, float(startup_retry_seconds or 0.0))
        self._provider_start_attempt_at: dict[str, float] = {}

    def provider_for_type(self, provider_type: str | None) -> SyncProvider:
        provider = _normalize_provider_type(provider_type)
        if provider == "local":
            return NoopSyncProvider()
        if provider == "ouisync" and self._providers.ouisync is not None:
            return self._providers.ouisync
        return self._providers.resilio

    def provider_for_game(self, game_id: str) -> SyncProvider:
        provider_type = self._resolve_game_provider_type(game_id)
        return self.provider_for_type(provider_type or self._default_provider_type)

    def _all_providers(self) -> list[tuple[str, SyncProvider]]:
        providers = [
            ("resilio", self._providers.resilio),
        ]
        if self._providers.ouisync is not None:
            providers.append(("ouisync", self._providers.ouisync))
        return providers

    def _is_starting(self, provider_name: str, status: SyncStatus | None = None) -> bool:
        if self._startup_retry_seconds <= 0:
            return False
        started_at = self._provider_start_attempt_at.get(provider_name, 0.0)
        if started_at <= 0:
            return False
        if time.monotonic() - started_at > self._startup_retry_seconds:
            return False
        if status is not None and status.running:
            return False
        if status is not None and str(status.state or "").strip().lower() in {
            "blocked",
            "failed",
            "error",
        }:
            return False
        return True

    def _wrap_status(self, provider_name: str, status: SyncStatus) -> SyncStatus:
        if self._is_starting(provider_name, status):
            return SyncStatus(
                provider=status.provider,
                running=False,
                state="starting",
                pid=status.pid,
                last_error=status.last_error,
            )
        return status

    def start(self) -> SyncStatus:
        logger = logging.getLogger(__name__)
        statuses: list[SyncStatus] = []
        enabled_types = {self._default_provider_type}
        if self._resolve_catalog_provider_types is None:
            enabled_types.update(name for name, _provider in self._all_providers())
        else:
            try:
                enabled_types.update(
                    _normalize_provider_type(value)
                    for value in self._resolve_catalog_provider_types()
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("sync_provider_catalog_inventory_failed error=%s", exc)
        for name, provider in self._all_providers():
            if name not in enabled_types:
                continue
            self._provider_start_attempt_at[name] = time.monotonic()
            try:
                status = provider.start()
                statuses.append(status)
                if not status.running or status.last_error:
                    logger.warning(
                        "sync_provider_start_result provider=%s running=%s state=%s pid=%s last_error=%s",
                        name,
                        status.running,
                        status.state,
                        status.pid,
                        status.last_error,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sync_provider_start_failed provider=%s error=%s", name, exc
                )
                statuses.append(
                    SyncStatus(
                        provider="dual",
                        running=False,
                        state="failed",
                        last_error=str(exc),
                    )
                )
        return self._aggregate_status(statuses)

    def stop(self) -> SyncStatus:
        statuses: list[SyncStatus] = []
        for name, provider in self._all_providers():
            self._provider_start_attempt_at.pop(name, None)
            try:
                statuses.append(provider.stop())
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning("sync_provider_stop_failed: %s", exc)
                statuses.append(
                    SyncStatus(
                        provider="dual",
                        running=False,
                        state="failed",
                        last_error=str(exc),
                    )
                )
        return self._aggregate_status(statuses)

    def status(self) -> SyncStatus:
        statuses: list[tuple[str, SyncStatus]] = []
        for name, provider in self._all_providers():
            try:
                statuses.append((name, self._wrap_status(name, provider.status())))
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning("sync_provider_status_failed: %s", exc)
                statuses.append((
                    name,
                    SyncStatus(
                        provider="dual",
                        running=False,
                        state="failed",
                        last_error=str(exc),
                    ),
                ))
        return self._aggregate_status([status for _name, status in statuses])

    def status_for_type(self, provider_type: str | None) -> SyncStatus:
        provider_name = _normalize_provider_type(provider_type)
        provider = self.provider_for_type(provider_name)
        try:
            status = provider.status()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "sync_provider_status_for_type_failed provider=%s error=%s",
                provider_name,
                exc,
            )
            return SyncStatus(
                provider=provider_name,
                running=False,
                state="failed",
                last_error=str(exc),
            )
        return self._wrap_status(provider_name, status)

    def metrics(self) -> SyncMetrics:
        total_download = 0
        total_upload = 0
        for name, provider in self._all_providers():
            try:
                status = provider.status()
                if self._is_starting(name, status):
                    continue
                metrics = provider.metrics()
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "sync_provider_metrics_failed provider=%s error=%s", name, exc
                )
                continue
            total_download += max(0, int(metrics.download_bps))
            total_upload += max(0, int(metrics.upload_bps))
        return SyncMetrics(download_bps=total_download, upload_bps=total_upload)

    def metrics_for_game(self, game_id: str) -> SyncMetrics:
        provider = self.provider_for_game(game_id)
        provider_name = _normalize_provider_type(
            self._resolve_game_provider_type(game_id) or self._default_provider_type
        )
        try:
            status = provider.status()
            if self._is_starting(provider_name, status):
                return SyncMetrics(download_bps=0, upload_bps=0)
            return provider.metrics()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "sync_provider_metrics_for_game_failed game_id=%s error=%s",
                game_id,
                exc,
            )
            return SyncMetrics(download_bps=0, upload_bps=0)

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        provider = self.provider_for_type(self._default_provider_type)
        return provider.ensure_folder_synced(folder_path, secret)

    def ensure_folder_synced_for_game(
        self, game_id: str, folder_path: str, secret: str, provider_type: str | None
    ) -> tuple[bool, str]:
        provider = self.provider_for_type(provider_type or self._resolve_game_provider_type(game_id))
        return provider.ensure_folder_synced(folder_path, secret)

    def remove_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        results: list[tuple[bool, str]] = []
        for _name, provider in self._all_providers():
            results.append(provider.remove_folder_sync(folder_path))
        for ok, detail in results:
            if ok:
                return True, detail
        return results[-1] if results else (False, "sync_provider_unavailable")

    def remove_folder_sync_for_game(
        self, game_id: str, folder_path: str, provider_type: str | None
    ) -> tuple[bool, str]:
        provider = self.provider_for_type(provider_type or self._resolve_game_provider_type(game_id))
        return provider.remove_folder_sync(folder_path)

    def remove_folder_sync_by_secret(self, secret: str) -> tuple[bool, str]:
        results: list[tuple[bool, str]] = []
        for _name, provider in self._all_providers():
            results.append(provider.remove_folder_sync_by_secret(secret))
        for ok, detail in results:
            if ok:
                return True, detail
        return results[-1] if results else (False, "sync_provider_unavailable")

    def folder_sync_status(self, folder_path: str) -> dict[str, int | bool]:
        statuses = []
        for _name, provider in self._all_providers():
            try:
                statuses.append(provider.folder_sync_status(folder_path))
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "sync_provider_folder_status_failed provider=%s error=%s",
                    _name,
                    exc,
                )
        if not statuses:
            return {"active": False, "progress_percent": 0}

        best = statuses[0]
        for status in statuses[1:]:
            if bool(status.get("active", False)) and not bool(best.get("active", False)):
                best = status
                continue
            if int(status.get("progress_percent", 0) or 0) > int(
                best.get("progress_percent", 0) or 0
            ):
                best = status
        return best

    def folder_sync_status_for_game(
        self, game_id: str, folder_path: str, provider_type: str | None
    ) -> dict[str, int | bool]:
        provider = self.provider_for_type(provider_type or self._resolve_game_provider_type(game_id))
        try:
            return provider.folder_sync_status(folder_path)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "sync_provider_folder_status_for_game_failed game_id=%s error=%s",
                game_id,
                exc,
            )
            return {"active": False, "progress_percent": 0}

    def debug_logs(self, limit: int = 200) -> list[dict]:
        logs: list[dict] = []
        for provider_name, provider in self._all_providers():
            try:
                entries = provider.debug_logs(limit=limit)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "sync_provider_debug_logs_failed provider=%s error=%s",
                    provider_name,
                    exc,
                )
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    tagged = dict(entry)
                    tagged.setdefault("provider", provider_name)
                    logs.append(tagged)
        def _sort_key(entry: dict) -> tuple[float, str, str, str]:
            raw_ts = str(entry.get("ts", "") or "").strip()
            try:
                normalized = raw_ts.replace("Z", "+00:00")
                parsed = datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                timestamp = parsed.timestamp()
            except Exception:  # noqa: BLE001
                timestamp = float("inf")
            return (
                timestamp,
                str(entry.get("provider", "") or ""),
                str(entry.get("level", "") or ""),
                str(entry.get("msg", "") or ""),
            )

        logs.sort(key=_sort_key)
        return logs[-limit:]

    def set_peer_device_ids(self, device_ids: list[str]) -> None:
        for _name, provider in self._all_providers():
            try:
                provider.set_peer_device_ids(device_ids)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "sync_provider_set_peers_failed provider=%s error=%s",
                    _name,
                    exc,
                )

    def _aggregate_status(self, statuses: list[SyncStatus]) -> SyncStatus:
        if not statuses:
            return SyncStatus(provider="dual", running=False, state="disabled")
        running = any(status.running for status in statuses)
        states = [str(status.state or "").strip().lower() for status in statuses]
        if running:
            state = "running"
        elif "blocked" in states:
            state = "blocked"
        elif "failed" in states or "error" in states:
            state = "failed"
        elif "starting" in states:
            state = "starting"
        else:
            state = "stopped"
        last_error = "; ".join(
            status.last_error for status in statuses if status.last_error
        )
        pid = next((status.pid for status in statuses if status.pid is not None), None)
        return SyncStatus(
            provider="dual",
            running=running,
            state=state,
            pid=pid,
            last_error=last_error,
        )


def create_dual_sync_provider(
    config: AppConfig,
    *,
    resolve_game_provider_type: Callable[[str], str | None],
    resolve_catalog_provider_types: Callable[[], set[str]] | None = None,
) -> DualSyncProviderRouter:
    resilio = ResilioSyncProvider(
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
    ouisync = OuisyncSyncProvider(
        binary_path=config.ouisync_binary_path,
        config_dir=config.ouisync_config_dir,
        log_path=config.ouisync_log_path,
        repo_root=config.repo_root,
        startup_timeout_seconds=config.ouisync_startup_timeout_seconds,
        request_timeout_seconds=config.sync_request_timeout_seconds,
    )
    return DualSyncProviderRouter(
        _ProviderPair(resilio=resilio, ouisync=ouisync),
        default_provider_type=config.sync_provider,
        resolve_game_provider_type=resolve_game_provider_type,
        resolve_catalog_provider_types=resolve_catalog_provider_types,
        startup_retry_seconds=max(30.0, config.sync_startup_retry_seconds),
    )
