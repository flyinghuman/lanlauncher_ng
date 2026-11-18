"""Tests for HTTP API endpoints."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.core.api.server import create_server
from src.core.catalog.repository import CatalogRepository
from src.core.db.store import open_database


class ApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        db = open_database(str(Path(self.temp.name) / "api.db"))
        self.conn = db.connection
        with self.conn:
            self.conn.execute(
                "INSERT INTO genres(id, name_en, name_de) VALUES (1, 'RTS', 'Echtzeit-Strategie')"
            )
            self.conn.execute(
                """
                INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                VALUES ('demo', 'Demo Game', 'Demo Spiel', 'KEY', 1.5, '8', 1, '1.0')
                """
            )
        self.metadata_root = Path(self.temp.name) / "metadata"
        self.metadata_root.mkdir()

        repo = CatalogRepository(self.conn, metadata_root=self.metadata_root)
        self.shutdown_requested = False
        self.shutdown_apply_session_id = ""
        self.shutdown_apply_action = ""
        self.shutdown_finalize_session_id = ""
        self.rollback_requested = False
        self.flags_requested = False
        self.disabled_ids: list[str] = []
        self.lan_disabled_ids: list[str] = []
        self.game_action_calls: list[tuple[str, str, str]] = []
        self.game_metadata_save_calls: list[tuple[str, dict]] = []
        self.sync_provider_actions: list[tuple[str, str]] = []
        self.app_log_level_updates: list[str] = []
        self.lan_game_inventory_calls: list[int] = []
        self.lan_server_game_inventory_calls: list[int] = []
        self.lan_game_share_updates: list[dict] = []
        self.local_game_settings_updates: list[dict] = []
        self.visibility_updates: list[tuple[str, bool]] = []
        self.lan_server_settings_updates: list[dict] = []
        self.ouisync_inventory_calls: list[tuple[str, str, str]] = []
        self.ouisync_debug_actions: list[str] = []
        self.ouisync_settings_updates: list[tuple[str, dict]] = []
        self.ouisync_repository_actions: list[tuple[str, str]] = []
        self.ouisync_entry_copies: list[tuple[str, str, str]] = []
        self.ouisync_peer_actions: list[tuple[str, str]] = []

        self.server = create_server(
            "127.0.0.1",
            0,
            started_ok=lambda: True,
            repo_supplier=lambda: repo,
            scan_run=lambda _force: {"scanned": 1, "installed": 1, "missing": 0},
            rescan_start=lambda _force: {
                "scan": {"scanned": 1, "installed": 1, "missing": 0},
                "resync": {
                    "running": False,
                    "phase": "done",
                    "total": 1,
                    "processed": 1,
                    "added": 1,
                    "skipped": 0,
                    "failed": 0,
                    "percent": 100,
                    "current_game_id": "",
                    "current_title": "",
                    "message": "completed",
                },
            },
            rescan_status=lambda: {
                "running": False,
                "phase": "done",
                "total": 1,
                "processed": 1,
                "added": 1,
                "skipped": 0,
                "failed": 0,
                "percent": 100,
                "current_game_id": "",
                "current_title": "",
                "message": "completed",
            },
            sync_status=lambda: {
                "provider": "noop",
                "running": False,
                "state": "disabled",
                "pid": None,
                "last_error": "",
            },
            sync_metrics=lambda: {
                "download_bps": 0,
                "upload_bps": 0,
                "disk_read_bps": 0,
                "disk_write_bps": 0,
                "disk_total_bps": 0,
                "disk_activity_bps": 0,
            },
            sync_metrics_for_game=lambda _game_id: {
                "download_bps": 0,
                "upload_bps": 0,
                "disk_read_bps": 0,
                "disk_write_bps": 0,
                "disk_total_bps": 0,
                "disk_activity_bps": 0,
            },
            sync_start=lambda: {
                "provider": "noop",
                "running": False,
                "state": "disabled",
                "pid": None,
                "last_error": "",
            },
            sync_stop=lambda: {
                "provider": "noop",
                "running": False,
                "state": "disabled",
                "pid": None,
                "last_error": "",
            },
            sync_provider_action=self._sync_provider_action,
            platform_info=lambda: {"name": "windows"},
            available_storage_locations=lambda: [
                {"id": "D", "path": "D:\\", "label": "Games", "display": "D: (Games)"},
                {"id": "E", "path": "E:\\", "label": "", "display": "E:"},
            ],
            winetricks_packages_read=lambda: {
                "packages": [
                    {"id": "d3dx9", "category": "graphics"},
                    {"id": "vcrun2019", "category": "runtime"},
                ],
                "default_selected": ["d3dx9"],
            },
            install_prerequisites_bundle=lambda: {
                "ok": True,
                "message": "launched",
                "path": "D:/LAN/eti_launcher/bin/preqsetup.exe",
            },
            install_wine_common_dependencies=lambda: {
                "ok": True,
                "message": "wine_dependencies_install_started",
                "detail": "d3dx9 vcrun2008",
                "packages": ["d3dx9", "vcrun2008"],
                "prefix": "/home/tester/.wine",
            },
            game_install_proton_common_dependencies=lambda game_id: {
                "ok": True,
                "message": "wine_dependencies_install_started",
                "detail": "d3dx9 vcrun2008",
                "packages": ["d3dx9", "vcrun2008"],
                "prefix": f"/srv/LAN/{game_id}/.compatdata/proton",
                "runtime": "proton",
                "game_id": game_id,
            },
            game_manage_prefix_wine_dependencies=lambda game_id, payload: {
                "ok": True,
                "message": "wine_dependencies_install_started"
                if payload.get("action") == "install"
                else "wine_prefix_uninstaller_started",
                "detail": "",
                "packages": payload.get("packages", []),
                "prefix": f"/srv/LAN/{game_id}/.compatdata/wine",
                "runtime": "wine",
                "game_id": game_id,
                "action": payload.get("action", "install"),
            },
            game_save_metadata=self._game_save_metadata,
            game_local_settings_update=self._game_local_settings_update,
            set_resilio_network_mode=lambda payload: {
                "ok": payload.get("mode") in {"lan", "internet"},
                "message": "network_mode_applied"
                if payload.get("mode") in {"lan", "internet"}
                else "invalid_network_mode",
                "mode": payload.get("mode", ""),
                "detail": "",
            },
            set_local_network_private=lambda _payload: {
                "ok": True,
                "message": "network_profile_applied",
                "detail": "",
            },
            storage_validate=lambda path: {
                "path": path,
                "exists": True,
                "writable": True,
                "is_directory": True,
                "ok": True,
                "message": "ok",
            },
            open_folder=lambda _path: {"ok": True, "message": "opened"},
            install_script_info=lambda game_id: {
                "game_id": game_id,
                "platform": "windows",
                "exists": True,
                "path": f"scripts/wrappers/windows/{game_id}.ps1",
            },
            game_action=self._game_action,
            game_launch_settings_read=lambda game_id: {
                "ok": True,
                "message": "ok",
                "game_id": game_id,
                "linux_runtime_override": "proton",
                "linux_leave_terminal_open": True,
                "effective_linux_runtime": "proton",
            },
            game_launch_settings_update=lambda game_id, payload: {
                "ok": True,
                "message": "saved",
                "game_id": game_id,
                "linux_runtime_override": payload.get("linux_runtime_override", ""),
                "linux_leave_terminal_open": bool(
                    payload.get("linux_leave_terminal_open", False)
                ),
                "effective_linux_runtime": payload.get("linux_runtime_override", "wine")
                or "wine",
            },
            game_sync_status=lambda _game_id: {
                "ok": True,
                "message": "ok",
                "active": False,
                "progress_percent": 0,
            },
            game_sync_start=lambda _game_id: {
                "ok": True,
                "message": "started",
                "active": True,
                "progress_percent": 10,
            },
            game_sync_stop=lambda _game_id: {
                "ok": True,
                "message": "stopped",
                "active": False,
                "progress_percent": 0,
            },
            game_video_path=lambda _game_id: "",
            game_image_path=lambda _game_id: "",
            settings_read=lambda: {
                "nickname": "Player",
                "theme": "dark",
                "log_level": "WARNING",
                "auto_start_sync": True,
                "sync_only_mode": False,
                "library_path_initialized": True,
                "windows_game_drive_letter": "D",
                "linux_install_path": "/srv/LAN",
                "platform": "windows",
                "effective_library_path": "D:/LAN",
                "provider_interfaces": [
                    {
                        "provider_type": "resilio",
                        "title": "Resilio",
                        "iframe_url": "http://127.0.0.1:13338/gui/",
                        "open_url": "http://127.0.0.1:13338/gui/",
                        "available": True,
                        "running": True,
                        "state": "running",
                    },
                    {
                        "provider_type": "ouisync",
                        "title": "Sync provider",
                        "iframe_url": "http://127.0.0.1:8384/",
                        "open_url": "http://127.0.0.1:8384/",
                        "available": True,
                        "running": True,
                        "state": "running",
                    },
                ],
            },
            launcher_site_read=lambda: {
                "source_url": "http://launcher.lan/launcher.ini",
                "reachable": True,
                "last_success_at": 0.0,
                "last_error": "",
                "lan_title": "My LAN Party",
                "lan_url": "http://launcher.lan",
                "stats_url": "http://launcher.lan/stats.php",
                "discord_url": "https://discord.gg/abcde12345",
                "ts3_server": "ts3server://1.2.3.4?port=9987",
                "links": [
                    {
                        "key": "lan_url",
                        "label": "My LAN Party",
                        "url": "http://launcher.lan",
                    }
                ],
                "disable_games": list(self.disabled_ids),
            },
            disabled_game_ids_read=lambda: list(self.disabled_ids),
            is_game_disabled=lambda game_id: (
                str(game_id or "").strip().lower() in set(self.disabled_ids)
            ),
            settings_update=lambda payload: {
                "ok": True,
                "message": "saved",
                "settings": payload,
            },
            extra_sync_items_read=lambda: {"items": []},
            extra_sync_item_upsert=lambda _payload: {
                "ok": True,
                "message": "saved",
                "items": [],
            },
            extra_sync_items_import_bootstrap=lambda payload: {
                "ok": True,
                "message": "imported",
                "imported": len(payload.get("items", [])),
                "items": [],
            },
            extra_sync_item_toggle=lambda _payload: {
                "ok": True,
                "message": "saved",
                "items": [],
            },
            extra_sync_item_refresh_images=lambda _payload: {
                "ok": True,
                "message": "refreshed",
                "items": [],
            },
            extra_sync_item_delete=lambda _payload: {
                "ok": True,
                "message": "saved",
                "items": [],
            },
            extra_sync_item_delete_data=lambda _payload: {
                "ok": True,
                "message": "saved",
                "items": [],
            },
            extra_sync_item_wipe=lambda _payload: {
                "ok": True,
                "message": "saved",
                "items": [],
            },
            app_log_level_update=self._app_log_level_update,
            logs_read=lambda _limit: {
                "entries": [
                    {
                        "source": "lanlauncherng",
                        "ts": "2026-06-17T10:00:00+00:00",
                        "msg": "hello",
                    },
                    {
                        "source": "resilio",
                        "ts": "2026-06-17T10:00:01+00:00",
                        "msg": "rslsync",
                    },
                ],
            },
            debug_logs_read=lambda _limit: {
                "sync": [{"msg": "resilio debug line"}],
                "providers": [{"msg": "resilio debug line"}],
            },
            app_shutdown=self._shutdown_request,
            app_shutdown_prepare=self._shutdown_prepare,
            app_shutdown_apply=self._shutdown_apply,
            app_shutdown_status=self._shutdown_status,
            app_shutdown_finalize=self._shutdown_finalize,
            app_update_check=lambda: {
                "ok": True,
                "update_available": True,
                "current_version": "0.1.6",
                "target_version": "0.1.7",
                "message": "shutdown_update_checked",
            },
            app_update_rollback=self._update_rollback,
            app_feature_flags_read=self._feature_flags_read,
            lan_game_inventory_read=self._lan_game_inventory_read,
            lan_server_game_inventory_read=self._lan_server_game_inventory_read,
            lan_game_share_update=self._lan_game_share_update,
            game_visibility_update=self._game_visibility_update,
            lan_server_settings_update=self._record_lan_server_settings_update,
            lan_server_settings_read=lambda: {
                "ok": True,
                "settings": {"disable_games": [], "links": []},
                "assets": [{"game_id": "demo", "title": "Demo Game"}],
            },
            lan_disabled_game_ids_read=lambda: list(self.lan_disabled_ids),
            ouisync_repository_inventory_read=self._ouisync_repository_inventory_read,
            ouisync_debug_action=self._ouisync_debug_action,
            ouisync_repository_settings_update=self._ouisync_repository_settings_update,
            ouisync_repository_action=self._ouisync_repository_action,
            ouisync_repository_entry_copy=self._ouisync_repository_entry_copy,
            ouisync_peer_action=lambda action, address: (
                self.ouisync_peer_actions.append((action, address))
                or {"ok": True, "message": "ouisync_peer_added", "address": address}
            ),
        )
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.05)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.conn.close()
        self.temp.cleanup()

    def _get_json(self, path: str) -> tuple[int, dict]:
        with urlopen(f"http://127.0.0.1:{self.port}{path}") as response:  # noqa: S310 local server
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req) as response:  # noqa: S310 local server
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body

    def _shutdown_request(self) -> dict:
        self.shutdown_requested = True
        return {"accepted": True}

    def _game_visibility_update(self, game_id: str, hidden: bool) -> dict:
        self.visibility_updates.append((game_id, hidden))
        return {"ok": True, "message": "hidden" if hidden else "visible"}

    def _record_lan_server_settings_update(self, payload: dict) -> dict:
        self.lan_server_settings_updates.append(payload)
        return {"ok": True, "message": "saved"}

    def _shutdown_prepare(self) -> dict:
        return {
            "accepted": True,
            "session_id": "sess-1",
            "phase": "ready",
            "will_apply_update": True,
            "update_available": True,
            "console_lines": ["checking update manifest..."],
        }

    def _shutdown_apply(self, session_id: str, action: str) -> dict:
        self.shutdown_apply_session_id = session_id
        self.shutdown_apply_action = action
        return {
            "accepted": True,
            "session_id": session_id,
            "phase": "running",
            "console_lines": ["launching updater"],
        }

    def _shutdown_status(self, session_id: str) -> dict:
        return {
            "accepted": True,
            "session_id": session_id,
            "phase": "done",
            "console_lines": ["update apply finished"],
        }

    def _shutdown_finalize(self, session_id: str) -> dict:
        self.shutdown_finalize_session_id = session_id
        return {
            "accepted": True,
            "session_id": session_id,
            "phase": "done",
            "message": "shutdown_finalize_requested",
        }

    def _update_rollback(self) -> dict:
        self.rollback_requested = True
        return {"ok": True, "message": "update_rollback_applied"}

    def _feature_flags_read(self) -> dict:
        self.flags_requested = True
        return {
            "values": {"shutdown_update_recovery": True},
            "definitions": [
                {
                    "key": "shutdown_update_recovery",
                    "default": True,
                    "description": "Enable interrupted shutdown-update recovery (resume/abort) flow.",
                    "enabled": True,
                }
            ],
            "source_path": "config/feature-flags.json",
        }

    def _game_action(self, game_id: str, action: str, locale: str) -> dict:
        self.game_action_calls.append((game_id, action, locale))
        return {
            "ok": True,
            "action": action,
            "game_id": game_id,
            "message": "ok",
            "details": {},
        }

    def _game_save_metadata(self, game_id: str, payload: dict) -> dict:
        self.game_metadata_save_calls.append((game_id, payload))
        if bool(payload.get("fail")):
            return {
                "ok": False,
                "message": "invalid_winetricks_package_set",
                "game_id": game_id,
                "packages": [],
            }
        return {
            "ok": True,
            "message": "ok",
            "game_id": game_id,
            "packages": payload.get("packages", []),
        }

    def _game_local_settings_update(self, payload: dict) -> dict:
        self.local_game_settings_updates.append(payload)
        item = payload.get("item", {}) if isinstance(payload, dict) else {}
        game_id = str(item.get("game_id", "")).strip()
        if not game_id:
            return {
                "ok": False,
                "message": "invalid_game_id",
                "game_id": "",
            }
        return {
            "ok": True,
            "message": "saved",
            "game_id": game_id,
            "metadata_file": f"/tmp/{game_id}.json",
            "metadata": {"title": {"en": item.get("title_en", ""), "de": item.get("title_de", "")}},
        }

    def _sync_provider_action(self, provider_type: str, action: str) -> dict:
        self.sync_provider_actions.append((provider_type, action))
        state = "running" if action in {"start", "restart"} else "stopped"
        running = action in {"start", "restart"}
        pid = 4321 if running else None
        last_error = "" if running or action == "stop" else "sync_provider_action_failed"
        return {
            "provider": provider_type,
            "running": running,
            "state": state,
            "pid": pid,
            "last_error": last_error,
        }

    def _app_log_level_update(self, payload: dict) -> dict:
        level = str(payload.get("level", "")).strip().upper()
        self.app_log_level_updates.append(level)
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            return {
                "ok": False,
                "message": "invalid_log_level",
                "settings": {"log_level": "WARNING"},
            }
        return {
            "ok": True,
            "message": "saved",
            "settings": {"log_level": level},
        }

    def _lan_game_inventory_read(self) -> dict:
        self.lan_game_inventory_calls.append(1)
        return {
            "root_path": "/srv/LAN",
            "folders": [
                {
                    "name": "alpha",
                    "path": "/srv/LAN/alpha",
                    "folder_id": "alpha",
                    "configured": True,
                    "shared": True,
                    "paused": False,
                    "type": "receiveonly",
                }
            ],
        }

    def _lan_server_game_inventory_read(self) -> dict:
        self.lan_server_game_inventory_calls.append(1)
        return {"root_path": "/srv/LAN", "folders": [{"name": "filtered"}]}

    def _lan_game_share_update(self, payload: dict) -> dict:
        self.lan_game_share_updates.append(payload)
        return {
            "ok": True,
            "message": "lan_share_updated",
            "lan": self._lan_game_inventory_read(),
        }

    def test_health_endpoint(self) -> None:
        status, payload = self._get_json("/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_root_serves_frontend(self) -> None:
        with urlopen(f"http://127.0.0.1:{self.port}/") as response:  # noqa: S310 local server
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn("LANLauncherNG", body)

    def test_lan_game_inventory_route_returns_selection_data(self) -> None:
        status, payload = self._get_json("/lan/games")
        self.assertEqual(status, 200)
        self.assertEqual(payload["lan"]["root_path"], "/srv/LAN")
        self.assertEqual(self.lan_game_inventory_calls, [1])

    def test_lan_game_inventory_route_supports_server_role_preview(self) -> None:
        status, payload = self._get_json("/lan/games?role=server")
        self.assertEqual(status, 200)
        self.assertEqual(payload["lan"]["folders"], [{"name": "filtered"}])
        self.assertEqual(self.lan_server_game_inventory_calls, [1])

    def test_lan_game_share_route_updates_inventory(self) -> None:
        status, payload = self._post_json(
            "/lan/games",
            {"folder_path": "/srv/LAN/alpha", "shared": False},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(
            self.lan_game_share_updates,
            [{"folder_path": "/srv/LAN/alpha", "shared": False}],
        )

    def test_version_endpoint(self) -> None:
        status, payload = self._get_json("/version")
        self.assertEqual(status, 200)
        self.assertIn("version", payload)
        self.assertIn("service", payload)

    def test_catalog_list_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games?locale=de&page=1&page_size=10")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["title"], "Demo Spiel")

    def test_catalog_visibility_endpoint(self) -> None:
        status, payload = self._post_json(
            "/catalog/games/demo/visibility",
            {"hidden": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(self.visibility_updates, [("demo", True)])

    def test_catalog_list_endpoint_supports_version_sort_desc(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                VALUES ('older', 'Older', 'Aelter', 'K1', 1.0, '8', 1, '20240101')
                """
            )
            self.conn.execute(
                """
                INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                VALUES ('newer', 'Newer', 'Neuer', 'K2', 1.0, '8', 1, '20250101')
                """
            )
        status, payload = self._get_json(
            "/catalog/games?locale=en&sort=version&order=desc&page_size=0"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"][0]["id"], "newer")

    def test_catalog_list_unpaged_returns_all_games(self) -> None:
        with self.conn:
            for idx in range(130):
                self.conn.execute(
                    """
                    INSERT INTO game_catalog(id, title_en, title_de, key, size_gb, max_players, genre_id, version)
                    VALUES (?, ?, ?, ?, 1.0, '8', 1, '1.0')
                    """,
                    (
                        f"bulk{idx:03d}",
                        f"Bulk Game {idx:03d}",
                        f"Bulk Spiel {idx:03d}",
                        f"BKEY{idx:03d}",
                    ),
                )

        status, payload = self._get_json("/catalog/games?locale=en&page_size=0")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 131)
        self.assertEqual(len(payload["items"]), 131)

    def test_catalog_genres_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/genres?locale=de")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["id"], 1)
        self.assertEqual(payload["items"][0]["name"], "Echtzeit-Strategie")

    def test_rescan_status_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/rescan-status")
        self.assertEqual(status, 200)
        self.assertIn("resync", payload)
        self.assertEqual(payload["resync"]["percent"], 100)

    def test_scan_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/scan?force=true")
        self.assertEqual(status, 200)
        self.assertEqual(payload["scan"]["installed"], 1)

    def test_catalog_detail_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo?locale=en")
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], "demo")
        self.assertEqual(payload["title"], "Demo Game")

    def test_catalog_endpoints_expose_metadata(self) -> None:
        (self.metadata_root / "demo.json").write_text(
            '{"title":"Metadata Demo","description":"Metadata description",'
            '"runner":"proton","game_start":{"file":"game_start.cmd","args":["--start"]}}',
            encoding="utf-8",
        )

        status, payload = self._get_json("/catalog/games?locale=en&page_size=0")
        self.assertEqual(status, 200)
        self.assertIn("metadata", payload["items"][0])
        self.assertEqual(payload["items"][0]["title"], "Metadata Demo")
        self.assertEqual(payload["items"][0]["metadata"]["runner"], "proton")

        status, payload = self._get_json("/catalog/games/demo?locale=en")
        self.assertEqual(status, 200)
        self.assertEqual(payload["metadata"]["title"]["en"], "Metadata Demo")
        self.assertEqual(payload["metadata"]["game_start"]["file"], "game_start.cmd")

    def test_catalog_not_found(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"http://127.0.0.1:{self.port}/catalog/games/unknown")  # noqa: S310 local server
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_sync_status_endpoint(self) -> None:
        status, payload = self._get_json("/sync/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["sync"]["provider"], "noop")

    def test_sync_speed_endpoint(self) -> None:
        status, payload = self._get_json("/sync/speed")
        self.assertEqual(status, 200)
        self.assertEqual(payload["speed"]["download_bps"], 0)
        self.assertEqual(payload["speed"]["disk_total_bps"], 0)
        self.assertEqual(payload["speed"]["disk_activity_bps"], 0)

    def test_sync_speed_endpoint_accepts_game_id(self) -> None:
        status, payload = self._get_json("/sync/speed?game_id=demo")
        self.assertEqual(status, 200)
        self.assertEqual(payload["speed"]["download_bps"], 0)
        self.assertEqual(payload["speed"]["disk_total_bps"], 0)
        self.assertEqual(payload["speed"]["disk_activity_bps"], 0)

    def test_sync_providers_endpoint(self) -> None:
        status, payload = self._get_json("/sync/providers")
        self.assertEqual(status, 200)
        self.assertIn("providers", payload)
        self.assertIsInstance(payload["providers"], list)

    def test_sync_provider_action_endpoint(self) -> None:
        status, payload = self._get_json("/sync/providers/ouisync/restart")
        self.assertEqual(status, 200)
        self.assertEqual(self.sync_provider_actions, [("ouisync", "restart")])
        self.assertEqual(payload["sync"]["provider"], "ouisync")
        self.assertTrue(payload["sync"]["running"])

    def _ouisync_repository_inventory_read(
        self, info_hash: str, directory_path: str, locale: str
    ) -> dict:
        self.ouisync_inventory_calls.append((info_hash, directory_path, locale))
        return {
            "available": True,
            "error": "",
            "repositories": [],
            "catalog": [],
            "network": {"throughput_rx": 12},
        }

    def test_ouisync_repository_inventory_endpoint(self) -> None:
        status, payload = self._get_json(
            "/sync/providers/ouisync/repositories?info_hash=abc123&path=%2Fassets&locale=de"
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["network"]["throughput_rx"], 12)
        self.assertEqual(self.ouisync_inventory_calls, [("abc123", "/assets", "de")])

    def _ouisync_debug_action(self, action: str) -> dict:
        self.ouisync_debug_actions.append(action)
        return {"ok": True, "message": "completed", "lines": [{"key": "check", "value": "ok"}]}

    def test_ouisync_debug_action_endpoint(self) -> None:
        status, payload = self._post_json(
            "/sync/providers/ouisync/debug", {"action": "ng-provider"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(self.ouisync_debug_actions, ["ng-provider"])

    def _ouisync_repository_settings_update(self, info_hash: str, settings: dict) -> dict:
        self.ouisync_settings_updates.append((info_hash, settings))
        return {"ok": True, "message": "ouisync_repository_settings_updated", "settings": settings}

    def test_ouisync_repository_settings_update_endpoint(self) -> None:
        status, payload = self._post_json(
            "/sync/providers/ouisync/settings",
            {"info_hash": "abc123", "settings": {"dht_enabled": True}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(
            self.ouisync_settings_updates,
            [("abc123", {"dht_enabled": True})],
        )

    def _ouisync_repository_action(self, action: str, info_hash: str) -> dict:
        self.ouisync_repository_actions.append((action, info_hash))
        return {"ok": True, "message": "ouisync_repository_mounted"}

    def _ouisync_repository_entry_copy(
        self, info_hash: str, path: str, destination_directory: str
    ) -> dict:
        self.ouisync_entry_copies.append((info_hash, path, destination_directory))
        return {"ok": True, "message": "ouisync_repository_entry_copied"}

    def test_ouisync_repository_mount_action_endpoint(self) -> None:
        status, payload = self._post_json(
            "/sync/providers/ouisync/repository-action",
            {"action": "mount", "info_hash": "abc123"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(self.ouisync_repository_actions, [("mount", "abc123")])

    def test_ouisync_repository_entry_copy_endpoint(self) -> None:
        status, payload = self._post_json(
            "/sync/providers/ouisync/copy-entry",
            {
                "info_hash": "abc123",
                "path": "/assets",
                "destination_directory": "local",
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(
            self.ouisync_entry_copies,
            [("abc123", "/assets", "local")],
        )

    def test_ouisync_peer_action_endpoint(self) -> None:
        status, payload = self._post_json(
            "/sync/providers/ouisync/peers",
            {"action": "add", "address": "192.168.1.20:20209"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(self.ouisync_peer_actions, [("add", "192.168.1.20:20209")])

    def test_manual_rollback_endpoint(self) -> None:
        status, payload = self._get_json("/app/update/rollback")
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["message"], "update_rollback_applied")
        self.assertTrue(self.rollback_requested)

    def test_update_check_endpoint(self) -> None:
        status, payload = self._get_json("/app/update/check")
        self.assertEqual(status, 200)
        self.assertTrue(payload["update"]["ok"])
        self.assertTrue(payload["update"]["update_available"])
        self.assertEqual(payload["update"]["target_version"], "0.1.7")

    def test_feature_flags_endpoint(self) -> None:
        status, payload = self._get_json("/app/flags")
        self.assertEqual(status, 200)
        self.assertTrue(self.flags_requested)
        self.assertIn("values", payload["flags"])
        self.assertTrue(payload["flags"]["values"]["shutdown_update_recovery"])

    def test_platform_info_endpoint(self) -> None:
        status, payload = self._get_json("/platform/info")
        self.assertEqual(status, 200)
        self.assertEqual(payload["platform"]["name"], "windows")

    def test_storage_locations_endpoint(self) -> None:
        status, payload = self._get_json("/platform/storage-locations")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["storage_locations"]), 2)
        self.assertEqual(payload["storage_locations"][0]["display"], "D: (Games)")

    def test_storage_validate_endpoint(self) -> None:
        status, payload = self._get_json("/platform/validate-storage?path=C:%5CData")
        self.assertEqual(status, 200)
        self.assertTrue(payload["storage"]["ok"])

    def test_install_prerequisites_endpoint(self) -> None:
        status, payload = self._get_json("/platform/install-prerequisites")
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertIn("preqsetup.exe", payload["result"]["path"])

    def test_winetricks_packages_endpoint(self) -> None:
        status, payload = self._get_json("/platform/winetricks-packages")
        self.assertEqual(status, 200)
        self.assertIn("packages", payload["winetricks"])
        self.assertEqual(payload["winetricks"]["default_selected"], ["d3dx9"])

    def test_install_wine_common_deps_endpoint(self) -> None:
        status, payload = self._get_json("/platform/install-wine-common-deps")
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(
            payload["result"]["message"], "wine_dependencies_install_started"
        )
        self.assertIn("d3dx9", payload["result"]["packages"])

    def test_install_game_proton_common_deps_endpoint(self) -> None:
        status, payload = self._get_json(
            "/catalog/games/demo/install-proton-common-deps"
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(
            payload["result"]["message"], "wine_dependencies_install_started"
        )
        self.assertEqual(payload["result"]["runtime"], "proton")
        self.assertIn("/demo/.compatdata/proton", payload["result"]["prefix"])

    def test_manage_game_prefix_wine_dependencies_endpoint(self) -> None:
        status, payload = self._post_json(
            "/catalog/games/demo/prefix-wine-dependencies",
            {"action": "install", "packages": ["d3dx9", "vcrun2019"]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["action"], "install")
        self.assertEqual(payload["result"]["runtime"], "wine")
        self.assertIn("vcrun2019", payload["result"]["packages"])

    def test_save_game_metadata_endpoint(self) -> None:
        status, payload = self._post_json(
            "/catalog/games/demo/metadata",
            {"packages": ["d3dx9", "vcrun2019"]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["game_id"], "demo")
        self.assertEqual(payload["result"]["packages"], ["d3dx9", "vcrun2019"])
        self.assertEqual(
            self.game_metadata_save_calls[-1],
            ("demo", {"packages": ["d3dx9", "vcrun2019"]}),
        )

    def test_save_local_game_endpoint(self) -> None:
        status, payload = self._post_json(
            "/catalog/games/local-settings",
            {
                "item": {
                    "game_id": "local-demo",
                    "title_en": "Local Demo",
                    "title_de": "Lokale Demo",
                    "genre_id": "1",
                    "size_gb": 1.25,
                }
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["game_id"], "local-demo")
        self.assertEqual(self.local_game_settings_updates[-1]["item"]["game_id"], "local-demo")

    def test_save_game_metadata_endpoint_returns_bad_request_on_error(self) -> None:
        req = Request(
            f"http://127.0.0.1:{self.port}/catalog/games/demo/metadata",
            method="POST",
            data=json.dumps({"fail": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)  # noqa: S310 local server
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertFalse(body["result"]["ok"])
        self.assertEqual(body["result"]["message"], "invalid_winetricks_package_set")
        ctx.exception.close()

    def test_set_resilio_network_mode_endpoint(self) -> None:
        status, payload = self._post_json(
            "/platform/resilio-network-mode", {"mode": "lan"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["mode"], "lan")

    def test_set_resilio_network_mode_endpoint_rejects_invalid_mode(self) -> None:
        req = Request(
            f"http://127.0.0.1:{self.port}/platform/resilio-network-mode",
            method="POST",
            data=json.dumps({"mode": "bad"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(req)  # noqa: S310 local server
        self.assertEqual(ctx.exception.code, 400)
        body = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(body["result"]["message"], "invalid_network_mode")
        ctx.exception.close()

    def test_set_local_network_private_endpoint(self) -> None:
        status, payload = self._post_json("/platform/set-local-network-private", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["message"], "network_profile_applied")

    def test_install_script_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/install-script")
        self.assertEqual(status, 200)
        self.assertTrue(payload["install_script"]["exists"])

    def test_game_install_action_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/install")
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["action"], "install")

    def test_game_status_local_action_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/status-local")
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["action"], "status")

    def test_game_start_server_action_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/start-server")
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["action"], "start-server")
        self.assertEqual(self.game_action_calls[-1], ("demo", "start-server", ""))

    def test_game_start_action_endpoint_forwards_locale(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/start?locale=de")
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["action"], "start")
        self.assertEqual(self.game_action_calls[-1], ("demo", "start", "de"))

    def test_game_delete_action_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/delete")
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["action"], "delete")

    def test_game_sync_status_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/sync-status")
        self.assertEqual(status, 200)
        self.assertFalse(payload["result"]["active"])

    def test_game_launch_settings_get_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/launch-settings")
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["game_id"], "demo")
        self.assertEqual(payload["result"]["linux_runtime_override"], "proton")
        self.assertTrue(payload["result"]["linux_leave_terminal_open"])

    def test_game_launch_settings_post_endpoint(self) -> None:
        status, payload = self._post_json(
            "/catalog/games/demo/launch-settings",
            {
                "linux_runtime_override": "wine",
                "linux_leave_terminal_open": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["game_id"], "demo")
        self.assertEqual(payload["result"]["linux_runtime_override"], "wine")
        self.assertTrue(payload["result"]["linux_leave_terminal_open"])
        self.assertEqual(payload["result"]["effective_linux_runtime"], "wine")

    def test_game_sync_start_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/sync-start")
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["active"])

    def test_game_sync_stop_endpoint(self) -> None:
        status, payload = self._get_json("/catalog/games/demo/sync-stop")
        self.assertEqual(status, 200)
        self.assertFalse(payload["result"]["active"])

    def test_settings_get_endpoint(self) -> None:
        status, payload = self._get_json("/settings")
        self.assertEqual(status, 200)
        self.assertEqual(payload["settings"]["theme"], "dark")
        self.assertFalse(payload["settings"]["sync_only_mode"])
        self.assertEqual(
            payload["settings"]["provider_interfaces"][0]["provider_type"],
            "resilio",
        )

    def test_launcher_site_get_endpoint(self) -> None:
        status, payload = self._get_json("/launcher-site")
        self.assertEqual(status, 200)
        self.assertTrue(payload["launcher_site"]["reachable"])
        self.assertEqual(payload["launcher_site"]["lan_title"], "My LAN Party")

    def test_lan_server_settings_get_endpoint(self) -> None:
        status, payload = self._get_json("/settings/lan-server")
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["assets"][0]["game_id"], "demo")

    def test_lan_server_settings_post_endpoint(self) -> None:
        status, payload = self._post_json(
            "/settings/lan-server",
            {"lan_title": "Party", "disable_games": ["demo"], "links": []},
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["message"], "saved")
        self.assertEqual(self.lan_server_settings_updates[0]["lan_title"], "Party")

    def test_catalog_hides_disabled_game_ids(self) -> None:
        self.disabled_ids = ["demo"]
        status, payload = self._get_json("/catalog/games?locale=en&page_size=0")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["items"], [])
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"http://127.0.0.1:{self.port}/catalog/games/demo")  # noqa: S310 local server
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_lan_disabled_game_list_exempts_locally_installed_games(self) -> None:
        self.lan_disabled_ids = ["demo"]
        status, payload = self._get_json("/catalog/games?locale=en&page_size=0")
        self.assertEqual(status, 200)
        self.assertEqual(payload["items"], [])
        CatalogRepository(self.conn).set_install_state("demo", "installed", "1.0")
        status, payload = self._get_json("/catalog/games?locale=en&page_size=0")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in payload["items"]], ["demo"])

    def test_settings_post_endpoint(self) -> None:
        status, payload = self._post_json(
            "/settings", {"nickname": "Neo", "theme": "light"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["settings"]["nickname"], "Neo")

    def test_extra_sync_items_endpoint(self) -> None:
        status, payload = self._get_json("/settings/extra-sync-items")
        self.assertEqual(status, 200)
        self.assertIn("items", payload)

    def test_extra_sync_items_post_endpoint(self) -> None:
        status, payload = self._post_json(
            "/settings/extra-sync-items",
            {"item": {"game_id": "eti_launcher", "game_key": "ABC"}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])

    def test_extra_sync_items_import_bootstrap_endpoint(self) -> None:
        status, payload = self._post_json(
            "/settings/extra-sync-items/import-bootstrap",
            {"items": [{"game_id": "provider_one", "is_game_provider": True}]},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["imported"], 1)

    def test_extra_sync_items_refresh_images_endpoint(self) -> None:
        status, payload = self._post_json(
            "/settings/extra-sync-items/refresh-images",
            {"game_id": "eti_launcher"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["result"]["ok"])

    def test_logs_endpoint(self) -> None:
        status, payload = self._get_json("/logs?limit=10")
        self.assertEqual(status, 200)
        self.assertIn("entries", payload["logs"])
        self.assertEqual(payload["logs"]["entries"][0]["source"], "lanlauncherng")
        self.assertEqual(payload["logs"]["entries"][1]["source"], "resilio")

    def test_logs_endpoint_accepts_maximum_limit(self) -> None:
        status, payload = self._get_json("/logs?limit=2000")
        self.assertEqual(status, 200)
        self.assertIn("entries", payload["logs"])

    def test_debug_log_endpoint(self) -> None:
        status, payload = self._get_json("/debug/log?limit=10")
        self.assertEqual(status, 200)
        self.assertIn("sync", payload["logs"])
        self.assertIn("providers", payload["logs"])
        self.assertEqual(payload["logs"]["sync"][0]["msg"], "resilio debug line")
        self.assertEqual(payload["logs"]["providers"][0]["msg"], "resilio debug line")

    def test_app_log_level_endpoint(self) -> None:
        status, payload = self._post_json("/app/log-level", {"level": "critical"})
        self.assertEqual(status, 200)
        self.assertEqual(self.app_log_level_updates, ["CRITICAL"])
        self.assertTrue(payload["result"]["ok"])
        self.assertEqual(payload["result"]["settings"]["log_level"], "CRITICAL")

    def test_app_shutdown_endpoint(self) -> None:
        status, payload = self._get_json("/app/shutdown")
        self.assertEqual(status, 200)
        self.assertTrue(payload["shutdown"]["accepted"])
        self.assertTrue(self.shutdown_requested)

    def test_app_shutdown_prepare_endpoint(self) -> None:
        status, payload = self._get_json("/app/shutdown/prepare")
        self.assertEqual(status, 200)
        self.assertTrue(payload["shutdown"]["accepted"])
        self.assertEqual(payload["shutdown"]["session_id"], "sess-1")

    def test_app_shutdown_apply_endpoint(self) -> None:
        status, payload = self._get_json("/app/shutdown/apply?session_id=sess-1")
        self.assertEqual(status, 200)
        self.assertEqual(self.shutdown_apply_session_id, "sess-1")
        self.assertEqual(self.shutdown_apply_action, "start")
        self.assertEqual(payload["shutdown"]["phase"], "running")

    def test_app_shutdown_apply_endpoint_with_resume_action(self) -> None:
        status, payload = self._get_json(
            "/app/shutdown/apply?session_id=sess-1&action=resume"
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.shutdown_apply_session_id, "sess-1")
        self.assertEqual(self.shutdown_apply_action, "resume")
        self.assertEqual(payload["shutdown"]["phase"], "running")

    def test_app_shutdown_status_endpoint(self) -> None:
        status, payload = self._get_json("/app/shutdown/status?session_id=sess-1")
        self.assertEqual(status, 200)
        self.assertEqual(payload["shutdown"]["phase"], "done")

    def test_app_shutdown_finalize_endpoint(self) -> None:
        status, payload = self._get_json("/app/shutdown/finalize?session_id=sess-1")
        self.assertEqual(status, 200)
        self.assertEqual(self.shutdown_finalize_session_id, "sess-1")
        self.assertTrue(payload["shutdown"]["accepted"])

    def test_video_not_found_endpoint(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"http://127.0.0.1:{self.port}/media/video/demo")  # noqa: S310 local server
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_image_not_found_endpoint(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"http://127.0.0.1:{self.port}/media/image/demo")  # noqa: S310 local server
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
