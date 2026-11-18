"""Tests for the standalone publisher index generator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "ng_provider" / "generate_index.py"
SPEC = importlib.util.spec_from_file_location("ng_provider_generate_index", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


class PublisherIndexGeneratorTests(unittest.TestCase):
    def test_metadata_example_contains_all_publisher_fields(self) -> None:
        example_path = SCRIPT_PATH.parent / "metadata-example.json"
        metadata = json.loads(example_path.read_text(encoding="utf-8"))

        self.assertEqual(metadata["game_provider_type"], "ouisync")
        self.assertEqual(set(metadata["description"]), {"de", "en", "fr"})
        self.assertEqual(metadata["distribution"]["schema_version"], 1)
        self.assertEqual(metadata["llng"]["schema_version"], 1)
        self.assertIn("sha256", metadata["distribution"]["archive"])
        self.assertIn("editable_files", metadata["llng"]["distribution"])

    def _make_game(self, root: Path, *, published: bool = True) -> Path:
        game_dir = root / "demo"
        game_dir.mkdir(parents=True)
        archive = game_dir / "demo.tar.gz"
        archive.write_bytes(b"test archive")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        metadata = {
            "game_id": "demo",
            "title": "Demo",
            "description": {
                "de": "Beispielspiel",
                "en": "Example game",
                "fr": "Jeu exemple",
            },
            "size_gb": 0,
            "master_required": False,
            "game_start": {"file": "game_start.sh", "args": ["--fullscreen"]},
            "category": "Strategy",
            "version": "1.0.0" if published else "",
            "game_provider_type": "ouisync" if published else "",
            "runner": "proton",
            "installer_tasks": [{"name": "protontricks", "args": "vcrun2019"}],
            "distribution": {
                "schema_version": 1,
                "archive": {
                    "file": "demo.tar.gz" if published else "",
                    "format": "tar.gz" if published else "",
                    "sha256": digest if published else "",
                    "version_file": "version.ini" if published else "",
                },
            },
            "llng": {
                "schema_version": 1,
                "distribution": {
                    "provider": "ouisync" if published else "",
                    "read_token": "read-token" if published else "",
                    "info_hash": "repository-hash" if published else "",
                    "editable_files": ["settings.ini"] if published else [],
                },
            },
        }
        (game_dir / "metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        return game_dir

    def test_generates_ouisync_entry_and_increments_existing_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_game(root)
            output = root / "index-draft.json"
            signed_index = root / "ng_provider" / "update" / "index.json"
            signed_index.parent.mkdir(parents=True)
            signed_index.write_text(
                json.dumps({"index_revision": 12}), encoding="utf-8"
            )

            first = GENERATOR.generate_index(root, output)
            second = GENERATOR.generate_index(root, output)
            entry = second["games"][0]

            self.assertEqual(first["index_revision"], 13)
            self.assertEqual(second["index_revision"], 14)
            self.assertEqual(entry["llng"]["distribution"]["info_hash"], "repository-hash")
            self.assertEqual(entry["description"]["fr"], "Jeu exemple")
            self.assertEqual(entry["size_gb"], 0)
            self.assertFalse(entry["master_required"])
            self.assertEqual(entry["game_start"]["file"], "game_start.sh")
            self.assertEqual(entry["distribution"]["archive"]["sha256"], hashlib.sha256(b"test archive").hexdigest())
            self.assertNotIn("signature", second)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["index_revision"], 14)

    def test_omits_blank_templates_for_catalog_only_games(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_game(root, published=False)

            document = GENERATOR.generate_index(
                root, root / "index-draft.json"
            )
            entry = document["games"][0]

            self.assertEqual(entry["game_provider_type"], "")
            self.assertNotIn("distribution", entry)
            self.assertNotIn("llng", entry)

    def test_rejects_archive_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game_dir = self._make_game(root)
            metadata_path = game_dir / "metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["distribution"]["archive"]["sha256"] = "0" * 64
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            with self.assertRaisesRegex(GENERATOR.PublisherIndexError, "SHA-256"):
                GENERATOR.generate_index(
                    root, root / "index-draft.json"
                )

    def test_refuses_to_write_unsigned_draft_inside_seed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._make_game(root, published=False)

            with self.assertRaisesRegex(GENERATOR.PublisherIndexError, "outside repos"):
                GENERATOR.generate_index(
                    root, root / "ng_provider" / "update" / "index-draft.json"
                )


if __name__ == "__main__":
    unittest.main()
