from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core.catalog.publisher_trust import (
    PublisherTrustStore,
    verify_catalog_signature,
)
from tests.core.publisher_trust_fixtures import (
    PUBLISHER_N,
    ROOT_KEYS,
    publisher_registry,
    sign,
    signed_index,
)


class PublisherTrustStoreTests(unittest.TestCase):
    def test_accepts_root_signed_registry_and_active_publisher_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "trusted-publishers.json"
            registry_path.write_text(json.dumps(publisher_registry(1)), encoding="utf-8")
            trust = PublisherTrustStore(
                root_public_keys=ROOT_KEYS,
                cache_path=root / "cache.json",
                state_path=root / "state.json",
                registry_path=registry_path,
            )

            keys = trust.load(registry_path)
            index = signed_index(
                {"game_id": "demo", "title": "Demo", "llng": {"schema_version": 1}}
            )

            self.assertEqual(keys["test-publisher"]["status"], "active")
            self.assertEqual(keys["test-publisher"]["modulus"], PUBLISHER_N)
            self.assertTrue(verify_catalog_signature(index, keys))
            index["games"][0]["title"] = "Tampered"
            self.assertFalse(verify_catalog_signature(index, keys))

    def test_rejects_registry_with_unknown_root_or_invalid_root_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = publisher_registry(1)
            trust = PublisherTrustStore(
                root_public_keys={},
                cache_path=root / "cache.json",
                state_path=root / "state.json",
            )
            self.assertIsNone(trust._accept(registry))  # noqa: SLF001

            registry["keys"][0]["status"] = "revoked"
            self.assertIsNone(PublisherTrustStore(
                root_public_keys=ROOT_KEYS,
                cache_path=root / "cache-2.json",
                state_path=root / "state-2.json",
            )._accept(registry))  # noqa: SLF001

    def test_revocation_is_cached_and_older_registry_cannot_undo_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "trusted-publishers.json"
            cache_path = root / "trusted-publishers-cache.json"
            state_path = root / "trust-state.json"
            registry_path.write_text(json.dumps(publisher_registry(1)), encoding="utf-8")
            trust = PublisherTrustStore(
                root_public_keys=ROOT_KEYS,
                cache_path=cache_path,
                state_path=state_path,
                registry_path=registry_path,
            )
            self.assertEqual(trust.load(registry_path)["test-publisher"]["status"], "active")

            registry_path.write_text(
                json.dumps(publisher_registry(2, revoked=True)), encoding="utf-8"
            )
            keys = trust.load(registry_path)
            self.assertEqual(keys["test-publisher"]["status"], "revoked")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["sequence"], 2)

            changed_same_sequence = publisher_registry(2, revoked=True)
            changed_same_sequence["keys"][0]["reason"] = "changed after publication"
            registry_path.write_text(
                json.dumps(sign(
                    {key: value for key, value in changed_same_sequence.items() if key != "signature"},
                    root=True,
                )),
                encoding="utf-8",
            )
            keys = trust.load(registry_path)
            self.assertEqual(keys["test-publisher"]["status"], "revoked")
            self.assertEqual(keys["test-publisher"].get("reason"), None)

            registry_path.write_text(json.dumps(publisher_registry(1)), encoding="utf-8")
            keys = trust.load(registry_path)
            self.assertEqual(keys["test-publisher"]["status"], "revoked")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["sequence"], 2)

            restarted = PublisherTrustStore(
                root_public_keys=ROOT_KEYS,
                cache_path=cache_path,
                state_path=state_path,
                registry_path=registry_path,
            )
            self.assertEqual(
                restarted.load(registry_path)["test-publisher"]["status"],
                "revoked",
            )

    def test_corrupt_rollback_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "trusted-publishers.json"
            state_path = root / "trust-state.json"
            registry_path.write_text(json.dumps(publisher_registry(1)), encoding="utf-8")
            state_path.write_text('{"sequence": "bad"}', encoding="utf-8")
            trust = PublisherTrustStore(
                root_public_keys=ROOT_KEYS,
                cache_path=root / "cache.json",
                state_path=state_path,
            )
            self.assertIsNone(trust.load(registry_path))

    def test_revoked_publisher_cannot_sign_catalog(self):
        registry = publisher_registry(2, revoked=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "trusted-publishers.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            trust = PublisherTrustStore(
                root_public_keys=ROOT_KEYS,
                cache_path=root / "cache.json",
                state_path=root / "state.json",
            )
            keys = trust.load(registry_path)
            self.assertFalse(
                verify_catalog_signature(
                    signed_index({"game_id": "demo", "title": "Demo"}), keys
                )
            )

    def test_rejects_active_key_with_revocation_fields(self):
        registry = publisher_registry(1)
        registry["keys"][0]["revoked_at_sequence"] = 1
        invalid = sign(
            {key: value for key, value in registry.items() if key != "signature"},
            root=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "trusted-publishers.json"
            registry_path.write_text(json.dumps(invalid), encoding="utf-8")
            trust = PublisherTrustStore(
                root_public_keys=ROOT_KEYS,
                cache_path=root / "cache.json",
                state_path=root / "state.json",
            )
            self.assertIsNone(trust.load(registry_path))

    def test_registry_parser_rejects_duplicate_json_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "trusted-publishers.json"
            registry_path.write_text(
                '{"schema_version":1,"schema_version":1}', encoding="utf-8"
            )
            trust = PublisherTrustStore(
                root_public_keys=ROOT_KEYS,
                cache_path=root / "cache.json",
                state_path=root / "state.json",
            )
            self.assertIsNone(trust.load(registry_path))


if __name__ == "__main__":
    unittest.main()
