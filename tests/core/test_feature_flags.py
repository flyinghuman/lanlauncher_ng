"""Tests for feature-flag loading and precedence."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.core.service.feature_flags import load_feature_flags


class FeatureFlagsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_backup = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_defaults_when_file_missing(self) -> None:
        flags = load_feature_flags("missing-feature-flags.json")
        self.assertTrue(flags.is_enabled("shutdown_update_recovery"))

    def test_file_overrides_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feature-flags.json"
            path.write_text(
                json.dumps({"shutdown_update_recovery": False}), encoding="utf-8"
            )
            flags = load_feature_flags(str(path))
            self.assertFalse(flags.is_enabled("shutdown_update_recovery"))

    def test_flags_object_in_file_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feature-flags.json"
            path.write_text(
                json.dumps({"flags": {"shutdown_update_recovery": False}}),
                encoding="utf-8",
            )
            flags = load_feature_flags(str(path))
            self.assertFalse(flags.is_enabled("shutdown_update_recovery"))

    def test_env_overrides_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "feature-flags.json"
            path.write_text(
                json.dumps({"shutdown_update_recovery": False}), encoding="utf-8"
            )
            os.environ["LLNG_FF_SHUTDOWN_UPDATE_RECOVERY"] = "true"
            flags = load_feature_flags(str(path))
            self.assertTrue(flags.is_enabled("shutdown_update_recovery"))


if __name__ == "__main__":
    unittest.main()
