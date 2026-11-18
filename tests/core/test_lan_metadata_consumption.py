"""Validated LAN metadata must drive catalog details and local game launch."""

import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from src.core.catalog.install_support import InstallSupport
from src.core.catalog.lan_snapshot import publish_snapshot
from src.core.catalog.metadata import MetadataStore
from src.core.catalog.repository import CatalogRepository, ListQuery
from src.core.config.loader import AppConfig
from src.core.db.store import open_database
from src.core.launcher.game_manager import GameLifecycleManager
from src.core.service.app import Application
from tests.core.test_game_manager import LinuxStubAdapter, WindowsStubAdapter


class LanMetadataConsumptionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        db = open_database(str(self.root / "app.db"))
        self.addCleanup(db.connection.close)
        self.repo = CatalogRepository(db.connection, self.root / "metadata")
        self.index = self.root / "locallansync" / "index.json"
        self.raw = {"schema_version": 1, "source": {"id": "lan-one", "folder_id": "locallansync"}, "games": [{
            "game_id": "demo", "title": {"en": "LAN title", "de": "LAN Titel"},
            "description": {"en": "LAN description", "de": "LAN Beschreibung"},
            "key": "wrong-key", "game_provider_type": "local",
            "llng": {"schema_version": 1, "distribution": {
                "provider": "ouisync", "read_token": "token",
                "info_hash": "ab" * 20, "editable_files": [],
            }},
            "game_start": {"file": "local/launch.sh", "args": ["--lan", "${GAME_DIR}"]},
            "installer_tasks": [{"name": "winetricks", "packages": ["directplay"]}],
            "website_url": "https://example.org/game", "media": {"image_url": "images/demo.jpg"},
        }]}
        publish_snapshot(self.index, self.raw)
        self.repo.reconcile_lan_snapshot(self.index)
        metadata_root = self.root / "metadata"
        metadata_root.mkdir()
        (metadata_root / "demo.json").write_text(json.dumps({"title": "Unrelated override", "key": "wrong"}))
        self.game_dir = self.root / "demo"
        (self.game_dir / "local").mkdir(parents=True)
        (self.game_dir / "local" / "launch.sh").write_text("#!/bin/sh\n")
        (self.game_dir / "game_start.sh").write_text("#!/bin/sh\n")
        (self.root / "checks.json").write_text('{"games":{}}')

    def manager(self, adapter):
        return GameLifecycleManager(repo=self.repo, platform_adapter=adapter,
            install_support=InstallSupport(str(self.root / "scripts"), str(self.root / "checks.json")),
            library_path=str(self.root), unrar_path="unrar", windows_drive_letter="D", windows_lan_root="LAN",
            linux_cmd_wrapper_path="wrapper", metadata_store=MetadataStore(self.root / "metadata"))

    def test_lan_metadata_takes_precedence_and_exposes_links_and_tasks_offline(self):
        self.index.unlink()
        detail = self.repo.get_game("demo", locale="de")
        self.assertEqual(detail["title"], "LAN Titel")
        self.assertEqual(detail["readme"], "LAN Beschreibung")
        self.assertEqual(detail["key"], "ab" * 20)
        self.assertEqual(detail["game_provider_type"], "ouisync")
        self.assertEqual(detail["metadata"]["game_start"]["file"], "local/launch.sh")
        self.assertEqual(detail["metadata"]["installer"]["tasks"][0]["name"], "winetricks")
        self.assertEqual(detail["metadata"]["links"][0]["url"], "https://example.org/game")
        self.assertEqual(self.repo.list_games(ListQuery(locale="de"))["items"][0]["title"], "LAN Titel")
        app = Application(AppConfig(bind_port=0, library_path=str(self.root)))
        self.addCleanup(app._server.server_close)
        app._state.repository = self.repo
        self.assertEqual(app._game_metadata("demo").game_start_file, "local/launch.sh")

    def test_install_tasks_use_lan_metadata(self):
        manager = self.manager(LinuxStubAdapter())
        with patch.object(manager, "_run_winetricks_task", return_value=None) as run:
            self.assertIsNone(manager._run_install_tasks("demo"))
        self.assertEqual(run.call_args.args[2]["packages"], ["directplay"])

    def test_linux_launch_uses_lan_start_path_and_arguments(self):
        adapter = LinuxStubAdapter()
        manager = self.manager(adapter)
        result = manager.start_game("demo")
        self.assertTrue(result.ok)
        self.assertEqual(Path(adapter.calls[0][0]), self.game_dir / "local" / "launch.sh")
        self.assertIn("--lan", adapter.calls[0][1])
        self.assertIn(str(self.game_dir), adapter.calls[0][1])

    def test_windows_launch_uses_updated_lan_metadata(self):
        self.raw["games"][0]["game_start"] = {"file": "local/launch.cmd", "args": ["--updated"]}
        publish_snapshot(self.index, self.raw)
        self.repo.reconcile_lan_snapshot(self.index)
        (self.game_dir / "local" / "launch.cmd").write_text("@echo off")
        adapter = WindowsStubAdapter()
        result = self.manager(adapter).start_game("demo")
        self.assertTrue(result.ok)
        self.assertEqual(Path(adapter.calls[0][0]), self.game_dir / "local" / "launch.cmd")
        self.assertIn("--updated", adapter.calls[0][1])
