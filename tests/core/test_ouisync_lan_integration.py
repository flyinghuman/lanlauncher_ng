"""Opt-in three-instance test for private Ouisync LAN seeding and offline peer relay."""

from __future__ import annotations

import json
import os
import platform
import tempfile
import time
import unittest
from pathlib import Path

from src.core.catalog.game_index import OuisyncRepositoryAccess
from src.core.sync.lan_discovery import (
    LanDiscoveryServer,
    LanPairing,
    paired_peer_addresses,
    pair_server_capabilities,
)
from src.core.sync.ouisync_provider import OuisyncSyncProvider


def _binary(root: Path) -> Path:
    manifest = json.loads((root / "tools" / "manifest.json").read_text(encoding="utf-8"))
    platform_tag = "windows-amd64" if platform.system() == "Windows" else "linux-x64"
    relative = next(item["path"] for item in manifest["tools"]
                    if item["name"] == "ouisync" and item["platform"] == platform_tag)
    return root / relative


def _wait(predicate, *, timeout: float = 75, details=None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    extra = f": {details()}" if callable(details) else ""
    raise AssertionError(f"Ouisync LAN transfer did not complete before timeout{extra}")


_SERVER_ID = "-".join(["AAAAAAA"] * 8)
_FIRST_CLIENT_ID = "-".join(["BBBBBBB"] * 8)
_THIRD_CLIENT_ID = "-".join(["CCCCCCC"] * 8)


@unittest.skipUnless(
    os.environ.get("LLNG_RUN_OUISYNC_LAN_INTEGRATION") == "1",
    "opt-in three-instance Ouisync LAN peer relay integration",
)
@unittest.skipUnless(platform.system() in {"Linux", "Windows"}, "Ouisync CLI is bundled for Linux and Windows")
@unittest.skipIf(
    os.environ.get("LLNG_TEST_WINE") == "1",
    "Wine cannot install the Windows Ouisync VFS driver",
)
class OuisyncLanIntegrationTests(unittest.TestCase):
    def test_paired_peer_seeds_third_client_after_owner_goes_offline(self) -> None:
        root = Path(__file__).resolve().parents[2]
        binary = _binary(root)
        with tempfile.TemporaryDirectory(prefix="llng-ouisync-lan-integration-") as temporary:
            base = Path(temporary)
            providers: list[OuisyncSyncProvider] = []
            pairing_server: LanDiscoveryServer | None = None
            lan_address = os.environ.get("LLNG_TEST_LAN_ADDRESS", "127.0.0.1")

            def start(name: str) -> OuisyncSyncProvider:
                provider = OuisyncSyncProvider(
                    binary_path=str(binary),
                    config_dir=str(base / name / "config"),
                    log_path=str(base / name / "logs" / "ouisync.log"),
                    repo_root=str(root),
                    startup_timeout_seconds=20,
                    request_timeout_seconds=10,
                )
                status = provider.start()
                self.assertTrue(status.running, status.last_error)
                providers.append(provider)
                return provider

            try:
                owner = start("owner")
                first = start("first-client")
                owner_game = base / "owner" / "library" / "demo"
                owner_source = owner_game / ".ouisync"
                owner_source.mkdir(parents=True)
                (owner_source / "metadata.json").write_text(
                    json.dumps({"game_id": "demo", "title": "Demo"}), encoding="utf-8"
                )
                (owner_source / "demo.tar.gz").write_bytes(b"private LAN archive")

                capability = owner.publish_lan_game(str(owner_game))
                access = OuisyncRepositoryAccess(
                    game_id="demo",
                    read_token=capability["read_token"],
                    expected_info_hash=capability["info_hash"],
                    repository_namespace="lan-repository",
                )
                pairing = LanPairing(
                    lambda: _SERVER_ID,
                    lambda _client_id: {
                        "catalog_token": access.read_token,
                        "catalog_hash": access.expected_info_hash,
                        "peer_addrs": owner.network_listener_addrs(),
                    },
                    storage=base / "owner" / "lan-pairing.json",
                )
                pairing_code = pairing.begin()
                pairing_server = LanDiscoveryServer(
                    lambda: {"device_id": _SERVER_ID},
                    pairing=pairing,
                    host="0.0.0.0",
                    port=0,
                )
                pairing_server.start()
                first_capability = pair_server_capabilities(
                    lan_address,
                    _SERVER_ID,
                    _FIRST_CLIENT_ID,
                    pairing_code,
                    port=pairing_server.port,
                    peer_addrs=first.network_listener_addrs(),
                    timeout=1,
                )
                self.assertIsNotNone(first_capability)
                first.add_network_peers(
                    paired_peer_addresses(first_capability, lan_address)
                )
                first_game = base / "first-client" / "library" / "demo"
                self.assertTrue(first.start_game_materialization(access, str(first_game))[0])
                _wait(
                    lambda: any(
                        getattr(peer, "source", None)
                        == first._session_api.PeerSource.USER_PROVIDED
                        and type(getattr(peer, "state", None)).__name__ == "PeerState_Active"
                        for peer in first._call_session("get_peers")
                    ),
                    timeout=10,
                )
                (owner_source / "late-update.txt").write_text(
                    "published after pairing", encoding="utf-8"
                )
                owner.publish_lan_game(str(owner_game))
                _wait(
                    lambda: first.game_materialization_status("demo")["phase"] == "complete",
                    timeout=30,
                )
                self.assertEqual(
                    (first_game / ".ouisync" / "demo.tar.gz").read_bytes(),
                    b"private LAN archive",
                )
                self.assertEqual(
                    (first_game / ".ouisync" / "late-update.txt").read_text(encoding="utf-8"),
                    "published after pairing",
                )
                self.assertFalse((first_game / "demo.tar.gz").exists())

                third = start("third-client")
                third_capability = pair_server_capabilities(
                    lan_address,
                    _SERVER_ID,
                    _THIRD_CLIENT_ID,
                    pairing_code,
                    port=pairing_server.port,
                    peer_addrs=third.network_listener_addrs(),
                    timeout=1,
                )
                self.assertIsNotNone(third_capability)
                self.assertEqual(
                    third_capability.get("known_peer_addrs"),
                    [
                        value.replace("0.0.0.0", lan_address)
                        for value in first.network_listener_addrs()
                    ],
                )
                third.add_network_peers(
                    paired_peer_addresses(third_capability, lan_address)
                )
                owner.stop()
                pairing_server.close()
                pairing_server = None
                third_game = base / "third-client" / "library" / "demo"
                self.assertTrue(third.start_game_materialization(access, str(third_game))[0])
                _wait(
                    lambda: third.game_materialization_status("demo")["phase"] == "complete",
                    timeout=30,
                )
                self.assertEqual(
                    (third_game / ".ouisync" / "demo.tar.gz").read_bytes(),
                    b"private LAN archive",
                )
                self.assertFalse((third_game / "demo.tar.gz").exists())
            finally:
                if pairing_server is not None:
                    pairing_server.close()
                for provider in reversed(providers):
                    provider.stop()


if __name__ == "__main__":
    unittest.main()
