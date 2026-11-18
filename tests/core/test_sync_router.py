"""Tests for the dual sync provider router."""

from __future__ import annotations

import unittest
import time
from unittest.mock import Mock, patch

from src.core.sync.provider import SyncMetrics, SyncStatus
from src.core.sync.router import DualSyncProviderRouter, _ProviderPair


class _FakeProvider:
    def __init__(
        self,
        *,
        name: str,
        running: bool = False,
        state: str = "stopped",
        download_bps: int = 0,
        upload_bps: int = 0,
        metrics_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.running = running
        self.state = state
        self.download_bps = download_bps
        self.upload_bps = upload_bps
        self.metrics_error = metrics_error
        self.started = 0
        self.stopped = 0

    def start(self) -> SyncStatus:
        self.started += 1
        return SyncStatus(provider=self.name, running=self.running, state=self.state, pid=123)

    def stop(self) -> SyncStatus:
        self.stopped += 1
        self.running = False
        self.state = "stopped"
        return SyncStatus(provider=self.name, running=False, state="stopped")

    def status(self) -> SyncStatus:
        return SyncStatus(provider=self.name, running=self.running, state=self.state)

    def metrics(self) -> SyncMetrics:
        if self.metrics_error is not None:
            raise self.metrics_error
        return SyncMetrics(
            download_bps=self.download_bps,
            upload_bps=self.upload_bps,
        )

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        _ = folder_path
        _ = secret
        return True, "ok"

    def remove_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        _ = folder_path
        return True, "ok"

    def remove_folder_sync_by_secret(self, secret: str) -> tuple[bool, str]:
        _ = secret
        return True, "ok"

    def folder_sync_status(self, folder_path: str) -> dict[str, int | bool]:
        _ = folder_path
        return {"active": False, "progress_percent": 0}

    def debug_logs(self, limit: int = 200) -> list[dict]:
        _ = limit
        return [{"msg": f"{self.name} log line"}]

    def set_peer_device_ids(self, device_ids: list[str]) -> None:
        _ = device_ids

    def web_ui_url(self) -> str:
        return f"http://127.0.0.1/{self.name}"


class SyncRouterTests(unittest.TestCase):
    def test_routes_ouisync_default_and_explicit_provider_types(self) -> None:
        resilio = _FakeProvider(name="resilio")
        ouisync = _FakeProvider(name="ouisync")
        router = DualSyncProviderRouter(
            _ProviderPair(resilio=resilio, ouisync=ouisync),
            default_provider_type="ouisync",
            resolve_game_provider_type=lambda _game_id: None,
        )

        self.assertIs(router.provider_for_game("ng_provider"), ouisync)
        self.assertIs(router.provider_for_type("ouisync"), ouisync)
        self.assertIs(router.provider_for_type("resilio"), resilio)

    def test_start_only_launches_providers_needed_by_catalog(self) -> None:
        resilio = _FakeProvider(name="resilio")
        ouisync = _FakeProvider(name="ouisync")
        router = DualSyncProviderRouter(
            _ProviderPair(resilio=resilio, ouisync=ouisync),
            default_provider_type="ouisync",
            resolve_game_provider_type=lambda _game_id: None,
            resolve_catalog_provider_types=lambda: {"ouisync"},
        )

        router.start()

        self.assertEqual(ouisync.started, 1)
        self.assertEqual(resilio.started, 0)

    def test_status_reports_starting_during_startup_grace(self) -> None:
        resilio = _FakeProvider(name="resilio")
        ouisync = _FakeProvider(name="ouisync")
        router = DualSyncProviderRouter(
            _ProviderPair(resilio=resilio, ouisync=ouisync),
            default_provider_type="resilio",
            resolve_game_provider_type=lambda _game_id: None,
            startup_retry_seconds=10.0,
        )

        router.start()
        status = router.status()

        self.assertEqual(status.state, "starting")
        self.assertFalse(status.running)

    def test_status_does_not_mask_failed_provider_as_starting(self) -> None:
        resilio = _FakeProvider(name="resilio", state="failed")
        ouisync = _FakeProvider(name="ouisync")
        router = DualSyncProviderRouter(
            _ProviderPair(resilio=resilio, ouisync=ouisync),
            default_provider_type="resilio",
            resolve_game_provider_type=lambda _game_id: None,
            startup_retry_seconds=10.0,
        )

        router.start()
        status = router.status()

        self.assertEqual(status.state, "failed")
        self.assertFalse(status.running)

    def test_start_logs_partial_provider_errors(self) -> None:
        resilio = _FakeProvider(name="resilio", running=True, state="running")
        ouisync = _FakeProvider(
            name="ouisync",
            running=True,
            state="running",
        )
        router = DualSyncProviderRouter(
            _ProviderPair(resilio=resilio, ouisync=ouisync),
            default_provider_type="resilio",
            resolve_game_provider_type=lambda _game_id: None,
            startup_retry_seconds=10.0,
        )

        def _start_with_error() -> SyncStatus:
            return SyncStatus(
                provider="ouisync",
                running=True,
                state="running",
                pid=4321,
                last_error="<urlopen error [Errno 111] Connection refused>",
            )

        ouisync.start = _start_with_error  # type: ignore[method-assign]
        logger = Mock()

        with patch("src.core.sync.router.logging.getLogger", return_value=logger):
            status = router.start()

        self.assertTrue(status.running)
        self.assertEqual(status.state, "running")
        self.assertIn("Connection refused", status.last_error)
        logger.warning.assert_called_with(
            "sync_provider_start_result provider=%s running=%s state=%s pid=%s last_error=%s",
            "ouisync",
            True,
            "running",
            4321,
            "<urlopen error [Errno 111] Connection refused>",
        )

    def test_metrics_suppresses_startup_connection_refused_warnings(self) -> None:
        resilio = _FakeProvider(
            name="resilio",
            metrics_error=OSError("[Errno 111] Connection refused"),
        )
        ouisync = _FakeProvider(
            name="ouisync",
            running=True,
            state="running",
            download_bps=1024,
            upload_bps=512,
        )
        router = DualSyncProviderRouter(
            _ProviderPair(resilio=resilio, ouisync=ouisync),
            default_provider_type="resilio",
            resolve_game_provider_type=lambda _game_id: None,
            startup_retry_seconds=10.0,
        )
        logger = Mock()
        router._provider_start_attempt_at["resilio"] = time.monotonic()  # noqa: SLF001

        with patch("src.core.sync.router.logging.getLogger", return_value=logger):
            metrics = router.metrics()

        self.assertEqual(metrics.download_bps, 1024)
        self.assertEqual(metrics.upload_bps, 512)
        logger.warning.assert_not_called()

    def test_debug_logs_tag_each_provider_source(self) -> None:
        resilio = _FakeProvider(name="resilio")
        ouisync = _FakeProvider(name="ouisync")
        router = DualSyncProviderRouter(
            _ProviderPair(resilio=resilio, ouisync=ouisync),
            default_provider_type="resilio",
            resolve_game_provider_type=lambda _game_id: None,
            startup_retry_seconds=10.0,
        )

        logs = router.debug_logs(limit=10)

        self.assertEqual(
            [entry.get("provider") for entry in logs],
            ["ouisync", "resilio"],
        )
        self.assertEqual(logs[0]["msg"], "ouisync log line")
        self.assertEqual(logs[1]["msg"], "resilio log line")

    def test_debug_logs_merge_by_timestamp_across_providers(self) -> None:
        class _TimedProvider(_FakeProvider):
            def __init__(self, *, name: str, entries: list[dict]) -> None:
                super().__init__(name=name)
                self._entries = entries

            def debug_logs(self, limit: int = 200) -> list[dict]:
                _ = limit
                return list(self._entries)

        resilio = _TimedProvider(
            name="resilio",
            entries=[
                {"ts": "2026-06-17T10:00:02+00:00", "msg": "resilio late"},
                {"ts": "2026-06-17T10:00:00+00:00", "msg": "resilio early"},
            ],
        )
        ouisync = _TimedProvider(
            name="ouisync",
            entries=[
                {"ts": "2026-06-17T10:00:01+00:00", "msg": "ouisync middle"},
                {"ts": "2026-06-17T10:00:00+00:00", "msg": "ouisync early"},
            ],
        )
        router = DualSyncProviderRouter(
            _ProviderPair(resilio=resilio, ouisync=ouisync),
            default_provider_type="resilio",
            resolve_game_provider_type=lambda _game_id: None,
            startup_retry_seconds=10.0,
        )

        logs = router.debug_logs(limit=10)

        self.assertEqual(
            [entry["msg"] for entry in logs],
            ["ouisync early", "resilio early", "ouisync middle", "resilio late"],
        )


if __name__ == "__main__":
    unittest.main()
