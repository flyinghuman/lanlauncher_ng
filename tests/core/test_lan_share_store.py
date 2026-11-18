"""Owner-local LAN share selection is validated and atomically persisted."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.core.catalog.lan_shares import InvalidLanShares, LanShareStore


class LanShareStoreTests(unittest.TestCase):
    def test_missing_store_is_empty_and_selection_roundtrips_case_insensitively(self):
        with TemporaryDirectory() as tmp:
            store = LanShareStore(Path(tmp) / "lan-shares.json")
            self.assertEqual(store.read(), [])
            self.assertEqual(store.write(["Demo", "demo", "Other"]), ["Demo", "Other"])
            self.assertEqual(store.read(), ["Demo", "Other"])
            self.assertEqual(store.set_shared("DEMO", False), ["Other"])
            self.assertEqual(store.set_shared("Next", True), ["Other", "Next"])

    def test_invalid_store_or_game_id_fails_closed(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "lan-shares.json"
            path.write_text(json.dumps({"schema_version": 2, "game_ids": []}), encoding="utf-8")
            store = LanShareStore(path)
            with self.assertRaises(InvalidLanShares):
                store.read()
            with self.assertRaises(InvalidLanShares):
                store.write(["../outside"])


if __name__ == "__main__":
    unittest.main()
