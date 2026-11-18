from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.scripts.sign_ogsi_document import sign_document


class SignOgsiDocumentTests(unittest.TestCase):
    def test_signs_canonical_v2_index_and_writes_signature_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "index-draft.json"
            output = root / "index.json"
            private_key = root / "private.pem"
            source.write_text(
                json.dumps(
                    {"schema_version": 2, "index_revision": 1, "games": [], "title": "é"},
                    indent=3,
                ),
                encoding="utf-8",
            )
            private_key.write_text("private fixture", encoding="utf-8")

            def fake_sign(command, check, capture_output):
                self.assertTrue(check)
                self.assertTrue(capture_output)
                self.assertEqual(command[1:4], ["dgst", "-sha256", "-sign"])
                self.assertEqual(command[4], str(private_key.resolve()))
                canonical = Path(command[-1]).read_bytes()
                self.assertEqual(
                    canonical,
                    b'{"games":[],"index_revision":1,"schema_version":2,"title":"\xc3\xa9"}',
                )
                Path(command[6]).write_bytes(b"test-signature")

            with patch("tools.scripts.sign_ogsi_document.subprocess.run", side_effect=fake_sign):
                sign_document(
                    "index", source, output, "publisher-test", private_key, "openssl-test"
                )

            signed = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(signed["signature"]["key_id"], "publisher-test")
            self.assertNotIn("private fixture", output.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["schema_version"], 2)

    def test_rejects_invalid_document_before_signing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "index.json"
            output = root / "signed.json"
            private_key = root / "private.pem"
            source.write_text('{"schema_version":1,"games":[]}', encoding="utf-8")
            private_key.write_text("private fixture", encoding="utf-8")
            with patch("tools.scripts.sign_ogsi_document.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "schema v2"):
                    sign_document("index", source, output, "publisher-test", private_key)
            run.assert_not_called()
            self.assertFalse(output.exists())

    def test_refuses_to_overwrite_private_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "index.json"
            private_key = root / "private.pem"
            source.write_text('{"schema_version":2,"index_revision":1,"games":[]}', encoding="utf-8")
            private_key.write_text("private fixture", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overwrite the private"):
                sign_document("index", source, private_key, "publisher-test", private_key)
            self.assertEqual(private_key.read_text(encoding="utf-8"), "private fixture")


if __name__ == "__main__":
    unittest.main()
