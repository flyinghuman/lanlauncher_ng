from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.scripts.register_game_catalog_root import register_catalog_root


class RegisterGameCatalogRootTests(unittest.TestCase):
    def test_registers_only_public_key_and_preserves_other_root_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_key = root / "catalog-root-public.pem"
            public_key.write_text("public only", encoding="utf-8")
            registry = root / "publisher_trust.py"
            registry.write_text(
                "GAME_CATALOG_ROOT_PUBLIC_KEYS: dict[str, tuple[int, int]] = {\n"
                '    "existing-root": (\n        17,\n        65537,\n    ),\n}\n',
                encoding="utf-8",
            )
            modulus = (1 << 3071) + 1
            with patch(
                "tools.scripts.register_game_catalog_root._extract_rsa_public_key_components",
                return_value=(modulus, 65537),
            ):
                bits = register_catalog_root(
                    public_key,
                    "new-catalog-root",
                    registry,
                    "openssl-test",
                )

            content = registry.read_text(encoding="utf-8")
            self.assertEqual(bits, 3072)
            self.assertIn('"existing-root"', content)
            self.assertIn('"new-catalog-root"', content)
            self.assertIn(str(modulus), content)
            self.assertNotIn("PRIVATE", content)

    def test_rejects_weak_or_nonstandard_root_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_key = root / "catalog-root-public.pem"
            public_key.write_text("public only", encoding="utf-8")
            registry = root / "publisher_trust.py"
            registry.write_text(
                "GAME_CATALOG_ROOT_PUBLIC_KEYS: dict[str, tuple[int, int]] = {}\n",
                encoding="utf-8",
            )
            with patch(
                "tools.scripts.register_game_catalog_root._extract_rsa_public_key_components",
                return_value=((1 << 2047) + 1, 3),
            ):
                with self.assertRaisesRegex(ValueError, "3072-4096 bits"):
                    register_catalog_root(public_key, "weak-root", registry)
            self.assertNotIn("weak-root", registry.read_text(encoding="utf-8"))

    def test_rejects_invalid_key_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public_key = root / "catalog-root-public.pem"
            public_key.write_text("public only", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "key ID"):
                register_catalog_root(public_key, "../unsafe", root / "missing.py")


if __name__ == "__main__":
    unittest.main()
