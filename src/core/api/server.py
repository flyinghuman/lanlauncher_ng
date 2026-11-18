"""HTTP API surface for launcher core."""

from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from src.core.catalog.repository import CatalogRepository, ListQuery
from src.core.version import APP_NAME, APP_VERSION, BUILD_DATE, GIT_COMMIT


def _to_int(raw: str | None, default: int, minimum: int = 1, maximum: int = 200) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _is_loopback_address(raw: str | None) -> bool:
    if not raw:
        return False
    host = raw.strip().lower()
    return host in {"127.0.0.1", "::1", "localhost"}


def _is_client_disconnect_error(exc: OSError) -> bool:
    """Return True for expected socket write failures after client-side aborts."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    win_error = getattr(exc, "winerror", None)
    return win_error in {10053, 10054}


def make_handler(
    started_ok: Callable[[], bool],
    repo_supplier: Callable[[], CatalogRepository | None],
    scan_run: Callable[[bool], dict],
    rescan_start: Callable[[bool], dict],
    rescan_status: Callable[[], dict],
    sync_status: Callable[[], dict],
    sync_metrics: Callable[[], dict],
    sync_start: Callable[[], dict],
    sync_stop: Callable[[], dict],
    platform_info: Callable[[], dict],
    available_storage_locations: Callable[[], list[dict]],
    winetricks_packages_read: Callable[[], dict],
    install_prerequisites_bundle: Callable[[], dict],
    install_wine_common_dependencies: Callable[[], dict],
    game_install_proton_common_dependencies: Callable[[str], dict],
    game_manage_prefix_wine_dependencies: Callable[[str, dict], dict],
    game_save_metadata: Callable[[str, dict], dict],
    game_local_settings_update: Callable[[dict], dict],
    set_resilio_network_mode: Callable[[dict], dict],
    set_local_network_private: Callable[[dict], dict],
    storage_validate: Callable[[str], dict],
    open_folder: Callable[[str], dict],
    install_script_info: Callable[[str], dict],
    game_action: Callable[[str, str, str], dict],
    game_launch_settings_read: Callable[[str], dict],
    game_launch_settings_update: Callable[[str, dict], dict],
    game_sync_status: Callable[[str], dict],
    game_sync_start: Callable[[str], dict],
    game_sync_stop: Callable[[str], dict],
    game_video_path: Callable[[str], str],
    game_image_path: Callable[[str], str],
    settings_read: Callable[[], dict],
    launcher_site_read: Callable[[], dict],
    disabled_game_ids_read: Callable[[], list[str]],
    is_game_disabled: Callable[[str], bool],
    settings_update: Callable[[dict], dict],
    extra_sync_items_read: Callable[[], dict],
    extra_sync_item_upsert: Callable[[dict], dict],
    extra_sync_item_toggle: Callable[[dict], dict],
    extra_sync_item_refresh_images: Callable[[dict], dict],
    extra_sync_item_delete: Callable[[dict], dict],
    extra_sync_item_delete_data: Callable[[dict], dict],
    extra_sync_item_wipe: Callable[[dict], dict],
    app_log_level_update: Callable[[dict], dict],
    logs_read: Callable[[int], dict],
    debug_logs_read: Callable[[int], dict],
    app_shutdown: Callable[[], dict],
    app_shutdown_prepare: Callable[[], dict],
    app_shutdown_apply: Callable[[str, str], dict],
    app_shutdown_status: Callable[[str], dict],
    app_shutdown_finalize: Callable[[str], dict],
    app_update_check: Callable[[], dict],
    app_update_rollback: Callable[[], dict],
    app_feature_flags_read: Callable[[], dict],
    sync_metrics_for_game: Callable[[str], dict] | None = None,
    sync_providers_read: Callable[[], list[dict]] | None = None,
    sync_provider_action: Callable[[str, str], dict] | None = None,
    lan_game_inventory_read: Callable[..., dict] | None = None,
    lan_game_share_update: Callable[[dict], dict] | None = None,
    game_visibility_update: Callable[[str, bool], dict] | None = None,
    lan_server_game_inventory_read: Callable[[], dict] | None = None,
    lan_server_settings_update: Callable[[dict], dict] | None = None,
    lan_server_settings_read: Callable[[], dict] | None = None,
    lan_disabled_game_ids_read: Callable[[], list[str]] | None = None,
    ouisync_repository_inventory_read: Callable[[str, str, str], dict] | None = None,
    ouisync_debug_action: Callable[[str], dict] | None = None,
    ouisync_repository_settings_update: Callable[[str, dict], dict] | None = None,
    ouisync_repository_action: Callable[[str, str], dict] | None = None,
    ouisync_repository_entry_copy: Callable[[str, str, str], dict] | None = None,
    extra_sync_items_import_bootstrap: Callable[[dict], dict] | None = None,
    ouisync_peer_action: Callable[[str, str], dict] | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Create request handler bound to runtime callbacks."""

    class ApiHandler(BaseHTTPRequestHandler):
        def _reject_non_local_client(self) -> bool:
            # Defense-in-depth: only local clients may access launcher control APIs.
            client_host = self.client_address[0] if self.client_address else ""
            if _is_loopback_address(client_host):
                return False
            self._send_json(
                {"error": "forbidden", "message": "local_requests_only"},
                status=HTTPStatus.FORBIDDEN,
            )
            return True

        def _frontend_roots(self) -> list[Path]:
            cwd = Path.cwd()
            return [
                cwd / "app" / "src" / "frontend",
                cwd / "src" / "frontend",
            ]

        def _static_file_for_route(self, route: str) -> Path | None:
            normalized = route or "/"

            if normalized == "/":
                relative = Path("app/index.html")
            else:
                relative = Path(normalized.lstrip("/"))

            for root in self._frontend_roots():
                candidate = (root / relative).resolve(strict=False)
                try:
                    candidate.relative_to(root.resolve(strict=False))
                except ValueError:
                    continue
                if candidate.exists() and candidate.is_file():
                    return candidate
            return None

        def _send_file(self, file_path: Path) -> None:
            content = file_path.read_bytes()
            content_type = (
                mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except OSError as exc:
                if not _is_client_disconnect_error(exc):
                    raise

        def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except OSError as exc:
                if not _is_client_disconnect_error(exc):
                    raise

        def do_GET(self) -> None:  # noqa: N802 - stdlib API signature
            if self._reject_non_local_client():
                return
            parsed = urlparse(self.path)
            route = parsed.path
            params = parse_qs(parsed.query)

            static_file = self._static_file_for_route(route)
            if static_file is not None:
                self._send_file(static_file)
                return

            if route == "/health":
                self._send_json(
                    {
                        "status": "ok" if started_ok() else "degraded",
                        "service": APP_NAME,
                    }
                )
                return

            if route == "/version":
                self._send_json(
                    {
                        "service": APP_NAME,
                        "version": APP_VERSION,
                        "build_date": BUILD_DATE,
                        "git_commit": GIT_COMMIT,
                    }
                )
                return

            if route == "/catalog/rescan":
                force = params.get("force", ["false"])[0].lower() == "true"
                self._send_json(rescan_start(force))
                return

            if route == "/catalog/scan":
                force = params.get("force", ["false"])[0].lower() == "true"
                self._send_json({"scan": scan_run(force)})
                return

            if route == "/catalog/rescan-status":
                self._send_json({"resync": rescan_status()})
                return

            if route == "/sync/status":
                self._send_json({"sync": sync_status()})
                return

            if route == "/sync/speed":
                game_id = params.get("game_id", [""])[0]
                if game_id and sync_metrics_for_game is not None:
                    self._send_json({"speed": sync_metrics_for_game(game_id)})
                else:
                    self._send_json({"speed": sync_metrics()})
                return

            if route == "/sync/providers":
                providers = sync_providers_read() if sync_providers_read is not None else []
                self._send_json({"providers": providers})
                return

            if route == "/sync/providers/ouisync/repositories":
                if ouisync_repository_inventory_read is None:
                    self._send_json(
                        {
                            "available": False,
                            "error": "sync_provider_unavailable",
                            "repositories": [],
                            "catalog": [],
                            "network": {},
                        }
                    )
                    return
                self._send_json(
                    ouisync_repository_inventory_read(
                        params.get("info_hash", [""])[0],
                        params.get("path", ["/"])[0],
                        params.get("locale", ["en"])[0],
                    )
                )
                return

            if route == "/sync/providers/ouisync/debug":
                mode = params.get("mode", [""])[0]
                if ouisync_debug_action is None or mode not in {"health", "ng-provider"}:
                    self._send_json({"error": "sync_provider_unavailable"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._send_json({"result": ouisync_debug_action(mode)})
                return

            if route.startswith("/sync/providers/"):
                route_tail = route.replace("/sync/providers/", "", 1)
                provider_type, separator, action = route_tail.partition("/")
                if separator and action in {"start", "stop", "restart"}:
                    if sync_provider_action is None:
                        self._send_json(
                            {
                                "error": "service_unavailable",
                                "message": "sync_provider_unavailable",
                            },
                            status=HTTPStatus.SERVICE_UNAVAILABLE,
                        )
                        return
                    self._send_json(
                        {
                            "sync": sync_provider_action(provider_type, action),
                        }
                    )
                    return
            if route == "/lan/games" and lan_game_inventory_read is not None:
                preview_server = params.get("role", [""])[0].strip().lower() == "server"
                inventory_read = (
                    lan_server_game_inventory_read
                    if preview_server and lan_server_game_inventory_read
                    else lan_game_inventory_read
                )
                self._send_json({"lan": inventory_read()})
                return

            if route == "/sync/start":
                self._send_json({"sync": sync_start()})
                return

            if route == "/sync/stop":
                self._send_json({"sync": sync_stop()})
                return

            if route == "/platform/info":
                self._send_json({"platform": platform_info()})
                return

            if route == "/platform/storage-locations":
                self._send_json({"storage_locations": available_storage_locations()})
                return
            if route == "/platform/winetricks-packages":
                self._send_json({"winetricks": winetricks_packages_read()})
                return

            if route == "/platform/install-prerequisites":
                self._send_json({"result": install_prerequisites_bundle()})
                return
            if route == "/platform/install-wine-common-deps":
                self._send_json({"result": install_wine_common_dependencies()})
                return

            if route == "/platform/validate-storage":
                target_path = params.get("path", [""])[0]
                self._send_json({"storage": storage_validate(target_path)})
                return

            if route == "/platform/open-folder":
                target_path = params.get("path", [""])[0]
                self._send_json({"action": open_folder(target_path)})
                return
            if route == "/settings":
                self._send_json({"settings": settings_read()})
                return
            if route == "/settings/lan-server":
                result = (
                    lan_server_settings_read()
                    if lan_server_settings_read is not None
                    else {"ok": False, "message": "lan_server_settings_unavailable"}
                )
                self._send_json({"result": result})
                return
            if route == "/launcher-site":
                self._send_json({"launcher_site": launcher_site_read()})
                return
            if route == "/settings/extra-sync-items":
                self._send_json(extra_sync_items_read())
                return
            if route == "/logs":
                limit = _to_int(params.get("limit", [None])[0], 200, 1, 2000)
                self._send_json({"logs": logs_read(limit)})
                return
            if route == "/debug/log":
                limit = _to_int(params.get("limit", [None])[0], 200, 1, 2000)
                self._send_json({"logs": debug_logs_read(limit)})
                return
            if route == "/app/shutdown":
                self._send_json({"shutdown": app_shutdown()})
                return
            if route == "/app/shutdown/prepare":
                self._send_json({"shutdown": app_shutdown_prepare()})
                return
            if route == "/app/shutdown/apply":
                session_id = params.get("session_id", [""])[0]
                action = params.get("action", ["start"])[0]
                self._send_json({"shutdown": app_shutdown_apply(session_id, action)})
                return
            if route == "/app/shutdown/status":
                session_id = params.get("session_id", [""])[0]
                self._send_json({"shutdown": app_shutdown_status(session_id)})
                return
            if route == "/app/shutdown/finalize":
                session_id = params.get("session_id", [""])[0]
                self._send_json({"shutdown": app_shutdown_finalize(session_id)})
                return
            if route == "/app/update/rollback":
                self._send_json({"result": app_update_rollback()})
                return
            if route == "/app/update/check":
                self._send_json({"update": app_update_check()})
                return
            if route == "/app/flags":
                self._send_json({"flags": app_feature_flags_read()})
                return

            if route.startswith("/media/video/"):
                game_id = route.replace("/media/video/", "", 1)
                path = Path(game_video_path(game_id))
                if path.exists() and path.is_file():
                    self._send_file(path)
                    return
                self._send_json(
                    {"error": "not_found", "message": "Video not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            if route.startswith("/media/image/"):
                game_id = route.replace("/media/image/", "", 1)
                path = Path(game_image_path(game_id))
                if path.exists() and path.is_file():
                    self._send_file(path)
                    return
                self._send_json(
                    {"error": "not_found", "message": "Image not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return

            repo = repo_supplier()
            if repo is None:
                self._send_json(
                    {
                        "error": "service_unavailable",
                        "message": "Catalog repository unavailable",
                    },
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return

            if route == "/catalog/games":
                locale = params.get("locale", ["en"])[0].lower()
                q = params.get("q", [""])[0]
                genre_raw = params.get("genre_id", [None])[0]
                installed = params.get("installed", [None])[0]
                sort = params.get("sort", ["title"])[0]
                order = params.get("order", ["asc"])[0]
                page = _to_int(params.get("page", [None])[0], 1, 1, 100000)
                page_size_raw = params.get("page_size", [None])[0]
                page_size = (
                    0 if page_size_raw == "0" else _to_int(page_size_raw, 25, 1, 1000)
                )
                visibility = str(params.get("visibility", ["visible"])[0] or "visible").strip().lower()
                genre_id = (
                    None
                    if genre_raw in (None, "")
                    else _to_int(genre_raw, 0, 0, 100000)
                )

                payload = repo.list_games(
                    ListQuery(
                        locale=locale if locale in {"en", "de", "fr"} else "en",
                        q=q,
                        genre_id=genre_id,
                        installed=installed,
                        sort=sort,
                        order=order,
                        page=page,
                        page_size=page_size,
                        excluded_ids=tuple(disabled_game_ids_read()),
                        disabled_ids=tuple(
                            lan_disabled_game_ids_read()
                            if lan_disabled_game_ids_read is not None
                            else ()
                        ),
                        visibility=visibility if visibility == "hidden" else "visible",
                    )
                )
                self._send_json(payload)
                return

            if route == "/catalog/genres":
                locale = params.get("locale", ["en"])[0].lower()
                payload = {
                    "items": repo.list_genres(
                        locale=locale if locale in {"en", "de"} else "en"
                    )
                }
                self._send_json(payload)
                return

            if route.startswith("/catalog/games/"):
                game_id = route.replace("/catalog/games/", "", 1)
                if game_id.endswith("/install-script"):
                    base_id = game_id.replace("/install-script", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"install_script": install_script_info(base_id)})
                    return
                if game_id.endswith("/status-local"):
                    base_id = game_id.replace("/status-local", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_action(base_id, "status", "")})
                    return
                if game_id.endswith("/install"):
                    base_id = game_id.replace("/install", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_action(base_id, "install", "")})
                    return
                if game_id.endswith("/update"):
                    base_id = game_id.replace("/update", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_action(base_id, "update", "")})
                    return
                if game_id.endswith("/uninstall"):
                    base_id = game_id.replace("/uninstall", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_action(base_id, "uninstall", "")})
                    return
                if game_id.endswith("/delete"):
                    base_id = game_id.replace("/delete", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_action(base_id, "delete", "")})
                    return
                if game_id.endswith("/start-server"):
                    base_id = game_id.replace("/start-server", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    locale = str(params.get("locale", [""])[0] or "").strip().lower()
                    self._send_json(
                        {"result": game_action(base_id, "start-server", locale)}
                    )
                    return
                if game_id.endswith("/launch-settings"):
                    base_id = game_id.replace("/launch-settings", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_launch_settings_read(base_id)})
                    return
                if game_id.endswith("/sync-status"):
                    base_id = game_id.replace("/sync-status", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_sync_status(base_id)})
                    return
                if game_id.endswith("/sync-start"):
                    base_id = game_id.replace("/sync-start", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_sync_start(base_id)})
                    return
                if game_id.endswith("/sync-stop"):
                    base_id = game_id.replace("/sync-stop", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json({"result": game_sync_stop(base_id)})
                    return
                if game_id.endswith("/sync-remove"):
                    base_id = game_id.replace("/sync-remove", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json(
                        {"result": game_action(base_id, "remove-sync-data", "")}
                    )
                    return
                if game_id.endswith("/install-proton-common-deps"):
                    base_id = game_id.replace("/install-proton-common-deps", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    self._send_json(
                        {"result": game_install_proton_common_dependencies(base_id)}
                    )
                    return
                if game_id.endswith("/start"):
                    base_id = game_id.replace("/start", "")
                    if is_game_disabled(base_id):
                        self._send_json(
                            {"error": "not_found", "message": "Game not found"},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    locale = str(params.get("locale", [""])[0] or "").strip().lower()
                    self._send_json({"result": game_action(base_id, "start", locale)})
                    return
                if is_game_disabled(game_id):
                    self._send_json(
                        {"error": "not_found", "message": "Game not found"},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                locale = params.get("locale", ["en"])[0].lower()
                payload = repo.get_game(
                    game_id, locale=locale if locale in {"en", "de", "fr"} else "en"
                )
                if payload is None:
                    self._send_json(
                        {"error": "not_found", "message": "Game not found"},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                self._send_json(payload)
                return

            self._send_json(
                {"error": "not_found", "message": "Route not found"},
                status=HTTPStatus.NOT_FOUND,
            )

        def do_POST(self) -> None:  # noqa: N802 - stdlib API signature
            if self._reject_non_local_client():
                return
            parsed = urlparse(self.path)
            route = parsed.path
            valid_routes = {
                "/settings",
                "/settings/lan-server",
                "/settings/extra-sync-items",
                "/settings/extra-sync-items/import-bootstrap",
                "/settings/extra-sync-items/toggle-sync",
                "/settings/extra-sync-items/refresh-images",
                "/settings/extra-sync-items/delete-item",
                "/settings/extra-sync-items/delete-data",
                "/settings/extra-sync-items/wipe",
                "/catalog/games/local-settings",
                "/app/log-level",
                "/platform/resilio-network-mode",
                "/platform/set-local-network-private",
                "/sync/providers/ouisync/debug",
                "/sync/providers/ouisync/settings",
                "/sync/providers/ouisync/repository-action",
                "/sync/providers/ouisync/copy-entry",
                "/sync/providers/ouisync/peers",
                "/lan/games",
            }
            is_game_launch_settings_route = route.startswith(
                "/catalog/games/"
            ) and route.endswith("/launch-settings")
            is_game_prefix_deps_route = route.startswith(
                "/catalog/games/"
            ) and route.endswith("/prefix-wine-dependencies")
            is_game_metadata_save_route = route.startswith(
                "/catalog/games/"
            ) and route.endswith("/metadata")
            is_game_visibility_route = route.startswith(
                "/catalog/games/"
            ) and route.endswith("/visibility")
            is_local_game_settings_route = route == "/catalog/games/local-settings"
            if (
                route not in valid_routes
                and not is_game_launch_settings_route
                and not is_game_prefix_deps_route
                and not is_game_metadata_save_route
                and not is_game_visibility_route
                and not is_local_game_settings_route
            ):
                self._send_json(
                    {"error": "not_found", "message": "Route not found"},
                    status=HTTPStatus.NOT_FOUND,
                )
                return

            length_raw = self.headers.get("Content-Length", "0")
            try:
                length = max(0, int(length_raw))
            except ValueError:
                self._send_json(
                    {"error": "invalid_request", "message": "Invalid content length"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self._send_json(
                    {"error": "invalid_json", "message": "Malformed JSON body"},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            body = payload if isinstance(payload, dict) else {}
            if is_game_launch_settings_route:
                game_id = route.replace("/catalog/games/", "", 1).replace(
                    "/launch-settings", "", 1
                )
                if is_game_disabled(game_id):
                    self._send_json(
                        {"error": "not_found", "message": "Game not found"},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                result = game_launch_settings_update(game_id, body)
            elif is_local_game_settings_route:
                result = game_local_settings_update(body)
            elif is_game_prefix_deps_route:
                game_id = route.replace("/catalog/games/", "", 1).replace(
                    "/prefix-wine-dependencies", "", 1
                )
                if is_game_disabled(game_id):
                    self._send_json(
                        {"error": "not_found", "message": "Game not found"},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                result = game_manage_prefix_wine_dependencies(game_id, body)
            elif is_game_metadata_save_route:
                game_id = route.replace("/catalog/games/", "", 1).replace(
                    "/metadata", "", 1
                )
                if is_game_disabled(game_id):
                    self._send_json(
                        {"error": "not_found", "message": "Game not found"},
                        status=HTTPStatus.NOT_FOUND,
                    )
                    return
                result = game_save_metadata(game_id, body)
            elif is_game_visibility_route:
                game_id = route.replace("/catalog/games/", "", 1).replace(
                    "/visibility", "", 1
                )
                if game_visibility_update is None:
                    result = {"ok": False, "message": "visibility_unavailable"}
                else:
                    result = game_visibility_update(
                        game_id, bool(body.get("hidden", False))
                    )
            elif route == "/settings":
                result = settings_update(body)
            elif route == "/settings/lan-server":
                result = (
                    lan_server_settings_update(body)
                    if lan_server_settings_update is not None
                    else {"ok": False, "message": "lan_server_settings_unavailable"}
                )
            elif route == "/app/log-level":
                result = app_log_level_update(body)
            elif route == "/settings/extra-sync-items":
                result = extra_sync_item_upsert(body)
            elif route == "/settings/extra-sync-items/import-bootstrap":
                result = (
                    extra_sync_items_import_bootstrap(body)
                    if extra_sync_items_import_bootstrap is not None
                    else {"ok": False, "message": "provider_import_unavailable"}
                )
            elif route == "/settings/extra-sync-items/toggle-sync":
                result = extra_sync_item_toggle(body)
            elif route == "/settings/extra-sync-items/refresh-images":
                result = extra_sync_item_refresh_images(body)
            elif route == "/settings/extra-sync-items/delete-item":
                result = extra_sync_item_delete(body)
            elif route == "/settings/extra-sync-items/delete-data":
                result = extra_sync_item_delete_data(body)
            elif route == "/platform/resilio-network-mode":
                result = set_resilio_network_mode(body)
            elif route == "/platform/set-local-network-private":
                result = set_local_network_private(body)
            elif route == "/sync/providers/ouisync/debug":
                result = (
                    ouisync_debug_action(str(body.get("action", "")))
                    if ouisync_debug_action is not None
                    else {"ok": False, "message": "sync_provider_unavailable"}
                )
            elif route == "/sync/providers/ouisync/settings":
                settings = body.get("settings")
                result = (
                    ouisync_repository_settings_update(
                        str(body.get("info_hash", "")),
                        settings if isinstance(settings, dict) else {},
                    )
                    if ouisync_repository_settings_update is not None
                    else {"ok": False, "message": "sync_provider_unavailable"}
                )
            elif route == "/sync/providers/ouisync/repository-action":
                result = (
                    ouisync_repository_action(
                        str(body.get("action", "")), str(body.get("info_hash", ""))
                    )
                    if ouisync_repository_action is not None
                    else {"ok": False, "message": "sync_provider_unavailable"}
                )
            elif route == "/sync/providers/ouisync/copy-entry":
                result = (
                    ouisync_repository_entry_copy(
                        str(body.get("info_hash", "")),
                        str(body.get("path", "")),
                        str(body.get("destination_directory", ".")),
                    )
                    if ouisync_repository_entry_copy is not None
                    else {"ok": False, "message": "sync_provider_unavailable"}
                )
            elif route == "/sync/providers/ouisync/peers":
                result = (
                    ouisync_peer_action(
                        str(body.get("action", "")), str(body.get("address", ""))
                    )
                    if ouisync_peer_action is not None
                    else {"ok": False, "message": "sync_provider_unavailable"}
                )
            elif route == "/lan/games":
                if lan_game_share_update is None:
                    result = {
                        "ok": False,
                        "message": "lan_game_management_unavailable",
                    }
                else:
                    result = lan_game_share_update(body)
            else:
                result = extra_sync_item_wipe(body)
            status = (
                HTTPStatus.OK if result.get("ok", False) else HTTPStatus.BAD_REQUEST
            )
            self._send_json({"result": result}, status=status)

        def do_PUT(self) -> None:  # noqa: N802 - stdlib API signature
            if self._reject_non_local_client():
                return
            self._send_json(
                {"error": "method_not_allowed", "message": "Route not found"},
                status=HTTPStatus.METHOD_NOT_ALLOWED,
            )

        def do_DELETE(self) -> None:  # noqa: N802 - stdlib API signature
            if self._reject_non_local_client():
                return
            self._send_json(
                {"error": "method_not_allowed", "message": "Route not found"},
                status=HTTPStatus.METHOD_NOT_ALLOWED,
            )

        def do_PATCH(self) -> None:  # noqa: N802 - stdlib API signature
            if self._reject_non_local_client():
                return
            self._send_json(
                {"error": "method_not_allowed", "message": "Route not found"},
                status=HTTPStatus.METHOD_NOT_ALLOWED,
            )

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib API signature
            if self._reject_non_local_client():
                return
            self._send_json(
                {"error": "method_not_allowed", "message": "Route not found"},
                status=HTTPStatus.METHOD_NOT_ALLOWED,
            )

        def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib API signature
            if self._reject_non_local_client():
                return
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Allow", "GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS")
            self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            # Suppress default per-request access logs; launcher logs focus on actionable events.
            return

    return ApiHandler


def create_server(
    host: str,
    port: int,
    started_ok: Callable[[], bool],
    repo_supplier: Callable[[], CatalogRepository | None],
    scan_run: Callable[[bool], dict],
    rescan_start: Callable[[bool], dict],
    rescan_status: Callable[[], dict],
    sync_status: Callable[[], dict],
    sync_metrics: Callable[[], dict],
    sync_start: Callable[[], dict],
    sync_stop: Callable[[], dict],
    platform_info: Callable[[], dict],
    available_storage_locations: Callable[[], list[dict]],
    winetricks_packages_read: Callable[[], dict],
    install_prerequisites_bundle: Callable[[], dict],
    install_wine_common_dependencies: Callable[[], dict],
    game_install_proton_common_dependencies: Callable[[str], dict],
    game_manage_prefix_wine_dependencies: Callable[[str, dict], dict],
    game_save_metadata: Callable[[str, dict], dict],
    game_local_settings_update: Callable[[dict], dict],
    set_resilio_network_mode: Callable[[dict], dict],
    set_local_network_private: Callable[[dict], dict],
    storage_validate: Callable[[str], dict],
    open_folder: Callable[[str], dict],
    install_script_info: Callable[[str], dict],
    game_action: Callable[[str, str, str], dict],
    game_launch_settings_read: Callable[[str], dict],
    game_launch_settings_update: Callable[[str, dict], dict],
    game_sync_status: Callable[[str], dict],
    game_sync_start: Callable[[str], dict],
    game_sync_stop: Callable[[str], dict],
    game_video_path: Callable[[str], str],
    game_image_path: Callable[[str], str],
    settings_read: Callable[[], dict],
    launcher_site_read: Callable[[], dict],
    disabled_game_ids_read: Callable[[], list[str]],
    is_game_disabled: Callable[[str], bool],
    settings_update: Callable[[dict], dict],
    extra_sync_items_read: Callable[[], dict],
    extra_sync_item_upsert: Callable[[dict], dict],
    extra_sync_item_toggle: Callable[[dict], dict],
    extra_sync_item_refresh_images: Callable[[dict], dict],
    extra_sync_item_delete: Callable[[dict], dict],
    extra_sync_item_delete_data: Callable[[dict], dict],
    extra_sync_item_wipe: Callable[[dict], dict],
    app_log_level_update: Callable[[dict], dict],
    logs_read: Callable[[int], dict],
    debug_logs_read: Callable[[int], dict],
    app_shutdown: Callable[[], dict],
    app_shutdown_prepare: Callable[[], dict],
    app_shutdown_apply: Callable[[str, str], dict],
    app_shutdown_status: Callable[[str], dict],
    app_shutdown_finalize: Callable[[str], dict],
    app_update_check: Callable[[], dict],
    app_update_rollback: Callable[[], dict],
    app_feature_flags_read: Callable[[], dict],
    sync_metrics_for_game: Callable[[str], dict] | None = None,
    sync_providers_read: Callable[[], list[dict]] | None = None,
    sync_provider_action: Callable[[str, str], dict] | None = None,
    lan_game_inventory_read: Callable[..., dict] | None = None,
    lan_game_share_update: Callable[[dict], dict] | None = None,
    game_visibility_update: Callable[[str, bool], dict] | None = None,
    lan_server_game_inventory_read: Callable[[], dict] | None = None,
    lan_server_settings_update: Callable[[dict], dict] | None = None,
    lan_server_settings_read: Callable[[], dict] | None = None,
    lan_disabled_game_ids_read: Callable[[], list[str]] | None = None,
    ouisync_repository_inventory_read: Callable[[str, str, str], dict] | None = None,
    ouisync_debug_action: Callable[[str], dict] | None = None,
    ouisync_repository_settings_update: Callable[[str, dict], dict] | None = None,
    ouisync_repository_action: Callable[[str, str], dict] | None = None,
    ouisync_repository_entry_copy: Callable[[str, str, str], dict] | None = None,
    extra_sync_items_import_bootstrap: Callable[[dict], dict] | None = None,
    ouisync_peer_action: Callable[[str, str], dict] | None = None,
) -> ThreadingHTTPServer:
    handler = make_handler(
        started_ok,
        repo_supplier,
        scan_run,
        rescan_start,
        rescan_status,
        sync_status,
        sync_metrics,
        sync_start,
        sync_stop,
        platform_info,
        available_storage_locations,
        winetricks_packages_read,
        install_prerequisites_bundle,
        install_wine_common_dependencies,
        game_install_proton_common_dependencies,
        game_manage_prefix_wine_dependencies,
        game_save_metadata,
        game_local_settings_update,
        set_resilio_network_mode,
        set_local_network_private,
        storage_validate,
        open_folder,
        install_script_info,
        game_action,
        game_launch_settings_read,
        game_launch_settings_update,
        game_sync_status,
        game_sync_start,
        game_sync_stop,
        game_video_path,
        game_image_path,
        settings_read,
        launcher_site_read,
        disabled_game_ids_read,
        is_game_disabled,
        settings_update,
        extra_sync_items_read,
        extra_sync_item_upsert,
        extra_sync_item_toggle,
        extra_sync_item_refresh_images,
        extra_sync_item_delete,
        extra_sync_item_delete_data,
        extra_sync_item_wipe,
        app_log_level_update,
        logs_read,
        debug_logs_read,
        app_shutdown,
        app_shutdown_prepare,
        app_shutdown_apply,
        app_shutdown_status,
        app_shutdown_finalize,
        app_update_check,
        app_update_rollback,
        app_feature_flags_read,
        sync_metrics_for_game,
        sync_providers_read,
        sync_provider_action,
        lan_game_inventory_read,
        lan_game_share_update,
        game_visibility_update,
        lan_server_game_inventory_read,
        lan_server_settings_update,
        lan_server_settings_read,
        lan_disabled_game_ids_read,
        ouisync_repository_inventory_read,
        ouisync_debug_action,
        ouisync_repository_settings_update,
        ouisync_repository_action,
        ouisync_repository_entry_copy,
        extra_sync_items_import_bootstrap,
        ouisync_peer_action,
    )
    return ThreadingHTTPServer((host, port), handler)
