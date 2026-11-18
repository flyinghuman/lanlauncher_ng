"""Ouisync-backed private LAN catalog publication tests."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.core.catalog.lan_catalog import reconcile_snapshot
from src.core.catalog.lan_publish import publish_shared_games
from src.core.catalog.lan_snapshot import read_snapshot
from src.core.db.store import open_database


class LanPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / "demo"
        self.game.mkdir()
        self.metadata = self.game / "metadata.json"
        self.metadata.write_text(
            json.dumps({"game_id": "demo", "title": "Demo", "media": {"image_url": "cover.jpg"}}),
            encoding="utf-8",
        )
        (self.game / "cover.jpg").write_bytes(b"cover")
        self.shared = [{"id": "demo", "path": str(self.game)}]
        self.index = self.root / "locallansync" / ".ouisync" / "index.json"

    @staticmethod
    def publisher(_folder):
        return {"read_token": "private-game-token", "info_hash": "ab" * 20}

    def publish(self, folders=None):
        return publish_shared_games(
            self.root,
            self.shared if folders is None else folders,
            ouisync_publisher=self.publisher,
        )

    def test_publishes_local_cover_and_imports_ouisync_capability(self):
        self.assertTrue(self.publish())
        snapshot = read_snapshot(self.index)
        generated = datetime.fromisoformat(snapshot["generated_at_utc"].replace("Z", "+00:00"))
        self.assertEqual(generated.utcoffset(), timezone.utc.utcoffset(generated))
        self.assertEqual(snapshot["schema_version"], 1)
        game = snapshot["games"][0]
        self.assertEqual(game["llng"]["distribution"]["read_token"], "private-game-token")
        image = game["media"]["image_url"]
        self.assertEqual((self.index.parent / image).read_bytes(), b"cover")
        db = open_database(str(self.root / "catalog.db"))
        self.addCleanup(db.connection.close)
        self.assertEqual(reconcile_snapshot(db.connection, self.index)["updated"], 1)
        row = db.connection.execute(
            "SELECT key, game_provider_type FROM game_catalog WHERE id='demo'"
        ).fetchone()
        self.assertEqual(tuple(row), ("ab" * 20, "ouisync"))
        self.assertFalse(self.publish())

    def test_ouisync_metadata_and_cover_are_published_from_source_tree(self):
        source = self.game / ".ouisync"
        source.mkdir()
        (source / "metadata.json").write_text(self.metadata.read_text(encoding="utf-8"), encoding="utf-8")
        (source / "cover.jpg").write_bytes(b"synced cover")
        self.assertTrue(self.publish())
        snapshot = read_snapshot(self.index)
        image = snapshot["games"][0]["media"]["image_url"]
        self.assertEqual((self.index.parent / image).read_bytes(), b"synced cover")

    def test_bad_or_missing_metadata_does_not_unpublish(self):
        self.publish()
        original = self.index.read_bytes()
        self.metadata.write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.index.read_bytes(), original)
        self.metadata.unlink()
        self.assertFalse(self.publish())
        self.assertEqual(self.index.read_bytes(), original)

    def test_unsharing_removes_game_and_keeps_source_id(self):
        self.publish()
        original_id = read_snapshot(self.index)["source"]["id"]
        self.assertTrue(self.publish([]))
        result = read_snapshot(self.index)
        self.assertEqual(result["games"], [])
        self.assertEqual(result["source"]["id"], original_id)

    def test_remote_cover_is_not_published_as_local_reference(self):
        (self.game / "cover.jpg").unlink()
        self.metadata.write_text(
            json.dumps({"title": "Demo", "media": {"image_url": "https://example.org/demo.jpg"}}),
            encoding="utf-8",
        )
        self.publish()
        self.assertNotIn("media", read_snapshot(self.index)["games"][0])

    def test_publication_requires_an_ouisync_publisher(self):
        with self.assertRaisesRegex(ValueError, "ouisync_lan_publisher_unavailable"):
            publish_shared_games(self.root, self.shared)


if __name__ == "__main__":
    unittest.main()
