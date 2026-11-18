"""Tests for game metadata parsing and caching."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core.catalog.metadata import MetadataStore


class MetadataStoreTests(unittest.TestCase):
    def test_metadata_file_is_loaded_and_overrides_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "metadata"
            root.mkdir()
            payload = {
                "title": {"en": "Demo One", "de": "Demo Eins"},
                "description": {
                    "en": "Localized install notes.",
                    "de": "Lokale Installationshinweise.",
                    "fr": "Notes d'installation locales.",
                },
                "key": "DEMO_KEY",
                "release_year": "2000",
                "publisher": "Codemasters",
                "size_gb": "1.45",
                "max_players": "8",
                "master_required": "1",
                "version": "20260101",
                "genre": {"en": "Racing", "de": "Rennspiel"},
                "genre_id": 5,
                "lan_supported": True,
                "runner": "proton",
                "game_start": {"file": "game_start.sh", "args": "--fullscreen"},
                "installer_tasks": [{"name": "winetricks", "args": "/S"}],
                "website_url": "https://example.org/game",
                "links": [
                    {
                        "label": {"en": "Discord", "de": "Discord"},
                        "url": "https://example.org/discord",
                    }
                ],
            }
            (root / "demo.json").write_text(json.dumps(payload), encoding="utf-8")

            store = MetadataStore(root)
            metadata = store.get("demo")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.effective_title("en"), "Demo One")
            self.assertEqual(metadata.effective_title("de"), "Demo Eins")
            self.assertEqual(
                metadata.effective_description("en"), "Localized install notes."
            )
            self.assertEqual(
                metadata.effective_description("de"), "Lokale Installationshinweise."
            )
            self.assertEqual(
                metadata.effective_description("fr"), "Notes d'installation locales."
            )
            self.assertEqual(metadata.runner, "proton")
            self.assertEqual(metadata.key, "DEMO_KEY")
            self.assertEqual(metadata.release_year, "2000")
            self.assertEqual(metadata.publisher, "Codemasters")
            self.assertEqual(metadata.size_gb, 1.45)
            self.assertEqual(metadata.max_players, "8")
            self.assertTrue(metadata.master_required)
            self.assertEqual(metadata.version, "20260101")
            self.assertEqual(metadata.effective_genre("en"), "Racing")
            self.assertEqual(metadata.effective_genre("de"), "Rennspiel")
            self.assertEqual(metadata.genre_id, 5)
            self.assertEqual(metadata.game_start_file, "game_start.sh")
            self.assertEqual(metadata.game_start_args, ["--fullscreen"])
            self.assertTrue(metadata.lan_supported)
            self.assertEqual(
                metadata.installer_tasks, [{"name": "winetricks", "args": "/S"}]
            )
            self.assertGreaterEqual(len(metadata.links), 2)
            self.assertEqual(metadata.links[0]["url"], "https://example.org/discord")
            self.assertEqual(metadata.links[1]["url"], "https://example.org/game")

    def test_legacy_description_string_falls_back_across_locales(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "metadata"
            root.mkdir()
            (root / "demo.json").write_text(
                json.dumps({"description": "Legacy description."}), encoding="utf-8"
            )

            metadata = MetadataStore(root).get("demo")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            for locale in ("en", "de", "fr"):
                self.assertEqual(metadata.effective_description(locale), "Legacy description.")

    def test_invalid_game_id_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "metadata"
            root.mkdir()
            store = MetadataStore(root)
            self.assertIsNone(store.get("bad/id"))
            self.assertIsNone(store.get(""))

    def test_metadata_disallows_traversal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "metadata"
            root.mkdir()
            payload = {"image": "../secrets/pic.jpg", "video": "/abs/movie.mp4"}
            (root / "demo.json").write_text(json.dumps(payload), encoding="utf-8")
            store = MetadataStore(root)
            metadata = store.get("demo")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertIsNone(metadata.image)
            self.assertIsNone(metadata.video)

    def test_game_start_file_disallows_absolute_and_parent_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "metadata"
            root.mkdir()
            for unsafe_path in ("../outside.sh", "/absolute/start.sh", "C:/outside.cmd"):
                with self.subTest(path=unsafe_path):
                    (root / "demo.json").write_text(
                        json.dumps({"game_start": {"file": unsafe_path}}),
                        encoding="utf-8",
                    )
                    metadata = MetadataStore(root).get("demo")

                    self.assertIsNotNone(metadata)
                    assert metadata is not None
                    self.assertEqual(metadata.game_start_file, "")

    def test_media_symlink_cannot_escape_metadata_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "game" / ".ouisync"
            root.mkdir(parents=True)
            outside = base / "outside.jpg"
            outside.write_bytes(b"outside")
            try:
                (root / "cover.jpg").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            (root / "metadata.json").write_text(
                json.dumps({"media": {"image": "cover.jpg"}}), encoding="utf-8"
            )

            metadata = MetadataStore(root).get_game_folder_metadata("game")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertIsNone(metadata.image)

    def test_default_media_symlink_cannot_escape_game_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "game"
            root.mkdir()
            outside = base / "outside.jpg"
            outside.write_bytes(b"outside")
            try:
                (root / "game.jpg").symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            (root / "metadata.json").write_text(
                json.dumps({"title": "Game"}), encoding="utf-8"
            )

            metadata = MetadataStore(root).get_game_folder_metadata("game")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertIsNone(metadata.image)

    def test_game_metadata_schema_covers_portable_llng_fields(self) -> None:
        schema_path = Path(__file__).parents[2] / "schemas" / "game-metadata-v1.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(schema["$defs"]["distribution"]["properties"]["schema_version"]["const"], 1)
        self.assertIn("runner", schema["properties"])
        self.assertIn("media", schema["properties"])
        self.assertIn("game_start", schema["properties"])
        self.assertIn("installer_tasks", schema["properties"])
        self.assertIn("archive", schema["$defs"]["distribution"]["properties"])
        self.assertIn("fr", schema["$defs"]["localizedText"]["oneOf"][1]["properties"])

    def test_game_folder_metadata_reads_distribution_archive_and_local_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp) / "demo"
            game_dir.mkdir()
            (game_dir / "cover.webp").write_bytes(b"image")
            (game_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "game_id": "demo",
                        "title": "Demo",
                        "media": {"image": "cover.webp"},
                        "distribution": {
                            "schema_version": 1,
                            "archive": {
                                "file": "payload/game.tar.gz",
                                "format": "tar.gz",
                                "sha256": "a" * 64,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            metadata = MetadataStore(game_dir).get_game_folder_metadata("demo")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.game_start_file, "")
            self.assertEqual(metadata.archive_file, "payload/game.tar.gz")
            self.assertEqual(metadata.archive_format, "tar.gz")
            self.assertEqual(metadata.archive_sha256, "a" * 64)
            self.assertEqual(metadata.image, "cover.webp")

    def test_game_folder_metadata_rejects_unsafe_archive_path_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp) / "demo"
            game_dir.mkdir()
            (game_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Demo",
                        "distribution": {
                            "archive": {
                                "file": "../outside.rar",
                                "sha256": "not-a-sha256",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            metadata = MetadataStore(game_dir).get_game_folder_metadata("demo")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.archive_file, "")
            self.assertEqual(metadata.archive_format, "")
            self.assertEqual(metadata.archive_sha256, "")

    def test_game_folder_metadata_ignores_unknown_distribution_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp) / "demo"
            game_dir.mkdir()
            (game_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "title": "Demo",
                        "distribution": {
                            "schema_version": 2,
                            "archive": {"file": "demo.rar", "format": "rar"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            metadata = MetadataStore(game_dir).get_game_folder_metadata("demo")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.title, "Demo")
            self.assertEqual(metadata.archive_file, "")
