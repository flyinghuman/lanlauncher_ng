from __future__ import annotations

import json
import unittest
from pathlib import Path


class PublisherTrustSchemaTests(unittest.TestCase):
    def test_index_v2_requires_a_signature_envelope(self):
        schema_path = (
            Path(__file__).resolve().parents[2]
            / "schemas"
            / "opensourcegameindex-v2.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertIn("signature", schema["required"])
        self.assertIn("index_revision", schema["required"])
        self.assertEqual(schema["properties"]["index_revision"]["minimum"], 1)
        self.assertEqual(
            schema["properties"]["signature"]["$ref"], "#/$defs/signature"
        )

    def test_trust_schema_defines_separate_root_signature_and_revocable_signers(self):
        schema_path = (
            Path(__file__).resolve().parents[2]
            / "schemas"
            / "opensourcegameindex-trust-v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertIn("sequence", schema["required"])
        self.assertIn("signature", schema["required"])
        self.assertFalse(schema["additionalProperties"])
        self.assertGreaterEqual(schema["properties"]["sequence"]["minimum"], 1)
        self.assertEqual(schema["properties"]["keys"]["maxItems"], 256)

        publisher = schema["$defs"]["publisherKey"]
        self.assertEqual(publisher["properties"]["algorithm"]["const"], "rsa-pkcs1v15-sha256")
        self.assertEqual(publisher["properties"]["usages"]["items"]["const"], "game-index")
        self.assertEqual(publisher["properties"]["status"]["enum"], ["active", "revoked"])
        self.assertEqual(publisher["properties"]["modulus_hex"]["minLength"], 512)
        self.assertEqual(
            publisher["properties"]["exponent"]["const"],
            65537,
        )
        self.assertEqual(
            schema["$defs"]["signature"]["properties"]["key_id"]["pattern"],
            publisher["properties"]["key_id"]["pattern"],
        )
        self.assertEqual(
            publisher["allOf"][0]["then"]["required"],
            ["revoked_at_sequence", "revoked_at_utc"],
        )


if __name__ == "__main__":
    unittest.main()
