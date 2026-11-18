"""Discovery remains separate from the loopback control API."""

import json
import socket
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from src.core.config.loader import AppConfig
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings
from src.core.sync.lan_discovery import LanDiscoveryServer, discover_servers

DEVICE = "-".join(["AAAAAAA"] * 8)


class DiscoveryTests(unittest.TestCase):
    def test_finds_server_over_loopback_and_closes_listener(self):
        server = LanDiscoveryServer(
            lambda: {"name": "Test LAN", "device_id": DEVICE}, host="127.0.0.1", port=0
        )
        server.start()
        try:
            found = discover_servers(target="127.0.0.1", port=server.port, timeout=0.2)
            self.assertEqual(
                found,
                [
                    {
                        "name": "Test LAN",
                        "device_id": DEVICE,
                        "address": "127.0.0.1",
                        "catalog_folder_id": "locallansync",
                        "tcp_port": 22000,
                    }
                ],
            )
        finally:
            server.close()
        self.assertFalse(server._thread.is_alive())

    def test_ignores_malformed_and_non_discovery_requests(self):
        server = LanDiscoveryServer(
            lambda: {"name": "Test", "device_id": DEVICE}, host="127.0.0.1", port=0
        )
        server.start()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(0.2)
                for payload in (
                    b"not json",
                    json.dumps({"type": "pair", "nonce": "a" * 32}).encode(),
                    b"x" * 1025,
                ):
                    client.sendto(payload, ("127.0.0.1", server.port))
                with self.assertRaises(socket.timeout):
                    client.recvfrom(1024)
        finally:
            server.close()

    def test_client_action_and_server_lifecycle_follow_role(self):
        app = Application(AppConfig(bind_port=0))
        self.addCleanup(app._server.server_close)
        settings = UserSettings(
            nickname="Host",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="library",
            lan_mode="server",
        )
        app._state.user_settings = settings
        server = Mock()
        with patch("src.core.service.app.LanDiscoveryServer", return_value=server):
            app._refresh_lan_discovery()
            server.start.assert_called_once()
            app._state.user_settings = replace(
                settings, lan_mode="client"
            )
            app._refresh_lan_discovery()
            server.close.assert_called_once()
        with patch(
            "src.core.service.app.discover_servers",
            return_value=[{"address": "127.0.0.1"}],
        ) as discover:
            result = app._lan_game_share_update(
                {"action": "discover_servers", "address": "127.0.0.1"}
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["servers"], [{"address": "127.0.0.1"}])
        discover.assert_called_once_with(target="127.0.0.1")

    def test_start_failure_closes_listener_and_is_backed_off(self):
        app = Application(AppConfig(bind_port=0))
        self.addCleanup(app._server.server_close)
        app._state.user_settings = UserSettings(
            nickname="Host",
            theme="dark",
            log_level="WARNING",
            auto_start_sync=True,
            library_path_initialized=True,
            windows_game_drive_letter="D",
            linux_install_path="library",
            lan_mode="server",
        )
        listener = Mock()
        listener.start.side_effect = RuntimeError("thread unavailable")
        with patch(
            "src.core.service.app.LanDiscoveryServer", return_value=listener
        ) as factory:
            app._refresh_lan_discovery()
            app._refresh_lan_discovery()
        factory.assert_called_once()
        listener.close.assert_called_once()
        self.assertIsNone(app._lan_discovery)
