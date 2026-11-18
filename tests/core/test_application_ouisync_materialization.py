from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from src.core.config.loader import AppConfig
from src.core.launcher.game_manager import GameActionResult
from src.core.service.app import Application
from src.core.sync.provider import SyncStatus


class ApplicationOuisyncMaterializationTests(unittest.TestCase):
    def test_repository_copy_is_limited_to_mapped_game_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            provider = Mock()
            provider.repository_token_status.return_value = {
                "available": True,
                "info_hash": "abc123",
            }
            provider.copy_repository_entry_to_disk.return_value = {
                "ok": True,
                "message": "ouisync_repository_entry_copied",
            }
            with (
                patch.object(app, "_sync_provider_for_type", return_value=provider),
                patch.object(
                    app,
                    "_extra_sync_items_read",
                    return_value={"items": [{"game_id": "demo", "game_key": "secret"}]},
                ),
            ):
                result = app._ouisync_repository_entry_copy(
                    "abc123", "/archive.tar.gz", "."
                )
            self.assertTrue(result["ok"])
            provider.copy_repository_entry_to_disk.assert_called_once_with(
                "abc123", "/archive.tar.gz", str(Path(temporary) / "demo"), "."
            )

    def test_ouisync_inventory_labels_extra_repository_with_its_game_id(self) -> None:
        app = Application(AppConfig(bind_port=0))
        self.addCleanup(app._server.server_close)
        provider = Mock()
        provider.repository_inventory.return_value = {
            "available": True,
            "repositories": [
                {"info_hash": "abc123", "label": "repository"},
            ],
            "network": {},
        }
        provider.repository_token_status.return_value = {
            "available": True,
            "attached": True,
            "info_hash": "abc123",
        }
        provider.status.return_value = SyncStatus("ouisync", True, "running")
        with (
            patch.object(app, "_sync_provider_for_type", return_value=provider),
            patch.object(
                app,
                "_extra_sync_items_read",
                return_value={
                    "items": [
                        {"game_id": "ng_provider", "game_key": "SECRET"},
                    ]
                },
            ),
        ):
            payload = app._ouisync_repository_inventory_read()  # noqa: SLF001

        self.assertEqual(payload["repositories"][0]["game_id"], "ng_provider")
        self.assertEqual(payload["repositories"][0]["label"], "ng_provider")
        provider.repository_token_status.assert_called_once_with("SECRET")

    def test_startup_reconciles_missing_ng_provider_repository_once_attached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            provider = Mock()
            provider.status.return_value = SyncStatus("ouisync", True, "running")
            provider.repository_token_status.side_effect = [
                {"available": True, "attached": False, "info_hash": "seed-hash"},
                {"available": True, "attached": True, "info_hash": "seed-hash"},
            ]
            provider.ensure_folder_synced.return_value = (
                True,
                "ouisync_repository_enabled",
            )
            provider.start_repository_materialization.return_value = (
                True,
                "ouisync_repository_syncing",
            )
            with (
                patch.object(app, "_sync_provider_for_type", return_value=provider),
                patch.object(
                    app,
                    "_extra_sync_items_read",
                    return_value={
                        "items": [
                            {
                                "game_id": "ng_provider",
                                "sync_enabled": True,
                                "game_key": "SECRET",
                            }
                        ]
                    },
                ),
                patch.object(app, "_effective_library_path", return_value=temporary),
            ):
                app._reconcile_ng_provider_repository()
                app._reconcile_ng_provider_repository()
            provider.ensure_folder_synced.assert_called_once_with(
                str(Path(temporary) / "ng_provider"), "SECRET"
            )
            provider.repository_token_status.assert_called_with("SECRET")
            provider.start_repository_materialization.assert_called_once()
            materialization = provider.start_repository_materialization.call_args
            self.assertEqual(materialization.args[0].game_id, "ng_provider")
            self.assertEqual(materialization.args[0].expected_info_hash, "seed-hash")
            self.assertEqual(materialization.args[1], str(Path(temporary) / "ng_provider"))
            self.assertEqual(
                materialization.kwargs["materialized_directory"],
                str(Path(temporary) / "ng_provider"),
            )
            self.assertEqual(
                materialization.kwargs["marker_paths"],
                (
                    "update/index.json",
                    "update/update-manifest.json",
                    "update/trusted-publishers.json",
                ),
            )

    def test_sync_watchdog_checks_ng_provider_when_ouisync_already_runs(self) -> None:
        app = Application(AppConfig(bind_port=0))
        self.addCleanup(app._server.server_close)
        ouisync = Mock()

        class _Router:
            def provider_for_type(self, provider_type: str):
                return Mock() if provider_type == "resilio" else ouisync

            @staticmethod
            def status_for_type(provider_type: str) -> SyncStatus:
                return SyncStatus(
                    provider_type,
                    provider_type == "ouisync",
                    "running" if provider_type == "ouisync" else "stopped",
                )

        app._state.sync_provider = _Router()  # noqa: SLF001
        with (
            patch.object(app, "_reconcile_ng_provider_repository") as reconcile,
            patch.object(app, "_ouisync_manage_lan_cycle"),
            patch.object(app, "_run_auto_install_watchdog_cycle"),
        ):
            handled = app._run_sync_watchdog_provider_cycle(  # noqa: SLF001
                app._state.sync_provider, logging.getLogger(__name__)
            )

        self.assertTrue(handled)
        reconcile.assert_called_once_with()

    def test_ouisync_diagnostics_report_missing_provider_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            provider = Mock()
            provider.status.return_value = SyncStatus("ouisync", True, "running")
            provider.repository_inventory.return_value = {
                "available": True,
                "repositories": [],
                "peer_count": 2,
            }
            provider.repository_token_status.return_value = {
                "available": True,
                "attached": False,
            }
            with (
                patch.object(app, "_sync_provider_for_type", return_value=provider),
                patch.object(
                    app,
                    "_extra_sync_items_read",
                    return_value={"items": [{"game_id": "ng_provider", "sync_enabled": True, "game_key": "SECRET"}]},
                ),
                patch.object(app, "_effective_library_path", return_value=temporary),
            ):
                result = app._ouisync_debug_action("ng-provider")
            self.assertFalse(result["ok"])
            self.assertTrue(any(line["key"] == "ui.ouisync_debug_repository_attached" for line in result["lines"]))
            self.assertNotIn("SECRET", str(result))

    def test_reset_ng_provider_clears_only_local_cache_and_reattaches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            root = Path(temporary) / "ng_provider"
            (root / ".ouisync").mkdir(parents=True)
            (root / ".ouisync" / "stale.db").write_text("stale", encoding="utf-8")
            provider = Mock()
            provider.status.return_value = SyncStatus("ouisync", True, "running")
            provider.remove_folder_sync.return_value = (False, "ouisync_repository_not_found")
            provider.ensure_folder_synced.return_value = (True, "ouisync_repository_enabled")
            with (
                patch.object(app, "_sync_provider_for_type", return_value=provider),
                patch.object(
                    app,
                    "_extra_sync_items_read",
                    return_value={"items": [{"game_id": "ng_provider", "sync_enabled": True, "game_key": "SECRET"}]},
                ),
                patch.object(app, "_effective_library_path", return_value=temporary),
            ):
                result = app._ouisync_debug_action("reset-ng-provider")
            self.assertTrue(result["ok"])
            self.assertTrue(root.is_dir())
            self.assertFalse((root / ".ouisync" / "stale.db").exists())
            provider.ensure_folder_synced.assert_called_once_with(str(root), "SECRET")

    def test_game_sync_start_uses_only_verified_index_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            access = object()
            index_store = Mock()
            index_store.ouisync_repository_access.return_value = access
            app._state.game_index_store = index_store
            app._state.sync_provider = Mock()
            app._state.sync_provider.start_game_materialization.return_value = (
                True,
                "ouisync_repository_materializing",
            )
            app._state.repository = Mock()
            app._state.repository.get_game.return_value = {
                "key": "",
                "game_provider_type": "ouisync",
                "installed_version": "1",
            }
            app._state.repository.current_install_state.return_value = "missing"

            with (
                patch.object(app, "_is_game_disabled", return_value=False),
                patch.object(app, "_effective_library_path", return_value=temporary),
                patch.object(
                    app, "_resolve_game_provider_type", return_value="ouisync"
                ),
                patch.object(
                    app,
                    "_sync_provider_for_game",
                    return_value=app._state.sync_provider,
                ),
                patch.object(app, "_game_sync_status_payload", return_value={}),
            ):
                result = app._game_sync_start("demo")

            self.assertTrue(result["ok"])
            index_store.ouisync_repository_access.assert_called_once_with("demo")
            app._state.sync_provider.start_game_materialization.assert_called_once_with(
                access,
                str(Path(temporary) / "demo"),
                str(Path(temporary) / "demo" / ".ouisync" / "demo"),
            )
            app._state.repository.set_install_state.assert_called_once_with(
                "demo", "downloading", "1"
            )

    def test_ouisync_sync_start_fails_closed_without_verified_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            app._state.game_index_store = Mock()
            app._state.game_index_store.ouisync_repository_access.return_value = None
            app._state.repository = Mock()
            app._state.repository.get_game.return_value = {
                "game_provider_type": "ouisync"
            }
            app._state.sync_provider = Mock()
            with (
                patch.object(app, "_is_game_disabled", return_value=False),
                patch.object(
                    app, "_resolve_game_provider_type", return_value="ouisync"
                ),
                patch.object(
                    app,
                    "_sync_provider_for_game",
                    return_value=app._state.sync_provider,
                ),
            ):
                result = app._game_sync_start("demo")
            self.assertFalse(result["ok"])
            self.assertEqual(result["message"], "ouisync_catalog_access_unavailable")
            app._state.sync_provider.start_game_materialization.assert_not_called()

    def test_stopping_ouisync_keeps_archive_source_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            game_folder = Path(temporary) / "demo"
            repository_root = game_folder / ".ouisync"
            repository_root.mkdir(parents=True)
            archive = repository_root / "demo.tar.gz"
            archive.write_bytes(b"archive")
            provider = Mock()
            provider.remove_folder_sync.return_value = (
                True,
                "ouisync_repository_paused",
            )
            app._state.sync_provider = provider
            app._state.repository = Mock()
            app._state.repository.get_game.return_value = {
                "install_state": "missing",
                "game_provider_type": "ouisync",
            }
            with (
                patch.object(app, "_is_game_disabled", return_value=False),
                patch.object(
                    app, "_resolve_game_provider_type", return_value="ouisync"
                ),
                patch.object(app, "_sync_provider_for_game", return_value=provider),
                patch.object(app, "_effective_library_path", return_value=temporary),
                patch.object(app, "_game_sync_status_payload", return_value={}),
            ):
                result = app._game_sync_stop("demo")
            self.assertTrue(result["ok"])
            self.assertTrue(archive.is_file())
            provider.remove_folder_sync.assert_called_once_with(
                str(game_folder / ".ouisync" / "demo")
            )

    def test_install_reads_archive_from_temporary_repository_mount(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            game_folder = Path(temporary) / "demo"
            mounted = Path(temporary) / "mounted" / "demo"
            mounted.mkdir(parents=True)
            (mounted / "metadata.json").write_text(
                '{"distribution":{"archive":{"file":"demo.tar.gz","format":"tar.gz"}}}',
                encoding="utf-8",
            )
            (mounted / "demo.tar.gz").write_bytes(b"archive")
            access = SimpleNamespace(editable_files=())
            manager = Mock()
            manager.install.return_value = GameActionResult(
                False, "install", "demo", "extract_failed", {}
            )
            app._state.game_manager = manager
            app._state.repository = Mock()
            app._state.repository.get_game.return_value = {
                "game_provider_type": "ouisync",
                "installed_version": "",
            }
            provider = Mock()
            provider.status.return_value = SimpleNamespace(state="running")
            provider.run_with_game_repository_mounted.side_effect = (
                lambda _access, _path, action: action(mounted)
            )

            with (
                patch.object(app, "_effective_library_path", return_value=temporary),
                patch.object(
                    app,
                    "_ouisync_game_repository_path",
                    return_value=game_folder / ".ouisync" / "demo",
                ),
                patch.object(app, "_ouisync_game_access", return_value=access),
                patch.object(app, "_sync_provider_for_game", return_value=provider),
            ):
                result = app._game_action("demo", "install")

            self.assertFalse(result["ok"])
            provider.run_with_game_repository_mounted.assert_called_once()
            self.assertEqual(
                manager.install.call_args.kwargs["archive_source_root"], mounted
            )
            self.assertTrue((game_folder / ".ouisync" / "metadata.json").is_file())

    def test_auto_install_watchdog_installs_completed_ouisync_repo_without_local_archive(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            manager = Mock()
            manager.archive_path.return_value = Path(temporary) / "missing.tar.gz"
            app._state.game_manager = manager
            app._state.repository = Mock()
            app._state.repository.list_sync_targets.return_value = [{"id": "demo"}]
            app._state.repository.get_game.return_value = {
                "game_provider_type": "ouisync",
                "install_state": "downloading",
                "needs_update": False,
                "size_gb": 1,
                "version": "1",
            }
            app._state.sync_provider = Mock()
            app._state.user_settings = SimpleNamespace(sync_only_mode=False)
            app._state.install_failed_archive_signatures = {}
            game_provider = Mock()
            game_provider.game_materialization_status.return_value = {
                "phase": "complete",
                "progress_percent": 100,
            }

            with (
                patch.object(app, "_effective_library_path", return_value=temporary),
                patch.object(app, "_is_game_disabled", return_value=False),
                patch.object(
                    app, "_sync_provider_for_game", return_value=game_provider
                ),
                patch.object(
                    app,
                    "_ouisync_game_access",
                    return_value=SimpleNamespace(expected_info_hash="verified-hash"),
                ),
                patch.object(
                    app,
                    "_game_action",
                    return_value={
                        "ok": False,
                        "message": "install_failed",
                        "details": {},
                    },
                ) as game_action,
            ):
                app._run_auto_install_watchdog_cycle()

            game_action.assert_called_once_with("demo", "install")
            manager.archive_path.assert_not_called()


    def test_lan_catalog_is_joined_as_private_repository_without_dht(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            provider = Mock()
            provider.game_materialization_status.return_value = {"phase": "idle"}
            provider.start_game_materialization.return_value = (True, "started")
            with (
                patch.object(
                    app,
                    "_lan_pair_access_read",
                    return_value={
                        "catalog_token": "TOKEN",
                        "catalog_hash": "abc",
                        "peer_addrs": [],
                    },
                ),
                patch.object(app, "_sync_provider_for_type", return_value=provider),
                patch.object(app, "_effective_library_path", return_value=temporary),
            ):
                app._ouisync_lan_catalog_cycle()

            access = provider.start_game_materialization.call_args.args[0]
            self.assertEqual(access.game_id, "locallansync")
            self.assertEqual(access.repository_namespace, "lan-repository")

    def test_ouisync_peer_action_routes_only_to_ouisync_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            provider = Mock()
            provider.update_user_provided_peer.return_value = {"ok": True}
            with patch.object(
                app, "_sync_provider_for_type", return_value=provider
            ) as provider_for_type:
                result = app._ouisync_peer_action(" ADD ", "192.168.1.20:20209")
            self.assertEqual(result, {"ok": True})
            provider_for_type.assert_called_once_with("ouisync")
            provider.update_user_provided_peer.assert_called_once_with(
                "add", "192.168.1.20:20209"
            )
            with patch.object(app, "_sync_provider_for_type", return_value=None):
                self.assertEqual(
                    app._ouisync_peer_action("add", "192.168.1.20:20209")["message"],
                    "sync_provider_unavailable",
                )

    def _watchdog_app(self, temporary: str, game: dict, game_provider: Mock):
        app = Application(AppConfig(bind_port=0, library_path=temporary))
        self.addCleanup(app._server.server_close)
        manager = Mock()
        app._state.game_manager = manager
        app._state.repository = Mock()
        app._state.repository.list_sync_targets.return_value = [{"id": "demo"}]
        app._state.repository.get_game.return_value = {
            "game_provider_type": "ouisync",
            "needs_update": False,
            "size_gb": 1,
            "version": "1",
            **game,
        }
        app._state.sync_provider = Mock()
        app._state.user_settings = SimpleNamespace(sync_only_mode=False)
        app._state.install_failed_archive_signatures = {}
        patches = (
            patch.object(app, "_effective_library_path", return_value=temporary),
            patch.object(app, "_is_game_disabled", return_value=False),
            patch.object(app, "_sync_provider_for_game", return_value=game_provider),
            patch.object(
                app,
                "_ouisync_game_access",
                return_value=SimpleNamespace(expected_info_hash="verified-hash"),
            ),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return app

    def test_auto_install_waits_while_fresh_repository_reports_zero_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game_provider = Mock()
            # A fresh replica reports 0/0 blocks before the first snapshot index.
            game_provider.folder_sync_status.return_value = {
                "active": True,
                "progress_percent": 100,
            }
            game_provider.game_materialization_status.return_value = {
                "phase": "syncing",
                "completed": 0,
                "total": 0,
                "progress_percent": 0,
            }
            app = self._watchdog_app(
                temporary, {"install_state": "downloading"}, game_provider
            )
            with patch.object(app, "_game_action") as game_action:
                app._run_auto_install_watchdog_cycle()

            game_action.assert_not_called()
            game_provider.start_game_materialization.assert_not_called()
            app._state.repository.set_install_state.assert_not_called()
            self.assertIn(
                "downloading archive: 0%", app._install_console_snapshot("demo")
            )

    def test_auto_install_resumes_interrupted_download_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game_provider = Mock()
            # After a restart the job is gone and Ouisync reopened the repository paused.
            game_provider.folder_sync_status.return_value = {
                "active": False,
                "progress_percent": 98,
            }
            game_provider.game_materialization_status.return_value = {"phase": "idle"}
            game_provider.start_game_materialization.return_value = (
                True,
                "ouisync_repository_syncing",
            )
            app = self._watchdog_app(
                temporary, {"install_state": "installing"}, game_provider
            )
            with patch.object(app, "_game_action") as game_action:
                app._run_auto_install_watchdog_cycle()
                app._run_auto_install_watchdog_cycle()

            game_action.assert_not_called()
            game_provider.start_game_materialization.assert_called_once()
            args = game_provider.start_game_materialization.call_args.args
            self.assertEqual(args[1], str(Path(temporary) / "demo"))
            self.assertEqual(
                args[2], str(Path(temporary) / "demo" / ".ouisync" / "demo")
            )
            app._state.repository.set_install_state.assert_called_with(
                "demo", "downloading", ""
            )

    def test_auto_install_does_not_resume_or_reinstall_without_download_intent(
        self,
    ) -> None:
        for phase in ("idle", "cancelled", "complete"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                game_provider = Mock()
                game_provider.game_materialization_status.return_value = {
                    "phase": phase
                }
                app = self._watchdog_app(
                    temporary, {"install_state": "missing"}, game_provider
                )
                with patch.object(app, "_game_action") as game_action:
                    app._run_auto_install_watchdog_cycle()

                game_action.assert_not_called()
                game_provider.start_game_materialization.assert_not_called()

    def test_auto_install_keeps_download_intent_when_install_is_interrupted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            game_provider = Mock()
            game_provider.game_materialization_status.return_value = {
                "phase": "complete"
            }
            app = self._watchdog_app(
                temporary, {"install_state": "downloading"}, game_provider
            )
            with patch.object(
                app,
                "_game_action",
                return_value={
                    "ok": False,
                    "message": "ouisync_install_interrupted",
                    "details": {},
                },
            ):
                app._run_auto_install_watchdog_cycle()

            app._state.repository.set_install_state.assert_called_with(
                "demo", "downloading", ""
            )
            self.assertEqual(app._state.install_failed_archive_signatures, {})

    def test_install_interrupted_by_ouisync_shutdown_keeps_download_intent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Application(AppConfig(bind_port=0, library_path=temporary))
            self.addCleanup(app._server.server_close)
            app._state.game_manager = Mock()
            app._state.repository = Mock()
            app._state.repository.get_game.return_value = {
                "game_provider_type": "ouisync",
                "installed_version": "",
            }
            provider = Mock()
            states = iter(["running", "stopped"])
            provider.status.side_effect = lambda: SimpleNamespace(state=next(states))
            provider.run_with_game_repository_mounted.side_effect = RuntimeError(
                "event loop stopped"
            )
            with (
                patch.object(app, "_effective_library_path", return_value=temporary),
                patch.object(
                    app,
                    "_ouisync_game_repository_path",
                    return_value=Path(temporary) / "demo" / ".ouisync" / "demo",
                ),
                patch.object(
                    app,
                    "_ouisync_game_access",
                    return_value=SimpleNamespace(editable_files=()),
                ),
                patch.object(app, "_sync_provider_for_game", return_value=provider),
            ):
                result = app._game_action("demo", "install")

            self.assertFalse(result["ok"])
            self.assertEqual(result["message"], "ouisync_install_interrupted")
            app._state.repository.set_install_state.assert_called_with(
                "demo", "downloading", ""
            )


if __name__ == "__main__":
    unittest.main()
