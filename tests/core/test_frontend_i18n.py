"""Frontend locale regression tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


class FrontendLocaleTests(unittest.TestCase):
    def test_ui_locale_key_parity(self) -> None:
        en_path = Path("src/frontend/app/locales/en/ui.json")
        de_path = Path("src/frontend/app/locales/de/ui.json")

        en = json.loads(en_path.read_text(encoding="utf-8"))
        de = json.loads(de_path.read_text(encoding="utf-8"))

        self.assertEqual(set(en.keys()), set(de.keys()))

    def test_required_ui_keys_present(self) -> None:
        en_path = Path("src/frontend/app/locales/en/ui.json")
        en = json.loads(en_path.read_text(encoding="utf-8"))

        required = {
            "app.title",
            "app.subtitle",
            "ui.language",
            "ui.search_placeholder",
            "ui.rescan",
            "sync.start",
            "sync.stop",
            "settings.install_check_background_started",
            "settings.section_general",
            "logs.collapse",
            "wizard.console_start",
            "wizard.provider_guidance_title",
            "wizard.provider_global",
            "wizard.provider_legacy",
            "wizard.provider_lan",
        }
        self.assertTrue(required.issubset(set(en.keys())))


if __name__ == "__main__":
    unittest.main()
