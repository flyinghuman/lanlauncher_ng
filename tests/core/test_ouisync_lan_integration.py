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

            def read_mounted(provider, game_dir, name):
                # Installs read LAN archives through a temporary read-only mount;
                # materialization only syncs and never copies files to disk.
                def read(mount: Path):
                    path = mount / name
                    return path.read_bytes() if path.is_file() else None

                try:
                    return provider.run_with_game_repository_mounted(
                        access, str(game_dir / ".ouisync" / "demo"), read
                    )
                except Exception:  # noqa: BLE001 - not synced yet
                    return None

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
                self.assertTrue(
                    first.start_game_materialization(
                        access, str(first_game), str(first_game / ".ouisync" / "demo")
                    )[0]
                )
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
                    read_mounted(first, first_game, "demo.tar.gz"),
                    b"private LAN archive",
                )
                _wait(
                    lambda: read_mounted(first, first_game, "late-update.txt")
                    == b"published after pairing",
                    timeout=30,
                )
                self.assertFalse((first_game / "demo.tar.gz").exists())
                self.assertFalse((first_game / ".ouisync" / "demo.tar.gz").exists())

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
                self.assertTrue(
                    third.start_game_materialization(
                        access, str(third_game), str(third_game / ".ouisync" / "demo")
                    )[0]
                )
                _wait(
                    lambda: third.game_materialization_status("demo")["phase"] == "complete",
                    timeout=30,
                )
                self.assertEqual(
                    read_mounted(third, third_game, "demo.tar.gz"),
                    b"private LAN archive",
                )
                self.assertFalse((third_game / "demo.tar.gz").exists())
            finally:
                if pairing_server is not None:
                    pairing_server.close()
                for provider in reversed(providers):
                    provider.stop()


    def test_lan_seed_stays_open_and_seeding_after_provider_restart(self) -> None:
        root = Path(__file__).resolve().parents[2]
        binary = _binary(root)
        with tempfile.TemporaryDirectory(prefix="llng-ouisync-lan-restart-") as temporary:
            base = Path(temporary)
            providers: list[OuisyncSyncProvider] = []

            def make(name: str) -> OuisyncSyncProvider:
                provider = OuisyncSyncProvider(
                    binary_path=str(binary),
                    config_dir=str(base / name / "config"),
                    log_path=str(base / name / "logs" / "ouisync.log"),
                    repo_root=str(root),
                    startup_timeout_seconds=20,
                    request_timeout_seconds=10,
                )
                providers.append(provider)
                status = provider.start()
                self.assertTrue(status.running, status.last_error)
                return provider

            try:
                owner = make("owner")
                owner_game = base / "owner" / "library" / "demo"
                (owner_game / ".ouisync").mkdir(parents=True)
                (owner_game / ".ouisync" / "demo.tar.gz").write_bytes(b"archive")
                seed = owner_game / ".ouisync" / "lan-repository"
                capability = owner.publish_lan_game(str(owner_game), str(seed))

                # Restart the same provider object, as Status -> restart does.
                owner.stop()
                self.assertTrue(owner.start().running)
                owner.publish_lan_game(str(owner_game), str(seed))

                async def seed_state():
                    for repository in (await owner._session.list_repositories()).values():
                        if str(await repository.get_info_hash()).lower() == capability["info_hash"]:
                            return await repository.is_sync_enabled()
                    return None

                self.assertTrue(owner._submit(seed_state()))
                # A manual nudge (peers, DHT, sync off/on) keeps the seed usable.
                nudged = owner.nudge_repository_sync(capability["info_hash"])
                self.assertTrue(nudged["ok"], nudged)
                self.assertIn("sync_relinked", nudged["actions"])
                self.assertTrue(owner._submit(seed_state()))
                client = make("client")
                client.add_network_peers(
                    [
                        value.replace("0.0.0.0", "127.0.0.1")
                        for value in owner.network_listener_addrs()
                    ]
                )
                access = OuisyncRepositoryAccess(
                    game_id="demo",
                    read_token=capability["read_token"],
                    expected_info_hash=capability["info_hash"],
                    repository_namespace="lan-repository",
                )
                client_game = base / "client" / "library" / "demo"
                self.assertTrue(
                    client.start_game_materialization(
                        access, str(client_game), str(client_game / ".ouisync" / "demo")
                    )[0]
                )
                _wait(
                    lambda: client.game_materialization_status("demo")["phase"] == "complete",
                    timeout=30,
                    details=lambda: client.game_materialization_status("demo"),
                )
            finally:
                for provider in reversed(providers):
                    provider.stop()


if __name__ == "__main__":
    unittest.main()
