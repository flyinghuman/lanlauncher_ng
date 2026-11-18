"""LAN-owned game activation must use the restricted peer configuration."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.core.config.loader import AppConfig
from src.core.service.app import Application
from src.core.sync.ouisync_provider import OuisyncRepositoryAccess


class LanGameRoutingTests(unittest.TestCase):
    def test_lan_sync_uses_ouisync_capability_without_external_seed_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(AppConfig(bind_port=0, library_path=tmp))
            self.addCleanup(app._server.server_close)
            provider = Mock()
            provider.start_game_materialization.return_value = (True, "ouisync_repository_ready")
            app._state.sync_provider = Mock()
            app._state.repository = Mock()
            app._state.repository.lan_game_ouisync_access.return_value = OuisyncRepositoryAccess(
                game_id="demo", read_token="token", expected_info_hash="ab" * 20
            )
            app._state.repository.get_game.return_value = {"key": "folder-id"}
            app._state.repository.game_id_records.return_value = {"lan_source": "lan-server"}
            app._state.repository.current_install_state.return_value = "missing"
            with (patch.object(app, "_is_game_disabled", return_value=False),
                  patch.object(app, "_effective_library_path", return_value=tmp),
                  patch.object(app, "_resolve_game_provider_type", return_value="ouisync"),
                  patch.object(app, "_sync_provider_for_game", return_value=provider),
                  patch.object(app, "_game_sync_status_payload", return_value={})):
                result = app._game_sync_start("demo")
            self.assertTrue(result["ok"])
            provider.start_game_materialization.assert_called_once()
            provider.set_peer_device_ids.assert_not_called()
            app._state.sync_provider.ensure_folder_synced_for_game.assert_not_called()

    def test_ouisync_materialization_progress_is_not_replaced_by_archive_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(AppConfig(bind_port=0, library_path=tmp))
            self.addCleanup(app._server.server_close)
            folder = Path(tmp) / "demo"
            folder.mkdir()
            (folder / "demo.eti").write_bytes(b"complete-looking archive")
            sync = Mock()
            sync.folder_sync_status.return_value = {"active": True, "progress_percent": 0,
                                                   "authoritative_progress": True, "down_status": 1}
            app._state.sync_provider = sync
            del sync.provider_for_game
            self.assertEqual(app._folder_sync_status(folder, 0.000000001)["progress_percent"], 0)

    def test_rescan_never_uses_legacy_provider_for_lan_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(AppConfig(bind_port=0, library_path=tmp))
            self.addCleanup(app._server.server_close)
            folder = Path(tmp) / "demo"
            folder.mkdir()
            (folder / "demo.eti").write_text("data")
            app._state.sync_provider = Mock()
            app._state.repository = Mock()
            app._state.repository.list_sync_targets.return_value = [{"id": "demo", "key": "folder"}]
            app._state.repository.game_id_records.return_value = {"lan_source": "lan-server"}
            app._state.rescan_sync_progress = {}
            with patch.object(app, "_effective_library_path", return_value=tmp), patch.object(app, "_is_game_disabled", return_value=False):
                app._run_resilio_folder_sync_rescan()
            app._state.sync_provider.ensure_folder_synced.assert_not_called()
            self.assertEqual(app._state.rescan_sync_progress["skipped"], 1)
