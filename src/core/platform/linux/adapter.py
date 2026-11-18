"""Linux-specific platform adapter."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from src.core.platform.base import ActionResult, StorageValidation
from src.core.platform.common.paths import normalize_user_path


class LinuxPlatformAdapter:
    _WINDOWS_FILESYSTEM_TYPES = {"fuseblk", "ntfs", "ntfs3", "drvfs"}
    _TERMINAL_CANDIDATES = (
        "x-terminal-emulator",
        "gnome-terminal",
        "konsole",
        "xfce4-terminal",
        "xterm",
    )

    def platform_name(self) -> str:
        return "linux"

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
        if ok:
            fs_type = self._filesystem_type(normalized)
            # Windows-backed mounts (for example NTFS via fuseblk/drvfs) are usable,
            # but large sync trees can perform significantly worse than native Linux FS.
            if fs_type in self._WINDOWS_FILESYSTEM_TYPES:
                message = "ok_windows_filesystem_warning"

        return StorageValidation(
            path=str(normalized),
            exists=exists,
            writable=writable,
            is_directory=is_directory,
            ok=ok,
            message=message,
        )

    def _filesystem_type(self, path: Path) -> str:
        stat_binary = shutil.which("stat")
        if stat_binary is None:
            return ""
        try:
            completed = subprocess.run(
                [stat_binary, "-f", "-c", "%T", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return ""
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip().lower()

    def open_folder(self, raw_path: str) -> ActionResult:
        normalized = normalize_user_path(raw_path)
        if not normalized.exists():
            return ActionResult(ok=False, message="path_not_found")

        xdg_open = shutil.which("xdg-open")
        if xdg_open is None:
            return ActionResult(ok=False, message="xdg_open_not_found")

        try:
            subprocess.Popen(
                [xdg_open, str(normalized)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )  # noqa: S603
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
        terminal_cmd = self._build_terminal_launch_command(str(exe), normalized_args)
        cmd = terminal_cmd if terminal_cmd is not None else [str(exe), *normalized_args]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
            return ActionResult(ok=True, message="launched")
        except OSError as exc:
            return ActionResult(ok=False, message=str(exc))

    def _build_terminal_launch_command(
        self, executable_path: str, args: list[str]
    ) -> list[str] | None:
        terminal_binary = ""
        for candidate in self._TERMINAL_CANDIDATES:
            resolved = shutil.which(candidate) or ""
            if resolved:
                terminal_binary = resolved
                break
        if not terminal_binary:
            return None

        bash_binary = shutil.which("bash") or "/bin/bash"
        shell_command = [
            bash_binary,
            "-lc",
            'exec "$@"',
            "llng-launch",
            executable_path,
            *args,
        ]

        # Terminal emulators use incompatible invocation styles; map the common forms explicitly.
        terminal_name = Path(terminal_binary).name.lower()
        if terminal_name == "gnome-terminal":
            return [terminal_binary, "--", *shell_command]
        if terminal_name == "xfce4-terminal":
            return [
                terminal_binary,
                "--command",
                " ".join(shlex.quote(part) for part in shell_command),
            ]
        return [terminal_binary, "-e", *shell_command]

    def list_storage_locations(self) -> list[dict[str, str]]:
        # Linux setup uses free-form paths instead of predefined mount selectors.
        return []

    def configure_sync_network_mode(
        self,
        script_path: str,
        sync_binary_path: str,
        mode: str,
    ) -> ActionResult:
        _ = sync_binary_path
        script = Path(script_path)
        if not script.exists():
            return ActionResult(ok=False, message="firewall_script_not_found")

        sudo_binary = shutil.which("sudo")
        if sudo_binary is None:
            return ActionResult(ok=False, message="sudo_not_found")

        # Linux firewall updates require root; sudo will prompt for password if needed.
        bash_binary = shutil.which("bash") or "/bin/bash"
        command = [sudo_binary, bash_binary, str(script), mode]
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
        _ = script_path
        return ActionResult(ok=False, message="not_supported_on_platform")

    def install_common_wine_dependencies(
        self,
        packages: list[str],
        *,
        winetricks_path: str = "",
        cache_path: str = "",
    ) -> ActionResult:
        return self.install_common_wine_dependencies_for_prefix(
            str(Path.home() / ".wine"),
            packages,
            winetricks_path=winetricks_path,
            cache_path=cache_path,
        )

    def install_common_wine_dependencies_for_prefix(
        self,
        prefix_path: str,
        packages: list[str],
        *,
        winetricks_path: str = "",
        cache_path: str = "",
    ) -> ActionResult:
        normalized = [str(item or "").strip().lower() for item in packages]
        normalized = [item for item in normalized if item]
        if not normalized:
            return ActionResult(ok=False, message="invalid_winetricks_package_set")

        prefix = str(prefix_path or "").strip()
        if not prefix:
            return ActionResult(ok=False, message="invalid_wine_prefix")

        winetricks_binary = self._resolve_binary_path(
            preferred_path=winetricks_path,
            fallback_name="winetricks",
        )
        if not winetricks_binary:
            return ActionResult(ok=False, message="winetricks_not_found")
        if not shutil.which("wine"):
            return ActionResult(ok=False, message="wine_not_found")

        args = ["-q", *normalized]
        launch_command = self._build_terminal_launch_command(winetricks_binary, args)
        command = launch_command or [winetricks_binary, *args]
        env = os.environ.copy()
        env["WINEPREFIX"] = prefix
        normalized_cache = str(cache_path or "").strip()
        if normalized_cache:
            cache_dir = Path(normalized_cache)
            cache_dir.mkdir(parents=True, exist_ok=True)
            # Winetricks still consults its historic W_CACHE variable in many
            # environments, so export both names for offline bundle compatibility.
            env["WINETRICKS_CACHE"] = str(cache_dir)
            env["W_CACHE"] = str(cache_dir)

        try:
            subprocess.Popen(  # noqa: S603
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            return ActionResult(
                ok=True,
                message="wine_dependencies_install_started",
                detail=" ".join(normalized),
            )
        except OSError as exc:
            return ActionResult(
                ok=False, message="winetricks_launch_failed", detail=str(exc)
            )

    def open_wine_prefix_uninstaller(self, prefix_path: str) -> ActionResult:
        prefix = str(prefix_path or "").strip()
        if not prefix:
            return ActionResult(ok=False, message="invalid_wine_prefix")
        prefix_dir = Path(prefix)
        if not prefix_dir.exists():
            return ActionResult(ok=False, message="wine_prefix_missing")

        wine_binary = shutil.which("wine")
        if not wine_binary:
            return ActionResult(ok=False, message="wine_not_found")

        args = ["uninstaller"]
        launch_command = self._build_terminal_launch_command(wine_binary, args)
        command = launch_command or [wine_binary, *args]
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix_dir)

        try:
            subprocess.Popen(  # noqa: S603
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            return ActionResult(
                ok=True,
                message="wine_prefix_uninstaller_started",
                detail=str(prefix_dir),
            )
        except OSError as exc:
            return ActionResult(
                ok=False,
                message="wine_prefix_uninstaller_launch_failed",
                detail=str(exc),
            )

    def _resolve_binary_path(self, preferred_path: str, fallback_name: str) -> str:
        candidate = str(preferred_path or "").strip()
        if candidate:
            candidate_path = Path(candidate)
            if candidate_path.is_file():
                return str(candidate_path)
        return shutil.which(fallback_name) or ""
