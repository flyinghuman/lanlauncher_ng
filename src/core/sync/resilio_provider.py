"""Resilio-compatible sync provider.

This provider wraps the configured sync binary and queries the local API
endpoint for transfer metrics. It includes retry logic and stale PID cleanup
to avoid common startup reliability issues after unclean shutdowns.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from src.core.sync.provider import SyncMetrics, SyncStatus

try:
    import resource
except ImportError:  # pragma: no cover - module is unavailable on Windows.
    resource = None  # type: ignore[assignment]


def parse_json_with_comments(raw: str) -> dict:
    """Parse Resilio's config.json, which may carry `//` comments."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        lines = []
        for line in raw.splitlines():
            if line.strip().startswith("//"):
                continue
            if "//" in line:
                line = line.split("//", 1)[0]
            lines.append(line)
        parsed = json.loads("\n".join(lines) or "{}")
    return parsed if isinstance(parsed, dict) else {}


def persist_runtime_paths(config_path: Path, runtime_root: Path) -> bool:
    """Pin storage_path/pid_file under runtime_root and create their directories.

    Shared by provider startup and the application watchdog so both apply the
    same rules. Stale absolute paths (moved installs, dev checkouts) are always
    replaced. Returns True when the config file was rewritten. Raises OSError or
    ValueError on unreadable/invalid configs.
    """
    config_path = config_path.expanduser().resolve(strict=False)
    sync_root = (runtime_root / "data" / "sync").resolve(strict=False)
    storage_abs = str(sync_root)
    pid_abs = str(sync_root / "rslsync.pid")
    raw = config_path.read_text(encoding="utf-8", errors="replace") if config_path.exists() else "{}"
    data = parse_json_with_comments(raw)
    changed = False
    # Resilio rejects unknown top-level keys, so strip launcher-internal metadata.
    if "lanlauncher_library_path" in data:
        del data["lanlauncher_library_path"]
        changed = True
    for key, value in (("storage_path", storage_abs), ("pid_file", pid_abs)):
        if data.get(key) != value:
            data[key] = value
            changed = True
    sync_root.mkdir(parents=True, exist_ok=True)
    if changed:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = config_path.with_name(f".{config_path.name}.{os.getpid()}.tmp")
        try:
            temporary_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            # Atomic replace: Resilio may read the file concurrently.
            os.replace(temporary_path, config_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return changed


@dataclass
class _ProcessState:
    process: subprocess.Popen | None = None
    log_handle: object | None = None
    log_lock: object | None = None
    launch_started_at: float = 0.0
    last_error: str = ""


def _pid_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _parse_json_or_jsonp(payload: str) -> dict | list:
    text = payload.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)

    # Resilio API can reply as JSONP callback(payload).
    first = text.find("(")
    last = text.rfind(")")
    if first > 0 and last > first:
        return json.loads(text[first + 1 : last])

    raise ValueError("Unsupported API payload format")


