"""Windows-specific platform adapter."""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes
from pathlib import Path

from src.core.platform.base import ActionResult, StorageValidation
from src.core.platform.common.paths import normalize_user_path


class WindowsPlatformAdapter:
    def platform_name(self) -> str:
        return "windows"

    def normalize_path(self, raw_path: str) -> str:
        return str(normalize_user_path(raw_path))

    def validate_storage_path(self, raw_path: str) -> StorageValidation:
        normalized = normalize_user_path(raw_path)
        exists = normalized.exists()
        is_directory = normalized.is_dir()
        writable = False

        if exists and is_directory:
            try:
                test_file = normalized / ".llng_write_test"
                test_file.write_text("ok", encoding="utf-8")
                test_file.unlink(missing_ok=True)
                writable = True
            except OSError:
                writable = False

        ok = exists and is_directory and writable
        message = "ok" if ok else "path_invalid_or_not_writable"

        return StorageValidation(
            path=str(normalized),
            exists=exists,
            writable=writable,
            is_directory=is_directory,
            ok=ok,
            message=message,
        )

    def open_folder(self, raw_path: str) -> ActionResult:
        normalized = normalize_user_path(raw_path)
        if not normalized.exists():
            return ActionResult(ok=False, message="path_not_found")

        try:
            os.startfile(str(normalized))  # type: ignore[attr-defined]
            return ActionResult(ok=True, message="opened")
        except OSError as exc:
            return ActionResult(ok=False, message=str(exc))

    def launch_executable(
        self, executable_path: str, args: list[str] | None = None
    ) -> ActionResult:
        exe = Path(executable_path)
        if not exe.exists():
            return ActionResult(ok=False, message="executable_not_found")

        normalized_args = args or []
        is_cmd_script = exe.suffix.lower() in {".cmd", ".bat"}
        cmd = [str(exe), *normalized_args]
        popen_kwargs: dict = {}
        if is_cmd_script:
            # .cmd/.bat scripts need a dedicated console window to preserve interactive prompts.
            cmd = ["cmd.exe", "/c", str(exe), *normalized_args]
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        else:
            popen_kwargs["stdout"] = subprocess.DEVNULL
            popen_kwargs["stderr"] = subprocess.DEVNULL
        try:
            subprocess.Popen(cmd, **popen_kwargs)  # noqa: S603
            return ActionResult(ok=True, message="launched")
        except OSError as exc:
            return ActionResult(ok=False, message=str(exc))

    def list_storage_locations(self) -> list[dict[str, str]]:
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError:
            return []

        drive_mask = kernel32.GetLogicalDrives()
        if drive_mask == 0:
            return []

        try:
            kernel32.GetVolumeInformationW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
                wintypes.LPWSTR,
                wintypes.DWORD,
            ]
            kernel32.GetVolumeInformationW.restype = wintypes.BOOL
        except AttributeError:
            # Test doubles may expose plain Python callables without ctypes metadata.
            pass

        locations: list[dict[str, str]] = []
        for index in range(26):
            if not (drive_mask & (1 << index)):
                continue

            letter = chr(ord("A") + index)
            root = f"{letter}:\\"

            # Querying labels via WinAPI keeps behavior stable even when paths are not mounted in explorer.
            volume_name = ctypes.create_unicode_buffer(261)
            filesystem_name = ctypes.create_unicode_buffer(261)
            serial_number = wintypes.DWORD(0)
            max_component_length = wintypes.DWORD(0)
            filesystem_flags = wintypes.DWORD(0)
            has_label = bool(
                kernel32.GetVolumeInformationW(
                    root,
                    volume_name,
                    len(volume_name),
                    ctypes.byref(serial_number),
                    ctypes.byref(max_component_length),
                    ctypes.byref(filesystem_flags),
                    filesystem_name,
                    len(filesystem_name),
                )
            )
            label = volume_name.value.strip() if has_label else ""
            display = f"{letter}: ({label})" if label else f"{letter}:"
            locations.append(
                {
                    "id": letter,
                    "path": root,
                    "label": label,
                    "display": display,
                }
            )
        return locations

    def configure_sync_network_mode(
        self,
        script_path: str,
        sync_binary_path: str,
        mode: str,
    ) -> ActionResult:
        script = Path(script_path)
        if not script.exists():
            return ActionResult(ok=False, message="firewall_script_not_found")

        # LAN mode rules target the configured sync executable; internet mode only removes rules.
        if mode == "lan":
            binary = Path(sync_binary_path)
            if not binary.exists():
                return ActionResult(ok=False, message="sync_binary_not_found")

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Mode",
            mode,
            "-ProgramPath",
            str(Path(sync_binary_path)),
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False
            )  # noqa: S603
        except OSError as exc:
            return ActionResult(
                ok=False, message="firewall_apply_failed", detail=str(exc)
            )

        detail = "\n".join(
            [
                line
                for line in [completed.stdout.strip(), completed.stderr.strip()]
                if line
            ]
        ).strip()
        if completed.returncode != 0:
            return ActionResult(
                ok=False, message="firewall_apply_failed", detail=detail
            )
        return ActionResult(ok=True, message="network_mode_applied", detail=detail)

    def set_local_network_private(self, script_path: str) -> ActionResult:
        script = Path(script_path)
        if not script.exists():
            return ActionResult(ok=False, message="network_profile_script_not_found")

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, check=False
            )  # noqa: S603
        except OSError as exc:
            return ActionResult(
                ok=False, message="network_profile_apply_failed", detail=str(exc)
            )

        detail = "\n".join(
            [
                line
                for line in [completed.stdout.strip(), completed.stderr.strip()]
                if line
            ]
        ).strip()
        if completed.returncode != 0:
            if "admin_prompt_cancelled" in detail.lower():
                return ActionResult(
                    ok=False, message="admin_prompt_cancelled", detail=detail
                )
            if "admin_required" in detail.lower():
                return ActionResult(ok=False, message="admin_required", detail=detail)
            return ActionResult(
                ok=False, message="network_profile_apply_failed", detail=detail
            )
        return ActionResult(ok=True, message="network_profile_applied", detail=detail)

    def install_common_wine_dependencies(
        self,
        packages: list[str],
        *,
        winetricks_path: str = "",
        cache_path: str = "",
    ) -> ActionResult:
        _ = packages
        _ = winetricks_path
        _ = cache_path
        return ActionResult(ok=False, message="not_supported_on_platform")

    def install_common_wine_dependencies_for_prefix(
        self,
        prefix_path: str,
        packages: list[str],
        *,
        winetricks_path: str = "",
        cache_path: str = "",
    ) -> ActionResult:
        _ = prefix_path
        _ = packages
        _ = winetricks_path
        _ = cache_path
        return ActionResult(ok=False, message="not_supported_on_platform")

    def open_wine_prefix_uninstaller(self, prefix_path: str) -> ActionResult:
        _ = prefix_path
        return ActionResult(ok=False, message="not_supported_on_platform")
