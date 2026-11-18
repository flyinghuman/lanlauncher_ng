"""Tests for the public game index loader."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urljoin
from unittest.mock import patch

from src.core.catalog.game_index import GameIndexStore
from tests.core.publisher_trust_fixtures import (
    ROOT_KEYS,
    publisher_registry,
    sign,
    signed_index,
)


class GameIndexStoreTests(unittest.TestCase):
    def test_v2_parses_namespaced_ouisync_distribution_without_exposing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            update_dir = root / "ng_provider" / "update"
            update_dir.mkdir(parents=True)
            index_path = update_dir / "index.json"
            (update_dir / "trusted-publishers.json").write_text(
                json.dumps(publisher_registry(1)), encoding="utf-8"
            )
            index_path.write_text(
                json.dumps(
                    signed_index(
                        {
                            "game_id": "demo",
                            "title": "Demo",
                            "description": {
                                "de": "Lokale Beschreibung.",
                                "en": "Localized description.",
                                "fr": "Description localisée.",
                            },
                            "size_gb": 0,
                            "master_required": False,
                            "game_start": {"file": "game_start.sh", "args": ["--fullscreen"]},
                            "website_url": "https://example.org/demo",
                            "version": "2.0",
                            "runner": "proton",
                            "installer_tasks": [{"name": "protontricks", "args": "vcrun2019"}],
                            "game_provider_type": "ouisync",
                            "distribution": {
                                "schema_version": 1,
                                "archive": {
                                    "file": "demo.tar.gz",
                                    "format": "tar.gz",
                                    "sha256": "a" * 64,
                                    "version_file": "version.ini",
                                },
                            },
                            "llng": {
                                "schema_version": 1,
                                "distribution": {
                                    "provider": "ouisync",
                                    "read_token": "private-read-token",
                                    "info_hash": "expected-hash",
                                    "editable_files": [
                                        "game_start.cmd",
                                        "bin/game.dll",
                                    ],
                                },
                            },
                        }
                    )
                ),
                encoding="utf-8",
            )
            store = GameIndexStore(
                "",
                root / "cache" / "index.json",
                local_index_path=index_path,
                trust_root_public_keys=ROOT_KEYS,
            )

            metadata = store.get("demo")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.distribution_provider, "ouisync")
            self.assertEqual(metadata.distribution_read_token, "private-read-token")
            self.assertEqual(metadata.distribution_info_hash, "expected-hash")
            self.assertEqual(metadata.version, "2.0")
            self.assertEqual(metadata.effective_description("de"), "Lokale Beschreibung.")
            self.assertEqual(metadata.effective_description("en"), "Localized description.")
            self.assertEqual(metadata.effective_description("fr"), "Description localisée.")
            self.assertEqual(metadata.size_gb, 0)
            self.assertFalse(metadata.master_required)
            self.assertEqual(metadata.game_start_file, "game_start.sh")
            self.assertEqual(metadata.game_start_args, ["--fullscreen"])
            self.assertEqual(metadata.runner, "proton")
            self.assertEqual(metadata.archive_file, "demo.tar.gz")
            self.assertEqual(metadata.archive_sha256, "a" * 64)
            self.assertEqual(metadata.archive_version_file, "version.ini")
            self.assertEqual(metadata.installer_tasks[0]["name"], "protontricks")
            self.assertEqual(
                metadata.distribution_editable_files,
                ["game_start.cmd", "bin/game.dll"],
            )
            access = store.ouisync_repository_access("demo")
            self.assertIsNotNone(access)
            assert access is not None
            self.assertEqual(access.game_id, "demo")
            self.assertEqual(access.read_token, "private-read-token")
            self.assertEqual(access.expected_info_hash, "expected-hash")
            self.assertNotIn("private-read-token", repr(access))
            self.assertIsNone(store.ouisync_repository_access("other-game"))
            catalog_entries = store.ouisync_catalog_entries("en")
            self.assertEqual(
                catalog_entries,
                [{"game_id": "demo", "title": "Demo", "info_hash": "expected-hash"}],
            )
            self.assertNotIn("private-read-token", json.dumps(catalog_entries))
            public_payload = json.dumps(metadata.as_payload())
            self.assertNotIn("private-read-token", public_payload)

    def test_v2_rejects_unsafe_editable_file_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            update_dir = root / "ng_provider" / "update"
            update_dir.mkdir(parents=True)
            index_path = update_dir / "index.json"
            (update_dir / "trusted-publishers.json").write_text(
                json.dumps(publisher_registry(1)), encoding="utf-8"
            )
            index_path.write_text(
                json.dumps(
                    signed_index(
                        {
                            "game_id": "unsafe",
                            "title": "Unsafe",
                            "llng": {
                                "schema_version": 1,
                                "distribution": {
                                    "provider": "ouisync",
                                    "read_token": "token",
                                    "editable_files": ["../../outside.exe"],
                                },
                            },
                        }
                    )
                ),
                encoding="utf-8",
            )
            store = GameIndexStore(
                "",
                root / "cache" / "index.json",
                local_index_path=index_path,
                trust_root_public_keys=ROOT_KEYS,
            )

            self.assertIsNone(store.get("unsafe"))

    def test_v1_ignores_llng_extension_until_index_is_versioned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "games": [
                            {
                                "game_id": "legacy",
                                "title": "Legacy",
                                "llng": {
                                    "schema_version": 1,
                                    "distribution": {
                                        "provider": "ouisync",
                                        "read_token": "must-not-be-used",
                                    },
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = GameIndexStore("", root / "cache.json", local_index_path=index_path)

            metadata = store.get("legacy")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.distribution_read_token, "")
            self.assertIsNone(store.ouisync_repository_access("legacy"))

    def test_v2_unsigned_index_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "games": [
                            {
                                "game_id": "unsigned",
                                "title": "Unsigned",
                                "llng": {
                                    "schema_version": 1,
                                    "distribution": {
                                        "provider": "ouisync",
                                        "read_token": "must-not-be-used",
                                    },
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = GameIndexStore(
                "", root / "cache" / "index.json", local_index_path=index_path
            )

            self.assertIsNone(store.get("unsigned"))

    def test_v2_rejects_case_insensitive_duplicate_game_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            update_dir = root / "ng_provider" / "update"
            update_dir.mkdir(parents=True)
            (update_dir / "trusted-publishers.json").write_text(
                json.dumps(publisher_registry(1)), encoding="utf-8"
            )
            index_path = update_dir / "index.json"
            payload = sign(
                {
                    "schema_version": 2,
                    "index_revision": 1,
                    "games": [
                        {"game_id": "duplicate", "title": "First"},
                        {"game_id": "DUPLICATE", "title": "Second"},
                    ],
                },
                root=False,
            )
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            store = GameIndexStore(
                "",
                root / "cache" / "index.json",
                local_index_path=index_path,
                trust_root_public_keys=ROOT_KEYS,
            )
            self.assertIsNone(store.get("duplicate"))

    def test_registry_revocation_removes_cached_ouisync_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            update_dir = root / "ng_provider" / "update"
            update_dir.mkdir(parents=True)
            registry_path = update_dir / "trusted-publishers.json"
            registry_path.write_text(json.dumps(publisher_registry(1)), encoding="utf-8")
            index_path = update_dir / "index.json"
            index_path.write_text(
                json.dumps(
                    signed_index(
                        {
                            "game_id": "revoked-game",
                            "title": "Revoked Game",
                            "llng": {
                                "schema_version": 1,
                                "distribution": {
                                    "provider": "ouisync",
                                    "read_token": "revocable-token",
                                },
                            },
                        }
                    )
                ),
                encoding="utf-8",
            )
            store = GameIndexStore(
                "",
                root / "cache" / "index.json",
                local_index_path=index_path,
                trust_root_public_keys=ROOT_KEYS,
            )
            metadata = store.get("revoked-game")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.distribution_read_token, "revocable-token")

            registry_path.write_text(
                json.dumps(publisher_registry(2, revoked=True)), encoding="utf-8"
            )
            store.refresh_if_changed()
            self.assertIsNone(store.get("revoked-game"))

            registry_path.write_text(json.dumps(publisher_registry(1)), encoding="utf-8")
            store.refresh_if_changed()
            self.assertIsNone(store.get("revoked-game"))

    def test_signed_index_revision_rejects_replayed_older_token_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            update_dir = root / "ng_provider" / "update"
            update_dir.mkdir(parents=True)
            (update_dir / "trusted-publishers.json").write_text(
                json.dumps(publisher_registry(1)), encoding="utf-8"
            )
            index_path = update_dir / "index.json"

            def write_index(revision: int, token: str) -> None:
                index_path.write_text(
                    json.dumps(
                        signed_index(
                            {
                                "game_id": "rotated-game",
                                "title": "Rotated Game",
                                "llng": {
                                    "schema_version": 1,
                                    "distribution": {
                                        "provider": "ouisync",
                                        "read_token": token,
                                    },
                                },
                            },
                            revision=revision,
                        )
                    ),
                    encoding="utf-8",
                )

            write_index(2, "new-token")
            store = GameIndexStore(
                "",
                root / "cache" / "index.json",
                local_index_path=index_path,
                trust_root_public_keys=ROOT_KEYS,
            )
            metadata = store.get("rotated-game")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.distribution_read_token, "new-token")

            write_index(1, "old-token")
            store.refresh_if_changed()
            metadata = store.get("rotated-game")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.distribution_read_token, "new-token")

    def test_provider_index_is_local_and_resolves_media_into_provider_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = root / "ng_provider" / "update"
            provider.mkdir(parents=True)
            index_path = provider / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "games": [
                            {
                                "game_id": "demo",
                                "title": "Demo",
                                "lan_supported": True,
                                "media": {
                                    "image_url": "media/demo.jpg",
                                    "video_url": "media/demo.mp4",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            store = GameIndexStore(
                index_url="https://example.invalid/index.json",
                cache_path=root / "cache" / "index.json",
                local_index_path=index_path,
            )

            with patch("src.core.catalog.game_index.urlopen") as mocked_urlopen:
                metadata = store.get("demo")

            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.image, str(provider / "media" / "demo.jpg"))
            self.assertEqual(metadata.video, str(provider / "media" / "demo.mp4"))
            mocked_urlopen.assert_not_called()

    def test_managed_game_ids_include_ouisync_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "ng_provider" / "update" / "index.json"
            index_path.parent.mkdir(parents=True)
            (index_path.parent / "trusted-publishers.json").write_text(
                json.dumps(publisher_registry(1)), encoding="utf-8"
            )
            index_path.write_text(
                json.dumps(
                    sign(
                        {
                            "schema_version": 2,
                            "index_revision": 1,
                            "games": [
                                {
                                    "game_id": "managed",
                                    "title": "Managed",
                                    "game_provider_type": "ouisync",
                                },
                                {
                                    "game_id": "ouisync-managed",
                                    "title": "Ouisync managed",
                                    "llng": {
                                        "schema_version": 1,
                                        "distribution": {
                                            "provider": "ouisync",
                                            "read_token": "read-only",
                                            "info_hash": "ab" * 20,
                                        },
                                    },
                                },
                                {"game_id": "catalog-only", "title": "Catalog"},
                            ],
                        },
                        root=False,
                    )
                ),
                encoding="utf-8",
            )
            store = GameIndexStore(
                index_url="",
                cache_path=root / "cache" / "index.json",
                local_index_path=index_path,
                trust_root_public_keys=ROOT_KEYS,
            )

            self.assertTrue(store.refresh(force=True))
            self.assertEqual(store.managed_game_ids(), {"managed", "ouisync-managed"})

    def test_unsupported_local_schema_uses_validated_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_index = root / "provider" / "index.json"
            local_index.parent.mkdir()
            local_index.write_text(
                json.dumps({"schema_version": 99, "games": []}), encoding="utf-8"
            )
            cache_path = root / "cache" / "index.json"
            cache_path.parent.mkdir()
            cache_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "games": [{"game_id": "cached", "title": "Cached"}],
                    }
                ),
                encoding="utf-8",
            )
            store = GameIndexStore(
                index_url="",
                cache_path=cache_path,
                local_index_path=local_index,
            )

            self.assertIsNotNone(store.get("cached"))
            self.assertIsNone(store.get("missing"))

    def test_refresh_if_changed_reloads_provider_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "ng_provider" / "update" / "index.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text(
                json.dumps({"schema_version": 1, "games": [{
                    "game_id": "demo", "title": "Before",
                }]}),
                encoding="utf-8",
            )
            store = GameIndexStore(
                index_url="",
                cache_path=root / "cache" / "index.json",
                local_index_path=index_path,
            )
            self.assertTrue(store.refresh(force=True))
            previous_stat = index_path.stat()
            index_path.write_text(
                json.dumps({"schema_version": 1, "games": [{
                    "game_id": "demo", "title": "After",
                }]}),
                encoding="utf-8",
            )
            os.utime(
                index_path,
                ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000_000),
            )

            self.assertTrue(store.refresh_if_changed())
            metadata = store.get("demo")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.title, "After")

    def test_unstable_provider_read_keeps_last_good_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "ng_provider" / "update" / "index.json"
            index_path.parent.mkdir(parents=True)
            index_path.write_text(
                json.dumps({"schema_version": 1, "games": [{
                    "game_id": "demo", "title": "Last good",
                }]}),
                encoding="utf-8",
            )
            store = GameIndexStore(
                index_url="",
                cache_path=root / "cache" / "index.json",
                local_index_path=index_path,
            )
            self.assertTrue(store.refresh(force=True))
            index_path.write_text('{"schema_version": 1, "games": [', encoding="utf-8")

            with patch.object(store, "_read_stable_local_index", return_value=(None, None)):
                self.assertFalse(store.refresh(force=True))

            metadata = store.get("demo")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.title, "Last good")

    def test_file_url_is_converted_with_platform_path_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "folder with spaces"
            root.mkdir()
            index_path = root / "index.json"
            index_path.write_text(json.dumps({"games": [{
                "game_id": "demo", "title": "Demo",
            }]}), encoding="utf-8")
            store = GameIndexStore(index_path.as_uri(), root / "cache.json")
            self.assertIsNotNone(store.get("demo"))

    def test_game_index_reads_foss_media_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            index_path.write_text(json.dumps({"games": [{
                "game_id": "supertuxkart", "title": "SuperTuxKart",
                "media": {"image_url": "https://example.org/cover.jpg",
                          "video_url": "https://example.org/trailer.mp4"},
            }]}), encoding="utf-8")
            store = GameIndexStore(index_path.as_uri(), root / "cache.json")
            game = store.get("supertuxkart")
            self.assertIsNotNone(game)
            assert game is not None
            self.assertEqual(game.image, "https://example.org/cover.jpg")
            self.assertEqual(game.video, "https://example.org/trailer.mp4")

    def test_game_index_store_reads_file_url_and_resolves_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            index_payload = {
                "schema_version": 1,
                "generated_at_utc": "2026-05-27T00:00:00Z",
                "source": {
                    "page_url": index_path.as_uri(),
                },
                "games": [
                    {
                        "game_id": "demo",
                        "title": {"en": "Demo", "de": "Demo"},
                        "description": {"en": "Example", "de": "Beispiel"},
                        "website_url": "https://example.org/game",
                        "community_url": "community/",
                        "lan_supported": True,
                        "max_players": "8",
                        "game_provider_type": "ouisync",
                        "media": {"image": "games/demo/media/cover.svg"},
                        "links": [
                            {
                                "label": {"en": "Discord", "de": "Discord"},
                                "url": "https://example.org/discord",
                            }
                        ],
                    }
                ],
            }
            index_path.write_text(
                json.dumps(index_payload, ensure_ascii=False), encoding="utf-8"
            )

            store = GameIndexStore(index_path.as_uri(), root / "cache" / "index.json")
            self.assertTrue(store.refresh(force=True))
            metadata = store.get("demo")
            self.assertIsNotNone(metadata)
            assert metadata is not None
            self.assertEqual(metadata.effective_title("de"), "Demo")
            self.assertEqual(metadata.effective_description("en"), "Example")
            self.assertEqual(metadata.publisher, "")
            self.assertTrue(metadata.lan_supported)
            self.assertEqual(metadata.max_players, "8")
            self.assertEqual(metadata.game_provider_type, "ouisync")
            self.assertEqual(metadata.links[0]["url"], "https://example.org/discord")
            self.assertEqual(metadata.links[1]["url"], "https://example.org/game")
            self.assertEqual(
                metadata.links[2]["url"],
                urljoin(index_path.parent.as_uri() + "/", "community/"),
            )
            self.assertEqual(metadata.source_file, index_path.as_uri())
            self.assertTrue((root / "cache" / "index.json").is_file())


    def test_game_index_store_skips_explicit_non_lan_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = root / "index.json"
            index_payload = {
                "schema_version": 1,
                "generated_at_utc": "2026-05-27T00:00:00Z",
                "games": [
                    {
                        "game_id": "solo",
                        "title": {"en": "Solo", "de": "Solo"},
                        "lan_supported": False,
                    }
                ],
            }
            index_path.write_text(
                json.dumps(index_payload, ensure_ascii=False), encoding="utf-8"
            )

            store = GameIndexStore(index_path.as_uri(), root / "cache" / "index.json")
            self.assertTrue(store.refresh(force=True))
            self.assertIsNone(store.get("solo"))
