"""Tests for LANPage launcher-site parsing helpers."""

from __future__ import annotations

import unittest

from src.core.service.launcher_site import (
    DEFAULT_LAUNCHER_INI_URL,
    build_snapshot_from_ini,
    default_snapshot,
    derive_launcher_ini_url,
    normalize_disable_games,
    parse_launcher_ini,
)


class LauncherSiteTests(unittest.TestCase):
    def test_parse_launcher_ini_blocks(self) -> None:
        payload = parse_launcher_ini(
            """
            lan_title ### Name {
            My LAN Party
            }
            disable_games ### disabled {
            game1, game2
            }
            """
        )
        self.assertEqual(payload["lan_title"], "My LAN Party")
        self.assertEqual(payload["disable_games"], "game1, game2")

    def test_normalize_disable_games(self) -> None:
        values = normalize_disable_games(" game1, GAME2 ; game1\n game3 ")
        self.assertEqual(values, ["game1", "game2", "game3"])

    def test_build_snapshot_from_ini_extracts_links_and_disable_list(self) -> None:
        snapshot = build_snapshot_from_ini(
            """
            lan_title ### Name {
            Summer LAN
            }
            lan_url ### URL {
            http://launcher.lan
            }
            link_1 ### Custom {
            Pizza|http://launcher.lan/index.php#Catering
            }
            discord_url ### Discord {
            https://discord.gg/example
            }
            ts3_server ### TS3 {
            ts3server://1.2.3.4?port=9987
            }
            disable_games ### Games {
            gamea, gameb
            }
            """,
            source_url=DEFAULT_LAUNCHER_INI_URL,
            fetched_at=123.0,
        )
        self.assertTrue(snapshot.reachable)
        self.assertEqual(snapshot.lan_title, "Summer LAN")
        self.assertEqual(snapshot.disable_games, ["gamea", "gameb"])
        urls = [item["url"] for item in snapshot.links]
        self.assertIn("http://launcher.lan", urls)
        self.assertIn("http://launcher.lan/index.php#Catering", urls)
        self.assertIn("https://discord.gg/example", urls)
        self.assertIn("ts3server://1.2.3.4?port=9987", urls)

    def test_derive_launcher_ini_url_prefers_lan_url_when_config_missing(self) -> None:
        url = derive_launcher_ini_url("", "http://launcher.lan")
        self.assertEqual(url, "http://launcher.lan/launcher.ini")

    def test_default_snapshot_uses_safe_defaults(self) -> None:
        snapshot = default_snapshot()
        self.assertFalse(snapshot.reachable)
        self.assertEqual(snapshot.disable_games, [])


if __name__ == "__main__":
    unittest.main()
