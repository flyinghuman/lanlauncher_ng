"""Tests for install script/check support."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.core.catalog.install_support import InstallSupport


class InstallSupportTests(unittest.TestCase):
    def test_install_script_resolution_with_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checks = root / "checks.json"
            checks.write_text('{"games":{}}', encoding="utf-8")

            win_dir = root / "windows"
            win_dir.mkdir(parents=True, exist_ok=True)
            fallback = win_dir / "install-game.ps1"
            fallback.write_text("Write-Host fallback", encoding="utf-8")

            support = InstallSupport(str(root), str(checks))
            info = support.install_script_for("demo", "windows")
            self.assertTrue(info.exists)
            self.assertTrue(info.path.endswith("install-game.ps1"))

    def test_marker_paths_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checks = root / "checks.json"
            checks.write_text('{"games":{"demo":{"markers":["a.exe","b.dat"]}}}', encoding="utf-8")

            support = InstallSupport(str(root), str(checks))
            markers = support.marker_paths_for("demo")
            self.assertEqual(markers, ["a.exe", "b.dat"])


if __name__ == "__main__":
    unittest.main()
