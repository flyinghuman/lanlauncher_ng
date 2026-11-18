"""Tests for the automatic version bump and update publication helpers."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path("tools/scripts/build_and_publish_update.py").resolve()
SPEC = importlib.util.spec_from_file_location("build_and_publish_update", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BuildAndPublishUpdateTests(unittest.TestCase):
    def test_bump_patch_version(self) -> None:
        self.assertEqual(MODULE.bump_patch_version("0.7.841"), "0.7.842")

    def test_bump_patch_version_rejects_non_semver(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.bump_patch_version("0.7")

    def test_dotenv_value_is_unquoted_and_process_environment_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text('LLNGUPDATEFOLDER="from-file"\n', encoding="utf-8")
            self.assertEqual(
                MODULE.resolve_update_folder(root, environ={"LLNGUPDATEFOLDER": "from-env"}),
                Path("from-env").resolve(),
            )

    def test_publish_artifacts_replaces_payload_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            payload = source / "lanlauncherng-update-1.0.1.zip"
            manifest = source / "update-manifest.json"
            payload.write_bytes(b"zip")
            manifest.write_text('{"version":"1.0.1"}\n', encoding="utf-8")
            published = MODULE.publish_artifacts(payload, manifest, target)
            self.assertEqual(
                [path.read_bytes() for path in published],
                [payload.read_bytes(), manifest.read_bytes()],
            )


if __name__ == "__main__":
    unittest.main()
