"""Tests for the LAN catalog exchange format."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.catalog.lan_snapshot import (
    InvalidLanSnapshot,
    publish_snapshot,
    read_snapshot,
)
from src.core.catalog.lan_settings import (
    InvalidLanSettings,
    display_links,
    new_settings,
    publish_settings,
    read_settings,
)


def snapshot():
    return {
        "schema_version": 1,
        "source": {"id": "lan-example", "folder_id": "locallansync"},
        "games": [
            {
                "game_id": "demo",
                "title": {"en": "Demo", "de": "Demo"},
                "llng": {"schema_version": 1, "distribution": {
                    "provider": "ouisync", "read_token": "token",
                    "info_hash": "ab" * 20, "editable_files": [],
                }},
                "media": {"image_url": "images/demo.jpg"},
                "custom_field": {"preserved": True},
            }
        ],
    }


class LanSnapshotTests(unittest.TestCase):
    def test_round_trip_preserves_fields_and_local_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog" / "index.json"
            publish_snapshot(path, snapshot())
            self.assertEqual(read_snapshot(path), snapshot())

    def test_rejects_bad_snapshot_without_replacing_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            publish_snapshot(path, snapshot())
            for bad_image in (
                "https://example.org/image.png",
                "../image.png",
                "/tmp/image.jpg",
                "C:\\image.jpg",
            ):
                bad = copy.deepcopy(snapshot())
                bad["games"][0]["media"]["image_url"] = bad_image
                with (
                    self.subTest(image=bad_image),
                    self.assertRaises(InvalidLanSnapshot),
                ):
                    publish_snapshot(path, bad)
                self.assertEqual(read_snapshot(path), snapshot())

    def test_optional_generation_timestamp_rejects_non_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            bad = snapshot()
            bad["generated_at_utc"] = 123
            with self.assertRaises(InvalidLanSnapshot):
                publish_snapshot(path, bad)
            self.assertFalse(path.exists())

    def test_duplicate_ids_and_incomplete_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            bad = snapshot()
            duplicate = copy.deepcopy(bad["games"][0])
            duplicate["game_id"] = "DEMO"
            bad["games"].append(duplicate)
            with self.assertRaises(InvalidLanSnapshot):
                publish_snapshot(path, bad)
            path.write_text('{"schema_version":', encoding="utf-8")
            with self.assertRaises(InvalidLanSnapshot):
                read_snapshot(path)

    def test_failed_replace_preserves_old_index_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            publish_snapshot(path, snapshot())
            changed = copy.deepcopy(snapshot())
            changed["games"] = []
            with patch(
                "src.core.catalog.lan_snapshot.os.replace",
                side_effect=OSError("failed"),
            ):
                with self.assertRaises(OSError):
                    publish_snapshot(path, changed)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), snapshot())
            self.assertEqual(list(Path(tmp).glob(".index-*.tmp")), [])


class LanSettingsTests(unittest.TestCase):
    def test_round_trip_and_validate_links_and_disabled_games(self):
        value = new_settings(
            lan_title="Summer LAN",
            lan_url="https://lan.example/",
            stats_url="https://lan.example/stats.php",
            discord_url="https://discord.gg/example",
            ts3_server="ts3server://1.2.3.4?port=9987",
            disable_games=["demo"],
            links=[{"key": "link_1", "label": "Food", "url": "https://lan.example/food"}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "locallansync" / "settings.json"
            publish_settings(path, value)
            self.assertEqual(read_settings(path), value)
        self.assertEqual(
            [item["key"] for item in display_links(value)],
            ["lan_url", "link_1", "discord_url", "ts3_server"],
        )

    def test_rejects_duplicate_ids_and_unsafe_links(self):
        with self.assertRaises(InvalidLanSettings):
            new_settings(disable_games=["demo", "DEMO"])
        with self.assertRaises(InvalidLanSettings):
            new_settings(links=[{"key": "x", "label": "Bad", "url": "javascript:alert(1)"}])

    def test_corrupt_settings_are_rejected_and_failed_publish_preserves_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            original = new_settings(disable_games=["demo"])
            publish_settings(path, original)
            changed = new_settings(disable_games=["other"])
            with patch("src.core.catalog.lan_settings.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    publish_settings(path, changed)
            self.assertEqual(read_settings(path), original)
            self.assertEqual(list(Path(tmp).glob(".settings-*.tmp")), [])
            path.write_text('{"schema_version":', encoding="utf-8")
            with self.assertRaises(InvalidLanSettings):
                read_settings(path)
