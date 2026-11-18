"""Tests for central application version resolution."""

from __future__ import annotations

from importlib import reload
from pathlib import Path
import unittest

import src.core.version as version_module


class VersionTests(unittest.TestCase):
    def test_app_version_matches_root_version_file(self) -> None:
        expected = Path("VERSION").read_text(encoding="utf-8").strip()
        reloaded = reload(version_module)
        self.assertEqual(reloaded.APP_VERSION, expected)


if __name__ == "__main__":
    unittest.main()
