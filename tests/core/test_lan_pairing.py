"""LAN pairing requires a bounded, explicitly issued approval code."""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from src.core.config.loader import AppConfig
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings
from src.core.sync.lan_discovery import LanDiscoveryServer, LanPairing, PAIRING_LIFETIME_SECONDS, _pair_proof, pair_server, pair_server_capabilities

SERVER = "-".join(["AAAAAAA"] * 8)
CLIENT = "-".join(["BBBBBBB"] * 8)
OTHER = "-".join(["CCCCCCC"] * 8)


def request(code, client=CLIENT, server=SERVER, nonce="a" * 32, peer_addrs=None):
    capabilities = {"peer_addrs": peer_addrs} if peer_addrs is not None else None
    result = {"type": "llng-pair-v1", "nonce": nonce, "server_id": server, "client_id": client,
              "proof": _pair_proof(code, "request", nonce, server, client, capabilities)}
    if peer_addrs is not None:
        result["peer_addrs"] = peer_addrs
    return result


class LanPairingTests(unittest.TestCase):
    def test_renew_replaces_the_code_and_restarts_its_lifetime(self):
        clock = Mock(return_value=100.0)
        pairing = LanPairing(lambda: SERVER, Mock(return_value=True), clock=clock)
        with patch("src.core.sync.lan_discovery.secrets.randbelow", side_effect=[1111, 1111]):
            old_code = pairing.begin()
            new_code = pairing.renew()
        self.assertEqual(old_code, "1111")
        self.assertEqual(new_code, "1112")
        self.assertEqual(pairing.remaining(), PAIRING_LIFETIME_SECONDS)
        self.assertIsNone(pairing.accept(request(old_code)))
        self.assertIsNotNone(pairing.accept(request(new_code)))

    def test_code_reusable_for_three_days_with_temporary_lockout(self):
        clock = Mock(return_value=100.0)
        approve = Mock(return_value=True)
        with TemporaryDirectory() as tmp:
            storage = Path(tmp) / "pairing.json"
            pairing = LanPairing(lambda: SERVER, approve, clock=clock, storage=storage)
            self.assertIsNone(pairing.accept(request("0000")))
            code = pairing.begin()
            self.assertEqual(len(code), 4)
            self.assertEqual(pairing.remaining(), PAIRING_LIFETIME_SECONDS)
            self.assertIsNotNone(pairing.accept(request(code)))
            self.assertIsNotNone(pairing.accept(request(code, OTHER)))
            self.assertEqual(approve.call_count, 2)
            clock.return_value += 2 * 24 * 60 * 60
            restarted = LanPairing(lambda: SERVER, approve, clock=clock, storage=storage)
            self.assertEqual(restarted.begin(), code)
            self.assertIsNotNone(restarted.accept(request(code)))
            wrong = "9999" if code != "9999" else "0000"
            repeated = request(wrong, nonce="b" * 32)
            for _ in range(8):
                self.assertIsNone(restarted.accept(repeated))
            self.assertIsNotNone(restarted.accept(request(code)))
            for index in range(4):
                self.assertIsNone(restarted.accept(request(wrong, nonce=f"{index:032x}")))
            self.assertIsNone(restarted.accept(request(code)))
            self.assertEqual(restarted.begin(), code)
            clock.return_value += 60
            self.assertIsNotNone(restarted.accept(request(code)))
            clock.return_value = 100 + PAIRING_LIFETIME_SECONDS
            self.assertIsNone(restarted.accept(request(code)))
            self.assertEqual(restarted.remaining(), 0)
            with patch("src.core.sync.lan_discovery.secrets.randbelow", return_value=1234):
                self.assertEqual(restarted.begin(), "1234")

    def test_real_udp_pairing_and_failed_code(self):
        approve = Mock(return_value=True)
        pairing = LanPairing(lambda: SERVER, approve)
        code = pairing.begin()
        server = LanDiscoveryServer(lambda: {"device_id": SERVER}, pairing=pairing, host="127.0.0.1", port=0)
        server.start()
        try:
            self.assertTrue(pair_server("127.0.0.1", SERVER, CLIENT, code, port=server.port, timeout=.3))
            self.assertTrue(pair_server("127.0.0.1", SERVER, CLIENT, code, port=server.port, timeout=.3))
            self.assertTrue(pair_server("127.0.0.1", SERVER, OTHER, code, port=server.port, timeout=.3))
            self.assertEqual(approve.call_count, 3)
        finally:
            server.close()

    def test_real_udp_pairing_returns_integrity_protected_capabilities(self):
        payload = {"catalog_token": "read-only-token", "catalog_hash": "ab" * 20}
        pairing = LanPairing(lambda: SERVER, Mock(return_value=payload))
        code = pairing.begin()
        server = LanDiscoveryServer(lambda: {"device_id": SERVER}, pairing=pairing, host="127.0.0.1", port=0)
        server.start()
        try:
            result = pair_server_capabilities("127.0.0.1", SERVER, CLIENT, code, port=server.port, timeout=.3)
            self.assertEqual(result, payload)
            self.assertTrue(pair_server("127.0.0.1", SERVER, CLIENT, code, port=server.port, timeout=.3))
        finally:
            server.close()

    def test_pairing_returns_persisted_endpoints_of_previously_paired_clients(self):
        payload = {
            "catalog_token": "read-only-token",
            "catalog_hash": "ab" * 20,
            "peer_addrs": ["quic/0.0.0.0:32100"],
        }
        with TemporaryDirectory() as tmp:
            storage = Path(tmp) / "pairing.json"
            pairing = LanPairing(lambda: SERVER, Mock(return_value=payload), storage=storage)
            code = pairing.begin()
            server = LanDiscoveryServer(
                lambda: {"device_id": SERVER}, pairing=pairing, host="127.0.0.1", port=0
            )
            server.start()
            try:
                first = pair_server_capabilities(
                    "127.0.0.1", SERVER, CLIENT, code, port=server.port,
                    peer_addrs=["quic/0.0.0.0:32101"], timeout=.5,
                )
                self.assertNotIn("known_peer_addrs", first)
                second = pair_server_capabilities(
                    "127.0.0.1", SERVER, OTHER, code, port=server.port,
                    peer_addrs=["quic/0.0.0.0:32102"], timeout=.5,
                )
                self.assertEqual(second["known_peer_addrs"], ["quic/127.0.0.1:32101"])
                self.assertEqual(second["peer_addrs"], ["quic/0.0.0.0:32100"])
            finally:
                server.close()

            restored = LanPairing(lambda: SERVER, Mock(return_value=payload), storage=storage)
            restarted_server = LanDiscoveryServer(
                lambda: {"device_id": SERVER}, pairing=restored, host="127.0.0.1", port=0
            )
            restarted_server.start()
            try:
                third = pair_server_capabilities(
                    "127.0.0.1", SERVER, "-".join(["DDDDDDD"] * 8), code,
                    port=restarted_server.port,
                    peer_addrs=["quic/0.0.0.0:32103"], timeout=.5,
                )
                self.assertEqual(
                    third["known_peer_addrs"],
                    ["quic/127.0.0.1:32101", "quic/127.0.0.1:32102"],
                )
            finally:
                restarted_server.close()

    def test_pairing_peer_endpoints_are_bound_to_the_request_proof(self):
        pairing = LanPairing(lambda: SERVER, Mock(return_value={"catalog_token": "token"}))
        code = pairing.begin()
        signed = request(code, peer_addrs=["quic/0.0.0.0:32101"])
        signed["peer_addrs"] = ["quic/0.0.0.0:32102"]
        self.assertIsNone(pairing.accept(signed, observed_address="10.0.0.1"))

    def test_pairing_capabilities_are_bound_into_response_proof_and_size_limited(self):
        pairing = LanPairing(lambda: SERVER, Mock(return_value={"catalog_token": "token-a"}))
        with patch("src.core.sync.lan_discovery.secrets.randbelow", return_value=1234):
            code = pairing.begin()
        response = pairing.accept(request(code))
        self.assertIsNotNone(response)
        changed = {**response, "capabilities": {"catalog_token": "token-b"}}
        self.assertNotEqual(response["proof"], _pair_proof(code, "response", response["nonce"], SERVER, CLIENT, changed["capabilities"]))

        oversized = LanPairing(lambda: SERVER, Mock(return_value={"token": "x" * 7000}))
        with patch("src.core.sync.lan_discovery.secrets.randbelow", return_value=1234):
            oversized_code = oversized.begin()
        self.assertIsNone(oversized.accept(request(oversized_code)))

    def test_local_actions_require_roles_and_use_ouisync_after_pairing(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = Application(AppConfig(bind_port=0, db_path=str(Path(tmp.name) / "state.db")))
        self.addCleanup(app._server.server_close)
        settings = UserSettings(nickname="Host", theme="dark", log_level="WARNING", auto_start_sync=True,
                                library_path_initialized=True, windows_game_drive_letter="D", linux_install_path="library", lan_mode="server")
        app._state.user_settings = settings
        app._lan_discovery = Mock()
        ouisync = Mock()
        ouisync.network_listener_addrs.return_value = []
        with patch.object(app, "_sync_provider_for_type", return_value=ouisync):
            self.assertEqual(len(app._lan_game_share_update({"action": "begin_pairing"})["code"]), 4)
            first_code = app._lan_game_share_update({"action": "begin_pairing"})["code"]
            renewed = app._lan_game_share_update({"action": "renew_pairing"})
            self.assertTrue(renewed["ok"])
            self.assertNotEqual(renewed["code"], first_code)
            self.assertEqual(renewed["expires_in"], PAIRING_LIFETIME_SECONDS)
            app._state.user_settings = replace(settings, lan_mode="client")
            payload = {"action": "pair_server", "address": "127.0.0.1", "device_id": SERVER, "code": "1234"}
            with patch("src.core.service.app.pair_server_capabilities", return_value=None) as pair:
                self.assertEqual(app._lan_game_share_update(payload)["message"], "lan_pair_failed")
                pair.assert_called_once()
            with (patch("src.core.service.app.pair_server_capabilities", return_value={
                    "catalog_token": "token", "catalog_hash": "ab" * 20,
                    "peer_addrs": ["quic/127.0.0.1:12345"],
                    "known_peer_addrs": ["quic/10.0.0.5:2345"],
                  }), patch.object(app, "_lan_pair_access_save", return_value=True) as save,
                  patch.object(app, "_ouisync_lan_catalog_cycle") as materialize):
                self.assertTrue(app._lan_game_share_update(payload)["ok"])
                save.assert_called_once_with(
                    SERVER, "token", "ab" * 20,
                    ["quic/127.0.0.1:12345", "quic/10.0.0.5:2345"],
                )
                materialize.assert_called_once()
                ouisync.add_network_peers.assert_called_with(
                    ["quic/127.0.0.1:12345", "quic/10.0.0.5:2345"]
                )
            with patch("src.core.service.app.pair_server_capabilities", return_value={}):
                self.assertFalse(app._lan_game_share_update(payload)["ok"])
            self.assertFalse(app._lan_game_share_update({"action": "begin_pairing"})["ok"])

    def test_pairing_capability_issue_and_client_storage(self):
        with TemporaryDirectory() as tmp:
            app = Application(AppConfig(bind_port=0, db_path=str(Path(tmp) / "state.db")))
            self.addCleanup(app._server.server_close)
            app._state.user_settings = replace(
                UserSettings(nickname="Host", theme="dark", log_level="WARNING", auto_start_sync=True,
                             library_path_initialized=True, windows_game_drive_letter="D",
                             linux_install_path="library", lan_mode="server"),
                lan_mode="server",
            )
            publisher = Mock()
            publisher.publish_lan_game.return_value = {"read_token": "secret", "info_hash": "ab" * 20}
            with patch.object(app, "_sync_provider_for_type", return_value=publisher):
                issued = app._lan_pairing_issue_capabilities(CLIENT)
            self.assertEqual(issued, {
                "catalog_token": "secret", "catalog_hash": "ab" * 20, "peer_addrs": []
            })
            catalog_folder = str(Path("library") / "locallansync")
            publisher.publish_lan_game.assert_called_once_with(
                catalog_folder,
                str(
                    Path(catalog_folder).resolve()
                    / ".ouisync"
                    / "lan-repository"
                ),
            )
            self.assertTrue(app._lan_pair_access_save(SERVER, "secret", "ab" * 20))
            saved = app._lan_pair_access_read()
            self.assertEqual(saved["catalog_token"], "secret")
            self.assertEqual(saved["catalog_hash"], "ab" * 20)
