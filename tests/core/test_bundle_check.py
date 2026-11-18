"""Tests for bundled tool integrity checks."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.tools.bundle_check import run_bundle_checks


class BundleCheckTests(unittest.TestCase):
    def test_missing_manifest_fails(self) -> None:
        result = run_bundle_checks("does-not-exist.json")
        self.assertFalse(result.ok)
        self.assertTrue(result.errors)

    def test_required_tool_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tool = tmp_path / "tool.bin"
            lic = tmp_path / "tool.lic"
            tool.write_bytes(b"abc")
            lic.write_text("license", encoding="utf-8")

            manifest = {
                "tools": [
                    {
                        "name": "demo",
                        "platform": "any",
                        "path": str(tool.relative_to(tmp_path)),
                        "version": "1",
                        "sha256": "0" * 64,
                        "license_file": str(lic.relative_to(tmp_path)),
                        "required": True,
                    }
                ]
            }
            manifest_path = tmp_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = run_bundle_checks(str(manifest_path), repo_root=str(tmp_path))
            self.assertFalse(result.ok)
            self.assertTrue(any("checksum" in err for err in result.errors))

    def test_optional_missing_tool_only_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest = {
                "tools": [
                    {
                        "name": "optional",
                        "platform": "any",
                        "path": "missing.bin",
                        "version": "1",
                        "sha256": "",
                        "license_file": "",
                        "required": False,
                    }
                ]
            }
            manifest_path = tmp_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = run_bundle_checks(str(manifest_path), repo_root=str(tmp_path))
            self.assertTrue(result.ok)
            self.assertTrue(result.warnings)

    def test_non_matching_platform_tools_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            linux_tool = tmp_path / "linux.bin"
            linux_license = tmp_path / "linux.lic"
            linux_tool.write_bytes(b"abc")
            linux_license.write_text("license", encoding="utf-8")

            manifest = {
                "tools": [
                    {
                        "name": "linux",
                        "platform": "linux-x64",
                        "path": "linux.bin",
                        "version": "1",
                        "sha256": "",
                        "license_file": "linux.lic",
                        "required": True,
                    },
                    {
                        "name": "windows",
                        "platform": "windows-amd64",
                        "path": "missing.exe",
                        "version": "1",
                        "sha256": "",
                        "license_file": "",
                        "required": True,
                    },
                ]
            }
            manifest_path = tmp_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with patch(
                "src.core.tools.bundle_check._current_platform_tag",
                return_value="linux-x64",
            ):
                result = run_bundle_checks(str(manifest_path), repo_root=str(tmp_path))
            self.assertTrue(result.ok)
            self.assertEqual(result.errors, [])


if __name__ == "__main__":
    unittest.main()
