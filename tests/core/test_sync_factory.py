"""Tests for sync provider factory selection."""

from __future__ import annotations

import unittest

from src.core.config.loader import AppConfig
from src.core.sync.factory import create_sync_provider
from src.core.sync.ouisync_provider import OuisyncSyncProvider
from src.core.sync.resilio_provider import ResilioSyncProvider


class SyncFactoryTests(unittest.TestCase):
    def test_legacy_syncthing_selection_migrates_to_ouisync(self) -> None:
        provider = create_sync_provider(AppConfig(sync_provider="syncthing"))
        self.assertIsInstance(provider, OuisyncSyncProvider)

    def test_creates_ouisync_provider_by_default(self) -> None:
        provider = create_sync_provider(AppConfig())

        self.assertIsInstance(provider, OuisyncSyncProvider)

    def test_creates_resilio_when_selected(self) -> None:
        provider = create_sync_provider(AppConfig(sync_provider="resilio"))

        self.assertIsInstance(provider, ResilioSyncProvider)


if __name__ == "__main__":
    unittest.main()