class ResilioSyncProvider:
    def __init__(
        self,
        binary_path: str,
        config_path: str,
        pid_path: str,
        log_path: str,
        license_key_path: str,
        api_url: str,
        api_key: str,
        request_timeout_seconds: float,
        retry_count: int,
        startup_retry_seconds: float,
    ):
        self._binary_path = Path(binary_path)
        self._config_path = Path(config_path)
        self._pid_path = Path(pid_path)
        self._log_path = Path(log_path)
        self._license_key_path = Path(license_key_path)
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._timeout = request_timeout_seconds
        self._retry_count = max(1, retry_count)
        self._startup_retry_seconds = startup_retry_seconds
        self._state = _ProcessState()
        self._license_bootstrap_done = False
        self._license_activation_ok = False
        self._api_auth_header: str = ""
        self._folder_secret_cache: dict[str, str] = {}
        self._refresh_api_settings_from_config()

    def _log_api_request_debug(self, endpoint: str, url: str) -> None:
        logger = logging.getLogger(__name__)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("sync_api_request endpoint=%s url=%s", endpoint, url)

    def _log_api_response_debug(self, endpoint: str, url: str, payload: object) -> None:
        logger = logging.getLogger(__name__)
        if not logger.isEnabledFor(logging.DEBUG):
            return
        try:
            encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        except Exception:  # noqa: BLE001
            encoded = str(payload)
        logger.debug(
            "sync_api_response endpoint=%s url=%s payload=%s", endpoint, url, encoded
        )

    def _runtime_root_from_config_path(self) -> Path:
        resolved = self._config_path.expanduser().resolve(strict=False)
        parent = resolved.parent
        if parent.name.lower() == "resilio" and parent.parent.name.lower() == "config":
            return parent.parent.parent
        return parent

    def _startup_log_tail(self, limit: int = 20) -> list[str]:
        try:
            lines = self._log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        tail = lines[-max(1, min(1000, limit)) :]
        return [line for line in tail if line.strip()]

    def _startup_looks_like_existing_instance(self, tail: list[str]) -> bool:
        joined = "\n".join(tail).lower()
        return "can't lock pid file" in joined or "already running" in joined

    def _process_exit_code(self, process: subprocess.Popen | None) -> int | None:
        if process is None:
            return None
        try:
            exit_code = process.poll()
        except Exception:  # noqa: BLE001
            return None
        return exit_code if isinstance(exit_code, int) else None

    def _folders_from_payload(self, payload: object) -> list[dict]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            folders = payload.get("folders", [])
            if isinstance(folders, list):
                return [item for item in folders if isinstance(item, dict)]
        return []

    def _build_start_command(self) -> list[str]:
        exe = str(self._binary_path.expanduser().resolve(strict=False))
        if platform.system().lower().startswith("win"):
            config = str(self._config_path.expanduser().resolve(strict=False))
            return [exe, "/minimized", "/config", config]
        return [exe, "--config", str(self._config_path.expanduser().resolve(strict=False))]

    def _storage_path_from_config(self) -> str:
        # Linux installs must never fall back to Resilio's cwd-dependent `./.sync`
        # default, so derive the launcher-managed storage root even when the config
        # file is missing or does not yet carry a storage_path entry.
        def _runtime_storage_root() -> Path:
            return self._runtime_root_from_config_path()

        try:
            raw = self._config_path.read_text(encoding="utf-8", errors="replace")
            cfg = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return str((_runtime_storage_root() / "data" / "sync").resolve(strict=False))
        if not isinstance(cfg, dict):
            return str((_runtime_storage_root() / "data" / "sync").resolve(strict=False))
        storage = cfg.get("storage_path")
        if not isinstance(storage, str) or not storage.strip():
            return str((_runtime_storage_root() / "data" / "sync").resolve(strict=False))
        raw_path = Path(storage.strip())
        if raw_path.is_absolute():
            return str(raw_path)
        return str((_runtime_storage_root() / raw_path).resolve(strict=False))

    def _prepare_runtime_storage(self) -> bool:
        """Resolve Resilio's storage path for this install and create it first."""
        try:
            if not self._config_path.expanduser().is_file():
                raise FileNotFoundError(str(self._config_path))
            persist_runtime_paths(
                self._config_path, self._runtime_root_from_config_path()
            )
            return True
        except (OSError, ValueError) as exc:
            self._state.last_error = f"storage_path_prepare_failed:{exc}"
            logging.getLogger(__name__).warning(
                "sync_storage_path_prepare_failed error=%s", exc
            )
            return False

    def _build_identity_command_variants(self) -> list[list[str]]:
        exe = str(self._binary_path)
        if platform.system().lower().startswith("win"):
            variants: list[list[str]] = []
            config = self._config_path.name
            variants.append([exe, "/config", config, "/identity", "LANLauncher"])
            variants.append([exe, "/config", config, "/identity", "LauncherNG"])
            return variants

        storage = self._storage_path_from_config()
        return [[exe, "--storage", storage, "--identity", "LauncherNG"]]

    def _build_license_command_variants(self) -> list[list[str]]:
        exe = str(self._binary_path)
        key = str(self._license_key_path.resolve())
        if platform.system().lower().startswith("win"):
            variants: list[list[str]] = []
            config = self._config_path.name
            variants.append([exe, "/config", config, "/license", key])
            return variants

        storage = self._storage_path_from_config()
        return [[exe, "--storage", storage, "--license", key]]

    def _run_cli_command(
        self, cmd: list[str], timeout_seconds: float = 15.0
    ) -> tuple[bool, str]:
        logger = logging.getLogger(__name__)
        cwd: str | None = None
        if platform.system().lower().startswith("win"):
            cwd = str(self._config_path.parent.resolve())
        try:
            result = subprocess.run(  # noqa: S603 - local configured binary
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                cwd=cwd,
            )
        except OSError as exc:
            self._state.last_error = str(exc)
            logger.warning(
                "sync_cli_command_failed command=%s error=%s", " ".join(cmd), exc
            )
            return False, str(exc)
        except subprocess.TimeoutExpired:
            self._state.last_error = "sync_cli_timeout"
            logger.warning("sync_cli_command_timeout command=%s", " ".join(cmd))
            return False, "timeout"

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or f"exit={result.returncode}"
            self._state.last_error = f"sync_cli_failed:{detail}"
            logger.warning(
                "sync_cli_command_nonzero command=%s returncode=%s detail=%s",
                " ".join(cmd),
                result.returncode,
                detail,
            )
            if stdout:
                logger.warning(
                    "sync_cli_stdout command=%s output=%s", " ".join(cmd), stdout
                )
            if stderr:
                logger.warning(
                    "sync_cli_stderr command=%s output=%s", " ".join(cmd), stderr
                )
            return False, detail
        return True, ""

    def _run_cli_variants(self, variants: list[list[str]], log_key: str) -> bool:
        logger = logging.getLogger(__name__)
        last_detail = ""
        for cmd in variants:
            logger.info("%s=%s", log_key, " ".join(cmd))
            ok, detail = self._run_cli_command(cmd)
            if ok:
                return True
            last_detail = detail
        if last_detail:
            self._state.last_error = f"sync_cli_failed:{last_detail}"
        return False

    def _ensure_identity_and_license(self) -> bool:
        if self._license_bootstrap_done:
            return self._license_activation_ok
        logger = logging.getLogger(__name__)
        if not self._license_key_path.exists():
            logger.warning("sync_license_key_missing path=%s", self._license_key_path)
            self._license_bootstrap_done = True
            self._license_activation_ok = False
            self._state.last_error = "sync_license_key_missing"
            return False

        identity_ok = self._run_cli_variants(
            self._build_identity_command_variants(), "sync_identity_command"
        )
        license_ok = self._run_cli_variants(
            self._build_license_command_variants(), "sync_license_command"
        )
        self._license_activation_ok = identity_ok and license_ok
        if not self._license_activation_ok:
            logger.warning(
                "sync_license_activation_failed identity_ok=%s license_ok=%s",
                identity_ok,
                license_ok,
            )
            self._state.last_error = "sync_license_activation_failed"
        self._license_bootstrap_done = True
        return self._license_activation_ok

    def _pid_file_paths(self) -> list[Path]:
        paths = [self._pid_path]
        storage_pid = Path(self._storage_path_from_config()) / "sync.pid"
        if storage_pid not in paths:
            paths.append(storage_pid)
        return paths

    def _read_pid(self, path: Path | None = None) -> int | None:
        pid_path = path or self._pid_path
        if not pid_path.exists():
            return None
        try:
            return int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def _cleanup_stale_pid(self) -> None:
        for pid_path in self._pid_file_paths():
            pid = self._read_pid(pid_path)
            if pid is None:
                continue
            if not self._pid_matches_configured_process(pid):
                try:
                    pid_path.unlink(missing_ok=True)
                except OSError:
                    # Keep startup resilient if stale pid files cannot be deleted.
                    pass

    def _pid_matches_configured_process(self, pid: int) -> bool:
        if not _pid_running(pid):
            return False
        if platform.system().lower() != "linux":
            return True
        argv = self._linux_process_argv(pid)
        return self._argv_matches_configured_process(argv)

    def _request_api(self, method: str) -> dict:
        params = {"method": method, "format": "json"}
        if self._api_key:
            params["api_key"] = self._api_key
        url = self._api_url_for_params(params)
        self._log_api_request_debug(method, url)

        last_error = None
        for _ in range(self._retry_count):
            try:
                request = Request(url)
                if self._api_auth_header:
                    request.add_header("Authorization", self._api_auth_header)
                with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 local endpoint
                    payload = response.read().decode("utf-8")
                try:
                    parsed = _parse_json_or_jsonp(payload)
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).debug(
                        "sync_api_parse_error endpoint=%s url=%s error=%s raw=%s",
                        method,
                        url,
                        exc,
                        payload,
                    )
                    raise
                self._log_api_response_debug(method, url, parsed)
                return parsed
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logging.getLogger(__name__).debug(
                    "sync_api_error endpoint=%s url=%s error=%s", method, url, exc
                )
                time.sleep(0.1)

        raise RuntimeError(last_error or "sync_api_request_failed")

    def _request_api_with_params(
        self, method: str, extra_params: dict[str, object], raw_query: bool = False
    ) -> dict:
        # Keep mutating API calls aligned with legacy btsync usage:
        # old launcher scripts did not include format=json for add/set calls.
        params: dict[str, object] = {"method": method, **extra_params}
        if self._api_key:
            params["api_key"] = self._api_key
        url = self._api_url_for_params(params, raw_query=raw_query)
        self._log_api_request_debug(method, url)

        last_error = None
        for _ in range(self._retry_count):
            try:
                request = Request(url)
                if self._api_auth_header:
                    request.add_header("Authorization", self._api_auth_header)
                with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 local endpoint
                    payload = response.read().decode("utf-8")
                try:
                    parsed = _parse_json_or_jsonp(payload)
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).debug(
                        "sync_api_parse_error endpoint=%s url=%s error=%s raw=%s",
                        method,
                        url,
                        exc,
                        payload,
                    )
                    raise
                self._log_api_response_debug(method, url, parsed)
                return parsed
            except HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                except Exception:  # noqa: BLE001
                    detail = ""
                last_error = f"HTTP {exc.code}: {detail or exc.reason or 'ERROR'}"
                logging.getLogger(__name__).debug(
                    "sync_api_http_error endpoint=%s url=%s error=%s",
                    method,
                    url,
                    last_error,
                )
                time.sleep(0.1)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logging.getLogger(__name__).debug(
                    "sync_api_error endpoint=%s url=%s error=%s", method, url, exc
                )
                time.sleep(0.1)

        raise RuntimeError(last_error or "sync_api_request_failed")

    def _api_url_for_params(
        self, params: dict[str, object], raw_query: bool = False
    ) -> str:
        if raw_query:
            parts = []
            for key, value in params.items():
                parts.append(f"{key}={value}")
            query = "&".join(parts)
        else:
            query = urlencode(params)
        return f"{self._api_url}?{query}"

    def _refresh_api_settings_from_config(self) -> None:
        try:
            raw = self._config_path.read_text(encoding="utf-8", errors="replace")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(parsed, dict):
            return

        webui = parsed.get("webui")
        if not isinstance(webui, dict):
            return

        listen = str(webui.get("listen", "") or "").strip()
        if listen:
            if "://" in listen:
                host_port = listen.split("://", 1)[1]
            else:
                host_port = listen
            self._api_url = f"http://{host_port}/api"

        api_key = webui.get("api_key")
        if isinstance(api_key, str):
            self._api_key = api_key.strip()

        user = ""
        password = ""
        login_field = webui.get("login")
        if isinstance(login_field, str) and ":" in login_field:
            user, password = login_field.split(":", 1)
        else:
            for user_key in ("username", "user", "login"):
                candidate = webui.get(user_key)
                if isinstance(candidate, str) and candidate.strip():
                    user = candidate.strip()
                    break
            for pass_key in ("password", "pass"):
                candidate = webui.get(pass_key)
                if isinstance(candidate, str):
                    password = candidate
                    break

        if user:
            token = f"{user}:{password}".encode("utf-8")
            self._api_auth_header = f"Basic {base64.b64encode(token).decode('ascii')}"
        else:
            self._api_auth_header = ""

    def _request_api_raw(
        self, method: str, ordered_pairs: list[tuple[str, str]]
    ) -> dict:
        parts = [f"method={method}"]
        for key, value in ordered_pairs:
            parts.append(f"{key}={value}")
        query = "&".join(parts)
        url = f"{self._api_url}?{query}"
        self._log_api_request_debug(method, url)

        last_error = ""
        for _ in range(self._retry_count):
            try:
                request = Request(url)
                if self._api_auth_header:
                    request.add_header("Authorization", self._api_auth_header)
                with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 local endpoint
                    payload = response.read().decode("utf-8")
                try:
                    parsed = _parse_json_or_jsonp(payload)
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).debug(
                        "sync_api_parse_error endpoint=%s url=%s error=%s raw=%s",
                        method,
                        url,
                        exc,
                        payload,
                    )
                    raise
                self._log_api_response_debug(method, url, parsed)
                return parsed
            except HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                except Exception:  # noqa: BLE001
                    detail = ""
                last_error = f"{exc} uri={url} body={detail or 'ERROR'}"
                logging.getLogger(__name__).debug(
                    "sync_api_http_error endpoint=%s url=%s error=%s",
                    method,
                    url,
                    last_error,
                )
                time.sleep(0.1)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{exc} uri={url}"
                logging.getLogger(__name__).debug(
                    "sync_api_error endpoint=%s url=%s error=%s", method, url, exc
                )
                time.sleep(0.1)

        raise RuntimeError(last_error or f"request_failed uri={url}")

    def _request_api_path(self, path: str) -> dict:
        url = path
        if not path.startswith("http://") and not path.startswith("https://"):
            base = self._api_url
            if base.endswith("/api"):
                base = base[: -len("/api")]
            url = f"{base.rstrip('/')}/{path.lstrip('/')}"
        self._log_api_request_debug(path, url)

        last_error = ""
        for _ in range(self._retry_count):
            try:
                request = Request(url)
                if self._api_auth_header:
                    request.add_header("Authorization", self._api_auth_header)
                with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 local endpoint
                    payload = response.read().decode("utf-8")
                try:
                    parsed = _parse_json_or_jsonp(payload)
                except Exception as exc:  # noqa: BLE001
                    logging.getLogger(__name__).debug(
                        "sync_api_parse_error endpoint=%s url=%s error=%s raw=%s",
                        path,
                        url,
                        exc,
                        payload,
                    )
                    raise
                self._log_api_response_debug(path, url, parsed)
                return parsed
            except HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                except Exception:  # noqa: BLE001
                    detail = ""
                last_error = f"HTTP {exc.code}: {detail or exc.reason or 'ERROR'}"
                logging.getLogger(__name__).debug(
                    "sync_api_http_error endpoint=%s url=%s error=%s",
                    path,
                    url,
                    last_error,
                )
                time.sleep(0.1)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logging.getLogger(__name__).debug(
                    "sync_api_error endpoint=%s url=%s error=%s", path, url, exc
                )
                time.sleep(0.1)
        raise RuntimeError(last_error or f"request_failed uri={url}")

    def _normalize_dir_for_match(self, raw: str) -> str:
        return str(raw or "").strip().replace("\\", "/").rstrip("/").lower()

    def _api_folder_path(self, folder_path: str) -> str:
        normalized = str(folder_path or "").strip()
        if platform.system().lower().startswith("win"):
            return normalized.replace("/", "\\")
        return normalized

    def _existing_folder_secret(self, folder_path: str) -> str:
        target = self._normalize_dir_for_match(folder_path)
        if target in self._folder_secret_cache:
            return self._folder_secret_cache[target]
        target_name = Path(folder_path).name.strip().lower()
        try:
            payload = self._request_api("get_folders")
        except Exception:  # noqa: BLE001
            return ""
        folders = self._folders_from_payload(payload)
        if not folders:
            return ""
        for item in folders:
            candidate = self._normalize_dir_for_match(str(item.get("dir", "") or ""))
            if candidate != target:
                continue
            secret = str(item.get("secret", "") or "").strip()
            if secret:
                self._folder_secret_cache[target] = secret
                return secret
        # Fallback for canonical path differences between launcher and Resilio.
        if target_name:
            for item in folders:
                dir_value = (
                    str(item.get("dir", "") or "").replace("\\", "/").rstrip("/")
                )
                if not dir_value:
                    continue
                if Path(dir_value).name.strip().lower() != target_name:
                    continue
                secret = str(item.get("secret", "") or "").strip()
                if secret:
                    self._folder_secret_cache[target] = secret
                    return secret
        return ""

    def ensure_folder_synced(self, folder_path: str, secret: str) -> tuple[bool, str]:
        self._refresh_api_settings_from_config()
        safe_folder = str(folder_path or "").strip()
        safe_secret = str(secret or "").strip()
        if not safe_folder:
            return False, "folder_path_required"
        if not safe_secret:
            return False, "secret_required"
        try:
            Path(safe_folder).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"folder_create_failed:{exc}"
        api_folder_value = self._api_folder_path(safe_folder)

        existing_secret = self._existing_folder_secret(safe_folder)
        effective_secret = existing_secret or safe_secret
        self._folder_secret_cache[self._normalize_dir_for_match(safe_folder)] = (
            effective_secret
        )
        if existing_secret:
            logging.getLogger(__name__).info(
                "sync_folder_existing_share_detected folder=%s", safe_folder
            )

        # Keep defaults aligned with verified legacy launcher calls.
        add_params = [
            ("dir", api_folder_value),
            ("secret", effective_secret),
            ("force", "1"),
            ("search_lan", "1"),
            ("use_dht", "1"),
            ("use_hosts", "1"),
            ("use_relay_server", "1"),
            ("overwrite_changes", "1"),
            ("use_sync_trash", "0"),
            ("use_tracker", "1"),
        ]
        prefs_params = [
            ("dir", api_folder_value),
            ("secret", effective_secret),
            ("search_lan", "1"),
            ("use_dht", "1"),
            ("use_hosts", "1"),
            ("use_relay_server", "1"),
            ("overwrite_changes", "1"),
            ("use_sync_trash", "0"),
            ("use_tracker", "1"),
        ]

        def _execute_sync_calls() -> None:
            if not existing_secret:
                self._request_api_raw("add_folder", add_params)
            self._request_api_raw("set_folder_prefs", prefs_params)

        try:
            _execute_sync_calls()
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            detail = str(exc)
            logging.getLogger(__name__).warning(
                "sync_folder_ensure_failed folder=%s secret=%s error=%s",
                safe_folder,
                safe_secret[:6] + "***",
                detail,
            )
            return False, detail

    def remove_folder_sync(self, folder_path: str) -> tuple[bool, str]:
        self._refresh_api_settings_from_config()
        safe_folder = str(folder_path or "").strip()
        if not safe_folder:
            return False, "folder_path_required"

        secret = self._existing_folder_secret(safe_folder)
        if not secret:
            return True, "not_found"

        api_folder_value = self._api_folder_path(safe_folder)
        try:
            # Keep parity with legacy launcher behavior expected by current deployments:
            # remove_folder with both dir + secret in one request.
            self._request_api_raw(
                "remove_folder",
                [("dir", api_folder_value), ("secret", secret)],
            )
            self._folder_secret_cache.pop(
                self._normalize_dir_for_match(safe_folder), None
            )
            return True, "ok"
        except Exception as first_error:  # noqa: BLE001
            # Compatibility fallback for older variants that accept secret-only.
            try:
                self._request_api_raw("remove_folder", [("secret", secret)])
                self._folder_secret_cache.pop(
                    self._normalize_dir_for_match(safe_folder), None
                )
                return True, "ok"
            except Exception as second_error:  # noqa: BLE001
                # Last fallback with reversed parameter order.
                try:
                    self._request_api_raw(
                        "remove_folder",
                        [("secret", secret), ("dir", api_folder_value)],
                    )
                    self._folder_secret_cache.pop(
                        self._normalize_dir_for_match(safe_folder), None
                    )
                    return True, "ok"
                except Exception as third_error:  # noqa: BLE001
                    detail = f"{first_error};{second_error};{third_error}"
                    logging.getLogger(__name__).warning(
                        "sync_folder_remove_failed folder=%s error=%s",
                        safe_folder,
                        detail,
                    )
                    return False, detail

    def _drop_cached_secret_entries(self, secret: str) -> None:
        safe_secret = str(secret or "").strip()
        if not safe_secret:
            return
        stale_keys = [
            key
            for key, value in self._folder_secret_cache.items()
            if str(value or "").strip() == safe_secret
        ]
        for key in stale_keys:
            self._folder_secret_cache.pop(key, None)

    def remove_folder_sync_by_secret(self, secret: str) -> tuple[bool, str]:
        self._refresh_api_settings_from_config()
        safe_secret = str(secret or "").strip()
        if not safe_secret:
            return False, "secret_required"

        try:
            payload = self._request_api_with_params(
                "get_folders",
                {"secret": safe_secret},
                raw_query=True,
            )
            if not self._folders_from_payload(payload):
                return True, "not_found"
        except Exception:  # noqa: BLE001
            # Some Resilio variants reject secret-scoped get_folders calls. Keep
            # going and attempt remove_folder directly.
            pass

        try:
            self._request_api_raw("remove_folder", [("secret", safe_secret)])
            self._drop_cached_secret_entries(safe_secret)
            return True, "ok"
        except Exception as first_error:  # noqa: BLE001
            try:
                self._request_api_raw(
                    "remove_folder",
                    [("force", "1"), ("secret", safe_secret)],
                )
                self._drop_cached_secret_entries(safe_secret)
                return True, "ok"
            except Exception as second_error:  # noqa: BLE001
                detail = f"{first_error};{second_error}"
                logging.getLogger(__name__).warning(
                    "sync_folder_remove_by_secret_failed secret=%s error=%s",
                    safe_secret[:6] + "***",
                    detail,
                )
                return False, detail

    def folder_sync_status(self, folder_path: str) -> dict[str, int | bool]:
        self._refresh_api_settings_from_config()
        safe_folder = str(folder_path or "").strip()
        if not safe_folder:
            return {
                "active": False,
                "progress_percent": 0,
                "down_eta": 0,
                "down_speed": 0,
                "down_status": 0,
                "downloaded_bytes": 0,
                "total_bytes": 0,
            }
        logger = logging.getLogger(__name__)
        target = self._normalize_dir_for_match(safe_folder)
        target_name = Path(safe_folder).name.strip().lower()
        secret = self._existing_folder_secret(safe_folder)
        try:
            if secret:
                payload = self._request_api_with_params(
                    "get_folders", {"secret": secret}, raw_query=True
                )
            else:
                payload = self._request_api("get_folders")
        except Exception:  # noqa: BLE001
            if secret:
                # Some Resilio builds reject or wrap secret-scoped responses unexpectedly.
                # Fall back to plain get_folders instead of reporting inactive immediately.
                try:
                    payload = self._request_api("get_folders")
                except Exception:  # noqa: BLE001
                    return {
                        "active": False,
                        "progress_percent": 0,
                        "down_eta": 0,
                        "down_speed": 0,
                        "down_status": 0,
                        "downloaded_bytes": 0,
                        "total_bytes": 0,
                    }
            else:
                return {
                    "active": False,
                    "progress_percent": 0,
                    "down_eta": 0,
                    "down_speed": 0,
                    "down_status": 0,
                    "downloaded_bytes": 0,
                    "total_bytes": 0,
                }
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "sync_get_folders_payload folder=%s secret=%s payload=%s",
                safe_folder,
                (secret[:6] + "***") if secret else "",
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
            )
        folders = self._folders_from_payload(payload)
        if (not folders) and secret:
            try:
                payload = self._request_api("get_folders")
                folders = self._folders_from_payload(payload)
            except Exception:  # noqa: BLE001
                folders = []
        if not folders:
            return {
                "active": False,
                "progress_percent": 0,
                "down_eta": 0,
                "down_speed": 0,
                "down_status": 0,
                "downloaded_bytes": 0,
                "total_bytes": 0,
            }
        matched_item: dict | None = None
        if secret:
            for item in folders:
                if str(item.get("secret", "") or "").strip() == secret:
                    matched_item = item
                    break
        for item in folders:
            if matched_item is not None:
                break
            candidate = self._normalize_dir_for_match(str(item.get("dir", "") or ""))
            if candidate != target:
                continue
            matched_item = item
            break
        if matched_item is None and target_name:
            # Some Resilio builds can report a canonical path that differs from launcher path formatting.
            for item in folders:
                dir_value = (
                    str(item.get("dir", "") or "").replace("\\", "/").rstrip("/")
                )
                if not dir_value:
                    continue
                if Path(dir_value).name.strip().lower() == target_name:
                    matched_item = item
                    break
        if matched_item is None:
            return {
                "active": False,
                "progress_percent": 0,
                "down_eta": 0,
                "down_speed": 0,
                "down_status": 0,
                "downloaded_bytes": 0,
                "total_bytes": 0,
            }

        percent = self._download_percent_from_folder_item(matched_item)
        folder_id = self._folder_identifier(matched_item)
        activity = self._folder_activity(folder_id) if folder_id else {}
        activity_metrics = self._extract_activity_metrics(activity)
        raw_eta = matched_item.get("down_eta")
        if not activity_metrics["down_eta"] and isinstance(raw_eta, (int, float)):
            activity_metrics["down_eta"] = int(max(0, raw_eta))
        if not activity_metrics["down_speed"]:
            raw_speed = matched_item.get("down_speed")
            if isinstance(raw_speed, (int, float)):
                activity_metrics["down_speed"] = int(max(0, raw_speed))
        raw_status = matched_item.get("down_status")
        if not activity_metrics["down_status"] and isinstance(raw_status, (int, float)):
            activity_metrics["down_status"] = int(max(0, raw_status))
        if not activity_metrics["down_status"] and percent < 100:
            activity_metrics["down_status"] = 1
        downloaded_bytes = 0
        total_bytes = 0
        size_value = matched_item.get("size")
        total_size_value = matched_item.get("total_size")
        if isinstance(size_value, (int, float)):
            downloaded_bytes = int(max(0, size_value))
        if isinstance(total_size_value, (int, float)):
            total_bytes = int(max(0, total_size_value))
        return {
            "active": True,
            "progress_percent": percent,
            **activity_metrics,
            "downloaded_bytes": downloaded_bytes,
            "total_bytes": total_bytes,
        }

    def debug_logs(self, limit: int = 200) -> list[dict]:
        safe_limit = max(1, min(1000, int(limit)))
        logger = logging.getLogger(__name__)
        try:
            payload = self._request_api_path("debug/log")
        except Exception as exc:  # noqa: BLE001
            logger.debug("sync_debug_log_fetch_failed error=%s", exc)
            return []

        if logger.isEnabledFor(logging.DEBUG):
            try:
                logger.debug(
                    "sync_debug_log_payload payload=%s",
                    json.dumps(payload, ensure_ascii=True, sort_keys=True),
                )
            except Exception:  # noqa: BLE001
                pass

        def _to_entry(raw: object) -> dict | None:
            if isinstance(raw, str):
                text = raw.strip()
                if text:
                    return {"msg": text}
                return None
            if not isinstance(raw, dict):
                text = str(raw).strip()
                if text:
                    return {"msg": text}
                return None
            msg = str(
                raw.get("msg", "")
                or raw.get("message", "")
                or raw.get("line", "")
                or raw.get("text", "")
            ).strip()
            if not msg:
                return None
            ts = str(
                raw.get("ts", "") or raw.get("time", "") or raw.get("date", "")
            ).strip()
            if ts:
                return {"ts": ts, "msg": msg}
            return {"msg": msg}

        items: list[object]
        if isinstance(payload, list):
            items = payload
        elif isinstance(payload, dict):
            for key in ("logs", "log", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    items = value
                    break
            else:
                items = [payload]
        else:
            items = [payload]

        rows: list[dict] = []
        for item in items:
            parsed = _to_entry(item)
            if parsed is not None:
                rows.append(parsed)
        return rows[-safe_limit:]

    def _folder_identifier(self, item: dict) -> str:
        for key in ("id", "folder_id", "folderId"):
            value = item.get(key)
            if isinstance(value, (str, int)):
                text = str(value).strip()
                if text:
                    return text
        secret = item.get("secret")
        if isinstance(secret, str) and secret.strip():
            return secret.strip()
        return ""

    def _folder_activity(self, folder_id: str) -> dict:
        safe_id = str(folder_id or "").strip()
        if not safe_id:
            return {}
        encoded_id = quote(safe_id, safe="")
        candidates = (
            f"folders/{encoded_id}/activity",
            f"api/folders/{encoded_id}/activity",
        )
        for path in candidates:
            try:
                payload = self._request_api_path(path)
                if isinstance(payload, dict):
                    return payload
            except Exception:  # noqa: BLE001
                continue
        return {}

    def _extract_activity_metrics(self, payload: dict) -> dict[str, int]:
        if not isinstance(payload, dict):
            return {"down_eta": 0, "down_speed": 0, "down_status": 0}
        candidate: dict = payload
        if isinstance(payload.get("activity"), dict):
            candidate = payload["activity"]
        elif isinstance(payload.get("data"), dict):
            candidate = payload["data"]
        elif isinstance(payload.get("items"), list) and payload["items"]:
            first = payload["items"][0]
            if isinstance(first, dict):
                candidate = first
        down_eta = candidate.get("down_eta")
        down_speed = candidate.get("down_speed")
        down_status = candidate.get("down_status")
        return {
            "down_eta": int(down_eta) if isinstance(down_eta, (int, float)) else 0,
            "down_speed": int(down_speed)
            if isinstance(down_speed, (int, float))
            else 0,
            "down_status": int(down_status)
            if isinstance(down_status, (int, float))
            else 0,
        }

    def _download_percent_from_folder_item(self, item: dict) -> int:
        down_diff_value = item.get("down_diff")
        total_size_value = item.get("total_size")
        if (
            isinstance(down_diff_value, (int, float))
            and isinstance(total_size_value, (int, float))
            and total_size_value > 0
        ):
            remaining = max(0.0, float(down_diff_value))
            total = max(1.0, float(total_size_value))
            downloaded = max(0.0, min(total, total - remaining))
            return int(max(0, min(100, (downloaded / total) * 100)))

        # Primary source: calculate download percent from current bytes vs total bytes.
        # Some Resilio versions expose misleading ready-made percent/status values.
        size_value = item.get("size")
        total_size_value = item.get("total_size")
        if (
            isinstance(size_value, (int, float))
            and isinstance(total_size_value, (int, float))
            and total_size_value > 0
        ):
            if size_value >= total_size_value:
                return 100
            return int(max(0, min(100, (size_value / total_size_value) * 100)))

        # Prefer explicit download-only fields; generic "progress/have" can include upload-side state.
        for key in (
            "download",
            "download_percent",
            "downloaded_percent",
            "download_progress",
            "download_progress_percent",
        ):
            raw = item.get(key)
            if isinstance(raw, (int, float)):
                return int(max(0, min(100, raw)))

        downloaded = item.get("downloaded")
        size = item.get("size")
        if (
            isinstance(downloaded, (int, float))
            and isinstance(size, (int, float))
            and size > 0
        ):
            return int(max(0, min(100, (downloaded / size) * 100)))

        # WebUI exposes this as "status" in some builds (for example "39%" or "Syncing 39%").
        status_value = item.get("status")
        if isinstance(status_value, (int, float)):
            return int(max(0, min(100, status_value)))
        if isinstance(status_value, str):
            match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", status_value)
            if match:
                try:
                    return int(max(0, min(100, float(match.group(1)))))
                except ValueError:
                    pass

        raw_progress = item.get("progress")
        if isinstance(raw_progress, (int, float)):
            return int(max(0, min(100, raw_progress)))

        have = item.get("have")
        if (
            isinstance(have, (int, float))
            and isinstance(size, (int, float))
            and size > 0
        ):
            return int(max(0, min(100, (have / size) * 100)))
        return 0

    def _is_running(self) -> tuple[bool, int | None]:
        # Prefer runtime process handle when available; PID file can lag on shutdown.
        proc = self._state.process
        if proc is not None:
            exit_code = self._process_exit_code(proc)
            if exit_code is None:
                return True, proc.pid
            self._state.process = None
            self._cleanup_stale_pid()

        for pid_path in self._pid_file_paths():
            pid = self._read_pid(pid_path)
            if pid is None:
                continue
            if self._pid_matches_configured_process(pid):
                return True, pid
        self._cleanup_stale_pid()
        fallback_pid = self._find_configured_process_pid_linux()
        if fallback_pid is not None:
            return True, fallback_pid
        return False, None

    def _linux_process_argv(self, pid: int) -> list[str]:
        try:
            raw_cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        except OSError:
            return []
        if not raw_cmdline:
            return []
        return [
            chunk.decode("utf-8", errors="replace")
            for chunk in raw_cmdline.split(b"\0")
            if chunk
        ]

    def _argv_matches_configured_process(self, argv: list[str]) -> bool:
        if len(argv) < 3:
            return False
        if Path(argv[0]).name != self._binary_path.name:
            return False
        if "--config" not in argv:
            return False
        try:
            config_value = argv[argv.index("--config") + 1]
        except IndexError:
            return False
        configured = self._config_path.expanduser().resolve(strict=False)
        candidate = Path(config_value).expanduser().resolve(strict=False)
        return candidate == configured

    def _find_configured_process_pid_linux(self) -> int | None:
        if platform.system().lower() != "linux":
            return None
        proc_root = Path("/proc")
        try:
            entries = list(proc_root.iterdir())
        except OSError:
            return None
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
            except ValueError:
                continue
            if self._argv_matches_configured_process(self._linux_process_argv(pid)):
                return pid
        return None

    def _is_api_reachable(self) -> bool:
        try:
            self._request_api("get_speed")
            return True
        except Exception:  # noqa: BLE001
            return False

    def _startup_grace_active(self) -> bool:
        if self._startup_retry_seconds <= 0:
            return False
        started_at = self._state.launch_started_at
        if started_at <= 0:
            return False
        return (time.monotonic() - started_at) <= self._startup_retry_seconds

    def _record_process_output(self, source: str, line: str) -> None:
        text = str(line or "").rstrip("\r\n")
        if not text:
            return
        logger = logging.getLogger(__name__)
        level = logging.WARNING if source == "stderr" else logging.INFO
        logger.log(level, "sync_process_%s=%s", source, text)
        if self._state.log_handle is None:
            return
        if self._state.log_lock is None:
            self._state.log_lock = Lock()
        with self._state.log_lock:  # type: ignore[union-attr]
            try:
                self._state.log_handle.write(f"[{source}] {text}\n")
                self._state.log_handle.flush()
            except (OSError, ValueError):
                # Keep startup tracing resilient if the log file becomes unavailable.
                pass

    def _forward_process_stream(self, source: str, stream: object) -> None:
        reader = getattr(stream, "readline", None)
        if not callable(reader):
            return
        while True:
            try:
                chunk = reader()
            except Exception:  # noqa: BLE001
                return
            if chunk == "":
                return
            self._record_process_output(source, chunk)

    def _start_process_output_forwarders(self, process: subprocess.Popen) -> None:
        for source, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            if stream is None:
                continue
            Thread(
                target=self._forward_process_stream,
                args=(source, stream),
                daemon=True,
            ).start()

    def _linux_nofile_preexec_fn(self):
        if platform.system().lower() != "linux" or resource is None:
            return None

        def _set_child_max_open_files() -> None:
            try:
                soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
                # Raise the child soft limit to the current hard limit so Resilio can
                # use the maximum descriptor budget the OS/user policy already allows.
                if hard_limit > soft_limit:
                    resource.setrlimit(
                        resource.RLIMIT_NOFILE,
                        (hard_limit, hard_limit),
                    )
            except (OSError, ValueError):
                # Keep startup robust even when rlimit changes are rejected.
                pass

        return _set_child_max_open_files

    def start(self) -> SyncStatus:
        if not self._binary_path.exists():
            self._state.last_error = f"binary_missing:{self._binary_path}"
            return self.status()

        if not self._prepare_runtime_storage():
            return SyncStatus(
                provider="resilio",
                running=False,
                state="blocked",
                pid=None,
                last_error=self._state.last_error,
            )

        self._cleanup_stale_pid()

        running, pid = self._is_running()
        if running:
            return self.status()
        if self._is_api_reachable():
            return SyncStatus(
                provider="resilio", running=True, state="running", pid=None
            )

        if not self._ensure_identity_and_license():
            return SyncStatus(
                provider="resilio",
                running=False,
                state="blocked",
                pid=None,
                last_error=self._state.last_error,
            )

        running, pid = self._is_running()
        if running or self._is_api_reachable():
            self._state.launch_started_at = 0.0
            if self._state.log_handle is not None:
                try:
                    self._state.log_handle.close()
                except OSError:
                    pass
                self._state.log_handle = None
            return self.status()

        logger = logging.getLogger(__name__)
        for launch_attempt in range(1, 4):
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                self._state.log_handle = self._log_path.open(
                    "a", encoding="utf-8", buffering=1
                )
                binary_path = self._binary_path.expanduser().resolve(strict=False)
                config_path = self._config_path.expanduser().resolve(strict=False)
                log_path = self._log_path.expanduser().resolve(strict=False)
                pid_path = self._pid_path.expanduser().resolve(strict=False)
                cmd = self._build_start_command()
                logger.info("sync_start_command=%s", " ".join(cmd))
                logger.info(
                    "sync_start_context binary=%s config=%s log=%s pid=%s api=%s",
                    binary_path,
                    config_path,
                    log_path,
                    pid_path,
                    self._api_url,
                )
                self._state.launch_started_at = time.monotonic()
                popen_kwargs = {
                    "stdout": subprocess.PIPE,
                    "stderr": subprocess.PIPE,
                    "stdin": subprocess.DEVNULL,
                    "text": True,
                    "bufsize": 1,
                    "cwd": str(self._runtime_root_from_config_path())
                    if platform.system().lower().startswith("win")
                    else None,
                }
                preexec_fn = self._linux_nofile_preexec_fn()
                if preexec_fn is not None:
                    popen_kwargs["preexec_fn"] = preexec_fn
                self._state.process = subprocess.Popen(  # noqa: S603 - local configured binary
                    cmd,
                    **popen_kwargs,
                )
                self._start_process_output_forwarders(self._state.process)
                logger.info("sync_process_started pid=%s", self._state.process.pid)
            except OSError as exc:
                self._state.last_error = str(exc)
                self._state.launch_started_at = 0.0
                logging.getLogger(__name__).warning("sync_start_failed: %s", exc)
                return self.status()

            retry_stale_pid_lock = False
            api_ready = False
            deadline = time.time() + self._startup_retry_seconds
            while time.time() < deadline:
                proc = self._state.process
                exit_code = self._process_exit_code(proc)
                if exit_code is not None:
                    tail = self._startup_log_tail()
                    existing_instance_hint = self._startup_looks_like_existing_instance(tail)
                    if existing_instance_hint:
                        # Resilio can briefly report an already-running pid while no
                        # matching process/API is actually available. That is a stale
                        # or transient pid-lock condition; retry startup in-process so
                        # automatic boot behaves like a later manual start.
                        startup_deadline = time.time() + min(
                            3.0, max(0.2, self._startup_retry_seconds)
                        )
                        while time.time() < startup_deadline:
                            running, existing_pid = self._is_running()
                            api_ready = self._is_api_reachable()
                            if api_ready:
                                self._state.process = None
                                self._state.launch_started_at = 0.0
                                if self._state.log_handle is not None:
                                    try:
                                        self._state.log_handle.close()
                                    except OSError:
                                        pass
                                    self._state.log_handle = None
                                if tail:
                                    logger.warning(
                                        "sync_start_existing_instance_detected pid=%s log_tail=%s",
                                        existing_pid,
                                        " | ".join(tail[-10:]),
                                    )
                                else:
                                    logger.warning(
                                        "sync_start_existing_instance_detected pid=%s",
                                        existing_pid,
                                    )
                                return SyncStatus(
                                    provider="resilio",
                                    running=True,
                                    state="running",
                                    pid=existing_pid,
                                )
                            time.sleep(0.2)
                        if launch_attempt < 3:
                            logger.warning(
                                "sync_start_pid_lock_retry attempt=%s pid=%s log_tail=%s",
                                launch_attempt,
                                proc.pid if proc is not None else None,
                                " | ".join(tail[-10:]),
                            )
                            self._state.process = None
                            self._state.launch_started_at = 0.0
                            self._cleanup_stale_pid()
                            if self._state.log_handle is not None:
                                try:
                                    self._state.log_handle.close()
                                except OSError:
                                    pass
                                self._state.log_handle = None
                            retry_stale_pid_lock = True
                            break

                    self._state.last_error = f"sync_process_exited:{exit_code}"
                    self._state.launch_started_at = 0.0
                    if tail:
                        logger.warning(
                            "sync_start_process_exited pid=%s returncode=%s log_tail=%s",
                            proc.pid if proc is not None else None,
                            exit_code,
                            " | ".join(tail[-10:]),
                        )
                    else:
                        logger.warning(
                            "sync_start_process_exited pid=%s returncode=%s",
                            proc.pid if proc is not None else None,
                            exit_code,
                        )
                    self._state.process = None
                    if self._state.log_handle is not None:
                        try:
                            self._state.log_handle.close()
                        except OSError:
                            pass
                        self._state.log_handle = None
                    return SyncStatus(
                        provider="resilio",
                        running=False,
                        state="failed",
                        pid=proc.pid if proc is not None else None,
                        last_error=self._state.last_error,
                    )
                try:
                    self.metrics()
                    api_ready = True
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(0.2)
            if not retry_stale_pid_lock:
                break

        if api_ready:
            self._state.launch_started_at = 0.0
            self._state.last_error = ""
            running, pid = self._is_running()
            return SyncStatus(
                provider="resilio",
                running=True,
                state="running",
                pid=pid,
            )
        return self.status()

    def recover_if_unhealthy(self) -> SyncStatus:
        """Recheck a failed API and restart its process only if it stays unreachable."""
        status = self.status()
        if status.running or status.state != "failed" or self._startup_grace_active():
            return status

        # A short burst distinguishes a transient API hiccup from a stuck service.
        for attempt in range(3):
            if self._is_api_reachable():
                logging.getLogger(__name__).info(
                    "sync_api_recovered_during_watchdog_probe pid=%s", status.pid
                )
                return self.status()
            if attempt < 2:
                time.sleep(0.5)

        running, pid = self._is_running()
        if running:
            logging.getLogger(__name__).warning(
                "sync_watchdog_restarting_unresponsive_process pid=%s", pid
            )
            stopped = self.stop()
            if stopped.running:
                return stopped
        return self.start()

    def stop(self) -> SyncStatus:
        running, pid = self._is_running()
        if not running:
            fallback_pid = self._find_configured_process_pid_linux()
            if fallback_pid is not None:
                running = True
                pid = fallback_pid
            elif self._is_api_reachable():
                try:
                    self._request_api("shutdown")
                    deadline = time.time() + self._startup_retry_seconds
                    while time.time() < deadline:
                        if not self._is_api_reachable():
                            break
                        time.sleep(0.2)
                except Exception:  # noqa: BLE001
                    pass
            if self._state.log_handle is not None:
                try:
                    self._state.log_handle.close()
                except OSError:
                    pass
                self._state.log_handle = None
            self._state.launch_started_at = 0.0
            if not running:
                return SyncStatus(
                    provider="resilio", running=False, state="stopped", pid=pid
                )
        assert pid is not None
        try:
            proc = self._state.process
            if proc is not None and proc.poll() is None:
                proc.terminate()
            else:
                os.kill(pid, 15)
            logging.getLogger(__name__).info("sync_process_stop_signal pid=%s", pid)
        except OSError as exc:
            self._state.last_error = str(exc)
            return self.status()

        deadline = time.time() + self._startup_retry_seconds
        still_alive = False
        while time.time() < deadline:
            alive, _ = self._is_running()
            if not alive:
                break
            still_alive = True
            time.sleep(0.2)

        if still_alive:
            try:
                proc = self._state.process
                if proc is not None and proc.poll() is None:
                    proc.kill()
                else:
                    os.kill(pid, 9)
                time.sleep(0.2)
            except OSError:
                pass

        self._state.process = None
        self._cleanup_stale_pid()
        if self._state.log_handle is not None:
            try:
                self._state.log_handle.close()
            except OSError:
                pass
            self._state.log_handle = None
        self._state.launch_started_at = 0.0
        return self.status()

    def status(self) -> SyncStatus:
        running, pid = self._is_running()
        api_reachable = self._is_api_reachable()
        if api_reachable:
            self._state.last_error = ""
            return SyncStatus(
                provider="resilio",
                running=True,
                state="running",
                pid=pid,
                last_error=self._state.last_error,
            )
        if (
            not running
            and self._license_bootstrap_done
            and not self._license_activation_ok
        ):
            return SyncStatus(
                provider="resilio",
                running=False,
                state="blocked",
                pid=pid,
                last_error=self._state.last_error or "sync_license_activation_failed",
            )
        if running and self._startup_grace_active():
            return SyncStatus(
                provider="resilio",
                running=False,
                state="starting",
                pid=pid,
                last_error=self._state.last_error,
            )
        if running:
            self._state.last_error = self._state.last_error or "sync_api_unreachable"
            return SyncStatus(
                provider="resilio",
                running=False,
                state="failed",
                pid=pid,
                last_error=self._state.last_error,
            )
        if self._startup_grace_active():
            return SyncStatus(
                provider="resilio",
                running=False,
                state="starting",
                pid=pid,
                last_error=self._state.last_error,
            )
        return SyncStatus(
            provider="resilio",
            running=False,
            state="stopped",
            pid=pid,
            last_error=self._state.last_error,
        )

    def metrics(self) -> SyncMetrics:
        payload = self._request_api("get_speed")
        return SyncMetrics(
            download_bps=int(payload.get("download", 0) or 0),
            upload_bps=int(payload.get("upload", 0) or 0),
        )

    def web_ui_url(self) -> str:
        base = self._api_url
        if base.endswith("/api"):
            base = base[: -len("/api")]
        return f"{base.rstrip('/')}/gui/"

    def set_peer_device_ids(self, device_ids: list[str]) -> None:
        _ = device_ids
